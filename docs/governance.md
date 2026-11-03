# Governance

How Bidwright is governed, stated in the terms a client's AI governance function uses: EY's roles for AI use cases, EY's trust layer for agentic AI, and the NIST AI Risk Management Framework (AI RMF 1.0). It describes the current tag. The sources were read at source on 2026-11-03 ([`verification_log.md`](verification_log.md)). The inventory of models, prompts, agent controls, tools, services and dependencies is the generated [AI bill of materials](ai-bom.md).

## Roles

EY's paper on AI use case management names four roles for AI models and agents. In a one-owner project, one person holds several of them; in a deployment, each has its own holder.

| Role, as EY defines it | In this project | In a deployment at a bid team |
|---|---|---|
| AI program sponsor: sets the objectives for AI models and agents, aligned with business strategy | The owner | The head of bids, or the partner who owns the pursuit process |
| Use case owner: sets purpose, data sources and goals, and for agents the execution boundaries, permissions and intervention mechanisms | The owner, through `config/agents.yaml`, `config/limits.yaml` and the ADRs | The bid manager who owns the tool for a pursuit |
| AI governance team: policies, compliance frameworks and ethical review | Not separate: the owner approves every ADR, and independent reviews check the design (`context/Master-Plan.md`, section 2.11) | The client's AI governance or risk function, which reviews the ADRs, the AI bill of materials and the evaluation results |
| Human-in-the-loop supervisor: monitors agent decisions and intervenes when autonomy exceeds acceptable risk | Whoever reads a draft: every output is `UNREVIEWED_DRAFT` (ADR-008) | The reviewer at the two gates, from Iterations 3 and 4: one approves the solution, the other the final proposal |

## The trust layer

EY's article on agentic AI governance sets out a trust layer that builds governance into the system rather than beside it, on three principles.

| Principle | In Bidwright |
|---|---|
| Clear decision rights, set by how much freedom an agent has | Agents reach only the tools their allowlist names, through `ToolGateway`, which code enforces outside the model. The tools are read-only. No agent can submit or approve anything (ADR-009, ADR-008). |
| Real-time monitoring of AI performance | Every call writes a ledger entry and a span, and every run ends in one status with a reason (ADR-015). Each run is scored against known answers, and quality signals tracked across runs arrive with the control plane in Iteration 2. |
| Escalation paths that send high-impact calls to people | Every output waits for a person. From Iteration 3, a run waits in `WAITING_HUMAN` at each gate, and a blocked gate is never passed automatically. |

The article also asks that every action be signed, traced and reversible. Each run's manifest records its commit, models, prompt hashes and input hashes; spans trace every node, call and tool call; and nothing leaves draft status, so every output can be discarded.

## NIST AI RMF 1.0

| Function | What it asks, in short | Where Bidwright answers it |
|---|---|---|
| GOVERN | Policies, accountability and roles; GOVERN 3.2 asks for defined roles and responsibilities for human-AI configurations and oversight | The roles above; ADRs with an owner decision for every design change; the boundaries in `AGENTS.md` |
| MAP | Context and intended use; MAP 1.1 asks that intended purposes, settings and context-specific laws and expectations be understood and documented | [`brief.md`](brief.md), `ASSUMPTIONS.md`, the threat model in [`security.md`](security.md) and the data classes below |
| MEASURE | Test, evaluation, verification and validation; MEASURE 2.4 asks that the system's behavior be monitored in production; MEASURE 2.10 that privacy risk be examined and documented | The evaluation harness and quality scenarios ([`evaluation.md`](evaluation.md), section 10 of [`architecture.md`](architecture.md)); the ledger and spans; the sensitive-information section below |
| MANAGE | Treating risks; MANAGE 2.4 asks for mechanisms to supersede, disengage or deactivate a system whose outcomes are inconsistent with its intended use | Per-run budgets and statuses, `DRAFT_ONLY`, the failure log in `DECISIONS.md`; a stop command between steps arrives in Iteration 2 |

## Sensitive information

A real RFP is confidential by default, and it often holds personal data: the names and contact details of the buyer's staff, signatures and forms, and in some annexes data about employees. It can also hold commercially sensitive facts, such as budgets, incumbents' prices or details of the buyer's security. Bidwright is built and evaluated on synthetic RFPs only, so no real person's data has entered it. This section records what protects a real document at `v0.0`, and what does not yet.

