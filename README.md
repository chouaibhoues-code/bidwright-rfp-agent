# Bidwright

Bidwright reads an RFP and drafts what a bid team needs first: a solution summary of requirements, approach and risks, with every requirement traced to a verified quote from the RFP. A short proposal draft follows from the same records. Later iterations add a proposal pack, generated from one solution manifest, that a bid team can edit.

> **Status:** `v0.1`, Iteration 1. Bidwright reads one RFP file or a package of PDF, DOCX and XLSX documents, screens each file before parsing and keeps hidden content out of what a model reads, sends every passage to extraction so that each gets a disposition, and checks every quote, number and date in code. Each run writes the solution summary, a short proposal, a compliance matrix, clarification questions and a submission checklist. A separate harness scores runs against known answers and names the stage that lost each miss, and CI holds the replayed hero package to its recorded baseline. Every output is labeled `UNREVIEWED_DRAFT` until a person signs it off.

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
| `uv run bidwright demo` | Replays a recorded run of the development RFP, with no keys and no network |
| `uv run bidwright run inputs/dev/dev_rfp.pdf` | A live run on the `free` profile (Gemini), which needs `GEMINI_API_KEY` |
| `uv run bidwright run inputs/hero` | A live run on a package folder: the hero RFP with its addendum and XLSX annex |
| `uv run bidwright run inputs/dev/dev_rfp.pdf --profile local` | A live run on a local Ollama model, with `num_ctx` set |
| `uv run bidwright run inputs/dev/dev_rfp.pdf --profile paid` | The same models on the paid tier, which needs `GEMINI_PAID_API_KEY` |
| `uv run bidwright run inputs/hero --until consolidate` | Stops after a node: `verify`, `coverage`, `consolidate` or `render` |
| `uv run bidwright run inputs/dev/dev_rfp.pdf --baseline ex0` | EX0, the one-call extraction baseline; `--baseline b0` is the rule-only floor, with no model call |
| `uv run bidwright record inputs/dev/dev_rfp.pdf` | A live run that also writes LLM and Docling cassettes, to `tests/cassettes/demo/` by default |
| `uv run bidwright purge <run>` | Deletes a run's folder and its cache entries; `--expired` deletes every client run past the retention period |
| `uv run bidwright matrix run config/matrices/s03-batch.yaml` | Runs a matrix's rungs and repeats, for the spikes and later the ablations |
| `uv run bidwright-eval score outputs/<run>` | Scores a finished run against its gold and writes `evals/results/runs/<run>/` |
| `uv run bidwright-eval explain outputs/<run> GR-0007` | Shows what happened to one gold item: its records, or the stage that lost it |
| `uv run pytest -m "not gold and not replay"` | The fast tests; `-m replay` and `-m gold` run the other two sets |

Parsing a PDF, DOCX or XLSX live needs the Docling service: `docker compose up -d docling`. Replays and tests read recorded Docling responses instead, so they need neither Docker nor a network.

`samples/dev/` holds one real run of the development RFP with the Iteration 1 pipeline, made on the paid key with the `free` profile's models after that day's free quota was spent, and `evals/results/runs/20261104T211354Z-dev-rfp-db9eeb00-paid/scorecard.md` its score against gold v2: none of the 8 mandatory requirements or the submission hazard missed, precision and recall 100%, every quote verbatim, the hidden trap quarantined and no trap action taken, every binding requirement mapped to an approach item, and one of three planted risks found, in 13 requests for $0.07. The demo replays that same run. On the hero package, the replayed recording misses 8 of 45 mandatory requirements, all of them designed traps, and none of the 9 submission hazards; that is the baseline the gate holds later runs to ([`docs/evaluation.md`](docs/evaluation.md)). Two earlier results, from the Iteration 0a pipeline against gold v1: EX0, the one-call extraction baseline, scored the same as the full thread on the four-page development RFP (`evals/results/runs/20261103T030640Z-dev-rfp-3c582e4c-free-ex0/scorecard.md`, 11 requests), so the extraction comparison runs on the hero package in Iteration 3. On `--profile local`, `qwen3.5:4b` on this laptop's CPU completed the same run in 17 minutes (`evals/results/runs/20261103T030503Z-dev-rfp-3c582e4c-local/scorecard.md`): no mandatory requirement or hazard missed, but none of the three planted risks found.

