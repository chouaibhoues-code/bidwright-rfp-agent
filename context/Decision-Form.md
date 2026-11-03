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

### D-05: How client documents are protected, due before the Iteration 1 build

**Context.** A real RFP is confidential, and it often holds personal data: buyer staff names and contacts, signatures and forms, and sometimes employee data in annexes. As built, Bidwright protects a client document by routing, not by inspection:
- `free` refuses files outside the synthetic corpus unless the run passes a consent string;
- `local` keeps everything on the machine;
- traces, the ledger and logs carry no document text, though run ids, and so spans, carry the input file's name.

The first proposals were a scan for personal data that would set the routing, and pseudonymization before hosted calls. Research jobs DR-20 and DR-21 tested both on 2026-11-03, and the deciding claims were checked at source (section 17 of [[Research-Register]]):
- **A clean scan cannot clear a document.** The candidate detector's own documentation gives no guarantee that it finds all sensitive information.
- **Pseudonymization is fragile.** Models alter, merge or invent placeholders on the way back. An altered placeholder inside a quote would get a true requirement rejected by the exact-quote check.
- **Pseudonymization does not lighten the sender's duties.** The Court of Justice judges them from the controller's side, before any transfer.
- **The consent string conflicts with Google's terms.** Google's terms for the free quota say not to submit sensitive, confidential or personal information to it, and the consent string lets a client document reach that tier.
- **The paid Gemini tier is not a full answer.** It does not train on prompts and runs under Google's data processing addendum, but it logs prompts for a limited period to detect abuse, and may cache data in any country.
- **The tender's own terms govern.** UK guidance does not prohibit suppliers' use of AI on bids; authorities may require disclosure, and controls against confidential information becoming training data. A bidder's confidentiality duty comes from each tender's terms.

A follow-up the same day, at the owner's request, tested masking as a local step around hosted calls, rather than as a reason to send (section 17 of [[Research-Register]]):
- **Bidwright can contain the round-trip problem.** Quotes need no placeholder back: a quote verified in the masked text maps to the original by character offsets, exactly. Only text the model writes depends on restoring values, and what fails to restore can be flagged for review.
- **Pseudonymization is a recognized safeguard, not a permission.** The UK GDPR names it among the measures for data minimization and for security (Articles 25 and 32), and requires the information that reverses it to be kept separately (Article 4). The sender's duties stay in place.
- **Masking leaves the confidential content.** The buyer, scope, figures and requirements remain, so masked text is still confidential, and the free tier stays closed to it.
- **Every outbound channel carries the same exposure:** research and documentation services reached through MCP servers, the trace collector, coding assistants, and metadata such as file names in run ids.
- **Similar implementations exist** in LangChain, Presidio, LlamaIndex and DSPy. In their documentation, all restore values by replacing text in the model's output, and none maps evidence back by offsets.

**Options**, which can be combined:
- **C1, every client document is confidential by default.** Any file outside the synthetic corpus is treated as confidential and personal, whatever a scan says. Routing follows the provider's terms, never a detector.
- **C2, the free tier takes synthetic documents only.** The consent override on `free` is removed, and client documents run on `local`.
- **C3, a hosted path only under client terms (Iteration 5).** A paid or in-tenant provider receives client documents only with all of the following:
  - a processor agreement;
  - regional processing, where the client requires it;
  - the client's written authorization, where its tender terms require it;
  - a data protection impact assessment by the deploying organization.
  The production path describes an in-tenant deployment.
