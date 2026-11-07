# Live walk-through script

Updated 2026-11-06. The 3-5 minute video is recorded, so this script now serves the 60-minute follow-up session. The session has three parts: a walk-through of the running system, a discussion of trade-offs, and one small change made live. The [live-change script](demo_script.md) covers the change. The walk-through uses the UI as built at Iteration 3 step 17b (see the [Iteration 3 design](designs/iteration-3.md)), on synthetic RFPs only.

Two rules hold for the whole session:
- Every figure said aloud comes from the run on screen, and the narration says whether that run was live or a replay. A replay's speed is playback speed, not model latency.
- Every output stays `UNREVIEWED_DRAFT`. The solution gate approves a proposed solution so the workflow can continue. It signs nothing off.

## Session plan

| Part | Minutes | Content |
|---|---:|---|
| Walk-through | 20 | Sections 1-5 below, on one live run that waits at the human gate |
| Trade-offs | 15 | The trade-off table and the likely questions below |
| Live change | 15 | One or two changes from the [live-change script](demo_script.md) |
| Reserve | 10 | Questions, or recovery when something fails |

## Preparation

**The day before**
1. On `main` at the submitted commit, run `uv sync`, `uv run pytest -m "not gold and not replay"` and `uv run bidwright demo`. These confirm the checkout and the keyless replay.
2. Put `GEMINI_API_KEY`, `CEREBRAS_API_KEY` and `GROQ_API_KEY` in `.env`, plus `PHOENIX_ENDPOINT=http://127.0.0.1:6006`. The endpoint makes runs started during the session send their spans to Phoenix while they run. Keep `.env` off the screen.
3. Start a rehearsal run that waits at the gate: on the Run page, open **Start a run**, choose `inputs/dev/dev_rfp.pdf`, keep the defaults and press **Start the run**. It reaches the gate in about four minutes of active time on `free`. Rehearse sections 3 and 4 on this run, never on GATE: a gate decision cannot be taken back.
4. Commit or set aside unrelated edits, so a revert in the live-change part touches only that change's files.

**Thirty minutes before**
1. Run `docker compose up -d phoenix`, then open `http://127.0.0.1:6006`.
2. Run `uv run bidwright ui --api` in its own terminal, then open `http://127.0.0.1:8501`. The API docs are at `http://127.0.0.1:8001/docs`.
3. In the sidebar's **Run** selector, choose GATE. Check that the Review page's **Solution gate** tab shows the **Gate decision** form. If GATE no longer waits, start a fresh run as in step 3 of the day before, and use it as GATE.
4. Keep four windows ready: the UI, Phoenix on GATE's trace, an editor on the repository, and a terminal at the repository root.

| Label | Run | Live or replay | Use |
|---|---|---|---|
| GATE | `20261106T040000Z-dev-rfp-gate-free` | Live on `free`, traced to Phoenix | Sections 1-5. At the gate: 35 requests, 216 active seconds, $0 charged and $0.0866 shadow cost |
| DONE | `20261106T001835Z-dev-rfp-db9eeb00-free` | Live on `free`; 7 of its 37 calls came from the cache | A completed run on the same RFP, used if GATE cannot finish |
| HERO | `20261105T114609Z-hero-free` | Live on `free` | Section 5: the larger package and the regression gate. Made before the solution path existed, so it has no solution manifest |
| DEMO | The run that `uv run bidwright demo` prints | Replay, no keys | Recovery when a provider or the network fails |

The sidebar hides matrix runs until **Show matrix runs** is checked. The selected run stays the same across pages and is kept in the address as `?run=`.

## Walk-through

All five sections use GATE unless a section names another run.

### 1. The input and its requirements (3 minutes)

On the Run page, go to **What the run produced**:
- **Summary** says the run stopped before `render`. GATE waits at the gate, and its summary appears in section 4, after the decision.
- **Input RFP** shows the PDF page by page.
- **Requirements**: search the statements, choose one requirement in **Check one against its source**, and the input page appears with the quote highlighted. **Open the extract call … in Phoenix** opens the model call that produced the record.

Talking points:
- The model cites passage ids. Code checks each quote against the frozen text, and a quote that is neither verbatim nor a normalized match is rejected.
- A verified quote shows that the evidence exists. It does not show that every requirement was found; section 5 shows how misses are measured.

### 2. Where the agents decide, and what constrains them (5 minutes)

