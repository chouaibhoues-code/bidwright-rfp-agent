"""The Ops page (`WP-3.6`, `CH-94`): ledger requests, four-layer tokens, cost, shadow cost and
latency by node and by model; evaluation scores from `evals/results/runs/<run>/` when present;
`keep_or_drop` ablation ladder reports from `evals/results/<matrix>/report.json`; matrix totals
summed from `outputs/matrices/<matrix>/*/ledger.jsonl`; and Phoenix (ADR-053): the run's
traces and sessions, and buttons that send the run, its code checks and review verdicts, and its
scores, each through the command that owns it.
"""

import streamlit as st

import app.actions as actions
from app.data import RunData, load_ladder_reports, load_matrix_totals
from app.phoenix_view import links_for
from app.state import current_run
from bidwright.obs.replay import replay_spans
from bidwright.preflight import Refused


def _phoenix(data: RunData) -> None:
    st.header("Phoenix")
    links = links_for(data)
    if not links.available:
        st.text(
            "Phoenix does not answer. Start it with docker compose up -d phoenix, or set"
            " PHOENIX_ENDPOINT; a run made meanwhile keeps its spans in spans.jsonl."
        )
        return
    st.text(f"Project: {links.project or 'none yet for this run'}")
    for trace, page in links.traces:
        if page:
            st.link_button(f"Trace {trace[:12]}", page)
        else:
            st.text(f"Trace {trace[:12]}: not in Phoenix yet")
    if links.sessions:
        st.link_button("All sessions (one per run)", links.sessions)
    left, right = st.columns(2)
    if left.button("Send the run, its checks and its review verdicts", key="ops_sync"):
        done = actions.run(actions.phoenix_sync(data.run_dir))
        st.code((done.stdout or "") + (done.stderr or ""), language=None)
        st.cache_data.clear()
    if right.button("Score the run and send its scores", key="ops_eval"):
        done = actions.run(actions.eval_to_phoenix(data.run_dir))
        st.code((done.stdout or "") + (done.stderr or ""), language=None)


def _run_sections(data: RunData) -> None:
    _phoenix(data)

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
        "Replaying a run twice sends its spans twice, so the trace appears twice in Phoenix;"
        " the send button above replays only a trace Phoenix does not hold."
    )
    if st.button("Replay spans.jsonl to Phoenix", disabled=not data.has_spans):
        try:
            count, url = replay_spans(data.run_dir)
            st.text(f"Replayed {count} spans to {url}.")
        except Refused as exc:
            st.text(f"Refused: {exc}")


def _matrix_sections() -> None:
    st.header("Ablation ladders (keep_or_drop)")
    ladder_reports = load_ladder_reports()
    if ladder_reports:
        for report in ladder_reports:
            st.subheader(f"Ladder: {report.matrix}")
            st.table([row.as_dict() for row in report.rows])
            for row in report.rows:
                st.text(
                    f"{report.matrix} {row.rung} (vs {row.comparator}): "
                    f"verdict={row.verdict}, interval={row.interval}, "
                    f"medians={row.medians}, cost_per_avoided_miss={row.cost_per_avoided_miss}"
                )
    else:
        st.text("No keep_or_drop ladder reports found under evals/results/.")

    st.header("Matrix totals")
    matrix_totals = load_matrix_totals()
    if matrix_totals:
        st.table([row.as_dict("matrix") for row in matrix_totals])
        for row in matrix_totals:
            st.text(
                f"Matrix {row.group}: requests={row.requests}, "
                f"tokens_in={row.tokens_in}, tokens_out={row.tokens_out}, "
                f"cost_usd={row.cost_usd:g}"
            )
    else:
        st.text("No matrix ledgers found under outputs/matrices/.")


def render_ops_page() -> None:
    st.title("Bidwright: Ops")
    data = current_run()
    if data is None:
        st.text("No run folders with run_manifest.json found under outputs/.")
    else:
        _run_sections(data)
    _matrix_sections()


render_ops_page()