- **C4, retention and purge (Iteration 1).** A retention period, and `bidwright purge <run>`, which deletes a run folder, its checkpoints and its cache entries.
- **C5, a privacy invariant (Iteration 1).** Synthetic personal data planted in the corpus never reaches a span, the ledger, the manifest, a log, or a committed file other than those that hold corpus content by design, and `free` refuses every file outside the corpus.
- **C6, detection as an audit signal only (Iteration 5, optional).** Counts and locations of personal data, listed for the reviewer and for the impact assessment, and never used to route.
- **C7, an AI-use disclosure for each bid (Iteration 4).** Generated from the run manifest and the AI bill of materials: the tools and models used, the tasks they assisted, where data went, and how people verified the outputs. These are the questions UK guidance suggests authorities ask suppliers.
- **C8, masking around hosted calls (its seam in Iteration 1, the masking in Iteration 5).** A minimization layer on a hosted path that C3 already allows. It never opens the free tier.
  - Local code finds personal data in layers: patterns with checksums, a small local entity recognizer, and a local model only on flagged areas such as contact blocks, signatures and tables of people. Code replaces each value with a realistic surrogate, the same one throughout the run.
  - Dates, amounts, legal references and section numbers are never masked, because they are requirement content. Tables about employees stay local and are sent as totals.
  - Hosted models and their tools see only the masked text. A verified quote maps back to the original by offsets. Text the model writes is restored from the mapping and an alias table, and anything left unrestored is flagged for review.
  - The mapping stays in the run folder, out of spans, the ledger, cassettes and logs, and `purge` deletes it.
  - Iteration 1 builds only the seam: every prompt and tool result is built from a text view, which is the original text by default, and a test shows that nothing bypasses it.
  - Iteration 5 builds the masking and compares privacy tiers on the hero, 5 repeats each. PV0 sends original text to a hosted model (synthetic documents only), PV1 sends masked text, and PV3 runs everything locally. PV2, a local `extract` that sends only masked records to hosted reasoning, joins the `hybrid` profile in Iteration 7. PV1 and PV2 serve client documents only if their missed mandatory requirements stay within noise of PV0, every quote restores, and leftovers are flagged. PV3, already allowed, shows how far local models trail PV0. S-15 compares typed placeholders with realistic surrogates.
- **C9, one egress rule for every outbound channel (Iteration 1 for the channels that exist, then each iteration that adds one).**
  - An egress register, `config/egress.yaml`, lists every destination a run may reach, with what it may receive and whether it is local: model providers, MCP servers, research and documentation services, the trace collector and the parser service. It also feeds the AI bill of materials and C7's disclosure.
  - Every outbound client is built through one check against the register and the run's data class. A client run reaches local destinations only, unless an engagement's C3 terms add a provider, and then only through C8's masked text.
  - Tool and MCP arguments follow the same rule. Research topics and documentation queries are built by code from typed fields, never from document text, and from Iteration 5 they are checked against the values the masking found. Until then, client runs keep research `off` or `pack`.
  - Metadata counts as content. Files outside the corpus get ids from their hash alone, so file names never reach run ids, spans or folder names. Research notebooks are titled by run hash. `reflect`'s thoughts go to the run folder, and spans carry only their counts and hashes, like every other span.
  - Development tools count too. Client documents live outside the repository, under a data root that `guard` checks, so coding assistants and Goldfish reviewers never read them.
  - [`docs/governance.md`](../docs/governance.md) lists the channels and their rules.
- **Dropped on the evidence:**
  - Routing gated by a scan, M2 as first proposed.
  - Pseudonymization before hosted calls as a basis for sending, M3 as first proposed. C8 keeps masking as minimization on a path that is already allowed.

**Recommendation.** C1, C2, C4 and C5 in Iteration 1, with C8's seam and C9's first part; C7 in Iteration 4; C3 with C8's masking in Iteration 5; C9's later parts with the channels they cover, research in Iteration 2 and Context7 and `reflect` in Iteration 3; C6 optional. C2 changes the consent override of ADR-010, so it needs a new ADR. Section 4.4 of [`docs/designs/iteration-1.md`](../docs/designs/iteration-1.md) gives the Iteration 1 parts.

**Status on 2026-11-03.** The first architecture review raised C2 on its own (item A-31: the override serves no stated need and admits a client document to a tier whose terms forbid it). The owner held it with this decision, so the override stays until D-05 is decided, and `docs/architecture.md` marks it as D-05's open question.

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
| Iteration 1 | Review gold v2, about 1 hour; write the held-out RFP's requirement list, about 1 hour; decide D-01, D-02 and D-05; triage the Stage 9 review |
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
