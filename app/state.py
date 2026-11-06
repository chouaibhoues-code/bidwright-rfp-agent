"""State the pages share (ADR-053).

The run selector runs in `app/main.py`, the entrypoint, so Streamlit keeps it on every page,
and it follows the URL's `?run=` so a link names its run. The filters each page sets keep
their values when the user moves to another page and back: Streamlit removes a widget's
state at the end of a run in which the widget was not drawn, unless the run saves the key
again first, which `keep_sticky` does in the entrypoint (Streamlit's documented option for
`st.navigation` apps).
"""

from pathlib import Path
from typing import Any

import streamlit as st

from app.data import RunData, list_runs, load_run_data

RUN_KEY = "run"
PENDING_KEY = "run_pending_select"
# Every page widget whose value outlives a page switch.
STICKY_KEYS = (
    "run_search",
    "run_kinds",
    "run_status_filter",
    "run_tab_requirement",
    "review_role",
    "review_kinds",
    "review_unreviewed_only",
    "review_auto_sync",
    "launch_input",
    "launch_profile",
    "launch_research",
    "launch_solution",
    "launch_risk_mode",
    "launch_reflect",
    "launch_until",
    "launch_auto_select",
)


def keep_sticky() -> None:
    """Save each sticky key again, so its widget's value survives a page without it."""
    for key in (RUN_KEY, *STICKY_KEYS):
        if key in st.session_state:
            st.session_state[key] = st.session_state[key]


def run_names() -> dict[str, Path]:
    return {run.name: run for run in list_runs()}


def _follow_url() -> None:
    wanted = st.query_params.get(RUN_KEY)
    names = run_names()
    if wanted and wanted in names and st.session_state.get(RUN_KEY) != wanted:
        st.session_state[RUN_KEY] = wanted


def _to_url() -> None:
    chosen = st.session_state.get(RUN_KEY)
    if chosen:
        st.query_params[RUN_KEY] = chosen


def run_selector() -> None:
    """The sidebar's run selector, drawn by the entrypoint on every page."""
    names = run_names()
    if not names:
        st.sidebar.text("No run under outputs/ yet: start one on the Run page.")
        return
    _follow_url()
    pending = st.session_state.pop(PENDING_KEY, None)
    if pending in names:
        st.session_state[RUN_KEY] = pending
    if st.session_state.get(RUN_KEY) not in names:
        st.session_state[RUN_KEY] = next(iter(names))
    st.sidebar.selectbox("Run", options=list(names), key=RUN_KEY, on_change=_to_url)
    _to_url()


def select_run(name: str) -> None:
    """Select `name` at the next rerun, before the sidebar draws its selector: Streamlit refuses
    a change to a drawn widget's value. The caller reruns."""
    st.session_state[PENDING_KEY] = name


def current_run() -> RunData | None:
    """The selected run's data, the newest run's when none is selected (a page alone in a
    test), or None when there is no run."""
    names = run_names()
    if not names:
        return None
    chosen = st.session_state.get(RUN_KEY)
    run_dir = names.get(chosen) if isinstance(chosen, str) else None
    return load_run_data(run_dir or next(iter(names.values())))


def default(key: str, value: Any) -> None:
    """Give a widget's key its first value without passing `value=` to the widget, so a
    sticky value is never reset."""
    if key not in st.session_state:
        st.session_state[key] = value
