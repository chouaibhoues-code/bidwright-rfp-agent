"""Spans for each run, node, LLM call and tool call, with OpenInference attributes.

Spans go over OTLP HTTP to Phoenix when `PHOENIX_ENDPOINT` is set and answers within a
second. Otherwise they go to `spans.jsonl` in the run folder, so a run never waits on a
missing collector. No prompt or response text enters a span, only ids, hashes, models,
counts and statuses. A failed call still leaves its span, with the error. `close` flushes
with a 5-second timeout, because short CLI runs end before a batch export would.
"""

import json
import socket
import threading
from collections.abc import Iterator, Sequence
from contextlib import contextmanager, nullcontext
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

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


def reachable(endpoint: str, timeout: float = 1.0) -> bool:
    url = urlparse(endpoint)
    port = url.port or (443 if url.scheme == "https" else 80)
    try:
        with socket.create_connection((url.hostname or "localhost", port), timeout=timeout):
            return True
    except OSError:
        return False


class Tracing:
    def __init__(self, run_id: str, run_dir: Path, endpoint: str | None = None) -> None:
        resource = Resource.create({"service.name": "bidwright", "bidwright.run_id": run_id})
        self.provider = TracerProvider(resource=resource)
        if endpoint and reachable(endpoint):
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

            exporter = OTLPSpanExporter(endpoint=endpoint.rstrip("/") + "/v1/traces", timeout=5)
            self.provider.add_span_processor(BatchSpanProcessor(exporter))
            self.target = endpoint
        else:
            run_dir.mkdir(parents=True, exist_ok=True)
            self.provider.add_span_processor(
                SimpleSpanProcessor(JsonlExporter(run_dir / "spans.jsonl"))
            )
            self.target = str(run_dir / "spans.jsonl")
        self._tracer = self.provider.get_tracer("bidwright")

    @contextmanager
    def span(
        self, name: str, kind: OpenInferenceSpanKindValues, **attributes: Any
    ) -> Iterator[Span]:
        clean = {k: v for k, v in attributes.items() if v is not None}
        with self._tracer.start_as_current_span(
            name, attributes={KIND: kind.value, **clean}
        ) as span:
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
            "bidwright.cost_usd": entry.cost_usd,
            "bidwright.shadow_cost_usd": entry.shadow_cost_usd,
            "bidwright.latency_ms": entry.latency_ms,
            "bidwright.retries": entry.retries,
            "bidwright.replayed": entry.replayed,
        }
    )
