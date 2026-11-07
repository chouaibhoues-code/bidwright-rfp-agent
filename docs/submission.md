# Submission preparation

**Status: `UNREVIEWED_DRAFT`.** Prepared 2026-11-05 for submission after Iteration 3. This is the release handoff, not a claim that `v0.3` has passed its gate. The other implementation session owns the build. The accepted scope and exit checks remain in [the Iteration 3 design](designs/iteration-3.md#7-exit-checks).

## Finish in this order

1. The implementation session completes Iteration 3, its measurements and the owner reviews already required by the plan. Freeze feature changes after the gate passes.
2. Refresh the reviewer documents and sample from that final implementation. Replace earlier-version descriptions and figures with evidence from the submitted revision.
3. Run the final checks below on the candidate commit. Record the commit, environment, results and any accepted exceptions.
4. Check the recorded 3-5 minute video against that revision: its duration and the reviewers' access to its link. The [walk-through script](demo_script_ui.md) and the [live-change script](demo_script.md) prepare the follow-up session.
5. After the owner's tag approval, verify the repository or ZIP from a clean directory and submit its link with the demo link. Keep the submitted revision fixed for the follow-up.

No additional feature is needed for submission preparation. Iterations 4 onward remain outside this handoff.

## Evidence for the assignment

| Deliverable | Reviewer entry point | Final release check |
|---|---|---|
| Working agentic app and README | [README](../README.md), `uv run bidwright demo`, [solution summary](../samples/dev/solution_summary.md) | The submitted revision runs end to end without keys after dependency setup; the summary includes requirements, approach and risks |
| Prompts with explanations | [Prompt directory](../prompts/), [agent reference](agents.md) | Active prompt versions match configuration; each has its rationale; generated references match code |
| Evaluation and sample results | [Evaluation report](evaluation.md), `evals/results/`, `evals/baselines/` | Show mandatory and hazard misses first, named limitations, repeated results and one keep-or-drop decision; distinguish replay, live and historical measurements |
| Token, latency and cost observability | [Sample ledger](../samples/dev/ledger.jsonl), [sample manifest](../samples/dev/run_manifest.json), [sample spans](../samples/dev/spans.jsonl), Ops page | Node/model totals reconcile with the ledger; shadow cost is identified; live latency is distinguished from replay time |
| Decisions and encountered failures | [DECISIONS](../DECISIONS.md), [architecture](architecture.md) | Explain one actual failure, its fix, a rejected alternative and the measured consequence |
| Assumptions, synthetic data and rough hours | [ASSUMPTIONS](../ASSUMPTIONS.md), [TIMELOG](../TIMELOG.md), `inputs/` | Actual hours and calendar span are supplied, including any overrun; assumptions distinguish verified facts from open questions |
| Three-to-five-minute demo | The recorded video, through a reviewer-accessible link | App, evaluation and observability all appear in the video; the revision shown matches the submission |
| Repository or ZIP | Approved release revision and its archive | Both code and documentation are present; private material and keys are absent; setup works from the delivered copy |

The rubric weights agentic depth at 30%, evaluation and observability at 20%, tooling and LLMOps at 15%, craft at 15%, communication at 10%, and product sense at 10%. Allocate demonstration time accordingly. The dashboard supports the evidence; the completed workflow and measured behavior lead it.

The [editable draw.io diagrams](diagrams/README.md) support the architecture explanation, agent flow, human gate and evaluation trace. Check their Iteration 3 target labels against the final build before using them as release evidence.

## Final handoff from the implementation session

- [ ] The Iteration 3 exit-check table has evidence for every row, including the UI/API and trace replay.
- [ ] The owner has reviewed and hashed gold v4 and the hypotheses before the scored experiments, reviewed ten assessments, and exercised the human gate with an edit.
- [ ] Ladder results, keep-or-drop ADRs and the five live hero repeats are committed. QS-2, QS-3, QS-5 and QS-8 pass, or each exception has the owner's recorded acceptance.
- [ ] Paid spend reconciles with the existing budget. No new spend is implied by this checklist.
- [ ] Architecture and drift reviews are triaged, and the code/security reviews and their fixes are complete.
- [ ] The [release step](../context/Master-Plan.md#213-release-step) is complete: held-out evidence, the owner's short brief on `local`, rubric review, figure verification (V-01), rehearsal and closeout lessons. The held-out set was already scored once at `v0.1`; keep it labeled with that configuration and disclose later tuning. Any new evaluation follows an explicit owner-approved policy rather than presenting reused results as a fresh `v0.3` test.
- [ ] The development sample is refreshed from the final live workflow. Sample, demo recording and hero results are identified separately; figures are never transferred between them.
- [ ] `README.md`, `docs/brief.md`, `docs/architecture.md`, `docs/evaluation.md`, `docs/governance.md`, `docs/demo_script_ui.md`, `docs/demo_script.md`, generated references and the package version describe the submitted release.
- [ ] Historical `v0.1` and `v0.2` results remain labeled as historical. The release claims use the final evidence, including remaining misses.
- [ ] `TIMELOG.md` contains honest rough hours and calendar span against the assignment's 36 focused hours across up to five calendar days, disclosing any overrun. Commit timestamps are not used to invent focused work hours.
- [ ] Every generated product output retains `UNREVIEWED_DRAFT`; approval of a solution does not become approval to submit a bid.

## Final verification

Run from the repository root on the candidate revision. Dependency setup may use the network; the fast, replay and gold suites and the recorded demo need no model calls.

```text
uv sync --locked
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest -m "not gold and not replay"
uv run pytest -m replay
uv run pytest -m gold
uv run python scripts/gen_docs.py --check
uv run python scripts/check_docs.py
uv run bidwright demo
uv run bidwright-eval score outputs/<run>
```

Use the run folder printed by the demo in place of `<run>`. Check its completed status, summary, compliance matrix, gate record, ledger and trace. Exercise the Run, Review and Ops pages against this same release. Keep the final CI run green, including image, dependency and secret checks. Record skipped checks and their reasons; a snapshot taken during implementation is not final release validation.

Repeat the setup, demo and score sequence from the actual archive or a clean checkout with no `.env`. This detects missing untracked assets, local-only configuration and stale cassettes. Setup instructions must identify any separate service needed for live parsing or the UI. A replay demonstrates the recorded workflow; committed live results establish provider behavior and latency.

## Freeze and package

The owner approves the release tag under the existing plan. The following example assumes that approved tag is `v0.3`; use its exact name. Commit the intended submission files before creating an archive, because `git archive` exports the tag rather than working-tree changes.

```text
git status --short
git rev-parse "v0.3^{commit}"
git ls-tree -r --name-only v0.3 -- .env private outputs
```

The last command must return no paths. Inspect all tracked environment-file variants as well: `.env.example` contains variable names and placeholders only. Include the synthetic inputs, lockfile, prompts, research packs, cassettes, committed samples and evaluation evidence needed by the documented reviewer path. Keep `.env`, `private/`, local state and raw `outputs/` out of the submission.

Create the archive in PowerShell after the checks:

```powershell
New-Item -ItemType Directory -Force -Path outputs/submission
git archive --format=zip --prefix=bidwright-v0.3/ --output=outputs/submission/bidwright-v0.3.zip v0.3
Get-FileHash -Algorithm SHA256 -LiteralPath outputs/submission/bidwright-v0.3.zip
```

Inspect the archive's entries and test the extracted copy before sending it. Record the archive hash and commit in the submission notes. A repository link must let the reviewer access the submitted revision; a video link must play with the intended reviewer permissions.

## Submission message draft

Replace each bracketed field and check every claim against the final release before sending. This text does not authorize sending a message.

> Bidwright reads a synthetic RFP package and produces a structured solution summary of requirements, approach and risks, with verified source quotations and human review boundaries.
>
> Repository or ZIP: [submission link]
>
> Submitted revision: [tag and commit]
>
> Demo: [video link, duration between 3 and 5 minutes]
>
> Quick start: install Python 3.12 and uv, run `uv sync --locked`, then `uv run bidwright demo`. The recorded demo needs no keys or network after setup. Evaluation: `uv run bidwright-eval score outputs/<run>`.
>
> Results: [final hero mandatory misses / 45, hazard misses / 9, five-run consistency, and one measured agent comparison]. Limitations: [one material remaining limitation].
>
> The README links the prompts, evaluation results, traces, decisions, assumptions and rough hours. All product outputs remain `UNREVIEWED_DRAFT`.

## Prepare for the follow-up

| Probe | Evidence to have open |
|---|---|
| Why agents rather than a single prompt? | One need's actual tool choices, its evidence, blind assessment and the corresponding ablation; explain a dropped rung as well as a retained one |
| How can a good-looking answer still fail? | A named missed clause and its loss funnel; the matcher correction in ADR-030; the difference between a verified quote and complete requirement coverage |
| Why trust the assessor? | Its restricted input and context manifest, joint error and the owner's ten labels; another model family alone is not proof of independence |
| What prevents an unsupported commitment? | Capability map, technology verdict, human gate, edited manifest and resulting rechecks |
| What happens on failure or restart? | A gateway denial, budget or circuit-breaker behavior, stop/resume and the journal of answered calls |
| What changes for a real client? | The synthetic-data limitation, approved provider/data terms, egress controls, local-profile constraints and the review process |
| Can a small change be made live? | One change from the [live-change script](demo_script.md): a lint rule offline, then a tool added to an allowlist on a live run on `free` if time remains |

The release plan's five changes (add a lint rule, change a threshold, swap a model role, add a tool to an allowlist, and add a zone) were rehearsed on 2026-11-06 at `fcdb5c7`. The [live-change script](demo_script.md) gives each one's edits, tests, expected output and revert. The threshold and lint changes need no keys; the model swap still replays once two test expectations are updated; the allowlist and zone changes miss their recordings, so they run live on `free` rather than with new cassettes. Keep this work on a separate branch or copy, preserving the submitted revision and its evidence.
