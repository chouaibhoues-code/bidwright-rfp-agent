"""Replay a run's `spans.jsonl` into Phoenix over OTLP HTTP (`WP-3.6`, `CH-94`).

When a run runs without a reachable Phoenix collector (or when a collector refuses a batch),
`FallbackExporter` in `obs/tracing.py` writes every span to `<run>/spans.jsonl`. `replay_spans`
reads `spans.jsonl`, builds an OTLP `ExportTraceServiceRequest` with `opentelemetry-proto`
preserving each span's trace id, span id, parent span id, start and end times, kind, status,
attributes, events and resource, checks the destination against the egress register's `phoenix`
entry, and posts the protobuf payload to `<endpoint>/v1/traces`.
"""

import json
import os
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest
from opentelemetry.proto.common.v1.common_pb2 import (
    AnyValue,
    ArrayValue,
    InstrumentationScope,
    KeyValue,
)
from opentelemetry.proto.resource.v1.resource_pb2 import Resource
from opentelemetry.proto.trace.v1.trace_pb2 import ResourceSpans, ScopeSpans, Span, Status

from bidwright.harness import egress
from bidwright.obs.tracing import trace_endpoint
from bidwright.preflight import Refused

DEFAULT_PHOENIX_ENDPOINT = "http://127.0.0.1:6006"
TRACES_PATH = "/v1/traces"
SCOPE_NAME = "bidwright"

_SPAN_KINDS: dict[str, Span.SpanKind.ValueType] = {
    "INTERNAL": Span.SpanKind.SPAN_KIND_INTERNAL,
    "SERVER": Span.SpanKind.SPAN_KIND_SERVER,
    "CLIENT": Span.SpanKind.SPAN_KIND_CLIENT,
    "PRODUCER": Span.SpanKind.SPAN_KIND_PRODUCER,
    "CONSUMER": Span.SpanKind.SPAN_KIND_CONSUMER,
}

_STATUS_CODES: dict[str, Status.StatusCode.ValueType] = {
    "UNSET": Status.StatusCode.STATUS_CODE_UNSET,
    "OK": Status.StatusCode.STATUS_CODE_OK,
    "ERROR": Status.StatusCode.STATUS_CODE_ERROR,
}

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


def _hex_bytes(value: str, length: int) -> bytes:
    cleaned = value.strip().removeprefix("0x").removeprefix("0X")
    return bytes.fromhex(cleaned.zfill(length * 2))


def _unix_nano(value: str | int) -> int:
    """Convert an ISO-8601 UTC timestamp (or integer nanoseconds) to exact integer nanoseconds."""
    if isinstance(value, int):
        return value
    text = value.strip()
    if text.isdigit():
        return int(text)
    dt = datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(UTC)
    delta = dt - _EPOCH
    return ((delta.days * 86_400 + delta.seconds) * 1_000_000 + delta.microseconds) * 1_000


def _any_value(value: Any) -> AnyValue:
    if isinstance(value, bool):
        return AnyValue(bool_value=value)
    if isinstance(value, int):
        return AnyValue(int_value=value)
    if isinstance(value, float):
        return AnyValue(double_value=value)
    if isinstance(value, bytes):
        return AnyValue(bytes_value=value)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return AnyValue(array_value=ArrayValue(values=[_any_value(item) for item in value]))
    return AnyValue(string_value=str(value))


def _key_values(attributes: Mapping[str, Any] | None) -> list[KeyValue]:
    if not attributes:
        return []
    return [
        KeyValue(key=str(key), value=_any_value(val))
        for key, val in attributes.items()
        if val is not None
    ]


