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

### D-03: When to create the Cerebras key, due at the Iteration 3 entry

**Context.** The Cerebras trial's credits expire 30 days after they are granted, and the key needs a payment method.

**Recommendation.** Create the key at the start of Iteration 3, so the trial covers the iteration that first uses it.

### D-06: Container-only host names in the egress register, due before the first run on client documents

**Context.** The egress register (ADR-026) decides whether a destination is local from its host name. `localhost` and `127.0.0.1` mean this machine everywhere. `ollama`, `phoenix` and `docling` exist only on the Compose network, and `host.docker.internal` means the machine running Docker only from inside a container. Outside Docker the operating system resolves these names through the hosts file and DNS, so on an office or client network a search suffix can turn `docling` into another computer. Bidwright reads `.env` outside Docker too: a Compose address copied there, such as `DOCLING_URL=http://docling:5001`, would let a client run send whole documents, or prompts to Ollama, to that computer while the register calls it local. Phoenix receives only hashes and counts.

**Options.**
- **A.** The four names count as local only inside Bidwright's container, flagged by a variable the Dockerfile sets; outside it, only `localhost` and `127.0.0.1` do, and any other name is refused with a message to use `localhost`.
- **B.** Resolve the name at check time and require a private address. Rejected on the facts: office networks give other computers private addresses too, and the answer can change between the check and the connection.
- **C.** Keep trusting names, and document that Compose addresses must not go in `.env`. This is the call-site trust ADR-026 set out to avoid.

**Recommendation.** A. It only tightens a privacy control; no current setup breaks, since outside Docker the defaults are `localhost` and inside the container the image sets the flag; a misconfiguration becomes a clear refusal instead of a silent leak; and it costs about an hour, with an ADR beside ADR-026. Reasoned step by step with the sequential-thinking tool on 2026-11-04. The owner deferred it the same day to after the delivery, since every run so far is synthetic; until it is built, `docs/architecture.md` lists the gap as technical debt.

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
| Iteration 1 | Review gold v2, about 1 hour; write the held-out list, about 1 hour; confirm the 555-01XX fiction block before step 4; read the paid-tier limits in AI Studio (V-03) before step 9; confirm CrackedPDFs access and license (V-02) before step 19; the NotebookLM login for the step-1 research launches; decide D-01 at the exit. The Stage 9 review was triaged on 2026-11-03; gold v2 was reviewed and hashed, V-02 confirmed, D-01 decided, the held-out list written and its gold hashed, and the paid limits read (V-03) on 2026-11-04. |
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
| D-01: the paid budget | Option A, staged: $40 for Iterations 2 and 3, and Iteration 5's amount set at the Iteration 3 exit from a measured run of the full pipeline. Sized from the measured hero run of 2026-11-04: 33 requests, $0.26 at the Flash-Lite list price and about $0.43 at Flash's. | CH-84 | 2026-11-04 |
| D-07: the Iteration 2 design doc's decisions | Accepted as recommended ("Let's go"), after the Stage 9 review's first round (53 issues) and its re-audit (29), both resolved in the doc: ADR-031 to ADR-036; ADR-037 for three of the six departures, the other three recorded in ADR-034 and ADR-036; the two process changes; and the `extract` examples' return at the start of Iteration 3's extraction ladder | ADR-031 to ADR-037; CH-88 to CH-90 | 2026-11-04 |
| The matcher's table-row defect, found in the release step's held-out scoring | Option B: correct the matcher, score every run of the `v0.1` era again with the old figures beside the new, and keep the shipped configuration, which the held-out RFP measured; the examples, which the corrected S-10 favors, return after the delivery. Declined: reconfiguring now (A), and disclosure without a fix (C). | ADR-030, CH-87 | 2026-11-04 |
