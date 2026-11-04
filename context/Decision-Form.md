---
title: Decision Form
type: decision-form
applies-to: bidwright
related: ["[[Master-Plan]]", "[[Project-Backlog]]", "[[Research-Register]]"]
date: 2026-11-03
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

### D-03: When to create the Cerebras key, due at the Iteration 3 entry

**Context.** The Cerebras trial's credits expire 30 days after they are granted, and the key needs a payment method.

**Recommendation.** Create the key at the start of Iteration 3, so the trial covers the iteration that first uses it.

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
| Iteration 0b | The first Goldfish architecture review is triaged (2026-11-03, ADR-022 to ADR-025). Start the drift report at the tag, `/egm:egm-drift-report docs`, limited to `architecture.md`, `agents.md` and `security.md`, and triage it with Claude |
| Iteration 1 | Review gold v2, about 1 hour; write the held-out list, about 1 hour; confirm the 555-01XX fiction block before step 4; read the paid-tier limits in AI Studio (V-03) before step 9; confirm CrackedPDFs access and license (V-02) before step 19; the NotebookLM login for the step-1 research launches; decide D-01 at the exit. The Stage 9 review was triaged on 2026-11-03. |
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
| The goal: two capabilities shown together, with an engagement brief, governance in the client's terms and an AI bill of materials | Accepted | CH-74 | 2026-11-03 |
| D-02: the Iteration 1 design doc's decisions | Accepted: ADR-017 to ADR-021 and the three process changes, at the Stage 9 review; the `paid` profile with a $10 matrix cap chosen there | ADR-017 to ADR-021; CH-79 to CH-82 | 2026-11-03 |
| D-04: two delegated decisions | Confirmed: `thinking: medium` for `extract` (CH-71) and the local Phoenix with authentication off (CH-72) | CH-71, CH-72 | 2026-11-03 |
| D-05: how client documents are protected | Decided: C1, C4, C5, C8's seam and C9's first part in Iteration 1; C2 declined, the consent override stays as a fourth mode; C3, C6, C7 and the later parts scheduled | ADR-026; CH-83 | 2026-11-03 |
