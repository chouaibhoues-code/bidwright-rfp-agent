"""Phoenix in the pages (ADR-053): whether it answers, the selected run's trace links, and a
span's link for a record. Lookups are cached for a few seconds and time out after one, so a
page never waits on a Phoenix that is down; then the pages show no link and say how to send
the run.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path

import streamlit as st

from app.data import RunData
from bidwright.fileio import read_lines
from bidwright.obs.phoenix import PhoenixClient, PhoenixUnavailable, run_spans
from bidwright.preflight import Refused

TTL_S = 10


@dataclass(frozen=True)
class TraceLinks:
    available: bool
    traces: list[tuple[str, str | None]] = field(default_factory=list)  # (trace id, its page)
    sessions: str | None = None
    node_ids: dict[str, str] = field(default_factory=dict)  # span id -> Phoenix's span id
    project: str | None = None


def _client(data_class: str) -> PhoenixClient | None:
    try:
        client = PhoenixClient.from_env(data_class)
    except Refused:
        return None
    client.timeout = 1.0
    return client


@st.cache_data(ttl=TTL_S, show_spinner=False)
def trace_links(run_dir: str, data_class: str, trace_ids: tuple[str, ...]) -> TraceLinks:
    client = _client(data_class)
    if client is None or not client.available():
        return TraceLinks(False)
    ids = list(trace_ids) or list(run_spans(Path(run_dir)).roots)
    traces: list[tuple[str, str | None]] = []
    node_ids: dict[str, str] = {}
    project: str | None = None
    try:
        for trace in ids:
            project = client.find_project(trace)
            traces.append((trace, client.trace_url(trace, project=project) if project else None))
            if project:
                node_ids |= client.span_node_ids(trace, project)
        return TraceLinks(True, traces, client.sessions_url(), node_ids, project)
    except PhoenixUnavailable:
        return TraceLinks(False)


def links_for(data: RunData) -> TraceLinks:
    return trace_links(str(data.run_dir), data.manifest.data_class, tuple(data.manifest.trace_ids))


def span_url(data: RunData, links: TraceLinks, span_id: str | None) -> str | None:
    """The Phoenix page of one span of the run, when Phoenix holds it."""
    if span_id is None or span_id not in links.node_ids:
        return None
    trace = _trace_of(data.run_dir, span_id)
    page = dict(links.traces).get(trace or "")
    return f"{page}?selectedSpanNodeId={links.node_ids[span_id]}" if page else None


def _trace_of(run_dir: Path, span_id: str) -> str | None:
    for line in read_lines(run_dir / "spans.jsonl"):
        context = json.loads(line).get("context", {})
        if context.get("span_id", "").removeprefix("0x") == span_id:
            return context.get("trace_id", "").removeprefix("0x")
    return None


def sidebar_links(data: RunData) -> None:
    links = links_for(data)
    if not links.available:
        st.sidebar.text("Phoenix: not reachable")
        return
    pages = [page for _, page in links.traces if page]
    if pages:
        st.sidebar.link_button("Open the run's trace in Phoenix", pages[-1])
    else:
        st.sidebar.text("Phoenix: this run's trace is not there yet (Ops page: send it)")
    if links.sessions:
        st.sidebar.link_button("Phoenix sessions", links.sessions)


__all__ = ["TraceLinks", "links_for", "sidebar_links", "span_url", "trace_links"]
