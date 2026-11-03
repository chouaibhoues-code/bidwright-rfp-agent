"""Spans: with no reachable collector they land in spans.jsonl, and the run does not wait.
A collector that refuses a batch sends that batch to spans.jsonl too."""

import json
import time
from collections import Counter
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor, SpanExporter, SpanExportResult

from bidwright.graph.build import execute
from bidwright.llm.replay import CassetteStore
from bidwright.obs.ledger import read_ledger
from bidwright.obs.tracing import FallbackExporter, JsonlExporter, reachable
from tests.node_fakes import DEV_RFP, RuleBackend


def _spans(run_dir: Path) -> list[dict[str, Any]]:
    lines = (run_dir / "spans.jsonl").read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines]


def test_a_closed_port_is_detected_quickly() -> None:
    started = time.perf_counter()
    assert not reachable("http://127.0.0.1:9", timeout=1.0)
    assert time.perf_counter() - started < 2


def test_without_a_collector_spans_land_in_jsonl(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PHOENIX_ENDPOINT", "http://127.0.0.1:9")  # nothing listens there
    result = execute(
        source=DEV_RFP,
        profile="free",
        outputs=tmp_path,
        mode="record",
        cassettes=CassetteStore(tmp_path / "cassettes"),
        backends={"gemini": RuleBackend()},
        run_id="traced",
    )
    assert result.status == "COMPLETED", result.reason
    spans = _spans(result.run_dir)
    kinds = Counter(span["attributes"]["openinference.span.kind"] for span in spans)
    assert kinds["LLM"] == len(read_ledger(result.run_dir / "ledger.jsonl"))
    assert kinds["TOOL"] >= 1 and kinds["AGENT"] == 1
    names = {span["name"] for span in spans}
    assert {"run", "node.ingest", "node.extract", "llm.extract", "tool.search_rfp"} <= names
    agent = next(span for span in spans if span["name"] == "node.risk")
    assert agent["attributes"]["bidwright.stop_reason"] == "answered"
    assert agent["attributes"]["bidwright.tool_calls"] == 1
    llm = next(span for span in spans if span["name"] == "llm.approach")
    assert llm["attributes"]["llm.model_name"] == "gemini-3.5-flash-lite"
    assert llm["attributes"]["llm.token_count.prompt"] > 0
    text = (result.run_dir / "spans.jsonl").read_text(encoding="utf-8")
    assert "Proposals must be submitted" not in text  # no RFP or prompt text in spans


class _Refusing(SpanExporter):
    """A collector that answers every export the way Phoenix 21 does without a key."""

    def __init__(self) -> None:
        self.calls = 0

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        self.calls += 1
        return SpanExportResult.FAILURE

    def shutdown(self) -> None:
        return None


def test_spans_a_collector_refuses_land_in_jsonl(tmp_path: Path) -> None:
    refusing = _Refusing()
    exporter = FallbackExporter(refusing, JsonlExporter(tmp_path / "spans.jsonl"))
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    with provider.get_tracer("test").start_as_current_span("run"):
        pass
    provider.shutdown()
    assert refusing.calls == 1 and exporter.refused == 1
    assert [span["name"] for span in _spans(tmp_path)] == ["run"]


def test_a_failed_call_leaves_an_error_span(tmp_path: Path) -> None:
    result = execute(
        source=DEV_RFP,
        profile="free",
        outputs=tmp_path,
        mode="replay",
        cassettes=CassetteStore(tmp_path / "empty"),
        run_id="failed",
    )
    assert result.status == "UNRECOVERABLE_FAULT"
    errors = [s for s in _spans(result.run_dir) if s["status"]["status_code"] == "ERROR"]
    assert any(span["name"] == "llm.extract" for span in errors)
