# Governance

How Bidwright is governed, stated in the terms a client's AI governance function uses: EY's roles for AI use cases, EY's trust layer for agentic AI, and the NIST AI Risk Management Framework (AI RMF 1.0). It describes the current tag, `v0.2`. The sources were read at source on 2026-11-03 ([`verification_log.md`](verification_log.md)). The inventory of models, prompts, agent controls, tools, services and dependencies is the generated [AI bill of materials](ai-bom.md).

## Roles

EY's paper on AI use case management names four roles for AI models and agents. In a one-owner project, one person holds several of them; in a deployment, each has its own holder.

| Role, as EY defines it | In this project | In a deployment at a bid team |
|---|---|---|
| AI program sponsor: sets the objectives for AI models and agents, aligned with business strategy | The owner | The head of bids, or the partner who owns the pursuit process |
| Use case owner: sets purpose, data sources and goals, and for agents the execution boundaries, permissions and intervention mechanisms | The owner, through `config/agents.yaml`, `config/limits.yaml`, `config/research.yaml`, the tool pins and the ADRs | The bid manager who owns the tool for a pursuit |
| AI governance team: policies, compliance frameworks and ethical review | Not separate: the owner approves every ADR, and independent reviews check the design (`context/Master-Plan.md`, section 2.11) | The client's AI governance or risk function, which reviews the ADRs, the AI bill of materials and the evaluation results |
| Human-in-the-loop supervisor: monitors agent decisions and intervenes when autonomy exceeds acceptable risk | The operator, who can stop, resume and re-budget any run, and whoever reads a draft: every output is `UNREVIEWED_DRAFT` (ADR-008) | The operator of each run, and the reviewer at the two gates, from Iterations 3 and 4: one approves the solution, the other the final proposal |

## The trust layer

EY's article on agentic AI governance sets out a trust layer that builds governance into the system rather than beside it, on three principles.

| Principle | In Bidwright |
|---|---|
| Clear decision rights, set by how much freedom an agent has | Agents reach only the tools their allowlist names, through `ToolGateway`, which code enforces outside the model with five rules beside its four checks; code binds every notebook and job id, so no agent names one. The tools are read-only for RFP data, and the research tools create only their own notebooks. No agent can submit or approve anything (ADR-008, ADR-009, ADR-032). |
| Real-time monitoring of AI performance | Every call appends a ledger entry as it finishes and writes a span; `events.jsonl` records every status change, recovery and security event as it happens, each security event with its attribution class, and `tool_calls.jsonl` every tool call and denial; a circuit breaker stops calls to a failing model or server (ADR-015, ADR-031). Each run is scored against known answers. |
| Escalation paths that send high-impact calls to people | Every output waits for a person. An operator can stop any run between steps. From Iteration 3, a run waits in `WAITING_HUMAN` at each gate, and a blocked gate is never passed automatically. |

The article also asks that every action be signed, traced and reversible. Each run's manifest records its commit, models, prompt hashes, input hashes, the environment it ran in and every status it passed through; spans trace every node, call and tool call, and `tool_calls.jsonl` every tool request and result; and nothing leaves draft status, so every output can be discarded.

## NIST AI RMF 1.0

| Function | What it asks, in short | Where Bidwright answers it |
|---|---|---|
| GOVERN | Policies, accountability and roles; GOVERN 3.2 asks for defined roles and responsibilities for human-AI configurations and oversight | The roles above; ADRs with an owner decision for every design change; the boundaries in `AGENTS.md`; a person re-pins the research server's tools after reviewing a new version |
| MAP | Context and intended use; MAP 1.1 asks that intended purposes, settings and context-specific laws and expectations be understood and documented | [`brief.md`](brief.md), `ASSUMPTIONS.md`, the threat model in [`security.md`](security.md) and the data classes below |
| MEASURE | Test, evaluation, verification and validation; MEASURE 2.4 asks that the system's behavior be monitored in production; MEASURE 2.10 that privacy risk be examined and documented | The evaluation harness and quality scenarios ([`evaluation.md`](evaluation.md), section 10 of [`architecture.md`](architecture.md)); the ledger, spans and events; the query audit, which reports how close each research query came to the RFP; the sensitive-information section below |
| MANAGE | Treating risks; MANAGE 2.4 asks for mechanisms to supersede, disengage or deactivate a system whose outcomes are inconsistent with its intended use | `bidwright stop`, which halts a run between steps, and `bidwright resume`, which continues it without repeating spend; per-run budgets, raised only by a recorded percentage; the circuit breaker; `DRAFT_ONLY`; the failure log in `DECISIONS.md` |

## Sensitive information

A real RFP is confidential by default, and it often holds personal data: the names and contact details of the buyer's staff, signatures and forms, and in some annexes data about employees. It can also hold commercially sensitive facts, such as budgets, incumbents' prices or details of the buyer's security. Bidwright is built and evaluated on synthetic RFPs only, so no real person's data has entered it. This section records what protects a real document at `v0.2`, and what does not yet. The rules are ADR-026's, decided by the owner as D-05 on 2026-11-03.

