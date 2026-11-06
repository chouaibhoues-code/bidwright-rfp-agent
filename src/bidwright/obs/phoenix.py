"""Phoenix's REST API, for the run's links and annotations (ADR-053).

`PhoenixClient` reaches the collector `PHOENIX_ENDPOINT` names, or the owner's local Phoenix at
`http://127.0.0.1:6006`, after the egress register's `phoenix` entry allows its host for the
run's data class, and sends `PHOENIX_API_KEY` as a bearer token when it is set. Links for a
browser use `PHOENIX_UI_URL`, or the endpoint itself when it is on loopback, else the local
URL: inside Compose the endpoint is `http://phoenix:6006`, which a browser cannot open.

`sync_run` sends a run's own findings to its trace, as annotations Phoenix shows beside the
spans: code's checks (`CODE`), the gate's decision, and each reviewer's verdict from
`review/decisions.jsonl` (`HUMAN`), each on the span of the node that made the record. A
trace Phoenix does not hold is replayed first from `spans.jsonl`. Every annotation carries an
identifier, so a sync run again updates its annotations instead of adding copies. An
annotation holds labels, counts, reasons and a reviewer's note; never a quote or a prompt.
"""

import json
import os
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse

import httpx

from bidwright.fileio import read_lines
from bidwright.harness import egress
from bidwright.harness.supervisor import read_manifest
from bidwright.obs.tracing import project_name, trace_endpoint
from bidwright.preflight import Refused

LOCAL_URL = "http://127.0.0.1:6006"
UI_VARIABLE = "PHOENIX_UI_URL"
LOOPBACK = {"127.0.0.1", "localhost"}


class PhoenixUnavailable(Refused):
    """Phoenix did not answer, or refused a request."""


