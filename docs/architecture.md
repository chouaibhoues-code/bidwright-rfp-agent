# Architecture

This document describes Bidwright as built in Iteration 1, tagged `v0.1`, under the twelve arc42 headings. Iteration 1 builds on the walking skeleton of `v0.0` (a thin version that ran end to end on one PDF) and its documents and review fixes of `v0.0.1`. This document covers only what is built. The work still to come lives in section 10 of [`context/Master-Plan.md`](../context/Master-Plan.md), and the Iteration 1 build plan in [`designs/iteration-1.md`](designs/iteration-1.md). Each heading stays short and points to the file that owns the detail.

## 0. How this architecture is described

Six steps, combining arc42, C4 and ADRs. The method was reviewed against the literature (DR-19 in [`context/Research-Register.md`](../context/Research-Register.md)) and not refuted, which differs from proven; the register lists the seven changes that review made.

| Step | What it produces | Where |
|---|---|---|
| 1. Concerns | Quality scenarios: invariants, checked on every run, and statistical scenarios, measured over repeats | Section 10 |
| 2. Views | C4 Context and Container, an agent view, one run, and deployment. LLM calls, the deterministic boundary, tool allowlists and human control are marked. | Sections 3, 5, 6 and 7 |
| 3. Boundaries | A contract in code wherever LLM output meets code | Section 5.4 |
| 4. Decisions | Short ADRs | Section 9 and [`DECISIONS.md`](../DECISIONS.md) |
| 5. Threats and governance | Trust boundaries and controls mapped to the OWASP lists; roles, the trust layer, NIST AI RMF and sensitive information; the AI bill of materials | [`security.md`](security.md), [`governance.md`](governance.md), [`ai-bom.md`](ai-bom.md) |
| 6. Conformance | Fitness functions in CI; behavior in the evaluation harness | Section 8.7 and [`evaluation.md`](evaluation.md) |

## 1. Introduction and goals

### 1.1 What the system does

The assignment asks for an LLM application that reads an RFP and produces a structured solution summary of requirements, approach and risks. It must be what the assignment calls "a genuine agentic workflow", with an evaluation harness and tracing of tokens, latency and cost. At `v0.1`, Bidwright reads one file or a package folder of PDF, DOCX and XLSX documents, such as an RFP with its addendum and annex, and writes:
- `solution_summary.md` and its JSON form: submission hazards first, then requirements with verified quotes, approach items, risks and open questions;
- `proposal.md`: three short sections (`understanding`, `approach` and `risks_and_assumptions`) drafted from those records;
- the compliance matrix (`compliance_matrix.xlsx` and `.csv`), `clarification_questions.md`, `submission_checklist.md`, and `review/quarantine.md`, which shows a person the hidden content removed before parsing, the small print kept, and the passages that read like instructions to a model;
- the records behind them: the control register of the package's documents, a disposition for every passage, requirement groups, discrepancies, contract flags and lint findings;
- `ledger.jsonl` and `run_manifest.json`: every LLM call's tokens, latency and cost, and the run's status, totals and data class.

Every output carries the status `UNREVIEWED_DRAFT`.

### 1.2 Quality goals

In priority order. Section 10 states each one as a measurable scenario.

| Priority | Goal | Scenarios |
|---|---|---|
| 1 | Functional correctness: no mandatory requirement missed, and every requirement traced to a quote that code has checked | QS-1, QS-2, QS-8 |
| 2 | Security: tools are authorized outside the model, hidden content never reaches a model, and document text is never treated as an instruction | QS-3, QS-4 |
| 3 | Transparency: an unsupported claim is marked, never asserted, and every number traces to a run | QS-5 |
| 4 | Controllability: people decide, and a run stops or waits when it should | QS-6 |
| 5 | Recoverability: provider faults are retried and failed over, and spend is never repeated | QS-7 |

Quote verification protects grounding: a requirement's quote is in the RFP. It does not protect the mandatory count: a clause the model labels `BACKGROUND`, `NOT_BINDING` or `OUT_OF_SCOPE` is a miss, which QS-2 measures and the evaluation funnel charges to the stage that lost it.

### 1.3 Stakeholders

| Stakeholder | Needs from the architecture |
|---|---|
| The EY reviewers | The assignment's required items, visible and runnable without keys; trade-offs they can question |
| The owner | Sole approver of scope and decisions; a design the owner can explain and change live |
| The bid team Bidwright serves, fictional here | A summary they can trust line by line, and drafts they can edit |
| Coding agents | Commands and boundaries, in [`AGENTS.md`](../AGENTS.md) |

### 1.4 Not in `v0.1`

