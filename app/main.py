"""Streamlit navigation entry point over the Run, Review and Ops pages (`WP-3.6`, `CH-94`)."""

from pathlib import Path

import streamlit as st

PAGES_DIR = Path(__file__).resolve().parent / "pages"

st.set_page_config(page_title="Bidwright — UNREVIEWED_DRAFT", layout="wide")

navigation = st.navigation(
    [
        st.Page(str(PAGES_DIR / "run.py"), title="Run", url_path="run", default=True),
        st.Page(str(PAGES_DIR / "review.py"), title="Review", url_path="review"),
        st.Page(str(PAGES_DIR / "ops.py"), title="Ops", url_path="ops"),
    ]
)
navigation.run()