### Data classes and where text goes

| Data class | How it is recognized | Profiles allowed at `v0.0` |
|---|---|---|
| Synthetic | Its sha256 is listed in `inputs/CORPUS.sha256` | `free` and `local` |
| Client document | Any other file | `local`, where nothing leaves the machine. `free` refuses it unless the run passes the consent string, which the run manifest records. |

On `free`, prompts go to Google's Gemini API, whose free-tier terms let the provider use prompt content (V-03). On `local`, they go to Ollama on the same machine. Where each model runs is listed in the [AI bill of materials](ai-bom.md).

### What holds the document's content

| Location | Content | Protection at `v0.0` |
|---|---|---|
| `outputs/<run>/`: frozen text, passages, search index, checkpoints, records, tool results, summary, proposal | Yes | Local disk, ignored by Git; no retention period or purge command yet |
| `tests/cassettes/` | Model answers, which quote the document | `bidwright record` refuses any file outside the synthetic corpus, on every profile (fixed 2026-11-03) |
| `spans.jsonl` and Phoenix | No document text: hashes, counts, timings and costs, and the run id, which holds the input file's name | Phoenix listens on loopback only |
| `ledger.jsonl`, `run_manifest.json` | No: models, hashes, token counts and costs, and the input's file name and hash | Local disk, ignored by Git |
| Logs | No: counts only | None needed |

### Outbound channels

Each place a run, or a tool around it, can send text. Rules marked D-05 are proposed, as C8 and C9 in [`context/Decision-Form.md`](../context/Decision-Form.md).

| Channel | From | What it receives | Rule |
|---|---|---|---|
| Model providers: Gemini, then Cerebras and Groq from Iteration 3 | `v0.0` | Prompts built from passages, records and tool results | Synthetic documents only on hosted profiles, unless the run passes the consent override, which the manifest records; client documents on `local`. Under client terms, masked text only (D-05). |
| The trace collector, Phoenix | `v0.0` | Spans without document text, and the run id | Loopback only. Client documents get ids from their hash alone (D-05). |
| The parser service, Docling | Iteration 1 | Whole documents | A local container. It gets no route out if its image needs no download at run time (D-05, checked at the build). |
| NotebookLM, through its MCP server | Iteration 2 | Research topics, follow-up questions and notebook titles | Never RFP text: a gateway rule denies a query that copies 8 or more words of a passage. Proposed under D-05: topics built by code from typed fields, notebook titles carrying a run hash, and research `off` or `pack` on client runs until the masking's list of values exists. |
| Context7 | Iteration 3 | Library names, versions and queries | Queries built by code from a claim's library, version and feature fields (D-05) |
| The sequential-thinking server, for `reflect` | Iteration 3, off by default | The agent's thoughts | A local process over stdio that needs no network, with its thought logging off. Thoughts are kept in the run folder, and spans carry only their counts and hashes (D-05). |
| Coding assistants and Goldfish reviewers | Development | Any file in the working tree that they open | Client documents stay outside the repository, under a data root that `guard` checks (D-05) |
| GitHub | Development | Committed files, including cassettes | `bidwright record` takes corpus files only; `private/` and `outputs/` are ignored by Git; gitleaks runs in CI |

### Not covered yet

- Nothing detects personal data or other sensitive content in an input.
- Nothing masks personal data before a hosted call.
- Run ids carry the input file's name, and spans carry the run id, so a remote trace collector would receive file names.
- No single control limits where a run connects: each outbound client is configured on its own.
- Run folders and caches have no retention period and no purge command, and rely on the operating system for protection at rest.
- The consent string on `free` records the operator's acceptance of the provider's terms. Those terms say not to submit sensitive, confidential or personal information to the free quota, so the string should not admit a client document at all.

Research jobs DR-20 and DR-21 tested the first proposals on 2026-11-03 (section 17 of [`context/Research-Register.md`](../context/Research-Register.md)). A clean scan cannot clear a document, and pseudonymization is fragile on a round trip and leaves the sender's duties in place, so the revised measures treat every client document as confidential and route by the providers' terms. A follow-up the same day added two measures: masking around hosted calls, as minimization on an allowed path, and one egress rule for every outbound channel above. All are decision D-05 in [`context/Decision-Form.md`](../context/Decision-Form.md).
