"""Streamlit navigation over the Run, Review and Ops pages (WP-3.6, ADR-050, ADR-053, ADR-060).

The entrypoint draws what every page shares, so it stays put as the user moves between pages:
the run selector, the selected run's status, and its Phoenix links.

The page scripts live in `app/views/`, not `app/pages/`: Streamlit serves a `pages/` folder
next to the entrypoint until some session has called `st.navigation`, so the first browser to
open a link such as `/review?run=...` after the UI starts would get that folder's pages, with
no run selector (ADR-060).
"""

from pathlib import Path

import streamlit as st

from app.phoenix_view import sidebar_links
from app.state import current_run, keep_sticky, run_selector

VIEWS_DIR = Path(__file__).resolve().parent / "views"

st.set_page_config(page_title="Bidwright (UNREVIEWED_DRAFT)", layout="wide")
keep_sticky()

navigation = st.navigation(
    [
        st.Page(str(VIEWS_DIR / "run.py"), title="Run", url_path="run", default=True),
        st.Page(str(VIEWS_DIR / "review.py"), title="Review", url_path="review"),
        st.Page(str(VIEWS_DIR / "ops.py"), title="Ops", url_path="ops"),
    ]
)
run_selector()
data = current_run()
if data is not None:
    st.sidebar.text(f"Status: {data.manifest.status}")
    if data.manifest.status_reason:
        st.sidebar.text(data.manifest.status_reason[:300])
    sidebar_links(data)
navigation.run()