@dataclass
class PhoenixClient:
    base: str
    api_key: str | None = None
    timeout: float = 5.0
    ui_base: str = LOCAL_URL
    _projects: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_env(
        cls, data_class: str = "synthetic", endpoint: str | None = None
    ) -> "PhoenixClient":
        base = (endpoint or trace_endpoint() or LOCAL_URL).strip().rstrip("/")
        egress.check(egress.TRACE_DESTINATION, base, data_class)  # type: ignore[arg-type]
        ui = os.environ.get(UI_VARIABLE, "").strip().rstrip("/")
        if not ui:
            ui = base if (urlparse(base).hostname or "") in LOOPBACK else LOCAL_URL
        key = os.environ.get("PHOENIX_API_KEY", "").strip() or None
        return cls(base=base, api_key=key, ui_base=ui)

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        try:
            response = httpx.request(
                method,
                f"{self.base}{path}",
                headers=self._headers(),
                timeout=self.timeout,
                **kwargs,
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise PhoenixUnavailable(f"Phoenix at {self.base}: {exc}") from exc
        return response.json() if response.content else {}

    def available(self) -> bool:
        try:
            self._request("GET", "/v1/projects")
        except PhoenixUnavailable:
            return False
        return True

    def projects(self) -> dict[str, str]:
        """Each project's name and id, which Phoenix's pages use in their paths."""
        if not self._projects:
            rows = self._request("GET", "/v1/projects").get("data", [])
            self._projects = {p["name"]: p["id"] for p in rows}
        return self._projects

    def project_id(self, name: str | None = None) -> str | None:
        return self.projects().get(name or project_name())

    def find_project(self, trace_id: str) -> str | None:
        """The project that holds a trace: this run's project first, then the others, since a
        run traced before ADR-053, or replayed from it, sits in Phoenix's `default`."""
        names = [project_name(), *sorted(n for n in self.projects() if n != project_name())]
        return next((n for n in names if n in self.projects() and self.spans(trace_id, n, 1)), None)

    def spans(
        self, trace_id: str, project: str | None = None, limit: int | None = None
    ) -> list[dict[str, Any]]:
        """The spans Phoenix holds for one trace, or its first `limit`."""
        path = f"/v1/projects/{quote(project or project_name())}/spans"
        rows: list[dict[str, Any]] = []
        cursor: str | None = None
        while True:
            params: dict[str, Any] = {"trace_id": trace_id, "limit": limit or 1000}
            if cursor:
                params["cursor"] = cursor
            page = self._request("GET", path, params=params)
            rows += page.get("data", [])
            cursor = page.get("next_cursor")
            if not cursor or (limit is not None and len(rows) >= limit):
                return rows

    def trace_url(
        self, trace_id: str, span_node_id: str | None = None, project: str | None = None
    ) -> str | None:
        """The page of a trace, with one span selected when `span_node_id`, the span's id in
        Phoenix, names it."""
        project_id = self.project_id(project or self.find_project(trace_id))
        if project_id is None:
            return None
        url = f"{self.ui_base}/projects/{project_id}/traces/{quote(trace_id)}"
        return f"{url}?selectedSpanNodeId={quote(span_node_id)}" if span_node_id else url

    def span_node_ids(self, trace_id: str, project: str | None = None) -> dict[str, str]:
        """Each span id of a trace, mapped to the id Phoenix's pages select it by."""
        project = project or self.find_project(trace_id)
        if project is None:
            return {}
        return {_hex(row["context"]["span_id"]): row["id"] for row in self.spans(trace_id, project)}

    def sessions_url(self) -> str | None:
        project = self.project_id()
        return f"{self.ui_base}/projects/{project}/sessions" if project else None

    def annotate_spans(self, rows: Sequence[dict[str, Any]]) -> int:
        if not rows:
            return 0
        self._request("POST", "/v1/span_annotations", params={"sync": "true"}, json={"data": rows})
        return len(rows)

    def annotate_traces(self, rows: Sequence[dict[str, Any]]) -> int:
        if not rows:
            return 0
        self._request("POST", "/v1/trace_annotations", params={"sync": "true"}, json={"data": rows})
        return len(rows)


# --- the run's spans, as spans.jsonl holds them ------------------------------------------------


@dataclass
class RunSpans:
    """Each trace's root span, and the node spans by node and call id."""

    roots: dict[str, str]  # trace id -> root span id
    nodes: dict[tuple[str, str | None], str]  # (node, call id) -> span id, the last part's

    def node(self, name: str, call_id: str | None = None) -> str | None:
        return self.nodes.get((name, call_id)) or self.nodes.get((name, None))


def _hex(value: str) -> str:
    return value.removeprefix("0x")


def run_spans(run_dir: Path) -> RunSpans:
    roots: dict[str, str] = {}
    nodes: dict[tuple[str, str | None], str] = {}
    for line in read_lines(run_dir / "spans.jsonl"):
        span = json.loads(line)
        context = span.get("context", {})
        trace, span_id = _hex(context.get("trace_id", "")), _hex(context.get("span_id", ""))
        if span.get("parent_id") is None and span.get("name") == "run":
            roots[trace] = span_id
        name = span.get("name", "")
        if name.startswith("node."):
            call = span.get("attributes", {}).get("bidwright.call_id")
            nodes[(name.removeprefix("node."), call)] = span_id
    return RunSpans(roots, nodes)


# --- the annotations of a run ------------------------------------------------------------------


def _rows(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in read_lines(path)]


def _batch_of(run_dir: Path) -> dict[str, str]:
    """Each passage id's extract call, from the calls' context manifests."""
    batches: dict[str, str] = {}
    for path in sorted((run_dir / "context").glob("extract-*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        for src in data.get("included_src_ids", []):
            batches.setdefault(src, data["call_id"])
    return batches


def _span_annotation(
    run_id: str, span_id: str, name: str, kind: str, label: str, **result: Any
) -> dict[str, Any]:
    return {
        "span_id": span_id,
        "name": name,
        "annotator_kind": kind,
        "result": {"label": label, **{k: v for k, v in result.items() if v is not None}},
        "identifier": f"bidwright:{run_id}:{name}",
        "metadata": {"run_id": run_id},
    }


def code_annotations(run_dir: Path, spans: RunSpans, run_id: str) -> list[dict[str, Any]]:
    """Code's checks of the run, each on the span of the node that made them."""
    rows: list[dict[str, Any]] = []
    rejected = Counter(r.get("batch_id") for r in _rows(run_dir / "rejected.jsonl"))
    for (node, call), span_id in spans.nodes.items():
        if node == "extract" and call is not None:
            count = rejected.get(call, 0)
            label = "all quotes verified" if count == 0 else "quotes rejected"
            rows.append(
                _span_annotation(
                    run_id, span_id, f"verify {call}", "CODE", label, score=float(count)
                )
            )
    risk = spans.node("risk")
    if risk is not None and (run_dir / "risks.jsonl").is_file():
        kept = len(_rows(run_dir / "risks.jsonl"))
        dropped = _rows(run_dir / "risk_rejected.jsonl")
        reasons = Counter(r["reason"].split(":")[0] for r in dropped)
        explanation = ", ".join(f"{n} {reason}" for reason, n in sorted(reasons.items())) or None
        rows.append(
            _span_annotation(
                run_id,
                risk,
                "risk checks",
                "CODE",
                f"{kept} kept, {len(dropped)} rejected",
                score=float(kept),
                explanation=explanation,
            )
        )
    techcheck = spans.node("techcheck")
    if techcheck is not None and (run_dir / "tech_validations.jsonl").is_file():
        verdicts = Counter(v["verdict"] for v in _rows(run_dir / "tech_validations.jsonl"))
        label = "blocked" if verdicts.get("INVALIDATED") else "not blocked"
        explanation = ", ".join(f"{n} {v}" for v, n in sorted(verdicts.items())) or None
        rows.append(
            _span_annotation(
                run_id,
                techcheck,
                "technology verdicts",
                "CODE",
                label,
                score=float(verdicts.get("INVALIDATED", 0)),
                explanation=explanation,
            )
        )
    cmap_span = spans.node("capability_map")
    if cmap_span is not None and (run_dir / "capability_map.json").is_file():
        counts = json.loads((run_dir / "capability_map.json").read_text("utf-8")).get("counts", {})
        total = sum(counts.values()) or 1
        rows.append(
            _span_annotation(
                run_id,
                cmap_span,
                "capability coverage",
                "CODE",
                ", ".join(f"{n} {status}" for status, n in sorted(counts.items())),
                score=round((counts.get("COVERED", 0) + counts.get("PARTNER", 0)) / total, 4),
            )
        )
    return rows


def gate_annotation(run_dir: Path, spans: RunSpans, run_id: str) -> list[dict[str, Any]]:
    path = run_dir / "review" / "solution_gate.approval.yaml"
    gate = spans.node("solution_gate")
    if gate is None or not path.is_file():
        return []
    import yaml

    approval = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    automatic = bool(approval.get("auto_selected"))
    reasons = [approval.get("override_reason"), approval.get("reject_reason")]
    explanation = "; ".join(str(r) for r in reasons if r) or None
    return [
        _span_annotation(
            run_id,
            gate,
            "gate decision",
            "CODE" if automatic else "HUMAN",
            str(approval.get("decision", "")),
            explanation=(
                f"{'automatic' if automatic else approval.get('approver_role', '')}"
                f"{': ' + explanation if explanation else ''}"
            ),
        )
    ]


def review_annotations(run_dir: Path, spans: RunSpans, run_id: str) -> list[dict[str, Any]]:
    """Each reviewer's last verdict, on the span of the node that made the record."""
    from bidwright.review import latest, review_queue

    queue = {item.id: item for item in review_queue(run_dir)}
    batches = _batch_of(run_dir)
    by_kind = {
        "risk": "risk",
        "tech_claim": "techcheck",
        "quarantine": "guard",
        "contract_flag": "lint",
    }
    rows = []
    for decision in latest(run_dir).values():
        item = queue.get(decision.item_id)
        if item is None:
            continue
        if item.kind in by_kind:
            span = spans.node(by_kind[item.kind])
        elif item.kind == "question":
            span = spans.node(str(item.detail.get("origin") or ""))
        else:  # requirements and sampled passages: the extract call that read the passage
            batch = next((batches[s] for s in item.src_ids if s in batches), None)
            span = spans.node("extract", batch)
        span = span or next(iter(spans.roots.values()), None)
        if span is None:
            continue
        name = "missed obligation" if item.kind == "passage" else f"review {item.kind}"
        stale = decision.item_sha256 != item.sha256
        row = _span_annotation(
            run_id,
            span,
            f"{name} {item.id}",
            "HUMAN",
            f"{decision.verdict}{' (stale)' if stale else ''}",
            score=0.0 if decision.verdict in ("reject", "missed") else 1.0,
            explanation=f"{decision.role}: {decision.note}" if decision.note else decision.role,
        )
        rows.append(row)
    return rows


def trace_annotations(run_dir: Path, spans: RunSpans, run_id: str) -> list[dict[str, Any]]:
    """The run's status on each of its traces, and the review's progress."""
    from bidwright.review import latest, progress, review_queue

    manifest = read_manifest(run_dir)
    done = progress(review_queue(run_dir), latest(run_dir))
    rows = []
    for trace in spans.roots:
        rows.append(
            {
                "trace_id": trace,
                "name": "run status",
                "annotator_kind": "CODE",
                "result": {"label": manifest.status, "explanation": manifest.status_reason},
                "identifier": f"bidwright:{run_id}:run status",
                "metadata": {"run_id": run_id},
            }
        )
        rows.append(
            {
                "trace_id": trace,
                "name": "human review",
                "annotator_kind": "HUMAN",
                "result": {
                    "label": f"{done.reviewed} of {done.total} reviewed",
                    "score": round(done.reviewed / done.total, 4) if done.total else 0.0,
                    "explanation": ", ".join(f"{n} {v}" for v, n in sorted(done.by_verdict.items()))
                    or None,
                },
                "identifier": f"bidwright:{run_id}:human review",
                "metadata": {"run_id": run_id, "stale": done.stale},
            }
        )
    return rows


@dataclass
class SyncReport:
    traces: list[str]
    replayed: list[str]
    span_annotations: int
    trace_annotations: int
    url: str | None


def sync_run(run_dir: Path, client: PhoenixClient | None = None) -> SyncReport:
    """Make sure Phoenix holds the run's traces, then send the run's annotations."""
    from bidwright.obs.replay import replay_spans

    manifest = read_manifest(run_dir)
    client = client or PhoenixClient.from_env(manifest.data_class)
    spans = run_spans(run_dir)
    if not spans.roots:
        raise Refused(f"{run_dir.name} holds no spans.jsonl with a run span to annotate")
    missing = [t for t in spans.roots if client.find_project(t) is None]
    if missing:
        replay_spans(run_dir, endpoint=client.base)
    rows = code_annotations(run_dir, spans, manifest.run_id)
    rows += gate_annotation(run_dir, spans, manifest.run_id)
    rows += review_annotations(run_dir, spans, manifest.run_id)
    count = client.annotate_spans(rows)
    traces = client.annotate_traces(trace_annotations(run_dir, spans, manifest.run_id))
    last = list(spans.roots)[-1]
    return SyncReport(list(spans.roots), missing, count, traces, client.trace_url(last))


__all__ = [
    "LOCAL_URL",
    "PhoenixClient",
    "PhoenixUnavailable",
    "RunSpans",
    "SyncReport",
    "code_annotations",
    "review_annotations",
    "run_spans",
    "sync_run",
    "trace_annotations",
]
