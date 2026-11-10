"""Span replay (`WP-3.6`, `CH-94`): `obs/replay.py` sends `spans.jsonl` over OTLP HTTP to a
collector on an allowed host and refuses any host not in `config/egress.yaml`'s `phoenix` entry.
"""

import json
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

import pytest
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import (
    ExportTraceServiceRequest,
    ExportTraceServiceResponse,
)

from bidwright.harness.egress import EgressRefused
from bidwright.obs.replay import _hex_bytes, _unix_nano, replay_spans
from bidwright.preflight import HOME, Refused

DEV_SAMPLE = HOME / "samples" / "dev"


class _CapturedOtlp:
    def __init__(self) -> None:
        self.paths: list[str] = []
        self.headers: list[dict[str, str]] = []
        self.requests: list[ExportTraceServiceRequest] = []


@contextmanager
def _otlp_receiver() -> Iterator[tuple[str, _CapturedOtlp]]:
    captured = _CapturedOtlp()

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length)
            req = ExportTraceServiceRequest()
            req.ParseFromString(body)
            captured.paths.append(self.path)
            captured.headers.append({k.lower(): v for k, v in self.headers.items()})
            captured.requests.append(req)
            resp = ExportTraceServiceResponse().SerializeToString()
            self.send_response(200)
            self.send_header("Content-Type", "application/x-protobuf")
            self.send_header("Content-Length", str(len(resp)))
            self.end_headers()
            self.wfile.write(resp)

        def log_message(self, format: str, *args: object) -> None:
            return None

    server = HTTPServer(("127.0.0.1", 0), Handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{port}", captured
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_every_span_of_samples_dev_arrives_with_its_ids_and_times(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PHOENIX_API_KEY", "test-phoenix-token")
    expected_lines = (DEV_SAMPLE / "spans.jsonl").read_text(encoding="utf-8").splitlines()
    expected: list[dict[str, Any]] = [json.loads(line) for line in expected_lines]

    with _otlp_receiver() as (endpoint, captured):
        monkeypatch.setenv("PHOENIX_ENDPOINT", endpoint)
        count, url = replay_spans(DEV_SAMPLE, endpoint=endpoint)

    assert count == len(expected) > 0
    assert url == f"{endpoint}/v1/traces"
    assert captured.paths == ["/v1/traces"]
    assert captured.headers[0]["content-type"] == "application/x-protobuf"
    assert captured.headers[0]["authorization"] == "Bearer test-phoenix-token"

    received_spans = [
        span
        for req in captured.requests
        for rs in req.resource_spans
        for ss in rs.scope_spans
        for span in ss.spans
    ]
    assert len(received_spans) == len(expected)

    for raw, proto in zip(expected, received_spans, strict=True):
        assert proto.name == raw["name"]
        assert proto.trace_id == _hex_bytes(raw["context"]["trace_id"], 16)
        assert proto.span_id == _hex_bytes(raw["context"]["span_id"], 8)
        expected_parent = _hex_bytes(raw["parent_id"], 8) if raw.get("parent_id") else b""
        assert proto.parent_span_id == expected_parent
        assert proto.start_time_unix_nano == _unix_nano(raw["start_time"])
        assert proto.end_time_unix_nano == _unix_nano(raw["end_time"])
        attrs = {kv.key: kv.value for kv in proto.attributes}
        assert (
            attrs["openinference.span.kind"].string_value
            == (raw["attributes"]["openinference.span.kind"])
        )


def test_an_unlisted_host_is_refused_before_sending() -> None:
    with pytest.raises(EgressRefused, match="phoenix"):
        replay_spans(DEV_SAMPLE, endpoint="https://collector.example.com:6006")


def test_a_folder_without_spans_is_refused(tmp_path: Path) -> None:
    with pytest.raises(Refused, match="no spans.jsonl"):
        replay_spans(tmp_path, endpoint="http://127.0.0.1:6006")


def test_the_phoenix_key_goes_only_to_the_configured_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Another port on an allowed host gets the spans but not the key (security review)."""
    monkeypatch.setenv("PHOENIX_API_KEY", "test-phoenix-token")
    monkeypatch.setenv("PHOENIX_ENDPOINT", "http://127.0.0.1:6006")
    with _otlp_receiver() as (endpoint, captured):
        replay_spans(DEV_SAMPLE, endpoint=endpoint)
    assert captured.headers and "authorization" not in captured.headers[0]