### Data classes and where text goes

| Data class | How it is recognized | Where it may run at `v0.2` |
|---|---|---|
| Synthetic | Its sha256 is listed in `inputs/CORPUS.sha256` | Every profile; every research mode |
| Client document | Any other file; a package is a client package when any of its files is | `local`, where nothing leaves the machine. `free` refuses it unless the run passes the consent override, which the run manifest records beside the data class; the owner accepted that exception's conflict with the free tier's terms (ADR-026). Research mode `pack` only: `live` is refused before the run folder exists. |

The data class is computed before the run folder exists, and `config/egress.yaml` lists every destination a run may reach: a client run reaches local destinations only, except Gemini on a `free` run that passed the consent override. On `free` and `paid`, prompts go to Google's Gemini API, whose free-tier terms let the provider use prompt content (V-03); on `local`, they go to Ollama on the same machine. Where each model runs is listed in the [AI bill of materials](ai-bom.md).

### What holds the document's content

| Location | Content | Protection at `v0.2` |
|---|---|---|
| `outputs/<run>/`: frozen text, passages, search index, checkpoints, journal, records, tool results, summary, proposal | Yes | Local disk, ignored by Git; client runs expire after 30 days, and `bidwright purge` deletes a run, its journal and its cache entries |
| `tests/cassettes/` | Model answers, which quote the document | `bidwright record` refuses any file outside the synthetic corpus, on every profile |
| `research_packs/` | Web research on a domain: source titles and URLs, and excerpts of at most 300 characters; no RFP text | Committed only by reviewed commits; the builder leaves out a source the operator names, such as a published tender, and lists solicitation-like sources for review |
| `spans.jsonl` and Phoenix | No document text: hashes, counts, timings and costs, and the run id; a client document's id comes from its hash, not its file name | Phoenix listens on loopback only |
| `ledger.jsonl`, `run_manifest.json`, `events.jsonl` | No document text: models, hashes, token counts, costs, statuses and reasons | Local disk, ignored by Git |
| Logs | No: counts only, with the loggers that would print a PDF's content or a request body held at `WARNING` | None needed |

### Outbound channels

Each place a run, or a tool around it, can send text. The rules come from D-05 (ADR-026), and each channel's part arrives with the iteration that adds the channel.

| Channel | From | What it receives | Rule |
|---|---|---|---|
| Model providers: Gemini, then Cerebras and Groq from Iteration 3 | `v0.0` | Prompts built from passages, records and tool results through the text view | Synthetic documents on hosted profiles, unless a `free` run passes the consent override, which the manifest records; client documents on `local`. Under client terms, masked text only, from Iteration 5. |
| The trace collector, Phoenix | `v0.0` | Spans without document text, and the run id | Loopback only; client documents get ids from their hash alone |
| The parser service, Docling | `v0.1` | Whole documents, after `guard` | A local container, published on loopback only |
| NotebookLM, through its MCP server | `v0.2` | Research queries, built by code from the brief's topics and a fixed research envelope, follow-up questions, and notebook titles carrying the run id | Never RFP text: the brief drops a topic sharing 4 consecutive words with a passage, and G3 denies any query or question sharing 8. The egress register treats the server as remote, so a client run gets research mode `pack` only. The server runs on the host, bound to loopback, only during research sessions, and its tools must match their pins. |
| Context7 | Iteration 3 | Library names, versions and queries | Queries built by code from a claim's library, version and feature fields |
| The sequential-thinking server, for `reflect` | Iteration 3, off by default | The agent's thoughts | A local process over stdio that needs no network, with its thought logging off. Thoughts are kept in the run folder, and spans carry only their counts and hashes. |
| Coding assistants and Goldfish reviewers | Development | Any file in the working tree that they open | Client documents stay outside the repository, under a data root that `guard` checks |
| GitHub | Development | Committed files, including cassettes and research packs | `bidwright record` takes corpus files only; `private/` and `outputs/` are ignored by Git; gitleaks runs in CI; the hygiene test and the pack builder check for names the repository must not carry |

### Not covered yet

- Nothing detects personal data or other sensitive content in an input, by design: a clean scan cannot clear a document, so routing follows the data class (ADR-026).
- Nothing masks personal data before a hosted call; the text view is the seam for Iteration 5's masking.
- The consent override on `free` admits a client document against the free tier's terms, which say not to submit sensitive, confidential or personal information; the owner accepted that risk, and each use is recorded.
- The egress register decides locality by host name, so a Compose service name copied into `.env` on the host could resolve to another computer (D-06, deferred).
- In research mode `live`, a source that reads like a published solicitation is left out before any excerpt is made (ADR-038), but a tender under a plain title, and the job's own report, are not filtered.
- Run folders rely on the operating system for protection at rest.

Research jobs DR-20 and DR-21 tested the first proposals on 2026-11-03 (section 17 of [`context/Research-Register.md`](../context/Research-Register.md)). A clean scan cannot clear a document, and pseudonymization is fragile on a round trip and leaves the sender's duties in place, so the measures treat every client document as confidential and route by the providers' terms.
