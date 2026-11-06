"""Phoenix's REST API (ADR-053): links, annotations and a run's sync, against a stand-in Phoenix
on 127.0.0.1 that keeps what it receives; and `bidwright-eval phoenix`'s score annotations."""

import json
import shutil
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest

from bidwright.harness.egress import EgressRefused
from bidwright.obs.phoenix import PhoenixClient, code_annotations, run_spans, sync_run
from bidwright.preflight import HOME
from bidwright.review import record

DEV_SAMPLE = HOME / "samples" / "dev"


class FakePhoenix:
    """Projects, the spans of the traces it holds, and every POST it received."""

    def __init__(self) -> None:
        self.projects = [{"name": "default", "id": "UHJvamVjdDox"}]
        self.spans: dict[str, list[dict[str, Any]]] = {}  # trace id -> spans
        self.posts: list[tuple[str, Any]] = []


@contextmanager
def _phoenix() -> Iterator[tuple[str, FakePhoenix]]:
    state = FakePhoenix()

    class Handler(BaseHTTPRequestHandler):
        def _send(self, payload: Any, status: int = 200) -> None:
            body = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            url = urlparse(self.path)
            if url.path == "/v1/projects":
                return self._send({"data": state.projects, "next_cursor": None})
            if url.path.endswith("/spans"):
                trace = parse_qs(url.query).get("trace_id", [""])[0]
                return self._send({"data": state.spans.get(trace, []), "next_cursor": None})
            return self._send({"detail": "not found"}, 404)

        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length)
            path = urlparse(self.path).path
            if path == "/v1/traces":  # a replay: hold the run's traces from now on
                state.posts.append((path, len(body)))
                for trace, rows in _sample_spans().items():
                    state.spans[trace] = rows
                self.send_response(200)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return None
            state.posts.append((path, json.loads(body)))
            return self._send({"data": [{"id": "x"}]})

        def log_message(self, format: str, *args: object) -> None:
            return None

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}", state
    finally:
        server.shutdown()


def _sample_spans() -> dict[str, list[dict[str, Any]]]:
    rows: dict[str, list[dict[str, Any]]] = {}
    for n, line in enumerate((DEV_SAMPLE / "spans.jsonl").read_text("utf-8").splitlines()):
        span = json.loads(line)
        trace = span["context"]["trace_id"].removeprefix("0x")
        context = {"trace_id": trace, "span_id": span["context"]["span_id"].removeprefix("0x")}
        rows.setdefault(trace, []).append({"id": f"U3Bhbjo{n}", "context": context})
    return rows


def test_a_trace_link_names_the_project_and_selects_a_span() -> None:
    with _phoenix() as (url, state):
        state.spans = _sample_spans()
        client = PhoenixClient.from_env(endpoint=url)
        trace = next(iter(state.spans))
        assert client.available()
        assert client.find_project(trace) == "default", "a run traced before ADR-053"
        page = client.trace_url(trace, "U3Bhbjo1")
        assert page == f"{url}/projects/UHJvamVjdDox/traces/{trace}?selectedSpanNodeId=U3Bhbjo1"
        node_ids = client.span_node_ids(trace)
        assert len(node_ids) == len(state.spans[trace])
        assert client.sessions_url() is None, "no project named bidwright yet"


def test_links_for_a_browser_use_the_local_url_when_the_endpoint_is_a_compose_service() -> None:
    client = PhoenixClient.from_env(endpoint="http://phoenix:6006")
    assert client.ui_base == "http://127.0.0.1:6006"


def test_a_remote_endpoint_is_refused_by_the_egress_register() -> None:
    with pytest.raises(EgressRefused):
        PhoenixClient.from_env(endpoint="https://collector.example.com:6006")


def test_a_sync_replays_a_missing_trace_then_annotates_checks_and_verdicts(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "dev"
    shutil.copytree(DEV_SAMPLE, run_dir)
    record(run_dir, [{"item": "REQ-0001", "verdict": "accept", "note": "Fine."}], "Bid manager")
    with _phoenix() as (url, state):
        report = sync_run(run_dir, PhoenixClient.from_env(endpoint=url))
        assert report.replayed == report.traces, "Phoenix held no trace, so it was sent first"
        posted = {path: body for path, body in state.posts if path != "/v1/traces"}
        spans = posted["/v1/span_annotations"]["data"]
        names = {row["name"] for row in spans}
        assert "verify B01" in names and "risk checks" in names
        human = next(row for row in spans if row["name"] == "review hazard REQ-0001")
        assert human["annotator_kind"] == "HUMAN" and human["result"]["label"] == "accept"
        batch_span = run_spans(run_dir).node("extract", "B01")
        assert human["span_id"] == batch_span, "on the extract call that read the passage"
        assert all(row["identifier"].startswith("bidwright:") for row in spans), "upserts"
        traces = posted["/v1/trace_annotations"]["data"]
        assert {row["name"] for row in traces} == {"run status", "human review"}
        # A second sync replays nothing: Phoenix now holds the trace.
        again = sync_run(run_dir, PhoenixClient.from_env(endpoint=url))
        assert again.replayed == []


def test_code_annotations_hold_counts_and_labels_never_a_quote(tmp_path: Path) -> None:
    run_dir = tmp_path / "dev"
    shutil.copytree(DEV_SAMPLE, run_dir)
    rows = code_annotations(run_dir, run_spans(run_dir), "dev")
    quotes = [
        json.loads(line)["quote"]
        for line in (run_dir / "requirements.jsonl").read_text("utf-8").splitlines()
    ]
    text = json.dumps(rows)
    assert rows and not any(q in text for q in quotes if len(q) > 20)


def test_eval_scores_go_to_the_traces_phoenix_holds(tmp_path: Path) -> None:
    from evals.phoenix import push_scores, score_annotations

    scores = {
        "run_id": "dev",
        "missed_mandatory_count": 1,
        "missed_mandatory": ["GR-0007"],
        "mandatory_total": 8,
        "missed_hazards": [],
        "hazards_total": 1,
        "recall": 0.9,
        "precision_low": 0.8,
        "f1": 0.85,
        "trap_actions_obeyed": 0,
    }
    rows = score_annotations(scores, ["abc"])
    missed = next(r for r in rows if r["name"] == "eval: missed mandatory")
    assert missed["result"] == {"label": "1 of 8 missed", "score": 1.0, "explanation": "GR-0007"}
    hazards = next(r for r in rows if r["name"] == "eval: missed hazards")
    assert hazards["result"]["label"] == "0 of 1 missed"
    with _phoenix() as (url, state):
        state.spans = _sample_spans()
        count, link = push_scores(DEV_SAMPLE, scores, PhoenixClient.from_env(endpoint=url))
        assert count == len(rows) and link is not None