def _proto_span(record: Mapping[str, Any]) -> Span:
    context = record.get("context") or {}
    trace_id = _hex_bytes(str(context["trace_id"]), 16)
    span_id = _hex_bytes(str(context["span_id"]), 8)
    parent_raw = record.get("parent_id")
    parent_span_id = _hex_bytes(str(parent_raw), 8) if parent_raw else b""
    kind_raw = str(record.get("kind", "INTERNAL")).removeprefix("SpanKind.")
    kind = _SPAN_KINDS.get(kind_raw, Span.SpanKind.SPAN_KIND_INTERNAL)

    status_raw = record.get("status") or {}
    code_name = str(status_raw.get("status_code", "UNSET")).removeprefix("StatusCode.")
    status = Status(
        code=_STATUS_CODES.get(code_name, Status.StatusCode.STATUS_CODE_UNSET),
        message=str(status_raw.get("description") or ""),
    )

    events = [
        Span.Event(
            name=str(event.get("name", "")),
            time_unix_nano=_unix_nano(event["timestamp"]) if event.get("timestamp") else 0,
            attributes=_key_values(event.get("attributes")),
        )
        for event in (record.get("events") or [])
    ]

    return Span(
        trace_id=trace_id,
        span_id=span_id,
        parent_span_id=parent_span_id,
        name=str(record.get("name", "")),
        kind=kind,
        start_time_unix_nano=_unix_nano(record["start_time"]),
        end_time_unix_nano=_unix_nano(record["end_time"]),
        attributes=_key_values(record.get("attributes")),
        events=events,
        status=status,
    )


def build_export_request(records: Sequence[Mapping[str, Any]]) -> ExportTraceServiceRequest:
    """Build an OTLP `ExportTraceServiceRequest` from decoded `spans.jsonl` records."""
    grouped: dict[str, tuple[Mapping[str, Any], list[Span]]] = {}
    for record in records:
        res_info = record.get("resource") or {}
        res_attrs = res_info.get("attributes") or {}
        key = json.dumps(res_attrs, sort_keys=True)
        if key not in grouped:
            grouped[key] = (res_attrs, [])
        grouped[key][1].append(_proto_span(record))

    resource_spans = [
        ResourceSpans(
            resource=Resource(attributes=_key_values(res_attrs)),
            scope_spans=[
                ScopeSpans(
                    scope=InstrumentationScope(name=SCOPE_NAME),
                    spans=spans,
                )
            ],
        )
        for res_attrs, spans in grouped.values()
    ]
    return ExportTraceServiceRequest(resource_spans=resource_spans)


def resolve_traces_url(endpoint: str | None = None) -> str:
    """Resolve the OTLP HTTP traces URL and check its host against the egress register."""
    base = (endpoint or trace_endpoint() or DEFAULT_PHOENIX_ENDPOINT).strip().rstrip("/")
    url = base if base.endswith(TRACES_PATH) else f"{base}{TRACES_PATH}"
    egress.check(egress.TRACE_DESTINATION, url, "synthetic")
    return url


def read_span_records(run_dir: Path) -> list[dict[str, Any]]:
    """Read the span records from `<run_dir>/spans.jsonl` (or a direct `spans.jsonl` file)."""
    spans_file = run_dir if run_dir.is_file() else run_dir / "spans.jsonl"
    if not spans_file.is_file():
        raise Refused(f"no spans.jsonl in {run_dir}")
    lines = [line for line in spans_file.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not lines:
        raise Refused(f"{spans_file} is empty")
    return [json.loads(line) for line in lines]


def replay_spans(
    run_dir: Path,
    endpoint: str | None = None,
    *,
    timeout: float = 10.0,
) -> tuple[int, str]:
    """Replay `<run_dir>/spans.jsonl` over OTLP HTTP to Phoenix and return `(count, url)`."""
    url = resolve_traces_url(endpoint)
    records = read_span_records(run_dir)
    request = build_export_request(records)
    headers = {"Content-Type": "application/x-protobuf"}
    if api_key := os.environ.get("PHOENIX_API_KEY", "").strip():
        headers["Authorization"] = f"Bearer {api_key}"
    try:
        response = httpx.post(
            url,
            content=request.SerializeToString(),
            headers=headers,
            timeout=timeout,
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise Refused(f"OTLP export to {url} failed: {exc}") from exc
    return len(records), url
