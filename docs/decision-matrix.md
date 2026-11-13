# Decision matrix

Bidwright's architecture choices, mapped to a published taxonomy of architecture options for agents built on foundation models, with the quality trade-offs the taxonomy assigns to each. The architecture review reads this beside [`architecture.md`](architecture.md) and the ADRs in [`DECISIONS.md`](../DECISIONS.md).

## The source

Zhou, Lu, Chen, Zhu, Xu, Xing and Harrer, "Analysis of Architecture Options for Foundation-model-based Agents: A Taxonomy and Decision Model", arXiv 2408.02920, version 2 of 2026-09-09 (https://arxiv.org/html/2408.02920v2), read 2026-11-02. The arXiv comment says "Accepted" and names no venue. The taxonomy has 11 categories of functional options and 9 non-functional qualities. Its Table 4, "Decision Matrix: Impact of Design Options on Non-functional Qualities", rates 68 options on each quality:
- `++` strong positive, `+` positive, `o` neutral or unspecified, `-` negative, `–` strong negative;
- the qualities, in column order: performance (Perf), reliability (Rel), robustness (Rob), resilience (Resil), security (Sec), maintainability (Maint), responsible and trustworthy AI (RAI), usability (Usab) and compatibility (Comp).

**How far to trust it.** The ratings synthesize a literature review of 66 studies and a survey of 12 experts. They are not measurements of this system, so this document uses them as a checklist: every minus on a chosen option needs an answer in the design, or an accepted cost. The paper's text and Table 4 disagree in six places. One affects a row used here: the text warns of a performance bottleneck for centralized coordination at the scale of thousands of documents, where the table gives `+`. Ratings below are copied from Table 4.

## Options chosen

Status is at `v0.3`. An option planned for a later iteration says so.

| Category | Option chosen | Perf | Rel | Rob | Resil | Sec | Maint | RAI | Usab | Comp | How the design answers each minus | ADR |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Input modality | Single-modality: text from the RFP file | ++ | + | o | o | o | ++ | o | - | o | Usability: Iteration 1 accepts DOCX, XLSX and package folders, all still text. Scanned PDFs are reported, and OCR stays optional. | ADR-010 |
| Context | Semantic context: each passage carries its section path, its list lead-in and its table header | o | ++ | o | o | o | o | + | ++ | o | No minus | ADR-006 |
| Context, goal seeking | Passive suggestion: Bidwright drafts, and people decide | + | o | + | o | o | o | + | o | - | Compatibility: outputs are Markdown and JSON with a schema reference, the compliance matrix is XLSX and CSV, and the proposal pack adds DOCX in Iteration 4 | ADR-008 |
| Role-playing | Agent-as-a-worker: each LLM role does one bounded task under code's routing | + | + | o | o | o | ++ | o | o | o | No minus | ADR-005 |
| Goal type | Task completion | + | o | o | o | o | + | o | + | o | No minus | ADR-005 |
| Planning engine | External planner: the plan is the LangGraph graph, in code | - | ++ | ++ | o | o | + | - | o | o | Performance: batches fan out with `Send`. RAI: the plan is drawn from the compiled graph in [`agents.md`](agents.md), and every step is a traced span. | ADR-005 |
| Tool selection | External tools: `search_rfp`, `read_section`, `search_capabilities`, `date_calc`, `sla_calc` and `ask_research` are code, and the research and documentation servers' tools are reached over MCP, all outside the model | - | ++ | ++ | o | o | + | - | o | o | Performance: tool results are capped at 8 passages, and the loop at 4 turns and 6 calls. RAI: every request and result is traced. | ADR-009 |
| Plan generation | Single-path plan generator: one fixed path per run | + | - | - | - | o | ++ | + | - | o | Reliability, robustness, resilience: code checks after every LLM call, one repair, retries with a fallback model, and a defined result for every failure (section 6.3 of [`architecture.md`](architecture.md)). Usability: the summary orders hazards first and lists open questions. | ADR-005 |
| Memory type | Short-term memory: the run's state; only the response cache, keyed by the whole request, and the committed research packs and knowledge base, which runs read and never write, outlast a run | ++ | o | + | o | o | - | ++ | o | ++ | Maintainability: state is plain typed data in a SQLite checkpoint, and each node writes its own files | ADR-005 |
| Memory format | Structured lists: typed JSONL records validated by Pydantic | ++ | + | ++ | + | o | o | ++ | + | o | No minus | ADR-006 |
| Memory format | Databases: the per-run FTS5 indexes of the RFP and the knowledge base, and the SQLite checkpointer | o | ++ | ++ | ++ | ++ | ++ | + | + | o | No minus | ADR-006 |
| Memory operation | Memory reading: `decide` reads the knowledge base and the RFP through `search_capabilities`, `search_rfp` and `read_section`, and the run's research through `ask_research`; the `risk` agent, off by default, reads the RFP through `search_rfp` | + | – | o | o | o | o | o | + | o | Reliability, strong negative: reading is only from the frozen RFP, the committed knowledge base and the run's screened research, and results carry ids; a claim keeps only the ids its own loop received, and `assess` judges it against those records; a risk that cites no passage, or shares no content word with what it cites, is rejected | ADR-006 |
| Agent coordination | Centralized coordination: the graph is the only coordinator | + | - | - | - | + | + | + | o | o | Reliability, robustness, resilience: the per-step failure table, budgets, the circuit breaker, and stop and resume from checkpoints with the journal (ADR-031). Performance at scale, which the paper's text questions: one RFP per run; a hero run of the `v0.3` defaults makes 92 to 118 requests. | ADR-005 |
| Agent communication | Partial transparency: a role sees typed records, never another role's reasoning | o | o | o | o | o | + | o | o | o | No minus. `assess` never sees the reasoning of the call that wrote the claim it judges. | ADR-005 |
| Tool interface | API: native tool calling with typed arguments | ++ | ++ | + | + | + | + | + | o | ++ | No minus | ADR-009 |
| Output integration | Inline integration: a tool result returns to the conversation as a typed message | + | o | o | o | o | o | + | o | o | No minus | ADR-009 |
| Actuation | Virtual actuation: writes files in the run folder, and nothing else | o | + | o | o | o | + | o | o | o | No minus. Nothing is submitted. | ADR-008 |
| Reflection provider | Environmental reflection: code's checks feed back to the model as repair messages | + | + | o | o | o | + | + | o | o | No minus | ADR-006 |
| Reflection provider | Human reflection: the solution gate, and the final review gate in Iteration 4 | – | ++ | ++ | ++ | + | o | ++ | o | o | Performance, strong negative: accepted. A run waits in `WAITING_HUMAN`, and `--auto-select` exists for evaluation only. | ADR-008 |
| Reflection provider | Cross-reflection: `assess` and `techcheck`'s verdicts on another model family where one can be reached (ADR-045), and `redteam` in Iteration 4 | - | o | o | o | - | - | + | o | o | Performance: `assess` makes no call for a claim with no evidence, and `techcheck` checks at most 15 claims. Security: neither has tools; `assess` reads one claim and the records it cites, `techcheck` one claim and the documentation code fetched for it under the gateway's G3 and G4. Maintainability: one client interface for every provider. Not cross-family on a client run or on `local`, where the generator's family assesses and each assessment is flagged `SAME_FAMILY`. | ADR-011 |
| Reflection mechanism | Chain of thought, as the model's own thinking: a thinking level per role, with free reasoning before the schema | - | + | o | o | o | + | ++ | o | o | Performance: `extract` uses `medium`, the cheapest setting within noise of the best in S-05, and `local` turns thinking off (ADR-004) | ADR-012 |
| Learning capability | In-context learning: a few fixed examples in each prompt; no training | ++ | - | - | o | – | ++ | + | ++ | o | Security, strong negative: examples come from `prompts/examples/`, never from an RFP or gold; RFP text enters only as delimited data; no instruction in data can authorize a tool. Reliability and robustness: code checks every output. | ADR-012 |
| Workflow | Centralized workflow | + | o | - | o | o | o | + | o | o | Robustness: the per-step failure table | ADR-005 |
| Underlying model type | General-purpose models: Gemini Flash-Lite, `gpt-oss-120b` on Cerebras and Groq, and Qwen on `local` | - | o | + | o | o | o | o | ++ | ++ | Performance: Flash-Lite on `free` and `paid` (ADR-003), packs of 40 passages (ADR-027), the ledger's latency per call | ADR-011 |
| Model composition | Multi-model: models per role and profile, a fallback per role, and another family for assessment (Cerebras, then Groq), chosen once a run | – | ++ | + | + | o | – | + | o | - | Performance, strong negative: measured per call in the ledger. Maintainability, strong negative: one client interface, models named only in `config/models.yaml`, and the model recorded on every ledger entry. Compatibility: one adapter per provider. | ADR-011 |
| Model sourcing | Fully externally sourced AI, on `free` | ++ | – | - | – | – | – | – | o | ++ | Reliability and resilience: retries, a fallback model, no retry on a spent daily quota, and cassettes for the demo and tests. Security: synthetic data on `free`, and a client document only through the consent override (ADR-026), keys only in `.env`, no prompt text in spans. Maintainability: model ids pinned in configuration, with their shutdown dates in ADR-011. RAI: verified quotes and `UNREVIEWED_DRAFT`. | ADR-010, ADR-011 |
| Model sourcing | Partially sourced AI, on `local`: open-weight models run on the owner's machine | + | o | o | o | + | o | + | o | + | No minus. It is slow on this machine's CPU (ADR-004), and `assess` runs on the generator's family there, flagged `SAME_FAMILY`. | ADR-004 |

## Options not chosen

| Category | Option | Why not | Reopen if |
|---|---|---|---|
| Role-playing | Agent-as-a-coordinator, rated `-` on performance, reliability and resilience | An LLM choosing the next step makes runs hard to test, resume and audit | Never at this scale; ADR-005 |
| Planning engine | Internal planner | Same reason | ADR-005 |
| Plan generation | Multi-path plan generator | One fixed path is testable. `options` compares 2-3 solutions inside one call, rather than as graph branches, and code ranks them. | A measured gain on the solution ablation |
| Memory type | Long-term memory: what one run writes entering a later run's context | It would open a memory-poisoning path, and no measured need exists. The response cache is not such memory: it answers only a request identical to one already made, with the stored answer, and adds nothing to any prompt. A research pack is not such memory: a person builds it with `bidwright research pack`, which checks for solicitation-like sources and for the names the repository must not carry, and commits it with its hashes; a run refuses a pack whose files do not match them and screens its entries again at load (ADR-033, ADR-038) | The project becomes long-lived |
| Memory format | Embedding memory, rated `-` on maintainability, RAI and usability | Lexical search is strong on text and tables and needs no embedding store | Iteration 7: dense retrieval with fusion beats BM25 |
| Reflection provider | Self-reflection | Published results find self-critique without an outside signal adds about nothing; the gated `reflect` tool is offered only after a failure signal, and stays off because the SO1-T and RK1-T rungs showed no gain (ADR-058, ADR-059) | A later ladder shows a gain |
| Reflection mechanism | Tree of thoughts, rated `–` on performance and maintainability | Cost, with no measured need | None planned |
| Agent coordination | Fully distributed, rated `-` on security and `–` on maintainability and RAI | Hard to test and audit | Never at this scale |
| Workflow | Decentralized workflow, rated `–` on RAI | Same reason | Never at this scale |
| Context, goal seeking | Proactive suggestion | Bid decisions carry legal and commercial weight, so people decide | None: an owner decision |
| Tool interface | UI understanding, rated `–` on performance and compatibility | All tools are code | None planned |
| Actuation | Physical actuation | Out of scope | None |
| Learning capability | Self-learning, group learning | No training or fine-tuning is in scope | None |

## Where the trade-offs concentrate

- **Reliability carries the most minuses:** fully external models (`–`), memory reading (`–`), single-path plans (`-`) and centralized coordination (`-`). Code checks carry the weight: quote verification, the gateway, schemas on every response, and fallback models. QS-1, QS-4 and QS-7 measure them.
- **Security has two strong negatives:** in-context learning and fully external sourcing. The design answers with synthetic data on `free`, a client document reaching it only through the consent override, a gateway outside the model, delimiters treated as hygiene rather than a boundary, and `guard` before any parser. [`security.md`](security.md) maps these to the OWASP lists.
- **Performance and maintainability are spent on purpose:** an external planner and tools, multiple models, and the human gate all cost speed. The ledger measures what the cost is, and the ablations decide whether each agent is worth it.
