---
title: Decision Form
type: decision-form
applies-to: bidwright
related: ["[[Master-Plan]]", "[[Project-Backlog]]", "[[Research-Register]]"]
date: 2026-11-02
status: current
tags: [bidwright, decisions, governance]
---

# Decision Form

> [!info] How this works
> Each open decision has its context, the options, Claude's recommendation and when it is due. The owner decides. Once taken, a product or architecture decision becomes an ADR in `DECISIONS.md`, a process decision becomes a line in the change log of [[Master-Plan]], and the row here moves to Closed.

## Open

### D-01: The paid budget, due at the Iteration 1 exit

**Context.** The free tiers carry development runs on Flash-Lite (ADR-003). Three things need paid calls: the planned comparison of Flash-Lite against Flash on solution work, which is ADR-003's reverse-if test; the Iteration 5 ablations on paid Flash, about $35-50 by a rough count; and the non-Gemini roles from Iteration 3, whose Cerebras trial gives $5 of credits for 30 days. Until this decision, paid spend is capped at $10.

**Options.**
- **A.** Set a budget from the measured partial hero run at the Iteration 1 exit, covering paid Flash for the comparisons and a paid non-Gemini fallback.
- **B.** No paid budget: the ablations run on the development RFP with one hero run per rung, and the Flash comparison is dropped.
- **C.** Flash-Lite everywhere, including the ablations, with no paid non-Gemini fallback once the trial ends.

**Recommendation.** A, sized from the measured run, because the Flash comparison is the evidence that keeps or reverses ADR-003, and the family rule for assessment needs a provider after the trial.

### D-02: The open decisions of the Iteration 1 design doc, due before the Iteration 1 build

**Context.** `docs/designs/iteration-1.md` closes five decisions as proposed ADRs in `DECISIONS.md`:
- ADR-017: every passage reaches `extract`, and cues annotate without filtering. This changes the plan's `candidates` filter and drops the 10% unflagged sample, because DR-01 refuted the cue filter.
- ADR-018: six zones per section, with a keyword fallback.
- ADR-019: the `consolidate` cluster rule.
- ADR-020: the review files for quarantined text, small print and suspect passages.
- ADR-021: the compliance matrix layout.

It also proposes two process changes for the change log: S-10 compares the prompt with and without examples instead of a CARE variant (DR-16), and `coverage` runs directly after `verify`.

**Options.** Accept each, change it, or keep the plan's original design where one differs (ADR-017 and the S-10 change).

**Recommendation.** Accept all, at the Stage 9 review of the design doc, which the owner starts with `/egm:egm-review docs/designs/iteration-1.md implementation`.

### D-03: When to create the Cerebras key, due at the Iteration 3 entry

**Context.** The Cerebras trial's credits expire 30 days after they are granted, and the key needs a payment method.

**Recommendation.** Create the key at the start of Iteration 3, so the trial covers the iteration that first uses it.

### D-04: Two decisions made under delegated rules, for confirmation

**Context.** Two settings changed in Iteration 0a under rules the plan delegates, and were reported to the owner at `v0.0`:
- CH-71: `extract` uses `thinking: medium`, because S-05's pass mark picks the cheapest variant within noise of the best.
- CH-72: the local Phoenix starts with authentication off, because Phoenix 21 turned it on by default and refused every trace; it listens on loopback only and holds spans of synthetic runs.

**Options.** Confirm both, or reverse either: `minimal` thinking again for `extract`, or `PHOENIX_ENABLE_AUTH=true` with a key in `PHOENIX_API_KEY`.

**Recommendation.** Confirm both.

### Decisions closed in later design docs

| Iteration | Decisions its design doc closes |
|---|---|
| 2 | The research pack schema, the `ask_research` match threshold, gateway rules beyond Iteration 0a, the approval-file format |
| 3 | What counts as a material claim; `options` weighting when weights are `not_stated` or scoring is pass or fail; the `bid_policy.yaml` schema; the manifest field list |
| 4 | `validate`'s entity extraction, banned-filler list and lexical-overlap threshold; the storyboard schema; the DOCX template |
| 5 | The judges' rubric criteria and anchors, and the EY review standard |

## Owner inputs by iteration

Not decisions, but work only the owner can do.

| When | Input |
|---|---|
| Iteration 0b | Start the first Goldfish architecture review, `/egm:egm-review docs/architecture.md feature_spec`, with section 10 of `docs/architecture.md` (the quality scenarios) and `docs/decision-matrix.md` as context, and the drift report at the tag; triage both with Claude |
| Iteration 1 | Review gold v2, about 1 hour; write the held-out RFP's requirement list, about 1 hour; decide D-01 and D-02; triage the Stage 9 review |
| Iteration 2 | The NotebookLM login for `live` research; triage Stage 9 |
| Iteration 3 | The Cerebras key (D-03); approve one manifest at the gate; triage Stage 9 |
| Iteration 4 | Review the two skills and one drafted section; triage Stage 9 |
| Iteration 5 | 40 judge-calibration labels and 10 accept or reject decisions, about 45 minutes |
| Release | Write a one-page brief; read the code against the defense notes; rehearse the live changes; record the demo; choose the tag to release |
| Any time | V-04: say whether RFP-SPEC-001, or the repository the owner's notes mention, exists |

## Closed

| Decision | Outcome | Recorded in | Date |
|---|---|---|---|
| The plan, after two Goldfish rounds | Approved | The change log, CH-01 to CH-68 | 2026-11-02 |
| The Compose key | Stays required | ADR-002 | 2026-11-02 |
| The free `reason` model | Gemini 3.5 Flash-Lite, with 3.1 Flash-Lite as fallback | ADR-003, CH-69 | 2026-11-02 |
| Thinking on the local profile | Off for every role | ADR-004, CH-70 | 2026-11-02 |
| Continue after `v0.0` | Continue to Iteration 0b | Master-Plan, section 9 | 2026-11-02 |