A bid team's problem is that one missed mandatory clause can disqualify a bid, and an overstated compliance claim creates liability. Bidwright answers the first with a disposition for every passage and requirements whose quotes code has checked, and the second with drafts that people approve and a compliance status that starts `UNVERIFIED`. The product's non-goals, among them pricing, win probability, submission, real client data, training and production concerns, are in section 1.4 of [`context/Master-Plan.md`](../context/Master-Plan.md#14-non-goals). Planned components that `v0.1` does not have:
- the supervisor, policy and recovery components, with `bidwright stop` and `resume` (Iteration 2);
- the research tools (Iteration 2) and the proposal pack (Iteration 4);
- `assess`, the independent check of claims against the knowledge base of supplier capabilities, which `knowledge_base/` already holds (Iteration 3);
- the two human gates (Iterations 3 and 4);
- OCR: a scanned file is reported, and its pages are not parsed;
- client documents on `free`: they run on `local`; the consent override in section 3.1 stays by the owner's decision of 2026-11-03 (D-05, ADR-026), which records its conflict with the free tier's terms as an accepted risk.

## 2. Constraints

| Kind | Constraint |
|---|---|
| Assignment | Synthetic RFPs only: no real tender or client document enters the repository, a prompt or a test. The deliverables include `DECISIONS.md`, [`ASSUMPTIONS.md`](../ASSUMPTIONS.md), rough timings and a 3-5 minute demo. |
| Models | Free tiers first. The owner's AI Studio limits, read 2026-11-02: 20 requests a day on `gemini-3.8-flash`, 500 on `gemini-3.5-flash-lite` (ADR-003). Free-tier prompts may be used by the provider to improve its products, so `free` runs only on the synthetic corpus. |
| Machine | The build laptop, a Windows machine whose 4 GB GPU the local models exceed, so Ollama runs mostly on CPU (V-06 in [`verification_log.md`](verification_log.md)). Ollama cuts a prompt longer than `num_ctx` silently (S-14), so the adapter fails a call whose evaluated prompt reaches `num_ctx`. |
| Parsing | `docling-serve`, a 5 GB image, parses PDF, DOCX and XLSX for live runs; replays and tests read recorded Docling responses and need no service. |
| Toolchain | Python 3.12 and uv; ruff, pyright and pytest; GitHub Actions on a private repository |
| Conventions | Keys only in `.env`; ISO 8601 dates; one writer per output file; a design change needs an ADR |

## 3. Context and scope

### 3.1 Business context

```mermaid
flowchart LR
    team(["Bid team member"])
    reviewer(["EY reviewer"])
    rfp[/"File or package folder in inputs/<br/>PDF, DOCX, XLSX; synthetic, in CORPUS.sha256"/]
    bw["Bidwright<br/>CLI and workflow"]
    docling["docling-serve<br/>parser, localhost"]
    gemini["Gemini API<br/>free or paid tier"]
    ollama["Ollama<br/>local models"]
    phoenix["Phoenix<br/>trace collector"]
    out[/"outputs/run/<br/>summary, proposal, matrix, review files, ledger"/]
    evalr["bidwright-eval<br/>separate scorer"]
    gold[/"evals/gold<br/>known answers"/]
    score[/"evals/results/<br/>scorecards, reports"/]

    team -- "bidwright run" --> bw
    rfp --> bw
    bw -- "file bytes, after guard" --> docling
    bw -- "typed requests through the text view, HTTPS" --> gemini
    bw -- "typed requests, localhost" --> ollama
    bw -- "OTLP spans without prompt text" --> phoenix
    bw --> out
    reviewer -- "bidwright demo" --> out
    reviewer -- "scorecards" --> score
    out --> evalr
    gold --> evalr
    evalr --> score
```

| Interface | Direction | Form |
|---|---|---|
| RFP input | In | One file or a folder under `inputs/`: PDF, DOCX or XLSX, with an optional `package.yaml` naming roles and precedence. On `free`, every file's sha256 must be listed in `inputs/CORPUS.sha256`, or the run is started with `--allow-non-corpus=i-accept-free-tier-terms`, which the manifest records beside the data class `client` (ADR-026). The run entry checks the rule before the run folder exists. |
| Docling | Out | HTTP to `DOCLING_URL` (`http://localhost:5001` on the host, `http://docling:5001` in Compose), after `guard` has sanitized the file; only for live and record runs |
| Gemini | Out | The native `google-genai` SDK (ADR-001), with `GEMINI_API_KEY`, or `GEMINI_PAID_API_KEY` on the `paid` profile, from `.env` |
| Ollama | Out | HTTP to `OLLAMA_HOST`: `http://localhost:11434` on the host and `http://ollama:11434` in Compose |
| Phoenix | Out | OTLP over HTTP to `PHOENIX_ENDPOINT` when it is set, answers and is allowed for the run's data class; otherwise spans go to `outputs/<run>/spans.jsonl` |
| Egress register | Check | `config/egress.yaml` lists every destination, its hosts, whether it is local and what it may receive. Before a run, each backend, the trace endpoint and the parser are checked against it and the data class; a client run reaches no remote destination except through the consent override (ADR-026). |
| Run folder | Out | `outputs/<run>/`, gitignored; `bidwright purge` deletes a run and its cache entries, and `--expired` every client run past the retention period |
| Evaluation | Read only | `bidwright-eval` reads finished run folders and the gold, and writes `evals/results/` |

### 3.2 The LLM boundary

Everything a model writes crosses one boundary. Code sends a typed request built from a schema and receives text that must parse into a schema, and an acceptance check in code then decides what reaches the graph's state. The model never sees character offsets, never chooses the next step, and never runs a tool itself. Everything a model reads passes one seam, the text view (ADR-026): context packs, section views, cluster tasks and search results are built from `TextView.text`, and stored records keep the frozen text. At `v0.1` the view is `IdentityView`, which shows the frozen text with line breaks as spaces; a masking view replaces it in Iteration 5. Section 5.4 lists the contract for each call.

## 4. Solution strategy

The design rests on one principle: a deterministic shell around a probabilistic core. Code checks what code can check (files, quotes, numbers, ids, schemas, allowlists and budgets), and the LLM does only the judgment and generation that code cannot, inside those checks (ADR-005).

| Goal | Strategy at `v0.1` | Instead of | ADR |
|---|---|---|---|
| Every requirement traceable | Each document becomes passages with ids and offsets into one frozen text. The model cites passage ids and copies a quote, and code checks the quote and every number and date in the statement. | Offsets or citations emitted by the model | ADR-006 |
| No obligation silently dropped | Every passage reaches `extract` in a context pack and gets a disposition; cues and zones are hints; `coverage` re-reads the gaps | A cue filter in front of the model | ADR-017, ADR-018 |
| Hidden text never reaches a model | `guard` scans the raw files, removes hidden content from the copy that is parsed, and lists it for review | Screening the parsed text, or delimiters alone | ADR-010, ADR-020 |
| Linked requirements read together | Code clusters requirements by section, reference and wording; one `consolidate` call per cluster | One call over all requirements, or none | ADR-019 |
| Agentic, yet testable | A LangGraph graph routes the run, with no LLM choosing the next step. One tool-using agent, `risk`; single-call functions elsewhere. | An LLM choosing the next step, or CrewAI | ADR-005 |
| No unauthorized action | Every tool call passes `ToolGateway` before it runs | Allowlists alone, or safety instructions in the prompt | ADR-009 |
| Client documents protected | A data class per run, an egress register, the text view and a retention period | Trusting each call site | ADR-026 |
| The assignment's output first | The solution summary is the first output of every run | The summary alone, or a pack without it | ADR-007 |
| People decide | `DRAFT_ONLY`: nothing is submitted, every output is `UNREVIEWED_DRAFT`, and compliance starts `UNVERIFIED` | A fully automatic pipeline | ADR-008, ADR-021 |
| Runs without keys | Recorded LLM and Docling cassettes replay a whole run; the host path needs no Docker | Live calls in every test | ADR-016 |
| Measured, not asserted | A separate evaluation package with a funnel and a regression gate; a ledger entry per call and spans per step | A judged-metric framework | ADR-014, ADR-015 |
| Fits the free tier | Flash-Lite for both roles on `free`, a limiter on the daily quota, a response cache for repeats; no thinking on `local` | Flash for `reason`; thinking on for `local` | ADR-003, ADR-004 |

The workflow follows three phases: requirements and reality (`guard` to `consolidate`), engineering and evidence (`approach`, `risk`), and proposal (`draft`, `render`). Of the planned control plane, `v0.1` has the tool gateway, the run budget, the limiter and the checkpointer, which writes each step's state to `checkpoints.sqlite`; nothing reads it until `resume` arrives in Iteration 2. The supervisor, policy and recovery components arrive in Iteration 2.

## 5. Building block view

### 5.1 Containers

Hexagons make LLM calls through the client. Everything else is code with no LLM.

```mermaid
flowchart TB
    cli["cli.py<br/>run, demo, record, purge, matrix run"]
    pre["preflight.py<br/>corpus rule, data class, backends, Docling health"]
    subgraph lg["graph/build.py: LangGraph graph with a SQLite checkpointer"]
        guard["guard"]
        ingest["ingest"]
        cand["candidates"]
        triage{{"triage"}}
        pack["pack"]
        extract{{"extract, one per pack"}}
        verify["verify"]
        coverage["coverage"]
        lint["lint"]
        cons{{"consolidate, one per cluster"}}
        approach{{"approach"}}
        risk{{"risk agent"}}
        draft{{"draft, three sections"}}
        render["render"]
    end
    view["harness/view.py<br/>text view"]
    ctxm["harness/context.py<br/>context packs and manifests"]
    client["llm/client.py<br/>model per role, limiter, cache, retries, fallback, cassettes"]
    gateway["harness/gateway.py<br/>allowlist, arguments, repeats, call cap"]
    tools["tools.py<br/>search_rfp over FTS5, date_calc"]
    egress["harness/egress.py<br/>egress register"]
    parsers["parsers/<br/>Docling client and parser, pdfplumber"]
    obs["obs/<br/>ledger and spans"]
    genai["llm/genai.py"] --> gem[("Gemini")]
    oll["llm/ollama.py"] --> ol[("Ollama")]
    dcs[("docling-serve")]
    cass[("tests/cassettes")]

    cli --> lg
    lg -- "checked before the run folder exists" --> pre
    pre --> egress
    guard --> ingest --> cand --> triage --> pack --> extract --> verify --> coverage
    coverage -- "gaps" --> extract
    coverage --> lint --> cons --> approach --> risk --> draft --> render
    ingest --> parsers --> dcs
    triage & extract & cons --> ctxm --> view
    triage & extract & cons & approach & risk & draft --> client
    risk -- "ToolRequest" --> gateway --> tools --> view
    client --> obs
    client --> genai
    client --> oll
    client <--> cass
    parsers <--> cass
```

### 5.2 Modules

| Module | Responsibility | Tested by |
|---|---|---|
| `cli.py` | The `run`, `demo`, `record`, `purge` and `matrix run` commands; prints what the run entry refuses | `test_cli.py`, `test_purge.py`, `test_matrix.py` |
| `preflight.py` | The run entry's preconditions: the corpus rule per file, the data class and package id, a backend per provider, the local models, Docling's health | `test_preflight.py`, `test_corpus_rule.py` |
| `config.py` | Loads and validates `config/*.yaml` with `yaml.safe_load` and Pydantic | `test_config.py` |
| `schemas.py` | Every record and every model-facing request and response, in [`reference/schemas.md`](reference/schemas.md) | `test_schemas.py` |
| `guard/` | Size, page, path and archive limits; scanned files; hidden content in PDF, DOCX and XLSX, removed from the parsed copy and kept in `quarantine.jsonl`; small print | `test_guard.py` |
| `parsers/`, `ingest.py`, `register.py` | The Docling client with its cassettes, the Docling and pdfplumber parsers, frozen text and passages with lead-ins, table headers, pages and small-print flags; the control register of documents, roles and precedence | `test_docling_parser.py`, `test_ingest.py`, `test_register.py` |
| `candidates.py`, `kb.py` | Cue annotations and the term registry; the B0 rule-only baseline; the knowledge base loader | `test_candidates.py`, `test_knowledge_base.py` |
| `graph/triage.py` | Section views, zones with the keyword fallback, the RFP profile and submission hazards | `test_triage.py` |
| `harness/context.py`, `harness/view.py` | Context packs within budget, with neighbors, lead-ins and terms, and their manifests; the text view | `test_context.py`, `test_text_view.py` |
| `verify.py` | Quote checks (verbatim, normalized or rejected) and number and date fidelity | `test_verify.py` |
| `coverage.py` | The gaps after `extract`, and when to stop re-reading them | `test_coverage.py` |
| `lint.py` | Requirement-quality rules, the coded checks and contract flags | `test_lint.py` |
| `clusters.py`, `graph/consolidate.py` | The cluster rule in code; one `consolidate` call per cluster, and the groups, discrepancies and questions it settles | `test_clusters.py`, `test_consolidate.py` |
| `retrieval.py`, `tools.py` | The per-run FTS5 index over the view's text; the `search_rfp` and `date_calc` tools | `test_tools.py` |
| `harness/gateway.py`, `harness/budget.py` | `ToolGateway`; per-run limits on requests, tokens and active time, checked before each provider attempt | `test_gateway.py`, `test_budget.py` |
| `harness/egress.py`, `purge.py` | The egress register's checks; deleting runs and their cache entries | `test_egress.py`, `test_purge.py` |
| `llm/client.py`, `llm/types.py`, `llm/limits.py`, `llm/cache.py` | One `complete` call for every role: model choice, decoding, the limiter, the response cache, retries, fallback, record and replay, schema validation, ledger entries | `test_client_replay.py`, `test_simulator.py`, `test_cache_key.py`, `test_limiter.py`, `test_cache.py` |
| `llm/genai.py`, `llm/ollama.py`, `llm/openai_compat.py` | The Gemini and Ollama adapters, and an adapter for OpenAI-compatible providers kept for Iteration 3 | `test_adapters.py` |
| `llm/replay.py`, `llm/simulator.py`, `llm/schema.py` | Cassettes; a replay backend that injects scripted faults; the provider form of a schema | `test_client_replay.py`, `test_simulator.py`, `test_provider_schema.py` |
| `prompts.py` | Loads versioned prompts, renders them with `string.Template.substitute`, seeds delimiters from the run id, and renders the few-shot examples, validated against the schemas | `test_prompts.py` |
| `graph/nodes.py`, `graph/state.py`, `graph/build.py` | The nodes, the graph state, the wiring, and `execute` | `test_nodes.py`, `test_risk_loop.py`, `test_e2e_replay.py` |
| `render.py`, `render_xlsx.py` | The outputs, after schema validation; the compliance matrix | `test_render_outputs.py`, `test_compliance_matrix.py` |
| `baselines.py`, `matrix.py` | EX0 and B0; the matrix runner for spikes and ablations | `test_e2e_replay.py`, `test_matrix.py` |
| `obs/ledger.py`, `obs/tracing.py` | Ledger totals and the models that answered; spans with a file fallback | `test_ledger.py`, `test_tracing.py` |
| `scripts/gen_docs.py`, `scripts/check_docs.py` | Generate `agents.md`, `ai-bom.md` and the CLI and schema references; check links, wikilinks, dates, front matter, voice and test names | `test_docs_generated.py`, `test_check_docs.py`, and the `docs-links` job |
| Repository rules | The import rule, repository hygiene, the Compose lockdown, the privacy invariant | `test_isolation.py`, `test_repo_hygiene.py`, `test_compose_lockdown.py`, `test_privacy_invariant.py` |
| `evals/` | The separate `bidwright-eval` package: corpus rendering, gold, matcher, funnel, seeds, scorer, gate, explain, report | `test_render.py`, `test_matcher.py`, `test_funnel.py`, `test_scorer_selftest.py`, `test_gates.py`, `test_hero_replay.py` |

### 5.3 Agent view

[`agents.md`](agents.md) is regenerated by CI from `config/agents.yaml`, `config/models.yaml`, the prompts' front matter, the tool specs and the compiled graph, and the `docs-generated` job fails on a diff. In summary:

| Role | Kind | Input to output | Model role | Tools | Limits |
|---|---|---|---|---|---|
| `triage` | Function, one per pack of sections | `TriageInput` to `TriageResult` | extract | None | 1 call, 1 repair |
| `extract` | Function, one per context pack | `ExtractBatch` to `ExtractResult` | extract | None | 1 call, 1 targeted repair, fixed in code |
| `consolidate` | Function, one per cluster the model step takes | `ClusterTask` to `ConsolidationResult` | reason | None | 1 call, 1 repair |
| `approach` | Function | `ApproachInput` to `ApproachResult` | reason | None | 1 call, 1 repair |
| `risk` | Agent | `RiskInput` to `RiskRegister` | reason | `search_rfp`, `date_calc` | 4 turns, 6 tool calls, stop on no progress |
| `draft` | Function, once per section | `DraftTask` to `DraftResult` | reason | None | 1 call, 1 repair |

The roles never exchange output. The graph passes each one a typed input built from checked records, and only checked output enters the state. Each `Send` worker returns its result through a list reducer, so no two workers write the same key.

### 5.4 Boundary contracts

Each LLM call has a schema, except the `risk` agent's tool turns, which return tool calls. Each has an acceptance check in code, a pinned prompt and model, and a defined result when the check fails.

| Call | Pinned by | Acceptance check in code | When the check fails |
|---|---|---|---|
| `triage` | `triage@0.1.0`; the `extract` role's model | Zones only for sections in the pack, at or above the confidence threshold; hazards cite passages that exist | A section without an accepted zone takes the keyword zone; a pack whose answer breaks its schema twice falls back to keywords, and the run ends `DEGRADED` |
| `extract` | `extract@0.3.0`; `extract` | Each quote is found in the view's text of a passage the item cites, from its own pack, and mapped to the frozen text; every number and date in the statement occurs in the quote, a cited passage, its lead-in or header, or its section path; every passage of the pack appears in an item or in `no_obligation_src_ids`. An item keeps its first 3 ids; a quote over 300 characters fails its item, not its pack (ADR-024). | One repair message naming each failed quote, number and long quote; items that still fail go to `rejected.jsonl`. A pack that breaks its schema twice is rejected whole. `coverage` re-reads passages left without a disposition. |
| `consolidate` | `consolidate@0.1.0`; `reason` | Duplicates, discrepancies, questions and references name members of the cluster; a merge never loses an anchor | A call that fails becomes a group built in code, and the run ends `DEGRADED` |
| `approach` | `approach@0.2.0`; `reason` | Requirement ids must name verified `BINDING` or `OPTIONAL` requirements; an item with none is dropped, and requirements left unmapped are listed | One format repair, then an empty result and the run ends `DEGRADED` |
| `risk`, tool turns | `risk@0.2.0`; `reason`; the allowlist in `config/agents.yaml` | `ToolGateway`: the tool is allowed and registered, the arguments validate, no third identical call, the call cap is not spent | A `DENIED` result goes back to the model and the tool never runs; a `FAILED` result goes back after the tool raised |
| `risk`, final register | The same | Each risk cites passages that exist and shares a content word with them, and carries no rating or probability | One retry for the rejected risks; a register that breaks its schema twice is empty, and the run ends `DEGRADED` |
| `draft` | `draft@0.2.0`; `reason` | Cited ids are kept only if they name the section's own records | One format repair, then the section is `FAILED` and the run `DEGRADED` |
| Every call | The cassette key | The response parses into its schema | Reported as a parse error for the node's repair |

[`agents.md`](agents.md) lists the prompt versions in force. `render` adds the last check: every record is validated against its schema before anything is written, and one failure blocks every output.

## 6. Runtime view

### 6.1 The graph

`guard` → `ingest` → `candidates` → `triage` → `pack` → `extract`, one `Send` per context pack → `verify` → `coverage`, which either ends the extraction or sends the packs holding its gaps back to `extract`, for at most 2 rounds → `lint` → `consolidate`, one `Send` per cluster the model step takes, with code groups for the rest → `approach` → `risk` → `draft` → `render`. `--until verify`, `coverage` or `consolidate` ends the run after that node, `COMPLETED` with the reason "stopped after <node> by request", and `--baseline b0` routes `candidates` to the rule-only B0 step and stops after `verify`. The diagram in [`agents.md`](agents.md) is drawn from the compiled graph.

Every passage reaches `extract`, in packs of at most `batch_size` passages within the call's token budget, so the hero package's several hundred passages take about 14 calls. At most 2 workers run at once on `free`, 4 on `paid` and 1 on `local`, because Ollama on the build laptop serves one request at a time (`config/limits.yaml`).

Before the run folder is created, `execute` checks the run entry's preconditions, in `preflight.py`: the corpus rule per file on `free`, the data class, a backend for every provider the profile's roles use, the local models on `local`, Docling's health when it parses live, and the egress register for every destination. A refused run leaves nothing behind, and the message says what to do instead.

### 6.2 One run

```mermaid
sequenceDiagram
    autonumber
    participant CLI as cli.py and execute
    participant G as Graph nodes
    participant C as LLM client
    participant P as Provider or cassettes
    participant T as ToolGateway
    CLI->>CLI: check the preconditions and the egress register, then create the run folder
    CLI->>G: start the run with its budget, prompts, text view and tracing
    G->>G: guard: limits, scanned pages, hidden content removed and kept for review
    G->>G: ingest: parse each document, control register, frozen text, passages, FTS5 index
    G->>G: candidates: cues and the term registry
    G->>C: triage: section views, one call per pack
    par each context pack, at most 2 at once on free
        G->>C: ExtractBatch through the text view
        C->>P: request, after the limiter, with retries and fallback
        P-->>C: ExtractResult
        G->>G: check quotes, numbers and ids, one repair
    end
    G->>G: verify: candidate ledger, requirements, rejected quotes, hazards
    G->>G: coverage: stop, or send the gap packs back to extract
    G->>G: lint: findings and contract flags
    par each cluster the model step takes
        G->>C: ClusterTask
    end
    G->>G: settle groups, discrepancies and questions
    G->>C: ApproachInput
    loop risk: at most 4 turns and 6 tool calls
        G->>C: turn with the tool specs
        C-->>G: tool calls
        G->>T: ToolRequest
        T-->>G: ToolResult: OK, EMPTY, DENIED or FAILED
    end
    G->>C: final call with no tools, for the RiskRegister
    G->>C: DraftTask for each of three sections
    G->>G: render: validate every record, write the summary, proposal, matrix and review files
    CLI->>CLI: write run_manifest.json and ledger.jsonl, whatever the outcome
```

Every LLM call goes through the client, which checks the limiter and the run budget before each provider attempt and records one ledger entry and one `LLM` span; each packed call also writes a context manifest, `context/<node>-<call>.json`.

### 6.3 Failure behavior per step

| Step | Failure | Response | Limit | Test |
|---|---|---|---|---|
| The run entry | A file not in the corpus, on `free` | Refused before the run folder exists; the consent override runs it, and the manifest records the override and the data class `client` | None | `test_corpus_rule.py` |
| The run entry | No backend for a provider the profile uses, a local model that is not pulled, or Docling not answering | Refused before the run folder exists, with the key to set, the pull command or the service to start | None | `test_preflight.py`, `test_a_docling_run_is_refused_when_the_health_check_fails` |
| The run entry | A destination the egress register refuses for the run's data class | Refused, or for a trace endpoint, spans go to `spans.jsonl` and the manifest lists the refused destination | None | `test_egress.py` |
| `guard` | A file over a limit, a path outside the input root, an archive bomb, an encrypted or corrupt file, or a missing input | The run ends `POLICY_BLOCKED`, with its manifest | 0 | `test_guard_limits`, `test_a_corrupt_input_is_blocked_by_guard_with_a_manifest`, `test_a_missing_input_is_blocked_with_a_manifest` |
| `guard` | Hidden content | Removed from the copy that is parsed, kept in `quarantine.jsonl` with its location, and shown in `review/quarantine.md` | 0 | `test_guard_quarantine_finds_each_hidden_kind_and_sanitizes` |
| `guard` | A scanned file, with no text layer | Reported and not parsed; the run ends `DEGRADED` | 0 | `test_guard_scanned` |
| `ingest` | Docling down or timing out | Retried, then `UNRECOVERABLE_FAULT` | 3 retries | `test_ingest_retry_retries_a_failing_docling_call_then_faults` |
| `ingest` | A partial conversion | The run continues and ends `DEGRADED` | 0 | `test_ingest_unparseable_a_partial_conversion_continues_degraded` |
| Any LLM call | 429, 5xx or timeout | Full-jitter backoff with a 2-second base and a 30-second cap, where a `Retry-After` header sets the wait; then the role's fallback model, once | 3 retries | `test_fi01_*` in `test_simulator.py` |
| Any LLM call | The limiter's daily count reaches the quota less its reserve, or a 429 names a daily limit | No retry: the fallback model at once; with none left, the run ends `QUOTA_PAUSED` | 0 | `test_a_spent_primary_moves_to_the_fallback_and_a_spent_fallback_raises`, `test_a_spent_daily_quota_moves_to_the_fallback_without_retrying` |
| Any LLM call | A 4xx other than 429 | `UNRECOVERABLE_FAULT` at once, because a retry fixes neither a bug nor a configuration error | 0 | `test_preflight.py` |
| Any LLM call | Request, token or active-time limit reached | Checked before each provider attempt; the run ends `BUDGET_EXCEEDED` | 0 | `test_budget.py`, `test_the_budget_stops_a_call_between_its_attempts` |
| Any LLM call, `local` | The evaluated prompt reaches `num_ctx` | `UNRECOVERABLE_FAULT` rather than continuing on a cut prompt | 0 | `test_ollama_fails_a_call_whose_prompt_reached_num_ctx` |
| Any LLM call, replay | No cassette for the key | The run ends `UNRECOVERABLE_FAULT`, with its manifest and ledger | 0 | `test_a_missing_cassette_ends_the_run_as_a_fault` |
| Anywhere | An unexpected error | The run is recorded as `UNRECOVERABLE_FAULT`, and the error propagates | 0 | `test_an_unexpected_error_is_recorded_as_a_fault` |
| `triage` | Low confidence or a malformed answer | The keyword zones; the run ends `DEGRADED` for a failed call | 1 repair | `test_triage_fallback` |
| `extract` | A quote not found, a number not in the source, a quote over 300 characters, or ids missing | One repair message for all the item's failures, then `REJECTED` in `rejected.jsonl` | 1 repair | `test_the_three_repair_kinds_go_in_one_message`, `test_a_long_quote_fails_only_its_item_and_is_rejected_if_still_long` |
| `extract` | Malformed output twice | The whole pack is rejected; `coverage` re-reads its passages | 1 repair | `test_fi02_malformed_twice_rejects_the_whole_batch` |
| `coverage` | Passages still without a disposition | Their packs are read again; the run ends `DEGRADED` when gaps remain after 2 rounds or stop shrinking | 2 rounds | `test_coverage_rounds`, `test_a_gap_that_never_shrinks_marks_the_run_degraded` |
| `lint` | A rule fails on unusual text | The rule is skipped for that requirement and logged; the run ends `DEGRADED` | 0 | `test_lint_resilience` |
| `consolidate` | A merge would lose an anchor, or the call fails | The records stay separate; a failed cluster becomes a code group, and the run ends `DEGRADED` | 1 repair | `test_consolidate_anchors`, `test_a_failed_call_falls_back_to_a_code_group` |
| `approach`, `risk` | Malformed output twice | The node's output is empty, the run continues and ends `DEGRADED`, so the summary keeps the verified requirements | 1 repair | `test_approach_degrades_after_two_schema_failures`, `test_risk_degrades_after_two_schema_failures` |
| `risk` | A tool outside the allowlist, bad arguments, a third identical call, or the cap spent | `DENIED`, returned to the model | 0 | `test_gateway.py` |
| `risk` | A tool raises | `FAILED`, returned to the model | 0 | `test_a_tool_that_raises_returns_failed_to_the_model` |
| `risk` | A turn adds nothing new, or a cap is reached | The loop ends, and a final call with no tools asks for the register | 4 turns, 6 calls | `test_loop_caps_stop_at_four_turns`, `test_loop_caps_stop_at_six_tool_calls` |
| `risk` | A generic risk, or one with a rating or probability | Rejected, with one retry for the rejected risks | 1 retry | `test_risk_generic_is_rejected_then_replaced_on_retry` |
| `draft` | Malformed output twice | That section is `FAILED`, the others continue, and the run ends `DEGRADED` | 1 repair | `test_nodes.py` |
| `render` | A record fails its schema | Nothing is written; `UNRECOVERABLE_FAULT` | 0 | `test_render_schema_failure_blocks_all_output` |
| Tracing | The collector is down or refuses a batch | Spans go to `spans.jsonl`, and the run never waits | None | `test_tracing.py` |

Nodes after `verify` degrade rather than fault because the requirements are complete and verified by then; `render` still faults, because a record that fails its schema cannot be written (ADR-024).

### 6.4 Run statuses at `v0.1`

A run ends `COMPLETED`, `DEGRADED` (with each shortfall in `status_reason`), `POLICY_BLOCKED` (refused by `guard`), `BUDGET_EXCEEDED`, `QUOTA_PAUSED`, `UNRECOVERABLE_FAULT`, or `STOPPED` when the operator interrupts it, which the manifest records. The checkpointer saves each step's state in `checkpoints.sqlite`, and no command resumes a run yet: `bidwright resume` arrives in Iteration 2, and until then a stopped run is started again, with the response cache answering the calls it already made when the cache is on. The other statuses in `RunStatus` belong to later iterations.

## 7. Deployment view

### 7.1 Two ways to run

Two ways to run, from one codebase.

| Path | Command | Needs |
|---|---|---|
| Host | `uv run bidwright demo`, `uv run bidwright run <file or folder>`, `uv run pytest` | Python 3.12 and uv. The demo and the tests need no keys, no network and no Docling service; CI's `host-path` job shows it on a clean checkout. A live run needs Docling, started with `docker compose up -d docling`, and for `local`, Ollama with `qwen3.5:4b` and `qwen3.5:2b` pulled. |
| Compose | `docker compose up -d`, `docker compose run --rm demo`, `docker compose run --rm test` | Docker, and `GEMINI_API_KEY` in `.env`, which Compose requires for every command (ADR-002) |

### 7.2 Services

| Compose service | Image | Job | Network and mounts |
|---|---|---|---|
| `app` | Built from the `Dockerfile` in stages with uv, running as a non-root user | The `bidwright` CLI, through `docker compose run` | `inputs/`, `config/` and `prompts/` read-only; `outputs/` read-write |
| `docling` | `docling-serve-cpu`, pinned by digest in `compose.yaml` | Parses PDF, DOCX and XLSX through its v1 API | Published on `127.0.0.1` only; the demo and test services never reach it |
| `phoenix` | `arizephoenix/phoenix`, pinned by digest in `compose.yaml` | Traces on port 6006 | Published on `127.0.0.1` only. Authentication is disabled by default for this local collector of synthetic runs; `.env` can enable it, and Bidwright then sends `PHOENIX_API_KEY` as a bearer token. |
| `eval` | The same image, Compose profile `eval` | `bidwright-eval` | The only service that mounts `evals/gold` and `evals/corpus`, read-only |
| `test` | The same image, Compose profile `test` | `pytest -m "not gold"` | No network; cassettes read-only |
| `demo` | The same image, Compose profile `demo` | `bidwright demo` | No network; cassettes read-only |
| `ollama` | `ollama/ollama`, pinned by digest in `compose.yaml`, Compose profile `local` | Local models, pulled with `docker compose exec ollama ollama pull <model>` | Published on `127.0.0.1` only |

### 7.3 What stays out of the image

`.dockerignore` keeps out `evals/corpus/`, `evals/gold/`, `evals/results/`, `evals/labels/`, `evals/spikes/`, `private/`, `outputs/` and `.env`, and CI's `docker` job checks that the image holds no gold, no corpus spec and no spike. The wheel excludes the same evaluation paths.

### 7.4 Data by location

| Location | Holds | In Git |
|---|---|---|
| `inputs/` | Rendered synthetic RFPs and packages, and `CORPUS.sha256` | Yes |
| `evals/corpus/`, `evals/gold/` | Corpus specs and the gold generated from them, hashed with `evals/hypotheses.yaml` in `MANIFEST.sha256` | Yes; never in the image |
| `knowledge_base/` | The fictional supplier's capabilities, case studies and certifications, used from Iteration 3 | Yes |
| `outputs/` | Run folders, matrix runs under `outputs/matrices/`, the limiter's daily counts and the response cache | No |
| `samples/dev-free/` | One real live run of the development RFP on `free`, the sample [`README.md`](../README.md) cites | Yes |
| `tests/cassettes/` | Recorded LLM responses for the demo, the development DOCX and the hero package, and recorded Docling responses by file hash | Yes |
| `.env` | Keys | No; `.env.example` holds names only |
| `private/` | Research reports, review reports, the assignment PDF | No |

## 8. Crosscutting concepts

### 8.1 What each call sees

`harness/context.py` builds what each packed call sees, from whole passages, never partial ones, within the call's token budget: `triage` sees section views (path, role, the first two passages and cue counts); `extract` sees a pack of passages with their section paths, lead-ins, zone and cue hints, the neighboring passages marked as context, and the definitions of the terms the pack uses; `consolidate` sees one cluster's members and context requirements, the package's order of precedence, its lint findings and, for addendum clusters, the precedence clause. Each packed call writes a manifest of the passages it included and the tokens by layer. `approach` sees the verified `BINDING` and `OPTIONAL` requirements, `risk` those, the approach items and the hazard ids plus what its tools return, and `draft` only its own section's records. Nothing carries over between runs except the response cache, keyed by the whole request.

Every prompt follows one layout: the system instruction first, with role, rules, output format and examples; then the data inside delimiter tags seeded from the run id; and the task last. Every document text a model reads comes through the text view (section 3.2).

### 8.2 Provenance

- Passages are half-open slices of `frozen.txt`, with ids `SRC-0001` and on, a document id, a page and a small-print flag.
- The control register lists each document's file, hash, role, title and precedence, from `package.yaml` or from rules.
- Each requirement cites at most 3 passage ids and quotes at most 300 characters, with the quote's status and its span in the frozen text, its zone, and whether it passed only after a repair.
- The candidate ledger, `candidates.jsonl`, gives every passage its dispositions and the reason for each, so a passage with no obligation is a recorded decision, not an omission.
- `run_manifest.json` records the commit, profile, the models configured by role and the models that answered by node, prompt hashes, every document's hash, the data class, overrides, refused destinations, start and end, status and reason, and totals derived from the ledger.

### 8.3 Limits

From `config/limits.yaml` and `config/agents.yaml`:
- Per run, by corpus tier and profile: 60 requests and 300,000 tokens for the development RFPs, with 20 active minutes on `free` and 60 on `local`; 250 requests, 2,000,000 tokens and 90 minutes for the hero package on `free` and `paid`. The clock counts the run's active time.
- The request limit counts provider attempts, retries and fallback attempts included, because that is what the quota counts (ADR-022). The limiter keeps each model's daily count under `outputs/.quota/`, by the provider's quota day, and keeps a 20% reserve of the free quota for development.
- Per call: a 120-second timeout on `free` and `paid`, 300 seconds on `local`, with 3 retries.
- Context packs hold at most `batch_size` passages within 12,000 tokens for `extract`, 8,000 for `triage` and `consolidate`. Clusters hold at most 12 members and 8 context requirements. `coverage` runs at most 2 rounds. The `risk` loop is capped at 4 turns and 6 tool calls, and `search_rfp` returns at most 8 passages.

The batch size, the quote cap, the 3 cited ids, the cluster caps and the loop caps are defaults from the plan; S-03 measures the batch size on the hero package, and the others stay judgment until an ablation measures them. A measured full hero run on `free` took 33 requests and 210,745 tokens, thinking included, in about 3 active minutes.

### 8.4 Human control

Bidwright drafts and never submits. Every summary, proposal and review file opens with the `UNREVIEWED_DRAFT` status line, every compliance status in the matrix starts `UNVERIFIED`, and every contract flag is `NEEDS_LEGAL_REVIEW`. `review/quarantine.md` puts the hidden content, the small print and the suspect passages in front of a person. `v0.1` has no gate; the two human gates arrive in Iterations 3 and 4.

### 8.5 Observability

- **Ledger.** One `LedgerEntry` per call: model, prompt and input hashes, input, cached, output and thinking tokens, latency and the provider's own timings, retries, the real cost (0 on `free` and `local`), and a shadow cost at the paid list price of the role's shadow model in `config/pricing.yaml`, so free, local and paid runs compare.
- **Spans.** `run` and `node.<name>` are `CHAIN` spans, except `node.risk`, an `AGENT` span with its stop reason, turns and tool calls. A fan-out worker's span names its call id, as its context manifest does. Each call adds `llm.<node>` (`LLM`) and each tool call `tool.<name>` (`TOOL`). Spans carry hashes and counts, never prompt or response text.
- **Tool calls.** Every tool request, its agent and its result are written to `tool_calls.jsonl`.
- **Logs.** Bidwright logs no document text, and it holds the `pdfminer` and `openai` loggers at `WARNING`, because at `DEBUG` they would log a PDF's text or a request body (`test_privacy_invariant.py`).
- **Where spans go.** OTLP to Phoenix when `PHOENIX_ENDPOINT` answers and the egress register allows it, and `spans.jsonl` otherwise.

### 8.6 Replay

The client runs in `live`, `record` or `replay` mode, and Docling in its own mode, which defaults to the client's. An LLM cassette's key is a sha256 over the prompt hash, the schema hash, the tool definitions' hash, the model, the decoding settings, the input hash taken before delimiters are inserted, and the repeat index; a Docling cassette's key is the file's hash with the conversion options. A change to any of them has no cassette, so replayed tests fail until the cassettes are recorded again. `bidwright record <file or folder> [--name] [--until]` writes both kinds and `recording.json`; `bidwright demo` replays `tests/cassettes/demo/`, and the replay tests also replay `tests/cassettes/dev-docx/` and `tests/cassettes/hero/` with the network disabled.

### 8.7 Conformance in CI

Structural rules are fitness functions that run on every push to `main` and every pull request. Behavior is measured by the evaluation harness, replayed in CI and run live at each tag.

| CI job | What it proves |
|---|---|
| `lint`, `types` | ruff and pyright pass |
| `unit` | The fast tests, including the import rule (`src/bidwright` never imports `evals`), the gateway rules, the egress register, the Compose lockdown test and the repository hygiene checks |
| `replay` | Nodes and whole runs replay from cassettes with no network: a run recorded in the test, the demo, the development DOCX and the hero package |
| `gold` | Corpus rendering, the matcher, the funnel, the scorer self-test, the text view and privacy tests and, from `v0.1`, the hero replay gated against its baseline |
| `host-path` | `bidwright demo` runs on a clean checkout with no `.env` |
| `docs-generated` | [`agents.md`](agents.md), [`ai-bom.md`](ai-bom.md), [`reference/cli.md`](reference/cli.md) and [`reference/schemas.md`](reference/schemas.md) match the code |
| `docs-links` | Links and wikilinks resolve, dates are ISO 8601, `context/` front matter is valid, the documents keep a neutral voice, and every test named under `docs/` exists |
| `docker` | The image builds, holds no gold and no spike, and passes the tests with no network |
| `secrets`, `deps` | gitleaks finds no secret; pip-audit finds no known vulnerability |

### 8.8 Configuration

`config/models.yaml`, `limits.yaml`, `agents.yaml`, `thresholds.yaml`, `pricing.yaml`, `ingest.yaml`, `cues.yaml`, `zones.yaml`, `lint.yaml` and `egress.yaml` are loaded with `yaml.safe_load` and validated by Pydantic in `config.py`, so a bad value fails at start-up; `config/matrices/` holds the matrix files. A prompt's decoding block may override only `thinking`, `think` and `num_ctx`. Keys and endpoints come from `.env`, whose names `.env.example` lists. Five more variables are read by code: `BIDWRIGHT_HOME` (the repository root, set in the `Dockerfile`), `BIDWRIGHT_CONFIG_DIR` (the configuration folder), `BIDWRIGHT_CLIENT_ROOT` (the folder client documents may come from, outside the repository), `BIDWRIGHT_COMMIT` (the commit the manifest records when Git is absent) and `LANGGRAPH_STRICT_MSGPACK` (set by the command line and the `Dockerfile`, so a checkpoint holds plain data only).

## 9. Architecture decisions

[`DECISIONS.md`](../DECISIONS.md) holds the ADRs, with their index, and the failure modes found while building. ADR-001 to ADR-004 were taken in Iteration 0a; ADR-005 to ADR-016 record the plan's product and architecture decisions; ADR-017 to ADR-021 were proposed by the Iteration 1 design doc and accepted at its Stage 9 review; ADR-022 to ADR-025 record what the first architecture review changed; ADR-026 records the owner's decision on client documents (D-05). [`decision-matrix.md`](decision-matrix.md) maps the choices to the architecture-options taxonomy for foundation-model agents, with the quality trade-offs each implies.

## 10. Quality requirements

### 10.1 Quality scenarios

Each scenario is tagged with its ISO/IEC 25059 characteristic. An **invariant** must hold on every run, and code checks it. A **statistical** scenario is measured over the corpus, its seeds and repeats, with a sample size, a threshold and an action, block or warn.

| ID | Kind | Characteristic | Stimulus | Required response | Measure | Runs at | Status at `v0.1` |
|---|---|---|---|---|---|---|---|
| QS-1 | Invariant | Functional correctness | A model emits a quote that is not in the source | Repaired once or rejected, never accepted | Accepted quotes that are neither verbatim nor normalized: 0, block | Every run; CI on replay and in the gate | **Holds.** `test_verify.py` and `test_nodes.py`; the regression gate blocks on any such quote. |
| QS-2 | Statistical | Functional correctness | A mandatory clause anywhere in the RFP | Captured, with exact provenance | On the hero package: at most 2 of 45 missed in the median of 5 repeats, and no rise against EX0; block | Iteration 3 exit and release, on 5 live hero repeats | **Measurable:** the hero package, gold v2, the funnel and the gate exist; the repeats run at the Iteration 3 exit. |
| QS-3 | Statistical | Robustness | An injected instruction with a unique marker and a detectable requested action, in a document or a research result; at least 6 per RFP | Flagged or quarantined, never obeyed | The requested action in an LLM-written field or a tool-call argument: 0, block | Iteration 3 exit and release, on 5 live hero repeats; CI on replay | **Built:** `guard` removes hidden content before parsing, the corpus holds 14 traps, and the scorer and the gate count obeyed traps; the repeats run at the Iteration 3 exit. |
| QS-4 | Invariant | Security | A tool request outside an allowlist or a rule | Stopped outside the model | Unauthorized calls allowed: 0, block | Every run; CI on replay and in the gate | **Holds** for the `risk` agent's two tools: `test_gateway.py`, and the scorer counts executed calls outside each agent's allowlist from `tool_calls.jsonl`. |
| QS-5 | Statistical | Transparency | A capability the knowledge base cannot support; at least 4 seeded gaps per RFP | Marked `UNVERIFIED`, never asserted | Seeded gaps claimed: 0, block | Iteration 3 exit and release, on 5 live hero repeats | **Not built:** the knowledge base and the hero's gap seeds exist; `assess` arrives in Iteration 3. Every approach item carries the evidence class `ASSUMPTION`. |
| QS-6 | Invariant | Intervenability, user controllability | A stop command, an exhausted budget, or a gate with no person | Halts at the next step, or waits in `WAITING_HUMAN`; output stays `UNREVIEWED_DRAFT` | Fault-injection tests | CI | **Partly holds:** the budget stops a run before its next provider attempt (`test_budget.py`), every output carries `UNREVIEWED_DRAFT` (`test_render_outputs.py`), and an operator interrupt is recorded as `STOPPED`. The stop command arrives in Iteration 2 and the gates in Iterations 3 and 4. |
| QS-7 | Invariant | Recoverability | A provider 429, a timeout, malformed output or a crash | Retries, fails over and resumes, with no repeated spend | FI-01, FI-02 and a resume test | CI | **Partly holds:** FI-01 and FI-02 pass (`test_simulator.py`, `test_nodes.py`), a spent daily quota moves to the fallback without retrying, and the response cache answers a repeated call (`test_cache.py`). Resume arrives in Iteration 2. |
| QS-8 | Statistical | Functional correctness | The same RFP run 5 times | The requirement set and the tool path stay within tolerance | Median pairwise Jaccard over the gold clause ids each run captures: at least 0.85, warn | Iteration 3 exit and release, on 5 live hero repeats | **Measurable:** the matrix runner runs repeats; the measurement runs at the Iteration 3 exit. |

Modifiability is shown by the live-change rehearsal at release, not by a scenario.

### 10.2 How a statistical scenario blocks

At the Iteration 3 exit and in the release step, a failed statistical scenario holds the tag or the release until it passes, or until the owner accepts a recorded exception: an ADR in [`DECISIONS.md`](../DECISIONS.md) giving the measured value and the reason, with the result reported in the README. CI blocks only on invariants and replayed checks: the unit and replay tests and, from `v0.1`, the regression gate on the replayed hero recording, which [`evaluation.md`](evaluation.md) describes.

### 10.3 When evidence goes stale

A change to a model, a prompt, a schema or a tool description changes the cassette keys, so replay fails until the cassettes are recorded again (section 8.6). A change to `batch_size`, the ingest rules or `config/limits.yaml` changes what a run does without changing a key. In both cases the live evidence behind each statistical scenario is stale from that change until it is measured again.

[`evaluation.md`](evaluation.md) describes the harness that measures these scenarios.

## 11. Risks and technical debt

Project risks live in section 7 of [`context/Master-Plan.md`](../context/Master-Plan.md). The design's residual risks are listed in [`security.md`](security.md#residual-risks-at-v00) and under "Not covered yet" in [`governance.md`](governance.md#not-covered-yet). Technical debt and known limits at `v0.1`:

| Item | Effect | Paid down in |
|---|---|---|
| `guard` reads the PDF's drawing operations, not the rendered page, so a font that maps glyphs to other characters escapes it | A hidden instruction of that kind reaches the parsed text | S-06, render-and-compare, in Iteration 7 |
| A scanned file is reported, not parsed, and so is an OCR'd scan, whose text layer is drawn invisible and so is never read as text | Its obligations are missing, and the run says so | OCR stays optional |
| The Docling path removes hidden PDF text by finding each hidden run's words in the item's text, because Docling's items carry no character positions | A hidden word that repeats a visible word earlier in the same item removes the visible one instead | The pdfplumber path removes hidden characters by position; Iteration 7's render-and-compare |
| Stored requirements keep the model's quote as the view showed it, which equals the frozen text under `IdentityView` | A masking view would store masked quotes | Iteration 5, with the masking view |
| Every passage costs `extract` tokens, so a long package takes more calls than a cue filter would | Cost and quota per run | S-03 sets the batch size; the measured hero run gives the figures |
| `risk` found 1 of 3 planted risks on `free` and 0 of 3 on `local` at `v0.0` | Risk recall is weak | Iteration 3, measured by the RK ablation |
| On retry, the model may omit a rejected risk instead of rewording it | A real risk can be lost to a fixable rating phrase | Iteration 3 |
| No resume command, although checkpoints are written | A stopped run starts again; the cache spares only the calls it holds | Iteration 2 |
| `reason` runs on Flash-Lite on `free` (ADR-003) | Approach, risk and draft quality against Flash is unmeasured | The SO comparison; the paid budget decision (D-01) |
| A development run takes about 17 minutes on `local`, on CPU | The local path is a privacy path, not a fast one | Iteration 6 bake-off |
| `free` depends on one provider | No free run can finish while Gemini is down | Iteration 3's second family; the paid key on the same model |
| Compose needs a key even for the demo (ADR-002) | Reviewers who run Compose need a key | The condition that reverses ADR-002 |
| Claude writes both the corpus and the prompts, under the owner's direction | Scores may overstate the system | The owner's held-out requirement list, written without the prompts in view; external stage benchmarks |

## 12. Glossary

| Term | Meaning |
|---|---|
| RFP | The buyer's request for proposal |
| Package | A folder of RFP documents, such as a main RFP, an addendum and an annex, with an optional `package.yaml` naming roles and precedence |
| Development RFP | The four-page synthetic RFP in `inputs/dev/dev_rfp.pdf`: 12 requirements, 8 of them mandatory, with traps and planted personal data from gold v2 |
| Development DOCX | The synthetic DOCX RFP in `inputs/dev-docx/`: 11 requirements, 9 of them mandatory |
| Hero package | The synthetic package in `inputs/hero/`: a main PDF, an addendum and an XLSX annex, 55 requirements with 45 mandatory, on which the statistical scenarios are measured |
| Held-out RFP | The DOCX RFP whose requirement list the owner writes; scored once, at release |
| Passage | A sentence, list item, table header or table row, with an id `SRC-0001` and half-open offsets into `frozen.txt` |
| Control register | The list of a package's documents with their hashes, roles, titles and precedence |
| Cue | A code annotation on a passage, such as a modal verb, a deadline or an amount; a hint, never a filter |
| Zone | The kind of section a passage sits in: instruction, evaluation, eligibility, obligation, contract or background |
| Context pack | What one packed call sees: whole passages with their context, within a token budget, with a manifest |
| Text view | The one seam between the frozen text and what a model reads (ADR-026) |
| Data class | `synthetic` when every file is in the corpus, `client` otherwise |
| Requirement | One obligation, with an id `REQ-0001`, a modality, a disposition, cited passages and a verified quote |
| Disposition | `BINDING` (the supplier must do it if it bids), `OPTIONAL` (invited, not required), `BACKGROUND` (context that obliges no one), `NOT_BINDING` (reads like an obligation but is not one here), `OUT_OF_SCOPE` (an obligation on another party or a later stage) |
| Candidate ledger | `candidates.jsonl`: every passage with its dispositions and the reason for each |
| Requirement group | The requirements `consolidate` read together, with their duplicates, discrepancies and questions |
| Mandatory | True exactly when the disposition is `BINDING` |
| Hazard | A requirement whose breach can disqualify a bid: a deadline, a format rule, a mandatory form, an eligibility condition |
| Quote status | `VERBATIM_VERIFIED`, `NORMALIZED_MATCH` (equal after the normalization `verify.py` defines) or `REJECTED` |
| Quarantine | Hidden content `guard` removed before parsing, kept with its location for review |
| Small print | Visible text from 2 up to 6 points, kept in the text and flagged for review |
| Generic risk | A risk that cites no passage, or whose condition and event share no content word with the passages it cites |
| Profile | `free` (Gemini free tier, synthetic corpus only), `paid` (the same models on the paid tier) or `local` (Ollama, nothing leaves the machine) |
| Model role | `extract` or `reason`, each mapped to a model and a fallback per profile |
| Agent | An LLM role that calls tools in a loop; at `v0.1`, only `risk` |
| `ToolGateway` | The code that authorizes every tool call before it runs |
| Cassette | A recorded response, keyed by everything that affects the call |
| Repeat index | The number of a run within a set of identical runs, part of every cassette and cache key, so repeats never share one |
| Ledger | One entry per LLM call, in `ledger.jsonl` |
| Shadow cost | What a call would cost at the paid list price of its role's shadow model |
| Run manifest | `run_manifest.json`: the run's inputs, models, prompts, data class, status and totals |
| `UNREVIEWED_DRAFT` | The status of every output until a person signs it off |
| Gold | The known answers for a synthetic RFP, generated from its spec |
| Seed | A planted item in the corpus, such as a risk or a trap, that a run should find or resist |
| Funnel | The stage that lost each missed mandatory requirement: `guard`, `parse`, `extract` or `verify` |
| Matrix | A file of rungs and repeats that `bidwright matrix run` executes for a spike or an ablation |
| EX0, B0 | The one-call extraction baseline, and the rule-only floor with no model call |
| Ablation | EX for extraction, SO for the solution, RK for the risk agent and PR for the proposal: each climbs from a one-call baseline to the full system, in Iterations 3 and 5, with 5 repeats per rung |
| Live-change rehearsal | Five rehearsed small changes made at the interview, such as adding a rule or changing a threshold |
| Reverse-if | The ADR line that states what would reverse the decision |
| The owner | The project's sponsor and sole approver |
| Claude | The AI coding agent that builds Bidwright under the owner's direction |
