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

from app.data import RunData, list_runs, load_manifest, load_run_data

RUN_KEY = "run"
PENDING_KEY = "run_pending_select"
# Every page widget whose value outlives a page switch.
STICKY_KEYS = (
    "run_search",
    "run_kinds",
    "run_status_filter",
    "run_tab_requirement",
    "run_doc",
    "run_page",
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
    for key in (RUN_KEY, MATRIX_KEY, *STICKY_KEYS):
        if key in st.session_state:
            st.session_state[key] = st.session_state[key]


MATRIX_KEY = "show_matrix_runs"


def run_names() -> dict[str, Path]:
    """The runs the selector offers, newest first; a matrix's runs only when asked for."""
    matrices = bool(st.session_state.get(MATRIX_KEY))
    return {
        run.name: run for run in list_runs() if matrices or run.parent.parent.name != "matrices"
    }


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
    st.sidebar.selectbox(
        "Run", options=list(names), key=RUN_KEY, on_change=_to_url, format_func=run_label
    )
    st.sidebar.checkbox("Show matrix runs", key=MATRIX_KEY)
    _to_url()


@st.cache_data(ttl=5, show_spinner=False)
def run_label(name: str) -> str:
    """A run as the selector lists it: its time, input, path and status."""
    run_dir = run_names().get(name)
    if run_dir is None:
        return name
    try:
        manifest = load_manifest(run_dir)
    except (OSError, ValueError):
        return name
    args = manifest.run_args
    source = Path(str(args.get("source") or "")).name or (
        manifest.documents[0].file if manifest.documents else "?"
    )
    path = (manifest.switches or {}).get("solution") or "approach"
    until = args.get("until") or "render"
    stop = "" if until == "render" else f", to {until}"
    stamp = name[:16] if name[:8].isdigit() else name
    return f"{stamp} | {source} | {path}{stop} | {manifest.status}"


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
