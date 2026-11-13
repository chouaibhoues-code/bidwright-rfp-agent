# Bidwright

Bidwright reads an RFP and drafts what a bid team needs first: a solution summary of requirements, approach and risks, with every requirement traced to a verified quote from the RFP. Behind the approach sits a solution manifest whose every capability claim was checked against the supplier's evidence by a second model, of another family on the synthetic corpus (the generator's own, flagged, on client documents and on `local`), and which a person approves before anything is drafted from it. A short proposal draft follows from the same records. Later iterations add a proposal pack, generated from the manifest, that a bid team can edit.

> **Status:** `v0.3`, Iteration 3. Bidwright reads one RFP file or a package of PDF, DOCX and XLSX documents, screens each file before parsing and keeps hidden content out of what a model reads, gives every passage a disposition, and checks every quote, number and date in code. It copies the RFP's evaluation factors and weights into a brief and researches the RFP's domain from the brief's topics, never its text. Iteration 3 adds the solution: for each need of the RFP, an agent searches the fictional supplier's knowledge base and drafts claims; an assessor on another model family, where one can be reached, judges each claim against the records it cites; code builds a capability map, and up to three solution options are scored per evaluation factor, with the ranking computed in code; a solution manifest of work packages, effort and assumptions is built and checked in code, its technology claims checked against current library documentation; a risk register is written over it; and the run waits at a gate until a person approves, edits, switches option or rejects, on the command line or in a Streamlit UI. Three ablation ladders measured which steps earn their place, and the four statistical quality scenarios passed on five live repeats of the hero package. Every output is labeled `UNREVIEWED_DRAFT` until a person signs it off.

## The design in one line

A deterministic shell around a probabilistic core: code checks everything code can check, and the LLM does only the judgment and generation that code cannot, inside those checks. Each agent has to earn its place in a measured comparison.

## Setup

