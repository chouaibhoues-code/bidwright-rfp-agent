# Live-change script

Updated 2026-11-06. The follow-up session asks for a small change made live. This script covers the five changes named in the Master-Plan's release step: change a threshold, add a `lint` rule, swap a model role, add a tool to an agent's allowlist, and add a zone. Each change was rehearsed on 2026-11-06 at commit `fcdb5c7`, in a separate worktree. The outputs quoted below are what those rehearsals printed. The [walk-through script](demo_script_ui.md) covers the rest of the session.

## Choosing a change

| Change | Files | Needs a live run | Time |
|---|---|---|---|
| 1. Threshold | `config/thresholds.yaml` | No | 5 minutes |
| 2. Lint rule | `config/lint.yaml`, `tests/test_lint.py` | No, unless the new pattern matches a corpus quote | 5 minutes |
| 3. Model role | `config/models.yaml`, two test expectations, generated docs | Only to show the new model answering | 10 minutes |
| 4. Tool allowlist | `config/agents.yaml`, `src/bidwright/graph/build.py`, generated docs | Yes, to show the agent using the tool | 10 minutes |
| 5. Zone | `config/zones.yaml`, `src/bidwright/schemas.py`, `prompts/triage.md`, version pins, generated docs | Yes | 15 minutes |

The times are estimates. Unless the reviewers ask for a particular change, show change 2 as the offline case, then change 4 if time remains.

## Why some changes replay and others need a live run

A cassette's key hashes six things: the prompt text, the response schema, the tool definitions, the model, the decoding settings and the input. A change that leaves all six unchanged for every recorded call still replays, so `bidwright demo` and `pytest -m replay` stay green with no keys. A change to any of the six misses its cassette. The replay then ends `UNRECOVERABLE_FAULT`, with `CassetteMissing: no cassette sha256:… for <model>`.

That failure is the guard working: CI refuses a change that no recording covers. A replay looks up each call under every model its role lists, primary first, so reordering a role's models still replays.

A live run on `free` reaches the gate in about four minutes of active time on the development RFP. To start one, use the Run page's **Start a run**, or run `uv run bidwright run inputs/dev/dev_rfp.pdf --profile free`. It waits at the gate, after `triage`, the `decide` loops and `risk` have run, so all five changes show before any gate decision.

## Before and after each change

Work on a branch, so that discarding the change is one step:

```text
git switch -c live/<change>
```

After editing, run the checks the change touches, listed under each change. Before keeping any change, run the full set:

```text
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run python scripts/gen_docs.py --check
uv run pytest -m "not gold and not replay"
```

To discard a change, restore the files that change lists, then delete the branch:

```text
git switch main
git branch -D live/<change>
```

Restore only the files named under each change. Restoring a whole folder would also discard unrelated uncommitted edits. A change kept after the session needs an ADR in `DECISIONS.md` or a line in the Master-Plan change log, as `AGENTS.md` requires.

## 1. Change a threshold (offline)

This change tightens the regression gate's cost warning. The gate warns when a run's shadow cost passes 1.5 times its baseline's; after the change, the limit is 1.05.

First, write a baseline from the research-off run, and gate the research-pack run against it:

```text
uv run bidwright-eval baseline outputs/20261106T002941Z-dev-rfp-db9eeb00-free --out private/live/dev-research-off.json
uv run bidwright-eval gate outputs/20261106T001835Z-dev-rfp-db9eeb00-free --baseline private/live/dev-research-off.json
```

The gate prints `GATE PASSED`, and its cost line reads:

```text
pass    cost_increase_ratio    shadow cost $0.10647845 against $0.09962445: x1.069 (limit x1.5)
```

Then edit `config/thresholds.yaml`: `cost_increase_ratio: 1.5` becomes `cost_increase_ratio: 1.05`. Run the gate again. It prints `GATE PASSED with warnings`, and the cost line now starts with `warn` and ends with `(limit x1.05)`. `uv run pytest tests/test_gates.py` reports 10 passed, since the tests read the configured thresholds.

What it shows:
- The gate is configuration, applied in code, with no model call. `gate` scores the run in memory and writes nothing to `evals/results/`.
- The two runs differ in research mode (`pack` against `off`). The 7% is one run of each, not a measured difference.

