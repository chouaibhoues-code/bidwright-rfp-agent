"""Streamlit navigation over the Run, Review and Ops pages (WP-3.6, ADR-050, ADR-053).

The entrypoint draws what every page shares, so it stays put as the user moves between pages:
the run selector, the selected run's status, and its Phoenix links.
"""

from pathlib import Path

import streamlit as st

from app.phoenix_view import sidebar_links
from app.state import current_run, keep_sticky, run_selector

PAGES_DIR = Path(__file__).resolve().parent / "pages"

st.set_page_config(page_title="Bidwright (UNREVIEWED_DRAFT)", layout="wide")
keep_sticky()

navigation = st.navigation(
    [
        st.Page(str(PAGES_DIR / "run.py"), title="Run", url_path="run", default=True),
        st.Page(str(PAGES_DIR / "review.py"), title="Review", url_path="review"),
        st.Page(str(PAGES_DIR / "ops.py"), title="Ops", url_path="ops"),
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
