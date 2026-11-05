"""The Ops page (`WP-3.6`, `CH-94`): ledger requests, four-layer tokens, cost, shadow cost and
latency by node and by model; evaluation scores from `evals/results/runs/<run>/` when present;
and OTLP span replay into Phoenix.
"""

import streamlit as st

from app.data import select_run_data
from bidwright.obs.replay import replay_spans
from bidwright.preflight import Refused


def render_ops_page() -> None:
    st.title("Bidwright — Ops")
    data = select_run_data()
    if data is None:
        return

    st.header("Ledger totals")
    st.table([data.ledger_totals.as_dict("Scope")])

    st.subheader("By node")
    if data.by_node:
        st.table([row.as_dict("node") for row in data.by_node])
    else:
        st.text("No ledger entries.")

    st.subheader("By model")
    if data.by_model:
        st.table([row.as_dict("model") for row in data.by_model])
    else:
        st.text("No ledger entries.")

    st.subheader("Ledger calls")
    if data.ledger:
        st.dataframe(
            [
                {
                    "node": entry.node,
                    "agent": entry.agent,
                    "provider": entry.provider,
                    "model": entry.model,
                    "repeat": entry.repeat,
                    "tokens_in": entry.tokens_in,
                    "tokens_out": entry.tokens_out,
                    "tokens_cached": entry.tokens_cached,
                    "tokens_thinking": entry.tokens_thinking,
                    "cost_usd": entry.cost_usd,
                    "shadow_cost_usd": entry.shadow_cost_usd,
                    "latency_ms": entry.latency_ms,
                    "retries": entry.retries,
                    "replayed": entry.replayed,
                }
                for entry in data.ledger
            ]
        )

    st.header("Scores")
    if data.scores.scores is not None or data.scores.scorecard_text is not None:
        if data.scores.scores is not None:
            scalar_rows = [
                {"metric": k, "value": str(v)}
                for k, v in data.scores.scores.items()
                if not isinstance(v, (dict, list))
            ]
            if scalar_rows:
                st.table(scalar_rows)
        if data.scores.scorecard_text is not None:
            st.code(data.scores.scorecard_text, language=None)
    else:
        st.text("No scores recorded for this run.")

    st.header("Phoenix span replay")
    st.text(
        "Note: replaying a run twice sends its spans twice, so the trace appears twice in Phoenix."
    )
    if st.button("Replay spans.jsonl to Phoenix", disabled=not data.has_spans):
        try:
            count, url = replay_spans(data.run_dir)
            st.text(f"Replayed {count} spans to {url}.")
        except Refused as exc:
            st.text(f"Refused: {exc}")


render_ops_page()