Each run writes `outputs/<run>/`: `solution_summary.md` and its JSON twin, `proposal.md`, the compliance matrix as XLSX and CSV, `clarification_questions.md`, `submission_checklist.md` and `review/quarantine.md`; the control register, the frozen text and passages, the candidate ledger with a disposition for every passage, the verified requirements and rejected quotes, the requirement groups, the approach and the risks; a context manifest for every packed call; `ledger.jsonl` with one entry per LLM call, `run_manifest.json` with the status and totals, and `spans.jsonl` when no Phoenix collector takes the spans.

To see a run's trace tree in Phoenix, start it with `docker compose up -d phoenix` (Compose needs `GEMINI_API_KEY` in `.env`, ADR-002), set `PHOENIX_ENDPOINT=http://127.0.0.1:6006` in `.env`, run `uv run bidwright demo`, and open http://127.0.0.1:6006. Phoenix listens on loopback only and starts with authentication off; `.env.example` shows how to turn it on.

## How a run works

1. `guard` checks every file before any parser sees it: size, pages and paths, scanned pages, and hidden content (invisible or tiny text, hidden runs, sheets and comments), which it removes from the parsed copy and lists for review.
2. `ingest` parses each document with Docling, builds the control register of the package's documents and their precedence, freezes the text and registers sentences, list items and table rows as passages `SRC-0001` and on.
3. `candidates` marks obligation cues on passages, and `triage` zones each section (instructions, evaluation, eligibility, obligations, contract, background) and lists the submission hazards.
4. `extract` reads every passage in context packs, with their neighbors, lead-ins and defined terms, and gives each passage a disposition, returning obligations with exact quotes.
5. `verify` checks every quote and every number or date against the cited passage in code. One targeted repair is allowed; whatever still fails is rejected and logged. `coverage` re-reads any passage left without a disposition, for at most two rounds.
6. `lint` flags vague terms, escape clauses, missing units, broken references and contract terms for legal review, all in code. `consolidate` groups related requirements and drafts clarification questions and discrepancies, one model call per cluster.
7. `approach` maps approach items to the verified requirements, and `risk`, a tool-using agent, searches the RFP and does date arithmetic through a gateway that checks every call, for at most 4 turns and 6 tool calls.
8. `draft` writes three short sections that cite only the records they were given, and `render` validates every record and writes the outputs, including the compliance matrix, the clarification questions and the submission checklist; a schema failure blocks them all.

## Documents

A suggested reading order: this README, then [`docs/brief.md`](docs/brief.md), the one-page brief for business readers, then the sample summary in `samples/dev/solution_summary.md`, [`DECISIONS.md`](DECISIONS.md), [`docs/architecture.md`](docs/architecture.md), and [`context/Master-Plan.md`](context/Master-Plan.md) for the full vision and the plan.

| File | Holds |
|---|---|
| [`docs/brief.md`](docs/brief.md) | The request as read, success measures, scope, the questions a client would be asked, evidence, risks and open decisions, on one page |
| [`DECISIONS.md`](DECISIONS.md) | Architecture and product decisions as short ADRs, and the failure modes hit while building |
| [`ASSUMPTIONS.md`](ASSUMPTIONS.md) | What is assumed, what breaks if it is false, and how it is checked |
| [`TIMELOG.md`](TIMELOG.md) | Rough hours per part |
| `prompts/` | Versioned prompts, each with its "why it works" notes |
| [`docs/architecture.md`](docs/architecture.md) | The architecture of the current tag, under the arc42 headings, with the quality scenarios |
| [`docs/decision-matrix.md`](docs/decision-matrix.md) | The architecture choices against a published taxonomy of agent design options |
| [`docs/security.md`](docs/security.md) | The threat model, mapped to the OWASP agentic and LLM lists |
| [`docs/governance.md`](docs/governance.md), [`docs/ai-bom.md`](docs/ai-bom.md) | Roles, the trust layer, the NIST AI RMF mapping and the handling of sensitive information; the AI bill of materials, generated from the code |
| [`docs/evaluation.md`](docs/evaluation.md) | The evaluation harness and its results so far |
| [`docs/agents.md`](docs/agents.md), [`docs/reference/`](docs/reference/cli.md) | Generated from the code: roles, prompts, models, tools, the runtime graph, the CLI and the schemas |
| [`docs/designs/`](docs/designs/iteration-1.md) | One design doc per iteration, with its build plan |
| [`docs/verification_log.md`](docs/verification_log.md), [`docs/demo_script.md`](docs/demo_script.md) | Technical claims checked against documentation; the demo's structure |
| [`context/`](context/Master-Plan.md) | Project management: the plan, open decisions, the backlog and the research register |
