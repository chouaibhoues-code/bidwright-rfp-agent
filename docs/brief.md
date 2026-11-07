# Engagement brief

For business readers: what was asked, what the integrated `v0.2` workflow delivers, its measured limits, and what a client would decide next. Iteration 3 is in progress; its design is not evidence of a completed feature. The technical detail is in [`architecture.md`](architecture.md) and [`DECISIONS.md`](../DECISIONS.md).

## The problem

A bid team that receives an RFP package must find every mandatory requirement and submission rule before it writes a word, because one missed item can exclude the bid. The work is manual and repeated for every pursuit, and its misses stay invisible: a requirement nobody found leaves no row in the compliance matrix.

## The request, as read

EY asked for an application that reads an RFP and produces a structured solution summary of requirements, approach and risks, as a genuine agentic workflow with an evaluation harness and tracing of tokens, latency and cost. Two gaps in the request shaped the response:
- **No RFP came with it.** The owner chose synthetic RFPs whose correct answers are known, so quality can be measured. Real client documents are outside the submission's data scope.
- **It names the outputs, not the user.** Bidwright serves a bid team, so each output is written for one reader: the bid director, the bid manager, the solution lead.

## What good looks like

| Measure | Target | Measured evidence at `v0.2` |
|---|---|---|
| Submission hazards missed | None | Development: 0 of 1; two live hero runs: 0 of 9 |
| Mandatory requirements missed | At most 2 of 45 on the hero package, in the median of 5 runs | Development: 0 of 8; two live hero runs missed 2 and 3 of 45. The five-run Iteration 3 gate is pending |
| Requirements backed by a quote that code has checked against the RFP | All | Development: every accepted quote verified verbatim |
| Cost and time per RFP | Reported for every run | Development sample: 14 requests, 54 active seconds, $0 charged and $0.0544 at the recorded paid rate |
| Decisions taken by a person | All | Every output stays `UNREVIEWED_DRAFT` until a person signs it off |

The development sample found two of three planted risks. Its [scorecard](../evals/results/runs/20261105T120916Z-dev-rfp-db9eeb00-free/scorecard.md) and [run manifest](../samples/dev/run_manifest.json) support these figures. The independently authored held-out RFP missed none of its 22 mandatory requirements in five repeats with research off. Synthetic results establish repeatability on these cases; they do not establish production accuracy. [`evaluation.md`](evaluation.md) reports the larger package's misses, the baselines and a corrected scorer defect alongside the original figures.

## The response

Bidwright is a deterministic shell around a probabilistic core. Code screens and splits the RFP into numbered passages, checks quoted evidence, and routes the workflow. The model reads obligations, maps an approach, finds risks and drafts. The risk agent chooses searches and date arithmetic through a gateway outside the model. A research agent can investigate domain topics without sending RFP text; the default demo instead loads a committed research pack. Run control supports stop and resume without repeating an answered call. Everything Bidwright writes is a draft for people to decide on.

## Scope

- **Integrated at `v0.2`:** PDF, DOCX and XLSX packages with addenda and precedence; hidden-content screening; requirements with verified quotes; evaluation factors and weights; a solution summary, short proposal, compliance matrix, clarification questions and submission checklist; domain research; stop and resume; and a ledger and trace for every run. The recorded demo needs no keys or network after setup.
- **Iteration 3, in progress:** capability evidence assessment, solution options and a manifest, technology checks, a human solution gate, UI and API, and measured agent comparisons. Completion requires the gate in section 5 of [`context/Master-Plan.md`](../context/Master-Plan.md), not just individual modules passing tests.
- **Later scope:** the full proposal pack and final evaluation extensions. They are outside the integrated `v0.2` demonstration.

## Questions for the client

The request was not clarified with EY, by the owner's choice, so the open points are recorded as assumptions in [`ASSUMPTIONS.md`](../ASSUMPTIONS.md). Before a deployment, these would go to the client:
1. Which documents, and how large: a short brief, or full packages with annexes and addenda?
2. Which model providers and regions are approved for client documents, and on what data terms?
3. Who reviews and signs off each output, and how soon must a first compliance matrix be ready?
4. When they conflict, which matters more: finding every obligation, or the reviewer time spent on false alarms?
5. How long may run data be kept, and where?

## Risks

- **Missed or unsupported content.** The hero package still has missed mandatory requirements, and the current approach does not consume the domain research. Iteration 3 adds evidence assessment and measures agent contributions before claiming an improvement.
- **Synthetic documents are cleaner than real tenders.** A requirement list written independently by the owner, and public benchmarks for single stages, check the scores from outside.
- **Confidential documents.** Client files run on the local profile. Under D-05, Iteration 1 built one egress register for every outbound channel and the seam where masking of personal data around hosted calls will sit. [`governance.md`](governance.md) records what protects a document now.
- **Over-trust.** Each requirement shows its quote, rejected quotes are counted, and every output is labeled a draft.

## Owner decisions before release

The owner accepted the Iteration 3 design and UI scope on 2026-11-05 (D-10 and D-11), and created the assessment provider key (D-03). The owner reviewed and hashed gold v4 with the ladders' hypotheses on 2026-11-07, and has recorded the 3-5 minute demo. The remaining release work includes reviewing ten assessments, approving a manifest, triaging the architecture review, and accepting any measured gate exception. The owner also supplies rough hours in [`TIMELOG.md`](../TIMELOG.md) and checks reviewer access to the repository and video. [`context/Decision-Form.md`](../context/Decision-Form.md) records the decisions and owner inputs.