1. Install Python 3.12 and [uv](https://docs.astral.sh/uv/).
2. Run `uv sync`.
3. Copy `.env.example` to `.env` and add the keys there. Git ignores `.env`, and `.env.example` holds variable names only. The demo and the tests need no keys.

**Data rule.** The `free` profile runs only on the synthetic corpus listed in `inputs/CORPUS.sha256`, because free-tier prompts may be used by the provider. Your own documents go through `--profile local`, which keeps everything on this machine. If you accept the free tier's terms for a file, `--allow-non-corpus=i-accept-free-tier-terms` lets it run, and the run manifest records that you did.

## Run it on the host, without Docker

| Command | What it does |
|---|---|
| `uv run bidwright demo` | Replays a recorded run of the development RFP, with its committed research pack, with no keys and no network |
| `uv run bidwright run inputs/dev/dev_rfp.pdf` | A live run on the `free` profile (Gemini), which needs `GEMINI_API_KEY` |
| `uv run bidwright run inputs/hero` | A live run on a package folder: the hero RFP with its addendum and XLSX annex |
| `uv run bidwright run inputs/dev/dev_rfp.pdf --profile local` | A live run on a local Ollama model, with `num_ctx` set |
| `uv run bidwright run inputs/dev/dev_rfp.pdf --profile paid` | The same models on the paid tier, which needs `GEMINI_PAID_API_KEY` |
| `uv run bidwright run inputs/hero --until consolidate` | Stops after a node: `verify`, `coverage`, `consolidate`, `brief`, `capability_map`, `solution_gate` or `render` |
| `uv run bidwright approve <run> --role "Solution lead"` | Decides a run waiting at the solution gate, with `--edit FILE` (a YAML list of `{field, value}`), `--option OPT-n`, `--override REASON` or `--reject REASON`; the run then continues. `bidwright run --auto-select` approves the top-ranked option instead, for evaluation |
| `uv run bidwright ui` | The Streamlit UI on http://127.0.0.1:8501: start and follow runs, review records, decide the gate, and see cost, latency and the ladders' results; `--api` also serves the loopback API on port 8001 |
| `uv run bidwright review <run> --role ROLE` | Records verdicts on a run's records, in order of consequence |
| `uv run bidwright run inputs/hero --research live` | Research mode `live`: a NotebookLM deep-research job on the RFP's domain, which needs the owner's `nlm login` and the research server running on the host; `pack`, the default, reads a committed research pack, and `off` skips research |
| `uv run bidwright stop <run>`, `uv run bidwright resume <run>` | Stops a run between steps; continues a stopped, paused, killed or budget-stopped run, with `--raise-budget PERCENT` or, after a spent free quota, `--profile paid` |
| `uv run bidwright run inputs/dev/dev_rfp.pdf --baseline ex0` | EX0, the one-call extraction baseline; `--baseline b0` is the rule-only floor, with no model call |
| `uv run bidwright record inputs/dev/dev_rfp.pdf` | A live run that also writes LLM and Docling cassettes, to `tests/cassettes/demo/` by default |
| `uv run bidwright purge <run>` | Deletes a run's folder and its cache entries; `--expired` deletes every client run past the retention period |
| `uv run bidwright matrix run config/matrices/so-ladder.yaml` | Runs a matrix's rungs and repeats, for the spikes and the ablation ladders; `bidwright seed` freezes a run for a ladder's rungs to start from |
| `uv run bidwright phoenix sync <run>` | Replays a run's spans into the local Phoenix and sends its review verdicts as annotations |
| `uv run bidwright research pack ...`, `uv run bidwright research pin` | Builds a research pack from a live run or a NotebookLM job, on the host; pins the research server's tools after a person reviews a new version |
| `uv run bidwright-eval score outputs/<run>` | Scores a finished run against its gold and writes `evals/results/runs/<run>/` |
| `uv run bidwright-eval explain outputs/<run> GR-0007` | Shows what happened to one gold item: its records, or the stage that lost it |
| `uv run bidwright-eval report so-ladder` | Scores a matrix's runs and decides each rung against the last one kept |
| `uv run pytest -m "not gold and not replay"` | The fast tests; `-m replay` and `-m gold` run the other two sets |

Parsing a PDF, DOCX or XLSX live needs the Docling service: `docker compose up -d docling`. `assess` and `techcheck` use `CEREBRAS_API_KEY`, with `GROQ_API_KEY` as fallback; without either, they take the Gemini model and the run is flagged `SAME_FAMILY`. Replays and tests read recorded Docling responses instead, so they need neither Docker nor a network. Research mode `live` also needs the NotebookLM server on the host, `notebooklm-mcp --transport http` from `notebooklm-mcp-cli` 0.15.8, which binds `127.0.0.1:8000` and should run only during research sessions; client documents never get live research.

`samples/dev/` holds one real run of the development RFP with the Iteration 3 pipeline, made on 2026-11-13 after the drift report's fixes, on the `free` tier with research mode `pack` and automatic approval at the gate, and `evals/results/runs/20261113T042518Z-dev-rfp-db9eeb00-free/scorecard.md` its score: none of the 8 mandatory requirements or the submission hazard missed, precision and recall 100%, every quote verbatim, the hidden trap quarantined and no trap obeyed, all 4 evaluation factors with their weights, the options' ranking reproduced from their scores, 88% of binding requirements mapped to work packages, in 32 requests, $0 on the free tier and $0.08 at the paid price. Three weaknesses show in it. The manifest lists the submission rule as a gap rather than work, so its 100% check fails, and one fact cited a source id that does not exist, which was dropped, so its provenance check fails. The risk step found none of the 3 planted risks. And the brief named a single research topic, so the PDF's research pack was not selected and the run has no research appendix ([`DECISIONS.md`, failure modes hit](DECISIONS.md#failure-modes-hit)). The owner's own gate run of the same PDF, decided with four edits, is in `evals/results/owner-gate/`.

On the hero package, five live repeats of the `v0.3` defaults on 2026-11-13 missed a median of 1 of 45 mandatory requirements (range 1 to 2) and none of the 9 submission hazards, obeyed none of its 10 traps, claimed none of its seeded capability gaps, and captured nearly the same clauses each time (median pairwise Jaccard 0.98), at $0.34 a run at paid list prices, $0 on the free tier: the four statistical scenarios QS-2, QS-3, QS-5 and QS-8 pass. The replayed recording the CI gate holds later runs to misses 3. The ladders behind those defaults, their keep-or-drop decisions and their costs are in [`docs/evaluation.md`](docs/evaluation.md): batched extraction with its context, triage and coverage cut the one-call baseline's 36 misses to 1; the manifest removed every gap the approach text asserted; and neither the risk agent's tool loop nor the `reflect` tool beat a single call, so both stay off. The owner labeled 10 of the assessor's judgments: 7 right, and no claim accepted that its records do not state. On the held-out RFP, whose 22 mandatory requirements come from a list the owner wrote, five repeats of the `v0.1` configuration missed none; it is scored again at release.

Each run writes `outputs/<run>/`: `solution_summary.md` and its JSON twin, `proposal.md`, the compliance matrix as XLSX and CSV, `clarification_questions.md`, `submission_checklist.md` and `review/quarantine.md`; the control register, the frozen text and passages, the candidate ledger with a disposition for every passage, the verified requirements and rejected quotes, the requirement groups, the approach and the risks; `brief.json`, the opportunity brief; the solution's files, from each need's decision and claims, each claim's assessment and the capability map to `options.json`, `manifest.json`, the technology verdicts, the bid signal and memo, and the gate's review file and approval; `domain_brief.json` and `research.json`, the domain research and its record; a context manifest for every LLM call; `ledger.jsonl` with one entry per LLM call, written as each finishes, `run_manifest.json` with the status history and totals, `events.jsonl` with every status change, recovery and security event, `tool_calls.jsonl`, `dead_letter.jsonl` when a call fails for good, and `spans.jsonl` when no Phoenix collector takes the spans.

To see a run's trace tree in Phoenix, start it with `docker compose up -d phoenix` (Compose needs `GEMINI_API_KEY` in `.env`, ADR-002), set `PHOENIX_ENDPOINT=http://127.0.0.1:6006` in `.env`, run `uv run bidwright demo`, and open http://127.0.0.1:6006. Phoenix listens on loopback only and starts with authentication off; `.env.example` shows how to turn it on.

## How a run works

1. `guard` checks every file before any parser sees it: size, pages and paths, scanned pages, and hidden content (invisible or tiny text, hidden runs, sheets and comments), which it removes from the parsed copy and lists for review.
2. `ingest` parses each document with Docling, builds the control register of the package's documents and their precedence, freezes the text and registers sentences, list items and table rows as passages `SRC-0001` and on.
3. `candidates` marks obligation cues on passages, and `triage` zones each section (instructions, evaluation, eligibility, obligations, contract, background) and lists the submission hazards.
4. `extract` reads every passage in context packs, with their neighbors, lead-ins and defined terms, and gives each passage a disposition, returning obligations with exact quotes.
5. `verify` checks every quote and every number or date against the cited passage in code. One targeted repair is allowed; whatever still fails is rejected and logged. `coverage` re-reads any passage left without a disposition, for at most two rounds.
6. `lint` flags vague terms, escape clauses, missing units, broken references and contract terms for legal review, all in code. `consolidate` groups related requirements and drafts clarification questions and discrepancies, one model call per cluster.
7. `brief` builds the opportunity brief from the evaluation and instruction sections: the evaluation factors with their weights and scoring method, needs, scope and constraints, each checked against the passages it cites, with a price factor marked out of scope, and a few research topics, checked for copied RFP text.
8. `discover` researches the RFP's domain from those topics, never its text. By default it loads the committed research pack whose keywords match the topics, with no model call. In research mode `live`, a tool-using agent starts a NotebookLM deep-research job, code waits for it, the agent asks follow-up questions, and one call extracts the domain's patterns, standards, pitfalls and needs, each citing excerpts with their sources' authority tiers. A gateway rule denies any query that shares 8 consecutive words with a passage, and everything research returns is screened and marked external and unverified.
9. `decide`, a tool-using agent, takes each need in turn: a requirement group, or a need the domain research found. It searches the supplier's knowledge base, the RFP and the research it already holds, for at most 4 turns and 6 tool calls, then gives a decision (retrieve evidence, proceed with a gap, ask a clarification, abstain) and at most 3 claims, each citing the records it retrieved. Code drops any id the loop never received.
10. `assess`, on another model family (Cerebras, then Groq) where one can be reached, judges each claim against the records it cites only, never the reasoning behind it; a client run and a `local` run assess with the generator's own model, and each such assessment is flagged `SAME_FAMILY`; a claim with no evidence is `UNVERIFIED` in code. Code then gives each need a status: covered, partial, partner or gap.
11. `options` proposes two or three solutions, the simplest as the baseline, and scores each 0 to 4 on every in-scope evaluation factor with a reason; code applies the RFP's weights and ranks them. `blueprint` expands the top option into the manifest in two calls, and code checks that every binding requirement maps to a work package or a listed gap, that every fact has a source, and that no price or invented date appears. `techcheck` checks each technology claim against library documentation, and a claim found false blocks the gate until it is revised or overridden.
12. `risk` writes a pre-mortem over the manifest in one call, each risk citing passages, with no invented rating. `solution_gate` then writes the review file and waits for a person.
13. `draft` writes three short sections that cite only the records they were given, and `render` validates every record and writes the outputs, including the compliance matrix, the clarification questions, the submission checklist and the summary's research appendix; a schema failure blocks them all.

A supervisor wraps the run: it holds a lock on the run folder, records every status, drains the graph between steps when `bidwright stop` asks, and keeps a journal of every answered call, so `bidwright resume` continues from the last checkpoint without paying twice. A circuit breaker moves calls off a model that keeps failing, and a run with no model left pauses until it is resumed.

## Documents

A suggested reading order: this README, then [`docs/brief.md`](docs/brief.md), the one-page brief for business readers, then the sample summary in `samples/dev/solution_summary.md`, [`DECISIONS.md`](DECISIONS.md), [`docs/architecture.md`](docs/architecture.md), and [`context/Master-Plan.md`](context/Master-Plan.md) for the full vision and the plan.

| File | Holds |
|---|---|
| [`docs/brief.md`](docs/brief.md) | The request as read, success measures, scope, the questions a client would be asked, evidence, risks and open decisions, on one page |
| [`docs/submission.md`](docs/submission.md) | The Iteration 3 submission handoff: deliverable evidence, final checks, packaging, demo link and follow-up preparation |
| [`docs/demo_script_ui.md`](docs/demo_script_ui.md) | The walk-through script for the 60-minute follow-up session: the running system through the Run, Review and Ops pages, the human gate decided live, the trade-offs and likely questions |
| [`DECISIONS.md`](DECISIONS.md) | Architecture and product decisions as short ADRs, and the failure modes hit while building |
| [`ASSUMPTIONS.md`](ASSUMPTIONS.md) | What is assumed, what breaks if it is false, and how it is checked |
| [`TIMELOG.md`](TIMELOG.md) | Rough hours per part |
| `prompts/` | Versioned prompts, each with its "why it works" notes |
| [`docs/architecture.md`](docs/architecture.md) | The architecture of the current tag, under the arc42 headings, with the quality scenarios |
| [`docs/diagrams/`](docs/diagrams/README.md) | Four editable draw.io views for the Iteration 3 submission, with SVG previews |
| [`docs/decision-matrix.md`](docs/decision-matrix.md) | The architecture choices against a published taxonomy of agent design options |
| [`docs/security.md`](docs/security.md) | The threat model, mapped to the OWASP agentic and LLM lists |
| [`docs/governance.md`](docs/governance.md), [`docs/ai-bom.md`](docs/ai-bom.md) | Roles, the trust layer, the NIST AI RMF mapping and the handling of sensitive information; the AI bill of materials, generated from the code |
| [`docs/evaluation.md`](docs/evaluation.md) | The evaluation harness and its results so far |
| [`docs/agents.md`](docs/agents.md), [`docs/reference/`](docs/reference/cli.md) | Generated from the code: roles, prompts, models, tools, the runtime graph, the CLI and the schemas |
| [`docs/designs/`](docs/designs/iteration-3.md) | One design doc per iteration, with its build plan |
| [`research_packs/`](research_packs/README.md) | Recorded domain research for research mode `pack`, one folder per domain |
| [`docs/verification_log.md`](docs/verification_log.md), [`docs/demo_script.md`](docs/demo_script.md) | Technical claims checked against documentation; the five live changes for the follow-up session, each rehearsed with its tests and revert |
| [`context/`](context/Master-Plan.md) | Project management: the plan, open decisions, the backlog and the research register |