A variation: tightening `f1_drop_points` from 3 to 1 fails `tests/test_gates.py::test_an_f1_drop_and_a_cost_rise_warn_without_blocking`. Its assertion message, "2 points is inside 3", pins the old edge, so the test's expectation changes in the same commit.

Block tiers are not loosened live, because the change rule never weakens a safety or honesty control.

To revert, restore `config/thresholds.yaml` and delete `private/live/`.

## 2. Add a lint rule (offline)

This change makes `lint` question the word "promptly", which sets no measurable time.

1. In `config/lint.yaml`, add `'\bpromptly\b'` to the `patterns` of the rule `vague-terms`.
2. Add a case to the parametrized list of `tests/test_lint.py::test_each_rule_on_a_matching_and_a_quiet_sentence`:

```text
        (
            "VAGUE",
            "The Supplier shall reply promptly to every complaint.",
            "The Supplier shall reply to every complaint within 2 working days.",
        ),
```

The checks:
- `uv run pytest tests/test_lint.py`: 35 passed.
- `uv run pytest -m replay`: 36 passed.
- `uv run bidwright demo`: completes.

The replays stay green because no requirement quote in the corpus contains "promptly". `lint` finds nothing new, so `consolidate`, which turns findings into clarification questions, gets the same input.

The counter-case was rehearsed with "audit", a word the development RFP uses. The new findings change `consolidate`'s input, and the demo ends `UNRECOVERABLE_FAULT` with `CassetteMissing`. A rule that fires on the corpus needs a live run, and then `bidwright record`, before CI can replay it. In a live run, the findings land in `lint_findings.jsonl`, and `consolidate` turns them into clarification questions in `questions.jsonl`.

To revert, restore `config/lint.yaml` and `tests/test_lint.py`.

## 3. Swap a model role

This change runs the `reason` role on `gemini-3.1-flash-lite`, with `gemini-3.5-flash-lite` as its fallback.

In `config/models.yaml`, swap `model` and `fallback` on the `reason` line of both the `free` and the `paid` profile. The paid profile mirrors free, so changing only one fails `tests/test_config.py::test_the_paid_profile_mirrors_free_with_its_own_limits`. Then run:

```text
uv run python scripts/gen_docs.py
uv run pytest tests/test_config.py tests/test_ledger.py tests/test_e2e_replay.py
```

`gen_docs.py` rewrites `docs/agents.md` and `docs/ai-bom.md`, which list the models; `--check` fails until then. Two tests fail, both naming the old model, because they pin which model answered each role:
- `tests/test_ledger.py::test_the_manifest_lists_the_models_that_answered`
- `tests/test_e2e_replay.py::test_a_development_run_replays_with_no_network`

Their expected `reason` model changes with the swap.

`uv run bidwright demo` still completes. The role still lists `gemini-3.5-flash-lite`, so its cassettes answer as the fallback. A model the role never listed ends the replay `UNRECOVERABLE_FAULT` with `CassetteMissing`; the rehearsal tried `gemini-3.6-flash`.

In a live run, the Ops page's **By model** and **Ledger calls** show `gemini-3.1-flash-lite` on the `reason` calls. Charged cost stays $0 on `free`. Shadow cost prices each role at the `shadow_model` in `config/pricing.yaml`, so it changes only if that line changes too.

To revert, restore `config/models.yaml`, `docs/agents.md`, `docs/ai-bom.md`, `tests/test_ledger.py` and `tests/test_e2e_replay.py`.

## 4. Add a tool to an allowlist (live)

This change gives `risk` the `read_section` tool, which `decide` already has. With it, `risk` can read a whole section rather than search for passages.

**Step a, the allowlist alone.** In `config/agents.yaml`, set the `risk` tools to `[search_rfp, date_calc, sla_calc, read_section, reflect]`. Then:
- `uv run pytest tests/test_config.py tests/test_gateway.py`: 65 passed.
- `uv run bidwright demo`: still completes.

The gateway offers a tool only when it is both allowed and registered, so the model's tool list has not changed yet. `docs/agents.md` and `docs/ai-bom.md` are out of date until `gen_docs.py` runs.

**Step b, register the tool.** In `src/bidwright/graph/build.py`, import it:

```python
from bidwright.tools import date_tool, search_tool, section_tool, sla_tool
```

Then, in `risk_node`, add it after the line that builds `listed`:

```text
        listed.append(section_tool(list(ctx.passages.values()), ctx.view))
```