On the Run page's **Solution** tab, show **Approach**, **Capability map**, **Options**, **Solution manifest**, **Technology verdicts** and **Bid signal**. GATE's map has 2 PARTIAL and 3 GAP needs and offers 2 options. Then open GATE's trace in Phoenix: the `decide` spans with their tool calls, and an `assess` span.

Talking points:
- LangGraph routes the run, and no LLM chooses the next node. The agents are `discover`, `decide` and `risk`: each runs a bounded tool loop and stops when a turn adds no new evidence.
- The gateway checks every tool call against `config/agents.yaml` outside the model: the allowlist, the argument schema, repeated calls and the budget.
- `assess` ran on another model family (`gpt-oss-120b` on Cerebras). It sees the claim and its cited spans, never the author's reasoning. With no KB evidence, code marks a claim `UNVERIFIED` and makes no LLM call.
- A need the supplier KB cannot support stays a GAP, and the gate shows it to a person.

### 3. Records reviewed by a person (4 minutes)

On the Review page, enter a role in the role field, such as `Bid manager`. The field takes a role, never a person's name. Keep **Send verdicts to Phoenix as they are recorded** checked.
- **Records** lists the items in order of consequence, hazards first, each beside its source passage. GATE has 29 items: 1 hazard, 7 requirements, 4 optional requirements, 4 risks, 2 technology claims, 1 quarantine item and 10 negative-space passages. Record `accept` on the hazard, `correct` with a note on a requirement, `flag` on a technology claim and `accept` on a risk. Then press **Record these verdicts**. The metrics **Reviewed**, **Stale**, **Rejected or missed** and **Flagged** update.
- Change one verdict and record it again. The latest verdict counts, and `review/decisions.jsonl` keeps both lines.
- **Negative space** shows ten passages that no record cites. Every reviewer of the run sees the same sample. Mark one `clear` or `missed`.
- **Quarantine report and open questions** shows the hidden text that `guard` removed before parsing. The text appears as possible requirements, never as instructions.
- In Phoenix, the verdicts arrive as HUMAN annotations on the extract calls that read those passages.

Talking points:
- A missed requirement leaves no row to review, so the negative-space sample puts uncited passages in front of the reviewer.
- If a later resume rewrites a record, its verdict counts as Stale until someone reviews it again.

### 4. The human gate, decided live (5 minutes)

On the Review page's **Solution gate** tab, show **Bid memo**, **The review file, review/solution_gate.md**, **Options ranking** and **Capability map**. Then fill in **Gate decision**:
- **Approver role**: `Solution lead`. **Option**: `(keep current)`.
- One rehearsed effort edit. For example, raise `work_packages[1.2].effort.high_days` from 20 to 24. Package 1.2 is legacy data migration and integration, estimated at 10 to 20 days at the gate.
- Press **Submit gate decision**. The page runs the same `bidwright approve` command as the CLI and shows its output when the run stops again. The edit re-runs `techcheck` and `risk` on the changed fields before the run goes on to `render`.

The rechecks make model calls, so the wait can last a minute or two. To fill it, open the same address in a second browser tab and show the Ops page there. When the command returns:
- The gate tab shows the approval record: the decision, the role, the option and `Automatic: False`.
- The Run page's **Summary** tab now holds the summary: hazards first, then requirements, approach, risks and open questions, labeled `UNREVIEWED_DRAFT`. **Files** offers the compliance matrix and the other outputs.
- Back on Review, **Stale** counts any record the resume rewrote, such as a risk from the `risk` recheck.
- Ops lists a second trace for the resume, in the same Phoenix session.

Talking points:
- The run waited in `WAITING_HUMAN`, and nothing approved it automatically. `--auto-select` exists for evaluation runs only, and it records `auto_selected: true`.
- An `INVALIDATED` technology claim blocks the gate until the claim is revised or a person overrides it with a recorded reason. Under `--auto-select`, a blocked gate ends the run `POLICY_BLOCKED`.

### 5. Evidence: quality, cost and latency (3 minutes)

On the Ops page for GATE:
- **Phoenix** has one button per trace, **All sessions (one per run)**, **Send the run, its checks and its review verdicts**, and **Score the run and send its scores**. The last button adds the scores to the trace as annotations.
- **Ledger totals**, **By node**, **By model** and **Ledger calls** show requests, token categories, retries, and charged and shadow cost per call. `latency_ms` sums call latencies. Active time is the run manifest's `active_seconds`.

