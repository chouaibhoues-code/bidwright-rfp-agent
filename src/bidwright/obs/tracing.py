"""Spans for each run, node, LLM call and tool call, with OpenInference attributes.

Every span goes to `spans.jsonl` in the run folder, and also over OTLP HTTP to Phoenix when
`PHOENIX_ENDPOINT` is set and answers within a second, so a run never waits on a missing
collector, and the run folder always holds its trace for the UI's links and for
`bidwright spans replay`. Phoenix 21 can answer an export without a key with 401, which
the OTLP exporter reports only as a failed result; the refused batches are counted.

Phoenix groups the spans (ADR-053): the resource names the project
(`openinference.project.name`, `PHOENIX_PROJECT_NAME` or `bidwright`); every span carries
`session.id`, the run id, so the parts of a resumed run form one session, and `tag.tags`;
the run span carries `metadata`, the run's settings as JSON. `PHOENIX_API_KEY`, when set, is
sent as a bearer token. No prompt or response text enters a span, only ids, hashes, models,
versions, decoding settings, counts and statuses. A failed call still leaves its
span, with the error. `close` flushes with a 5-second timeout, because short CLI runs end
before a batch export would.

The run entry reads the endpoint with `trace_endpoint` and checks it against the egress
register before any connection (D-05). An endpoint the register refuses, such as a remote
collector on a client run, is never contacted: the run passes no endpoint here, so its spans
go to `spans.jsonl`, and its manifest records the refusal in `refused_destinations`.
"""

import json
import os
import socket
import threading
from collections.abc import Iterator, Sequence
from contextlib import contextmanager, nullcontext
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from openinference.semconv.resource import ResourceAttributes
from openinference.semconv.trace import OpenInferenceSpanKindValues, SpanAttributes
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    SimpleSpanProcessor,
    SpanExporter,
    SpanExportResult,
)
from opentelemetry.trace import Span

from bidwright.schemas import LedgerEntry

FLUSH_MS = 5000
KIND = SpanAttributes.OPENINFERENCE_SPAN_KIND
ENDPOINT_VARIABLE = "PHOENIX_ENDPOINT"
PROJECT_VARIABLE = "PHOENIX_PROJECT_NAME"
DEFAULT_PROJECT = "bidwright"


def project_name() -> str:
    """The Phoenix project the run's spans go to."""
    return os.environ.get(PROJECT_VARIABLE, "").strip() or DEFAULT_PROJECT


def trace_endpoint() -> str | None:
    """The collector `PHOENIX_ENDPOINT` names, or None when it is unset or empty."""
    return os.environ.get(ENDPOINT_VARIABLE, "").strip() or None


