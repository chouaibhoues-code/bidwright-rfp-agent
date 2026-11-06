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
from bidwright.obs.tracing import JsonlExporter, TeeExporter, reachable
from bidwright.schemas import RunManifest
from tests.node_fakes import DEV_RFP, RuleBackend, fake_backends


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
        docling_mode="replay",
        source=DEV_RFP,
        profile="free",
        outputs=tmp_path,
        mode="record",
        cassettes=CassetteStore(tmp_path / "cassettes"),
        backends=fake_backends(RuleBackend()),
        run_id="traced",
    )
    assert result.status == "COMPLETED", result.reason
    spans = _spans(result.run_dir)
    kinds = Counter(span["attributes"]["openinference.span.kind"] for span in spans)
    assert kinds["LLM"] == len(read_ledger(result.run_dir / "ledger.jsonl"))
    agents = Counter(
        s["name"] for s in spans if s["attributes"]["openinference.span.kind"] == "AGENT"
    )
    assert kinds["TOOL"] >= 1 and set(agents) == {"node.risk", "node.decide"}
    assert agents["node.risk"] == 1, "one risk agent; one decide agent per need"
    needs = {s["attributes"]["bidwright.call_id"] for s in spans if s["name"] == "node.decide"}
    assert len(needs) == agents["node.decide"] and None not in needs
    names = {span["name"] for span in spans}
    assert {"run", "node.ingest", "node.extract", "llm.extract", "tool.search_rfp"} <= names
    agent = next(span for span in spans if span["name"] == "node.risk")
    assert agent["attributes"]["bidwright.stop_reason"] == "answered"
    assert agent["attributes"]["bidwright.tool_calls"] == 1
    llm = next(span for span in spans if span["name"] == "llm.options")
    assert llm["attributes"]["llm.model_name"] == "gemini-3.5-flash-lite"
    assert llm["attributes"]["llm.token_count.prompt"] > 0
    text = (result.run_dir / "spans.jsonl").read_text(encoding="utf-8")
    assert "Proposals must be submitted" not in text  # no RFP or prompt text in spans
    # Phoenix's grouping (ADR-053): one project, the run id as the session, tags on every span,
    # the run's settings on its root, and each LLM span's system, prompt version, decoding
    # settings and cost.
    assert {span["resource"]["attributes"]["openinference.project.name"] for span in spans} == {
        "bidwright"
    }
    assert {span["attributes"]["session.id"] for span in spans} == {"traced"}
    assert all("free" in span["attributes"]["tag.tags"] for span in spans)
    root = next(span for span in spans if span["name"] == "run")
    assert json.loads(root["attributes"]["metadata"])["solution"] == "manifest"
    assert llm["attributes"]["llm.system"] == "gemini"
    assert llm["attributes"]["llm.prompt_template.version"].startswith("options@")
    assert "thinking" in llm["attributes"]["llm.invocation_parameters"]
    assert llm["attributes"]["llm.cost.total"] > 0
    manifest = RunManifest.model_validate_json((result.run_dir / "run_manifest.json").read_text())
    assert manifest.trace_ids == [root["context"]["trace_id"].removeprefix("0x")]


class _Refusing(SpanExporter):
    """A collector that answers every export the way Phoenix 21 does without a key."""

    def __init__(self) -> None:
        self.calls = 0

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        self.calls += 1
        return SpanExportResult.FAILURE

    def shutdown(self) -> None:
        return None


class _Taking(_Refusing):
    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        self.calls += 1
        return SpanExportResult.SUCCESS


def test_spans_a_collector_takes_are_kept_in_jsonl_too(tmp_path: Path) -> None:
    """ADR-053: the run folder holds every span, so the UI links them and a replay resends."""
    taking = _Taking()
    exporter = TeeExporter(taking, JsonlExporter(tmp_path / "spans.jsonl"))
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    with provider.get_tracer("test").start_as_current_span("run"):
        pass
    provider.shutdown()
    assert taking.calls == 1 and exporter.refused == 0
    assert [span["name"] for span in _spans(tmp_path)] == ["run"]


def test_spans_a_collector_refuses_land_in_jsonl(tmp_path: Path) -> None:
    refusing = _Refusing()
    exporter = TeeExporter(refusing, JsonlExporter(tmp_path / "spans.jsonl"))
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    with provider.get_tracer("test").start_as_current_span("run"):
        pass
    provider.shutdown()
    assert refusing.calls == 1 and exporter.refused == 1
    assert [span["name"] for span in _spans(tmp_path)] == ["run"]


def test_a_failed_call_leaves_an_error_span(tmp_path: Path) -> None:
    result = execute(
        docling_mode="replay",
        source=DEV_RFP,
        profile="free",
        outputs=tmp_path,
        mode="replay",
        cassettes=CassetteStore(tmp_path / "empty"),
        run_id="failed",
    )
    assert result.status == "UNRECOVERABLE_FAULT"
    errors = [s for s in _spans(result.run_dir) if s["status"]["status_code"] == "ERROR"]
    assert any(span["name"] == "llm.triage" for span in errors), "the first call is triage's"
