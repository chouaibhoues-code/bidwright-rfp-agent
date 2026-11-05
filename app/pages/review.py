"""The Review page (`WP-3.6`, `CH-94`): `review/quarantine.md` and the summary's open questions,
shown strictly as plain text and tables, never as Markdown or HTML.
"""

import streamlit as st

from app.data import select_run_data
from bidwright.render import STATUS_LINE


def render_review_page() -> None:
    st.title("Bidwright — Review")
    st.text(STATUS_LINE)
    data = select_run_data()
    if data is None:
        return

    st.header("Quarantine and suspect text (review/quarantine.md)")
    if data.quarantine_text is not None:
        st.code(data.quarantine_text, language=None)
    else:
        st.text("No review/quarantine.md found for this run.")

    st.header("Open questions")
    bundle = data.summary_bundle
    if bundle is None:
        st.text("No solution_summary.json found for this run.")
        return

    rows = [
        {
            "id": "",
            "origin": "summary",
            "text": q.text,
            "src_ids": ", ".join(q.src_ids),
        }
        for q in bundle.open_questions
    ] + [
        {
            "id": q.id,
            "origin": q.origin,
            "text": q.text,
            "src_ids": ", ".join(q.src_ids),
        }
        for q in bundle.brief_questions
    ]
    if rows:
        st.table(rows)
        for row in rows:
            label = f"{row['id']}: " if row["id"] else ""
            st.text(f"{label}{row['text']} [{row['src_ids']}]")
    else:
        st.text("None.")


render_review_page()