class JsonlExporter(SpanExporter):
    """Writes each finished span as one JSON line."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        lines = "".join(json.dumps(json.loads(span.to_json())) + "\n" for span in spans)
        with self._lock, self.path.open("a", encoding="utf-8", newline="\n") as out:
            out.write(lines)
        return SpanExportResult.SUCCESS

    def shutdown(self) -> None:
        return None


class TeeExporter(SpanExporter):
    """Writes every span to the JSONL file and sends it to the collector, counting the
    batches the collector refuses."""

    def __init__(self, primary: SpanExporter, fallback: SpanExporter) -> None:
        self.primary = primary
        self.fallback = fallback
        self.refused = 0  # batches the collector did not take

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        kept = self.fallback.export(spans)
        try:
            result = self.primary.export(spans)
        except Exception:  # noqa: BLE001 - an exporter should not raise; a trace must survive
            result = SpanExportResult.FAILURE
        if result is not SpanExportResult.SUCCESS:
            self.refused += 1
        return kept

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return self.primary.force_flush(timeout_millis)

    def shutdown(self) -> None:
        self.primary.shutdown()
        self.fallback.shutdown()


def reachable(endpoint: str, timeout: float = 1.0) -> bool:
    url = urlparse(endpoint)
    port = url.port or (443 if url.scheme == "https" else 80)
    try:
        with socket.create_connection((url.hostname or "localhost", port), timeout=timeout):
            return True
    except OSError:
        return False


class Tracing:
    def __init__(
        self,
        run_id: str,
        run_dir: Path,
        endpoint: str | None = None,
        api_key: str | None = None,
        *,
        tags: Sequence[str] = (),
    ) -> None:
        resource = Resource.create(
            {
                "service.name": "bidwright",
                "bidwright.run_id": run_id,
                ResourceAttributes.PROJECT_NAME: project_name(),
            }
        )
        self.run_id = run_id
        self.project = project_name()
        self.tags = list(tags)
        self.trace_id: str | None = None  # the first root span's, as 32 hex digits
        self.provider = TracerProvider(resource=resource)
        run_dir.mkdir(parents=True, exist_ok=True)
        jsonl = JsonlExporter(run_dir / "spans.jsonl")
        self.exporter: TeeExporter | None = None
        if endpoint and reachable(endpoint):
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

            headers = {"authorization": f"Bearer {api_key}"} if api_key else None
            otlp = OTLPSpanExporter(
                endpoint=endpoint.rstrip("/") + "/v1/traces", timeout=5, headers=headers
            )
            self.exporter = TeeExporter(otlp, jsonl)
            self.provider.add_span_processor(BatchSpanProcessor(self.exporter))
            self.target = endpoint
        else:
            self.provider.add_span_processor(SimpleSpanProcessor(jsonl))
            self.target = str(run_dir / "spans.jsonl")
        self._tracer = self.provider.get_tracer("bidwright")

    @contextmanager
    def span(
        self, name: str, kind: OpenInferenceSpanKindValues, **attributes: Any
    ) -> Iterator[Span]:
        clean = {k: v for k, v in attributes.items() if v is not None}
        grouping: dict[str, Any] = {SpanAttributes.SESSION_ID: self.run_id}
        if self.tags:
            grouping[SpanAttributes.TAG_TAGS] = self.tags
        with self._tracer.start_as_current_span(
            name, attributes={KIND: kind.value, **grouping, **clean}
        ) as span:
            if self.trace_id is None:
                self.trace_id = f"{span.get_span_context().trace_id:032x}"
            yield span

    def close(self) -> None:
        self.provider.force_flush(FLUSH_MS)
        self.provider.shutdown()


def maybe_span(
    tracing: "Tracing | None", name: str, kind: OpenInferenceSpanKindValues, **attributes: Any
) -> Any:
    """A span when tracing is on, and a no-op context otherwise."""
    return tracing.span(name, kind, **attributes) if tracing else nullcontext()


def set_attribute(span: Any, key: str, value: Any) -> None:
    if isinstance(span, Span) and value is not None:
        span.set_attribute(key, value)


def record_llm(span: Any, entry: LedgerEntry) -> None:
    """Copy one ledger entry's counts onto its LLM span."""
    if not isinstance(span, Span):
        return
    span.set_attributes(
        {
            SpanAttributes.LLM_MODEL_NAME: entry.model,
            SpanAttributes.LLM_PROVIDER: entry.provider,
            SpanAttributes.LLM_TOKEN_COUNT_PROMPT: entry.tokens_in,
            SpanAttributes.LLM_TOKEN_COUNT_COMPLETION: entry.tokens_out + entry.tokens_thinking,
            SpanAttributes.LLM_TOKEN_COUNT_TOTAL: entry.tokens_in
            + entry.tokens_out
            + entry.tokens_thinking,
            SpanAttributes.LLM_TOKEN_COUNT_PROMPT_DETAILS_CACHE_READ: entry.tokens_cached,
            SpanAttributes.LLM_TOKEN_COUNT_COMPLETION_DETAILS_REASONING: entry.tokens_thinking,
            SpanAttributes.LLM_SYSTEM: entry.provider,
            # Phoenix's cost columns: the shadow price at paid list rates, comparable across
            # profiles; the real spend stays in bidwright.cost_usd.
            SpanAttributes.LLM_COST_TOTAL: entry.shadow_cost_usd,
            "bidwright.cost_usd": entry.cost_usd,
            "bidwright.shadow_cost_usd": entry.shadow_cost_usd,
            "bidwright.latency_ms": entry.latency_ms,
            "bidwright.retries": entry.retries,
            "bidwright.replayed": entry.replayed,
        }
    )


def run_metadata(settings: dict[str, Any]) -> str:
    """The run span's `metadata` attribute: the run's settings, as Phoenix reads it, JSON."""
    return json.dumps({k: v for k, v in settings.items() if v is not None}, sort_keys=True)