The checks:
- `ruff check` and `pyright` report no errors.
- `uv run pytest tests/test_config.py tests/test_gateway.py tests/test_risk_loop.py`: 98 passed.
- The whole-run tests on scripted models, `uv run pytest tests/test_ledger.py tests/test_supervisor.py tests/test_tracing.py`: 30 passed.

The tool definitions are part of the cassette key, so `uv run bidwright demo` now ends `UNRECOVERABLE_FAULT` with `CassetteMissing` at `risk`, and `uv run pytest -m replay` shows 5 failures. That is the guard asking for a new recording.

In a live run, a `read_section` call by the model appears as a TOOL span under `risk` in Phoenix, and as a line in the run's `tool_calls.jsonl`. The model may not call the tool; if it does not, say so.

Authorization stays outside the model. A call to a tool the agent's list leaves out returns `DENIED`, with the reason `'<tool>' is not allowed for agent '<agent>'`. `tests/test_gateway.py` tests this denial (FI-09).

To revert, restore `config/agents.yaml`, `src/bidwright/graph/build.py`, `docs/agents.md` and `docs/ai-bom.md`.

## 5. Add a zone (live)

This change adds a `PRICING` zone for sections that set out how the price is given. Four edits must agree:

1. **`config/zones.yaml`.** Before `CONTRACT`, add `PRICING: {definition: "How the price is set out: pricing schedules, rate cards, cost breakdowns", keywords: [pricing, price schedule, rate card]}`. The keyword fallback takes the first match in the order listed. `PRICING` therefore sits before `CONTRACT`, whose keyword `payment` would otherwise claim a heading such as "Pricing and payment".
2. **`src/bidwright/schemas.py`.** Add `"PRICING"` to `Zone`, at the same position. Then run `uv run ruff format src/bidwright/schemas.py`, since the line passes 100 characters.
3. **`prompts/triage.md`.** Add the row `| PRICING | How the price is set out: pricing schedules, rate cards, cost breakdowns |` to the zone table, before `CONTRACT`.
4. **The prompt version.** Set `version: 0.3.0` in `prompts/triage.md`, `prompt: triage@0.3.0` in `config/agents.yaml`, and `("triage", "0.3.0")` in the version list of `tests/test_prompts.py::test_the_prompts_revised_with_step_12_carry_their_versions`.

`tests/test_config.py` checks that the config and the literal list the same zones in the same order. With only edits 1 and 2, `tests/test_triage.py::test_the_zone_table_is_the_configured_one` fails until edit 3. After all four edits, `uv run pytest tests/test_config.py tests/test_triage.py tests/test_schemas.py tests/test_prompts.py` reports 175 passed. Then `uv run python scripts/gen_docs.py` rewrites `docs/agents.md`, `docs/reference/schemas.md` and `docs/ai-bom.md`.

The triage prompt's text changed, so every replay misses at `triage`, and `bidwright demo` ends `UNRECOVERABLE_FAULT` with `CassetteMissing`.

In a live run, `triage.json` holds each section's zone, and the triage LLM span carries the prompt version 0.3.0. The development RFP has no pricing section, so the new zone may not be assigned.

One consequence to name: gold labels carry a zone per clause, and none is `PRICING`. Any zone measure against gold would count a `PRICING` label as an error until the gold changes, and gold changes only as a new hashed version.

To revert, restore `config/zones.yaml`, `config/agents.yaml`, `src/bidwright/schemas.py`, `prompts/triage.md`, `tests/test_prompts.py`, `docs/agents.md`, `docs/reference/schemas.md` and `docs/ai-bom.md`.

## CLI equivalents of the UI actions

| UI action | Command |
|---|---|
| **Start the run** | `uv run bidwright run inputs/dev/dev_rfp.pdf --profile free` |
| **Stop at the end of the current step** | `uv run bidwright stop <run>` |
| **Resume the run** | `uv run bidwright resume <run>` |
| **Submit gate decision** | `uv run bidwright approve <run> --role "Solution lead"`, with `--option`, `--edit`, `--override` or `--reject` |
| **Record these verdicts** | `uv run bidwright review <run> --role "Bid manager" --item REQ-0001 --verdict accept` |
| **Send the run, its checks and its review verdicts** | `uv run bidwright phoenix sync <run>` |
| **Score the run and send its scores** | `uv run bidwright-eval phoenix outputs/<run>` |
