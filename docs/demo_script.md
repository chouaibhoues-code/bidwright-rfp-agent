# Demo script (3-5 minutes)

The full script is written at release. Its structure is fixed now, so every tag can be shown the same way.

| Part | Time | What is shown |
|---|---|---|
| 1. The problem | 30 s | A bid team receives an RFP package and must not miss a mandatory requirement |
| 2. The solution summary | 60 s | `outputs/<run>/solution_summary.md`: submission hazards first, then requirements with verified quotes, approach and risks |
| 3. The agentic step | 60 s | The `risk` loop's tool calls in the trace, and where it stopped |
| 4. Evaluation | 60 s | The scorecard: missed mandatory requirements, with the stage that lost each miss |
| 5. Cost and latency | 30 s | Ledger totals per node and per run, with the shadow price |
| 6. What a person still decides | 30 s | Every output stays `UNREVIEWED_DRAFT` until sign-off |

## Commands at `v0.1`

| Part | Command or file |
|---|---|
| 2 | `uv run bidwright demo`, then open the `solution_summary.md` it names; beside it, `compliance_matrix.xlsx`, `clarification_questions.md`, `submission_checklist.md` and `review/quarantine.md`, which lists the hidden trap `guard` removed before parsing |
| 3 | `spans.jsonl` in the same folder: the `node.risk` agent span with its `bidwright.stop_reason`, `turns` and `tool_calls`, and its `tool.search_rfp` and `tool.date_calc` children; with `PHOENIX_ENDPOINT` set, the same tree in Phoenix |
| 4 | `uv run bidwright-eval score outputs/<run>` on the demo's run, which misses none of the 8 mandatory requirements, so its funnel is empty; for misses, the hero package's committed scorecard, `evals/results/runs/20261104T211602Z-hero-paid/scorecard.md`, with 8 of 45 charged to `extract` against B0's 13 ([`evaluation.md`](evaluation.md)); and `uv run bidwright-eval explain outputs/<run> GR-0003` for one gold item |
| 5 | `ledger.jsonl` and the `totals` in `run_manifest.json`; each entry's `retry_reasons` says why an attempt was retried |
| 6 | The status line at the top of `solution_summary.md`, `proposal.md` and the review files, and the compliance status `UNVERIFIED` on every row of the matrix |
