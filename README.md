# Bidwright

Bidwright reads an RFP and drafts what a bid team needs first: a solution summary of requirements, approach and risks, with every requirement traced to a verified quote from the RFP. A short proposal draft follows from the same records. Later iterations add a proposal pack, generated from one solution manifest, that a bid team can edit.

> **Status:** Iteration 0a, the walking skeleton. The thread from RFP to solution summary and proposal draft runs end to end, with a scored evaluation, a replayable demo and traces. Every output is labeled `UNREVIEWED_DRAFT` until a person signs it off.

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
| `uv run bidwright run inputs/dev/dev_rfp.pdf --profile local` | A live run on a local Ollama model, with `num_ctx` set |
| `uv run bidwright run inputs/dev/dev_rfp.pdf --baseline ex0` | EX0, the one-call extraction baseline |
| `uv run bidwright record inputs/dev/dev_rfp.pdf` | A live run that also writes replay cassettes to `tests/cassettes/demo/` |
| `uv run bidwright-eval score outputs/<run>` | Scores a finished run against its gold and writes `evals/results/runs/<run>/` |
| `uv run pytest -m "not gold and not replay"` | The fast tests; `-m replay` and `-m gold` run the other two sets |

`samples/dev-free/` holds one real run of the development RFP on the `free` profile, and `evals/results/runs/20261103T030541Z-dev-rfp-3c582e4c-free/scorecard.md` its score: no mandatory requirement or submission hazard missed, every quote verbatim, every binding requirement mapped to an approach item, and one of three planted risks found, in 11 requests. One extra item, the buyer's invitation to bid recorded as optional, matches no gold clause, so precision is 92-100% until it is adjudicated. The demo replays that same run. EX0, the one-call extraction baseline, scored the same on this four-page RFP (`evals/results/runs/20261103T030640Z-dev-rfp-3c582e4c-free-ex0/scorecard.md`, 11 requests), so the extraction comparison waits for the longer hero RFP in Iteration 1. On `--profile local`, `qwen3.5:4b` on this laptop's CPU completed the same run in 17 minutes (`evals/results/runs/20261103T030503Z-dev-rfp-3c582e4c-local/scorecard.md`): no mandatory requirement or hazard missed, but none of the three planted risks found.

Each run writes `outputs/<run>/`: `solution_summary.md` and its JSON twin, `proposal.md`, the frozen text and passages, the verified requirements and rejected quotes, the approach, the risks, `ledger.jsonl` with one entry per LLM call, `run_manifest.json` with the status and totals, and `spans.jsonl` when no Phoenix collector takes the spans.

To see a run's trace tree in Phoenix, start it with `docker compose up -d phoenix` (Compose needs `GEMINI_API_KEY` in `.env`, ADR-002), set `PHOENIX_ENDPOINT=http://127.0.0.1:6006` in `.env`, run `uv run bidwright demo`, and open http://127.0.0.1:6006. Phoenix listens on loopback only and starts with authentication off; `.env.example` shows how to turn it on.

## How a run works

1. `ingest` freezes the PDF's text and registers sentences, list items and table rows as passages `SRC-0001` and on.
2. `extract` reads batches of 20 passages in parallel and returns obligations with exact quotes.
3. `verify` checks every quote against its cited passage in code. One targeted repair is allowed; whatever still fails is rejected and logged.
4. `approach` maps approach items to the verified requirements.
5. `risk` is a tool-using agent: it searches the RFP and does date arithmetic through a gateway that checks every call, for at most 4 turns and 6 tool calls, then returns a typed risk register. Generic or rated risks are rejected.
6. `draft` writes three short sections that cite only the records they were given.
7. `render` validates every record and writes the outputs; a schema failure blocks them all.

## Documents

| File | Holds |
|---|---|
| `DECISIONS.md` | Architecture and product decisions, and the failure modes hit while building |
| `ASSUMPTIONS.md` | What is assumed, what breaks if it is false, and how it is checked |
| `TIMELOG.md` | Rough hours per part |
| `prompts/` | Versioned prompts, each with its "why it works" notes |
| `docs/` | Engineering documents, including the verification log and the demo script |
| `context/` | Project management: plan, decisions in progress, backlog, research register (from Iteration 0b) |
