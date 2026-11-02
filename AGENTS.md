# AGENTS.md

Instructions for coding agents working in this repository, such as Claude Code, Copilot, Cursor and opencode.

## Commands

- Install: `uv sync`
- Fast tests, no keys and no network: `uv run pytest -m "not gold and not replay"`
- Replay tests: `uv run pytest -m replay`
- Gold tests, which need `evals/gold` and the corpus specs: `uv run pytest -m gold`
- Lint and format: `uv run ruff check .` and `uv run ruff format --check .`
- Types: `uv run pyright`

## Boundaries

- Keys live only in `.env`. Never write a key anywhere else, and never commit `.env` or `private/`.
- Synthetic RFPs only. No real tender or client document enters the repo, a prompt or a test.
- `src/bidwright` never imports `evals`, and producer code never reads `evals/gold` or `evals/corpus`.
- Every output stays labeled `UNREVIEWED_DRAFT` until a person signs it off.
- Research queries never carry RFP text.
- Each output file has exactly one writer.
- Dates are ISO 8601.
- A design or scope change needs an ADR in `DECISIONS.md` for product and architecture changes, or a line in the Master-Plan change log for process changes.
- Committed documents use a neutral voice, one name per actor and US spelling.

## Layout

| Path | Holds |
|---|---|
| `src/bidwright/` | Producer code: the workflow, agents, tools and harness |
| `evals/` | The separate evaluation harness, `bidwright-eval` |
| `tests/` | Unit, property, fault-injection and replay tests |
| `config/` | Models, limits, agents, thresholds and pricing |
| `prompts/` | Versioned prompts with their notes |
| `docs/` | Engineering documents |
| `context/` | Project management documents, from Iteration 0b |
