# Engagement brief

For business readers: what was asked, how the request was read, what Bidwright does at `v0.0` and how well, and what a client would decide next. The technical detail is in [`architecture.md`](architecture.md) and [`DECISIONS.md`](../DECISIONS.md).

## The problem

A bid team that receives an RFP package must find every mandatory requirement and submission rule before it writes a word, because one missed item can exclude the bid. The work is manual and repeated for every pursuit, and its misses stay invisible: a requirement nobody found leaves no row in the compliance matrix.

## The request, as read

EY asked for an application that reads an RFP and produces a structured solution summary of requirements, approach and risks, as a genuine agentic workflow with an evaluation harness and tracing of tokens, latency and cost. Two gaps in the request shaped the response:
- **No RFP came with it.** Rather than ask, the owner chose to build synthetic RFPs whose correct answers are known, so quality is measured, not judged by eye. A client's own documents run on a profile that keeps them on the machine.
- **It names the outputs, not the user.** Bidwright serves a bid team, so each output is written for one reader: the bid director, the bid manager, the solution lead.

## What good looks like

| Measure | Target | At `v0.0`, on the 4-page development RFP |
|---|---|---|
| Submission hazards missed | None | 0 of 1 |
| Mandatory requirements missed | At most 2 of 45 on the 25-page hero RFP, in the median of 5 runs | 0 of 8; the hero RFP arrives in Iteration 1 |
| Requirements backed by a quote that code has checked against the RFP | All | All |
| Cost and time per RFP | Reported for every run | 11 model calls in 26 seconds; $0 on the free tier, $0.03 at paid list prices |
| Decisions taken by a person | All | Every output stays a draft until a person signs it off |

Planted risks are the weak point so far: the run found 1 of 3.

## The response

Bidwright is a deterministic shell around a probabilistic core. Code splits the RFP into numbered passages, checks every quote the model gives against the document, and routes every step. The model does only what code cannot: reading obligations, mapping an approach, finding risks, drafting. One agent with tools works where a loop earns its place, the risk search, and every other step is a single checked call. A measured comparison decides whether each agent stays. Everything Bidwright writes is a draft for people to decide on.

## Scope

- **Built, `v0.0`:** one PDF in; out come the solution summary (hazards first, then requirements with checked quotes, approach, risks and open questions), a three-section proposal draft, and the cost and timing of every model call. A recorded run replays without keys.
- **Next, Iteration 1:** packages with addenda and spreadsheets, screening for hidden text, a compliance matrix, clarification questions and a submission checklist. Its design is in [`designs/iteration-1.md`](designs/iteration-1.md), awaiting review.
- **Later:** research into the RFP's domain, solution options approved by a person, the full proposal pack, and measured comparisons of every agent. The plan is in section 10 of [`context/Master-Plan.md`](../context/Master-Plan.md).

## Questions for the client

The request was not clarified with EY, by the owner's choice, so the open points are recorded as assumptions in [`ASSUMPTIONS.md`](../ASSUMPTIONS.md). Before a deployment, these would go to the client:
1. Which documents, and how large: a short brief, or full packages with annexes and addenda?
2. Which model providers and regions are approved for client documents, and on what data terms?
3. Who reviews and signs off each output, and how soon must a first compliance matrix be ready?
4. When they conflict, which matters more: finding every obligation, or the reviewer time spent on false alarms?
5. How long may run data be kept, and where?

## Risks

- **Model quality on free tiers.** Every role runs Gemini Flash-Lite on the free profile (ADR-003). A comparison with the larger Flash model waits for a paid budget.
- **Synthetic documents are cleaner than real tenders.** A requirement list written independently by the owner, and public benchmarks for single stages, check the scores from outside.
- **Confidential documents.** Client files run on the local profile. Detecting and pseudonymizing personal data is proposed; [`governance.md`](governance.md) records what protects a document now.
- **Over-trust.** Each requirement shows its quote, rejected quotes are counted, and every output is labeled a draft.

## Decisions open

The owner decides, as the client would. Each decision is set out in [`context/Decision-Form.md`](../context/Decision-Form.md):
- D-01: the paid budget.
- D-02: the Iteration 1 design.
- D-05: the measures for sensitive information.