Then select HERO, show **Scores**, and run in the terminal:

```text
uv run bidwright-eval gate outputs/20261105T114609Z-hero-free --baseline evals/baselines/hero.json
```

It prints `GATE BLOCKED`. The run missed 3 mandatory requirements, against 2 in the committed baseline. Its F1 is 7.57 points higher (0.8667 against 0.7910).

Talking points:
- The headline metric is missed mandatory requirements, and a rise blocks. F1 only warns.
- This run predates the worked examples that ADR-049 restored to the extract prompt. The baseline is the hero replay recorded with them, which traded precision for recall. That is one run against one replay, not a measured comparison.
- The comparisons with repeats are the spike reports under `evals/results/`: `s03-batch`, `s10-examples` and `s13-second-pass`.

## Trade-offs to discuss

| Decision | Cost accepted | Evidence |
|---|---|---|
| Missed mandatory requirements block, and F1 only warns | Precision falls when recall rises: on the hero replay, misses fell from 3 to 2 and F1 fell 4.3 points | `evals/baselines/README.md`, `config/thresholds.yaml`, ADR-049 |
| A fixed graph, with tool loops only in `discover`, `decide` and `risk` | Less freedom for the model. Each loop must beat a fixed control with repeats, and those ladders are not run yet | `docs/agents.md`, the [Iteration 3 design](designs/iteration-3.md) |
| `assess` on another model family | An extra provider and its quota. A same-family fallback ends the run `DEGRADED` with `SAME_FAMILY` | ADR-045, `config/models.yaml` |
| Flash-Lite for the `reason` role on `free` | A smaller model than Flash, because Flash allowed 20 free requests a day | ADR-003 |
| A synthetic corpus, with gold written in the specs | Synthetic text is cleaner than real tenders, and one author wrote both corpus and prompts | `ASSUMPTIONS.md` |
| The gate waits for a person by default | A run cannot finish unattended outside evaluation | The Review page, `bidwright approve` |
| Replay cassettes keyed on prompt, schema, tools, model, settings and input | Any such change needs a new recording before CI replays it | The [live-change script](demo_script.md) |
| Lexical search with SQLite FTS5 | Paraphrases that dense retrieval would find can be missed | ADR-006 |

## Likely questions

| Question | Short answer | What to show |
|---|---|---|
| Is this agentic, or a pipeline? | Both: a fixed graph, with tool-using loops where a choice depends on the input | The `decide` spans in Phoenix |
| What stops prompt injection? | `guard` removes hidden text before parsing, the gateway authorizes tools outside the model, and planted traps are scored as a blocking check | The quarantine tab, and the hero gate's `trap_actions_obeyed` line |
| Can it read a real tender? | Not on `free`, which refuses files outside `inputs/CORPUS.sha256`. `--profile local` keeps everything on the laptop | `README.md` |
| What does a run cost? | GATE took 35 requests to reach the gate: $0 charged on `free`, $0.0866 at paid list prices | Ops, **Ledger totals** |
| How does it recover? | A checkpoint per node, plus stop, resume, quota pause and budget stop | **Follow and steer** on the Run page |
| Why trust the scores? | Gold is hashed before any score, and the scorer's self-test must fail on deliberately corrupted outputs | `evals/gold/MANIFEST.sha256`, `tests/test_scorer_selftest.py` |
| What is not built yet? | The Iteration 3 steps not reached, and Iterations 4 and 5 | The [Iteration 3 design](designs/iteration-3.md), `context/Master-Plan.md` |

## When something fails during the session

| Failure | Response |
|---|---|
| The free quota runs out | The run pauses in `QUOTA_PAUSED`. On the Run page, check **Continue on the paid key** and press **Resume the run** |
| A provider error ends the run `UNRECOVERABLE_FAULT` | Show the reason under **Follow and steer**, then continue on DONE, or on DEMO with no keys |
| Phoenix does not answer | Ops says so. The run keeps its spans in `spans.jsonl`, and **Replay spans.jsonl to Phoenix** sends them later |
| The gate form refuses a decision | The page prints `Refused:` with the reason. Correct the field and submit again |
| The UI stops | Restart `uv run bidwright ui --api`. The `?run=` in the address keeps the selected run |
| Nothing runs | Play the recorded video, then go on to the trade-offs |

The [submission handoff](submission.md) owns packaging and the release checklist.
