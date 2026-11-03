# Architecture

Bidwright as built in Iteration 0a, the walking skeleton tagged `v0.0`, under the twelve arc42 headings. Tag `v0.0.1` adds this document and the others of Iteration 0b, plus one fix: a run that fails with an unexpected error is now recorded as `UNRECOVERABLE_FAULT`. This document covers only what is built. The full vision and the work still to come live in section 10 of [`context/Master-Plan.md`](../context/Master-Plan.md). Each heading stays short and points to the file that owns the detail.

## How this architecture is described

Six steps, combining arc42, C4 and ADRs. Research job DR-19 reviewed the method against the literature and found no better-established method for agentic systems. Its seven changes are listed in [`context/Research-Register.md`](../context/Research-Register.md).

| Step | What it produces | Where |
|---|---|---|
| 1. Concerns | Quality scenarios: invariants, checked on every run, and statistical scenarios, measured over repeats | Section 10 |
| 2. Views | C4 Context and Container, an agent view, one run, and deployment. LLM calls, the deterministic boundary, tool allowlists and human control are marked. | Sections 3, 5, 6 and 7 |
| 3. Boundaries | A contract in code wherever LLM output meets code | Section 5.4 |
| 4. Decisions | Short ADRs | Section 9 and [`DECISIONS.md`](../DECISIONS.md) |
| 5. Threats | Trust boundaries, and controls mapped to the OWASP lists | [`security.md`](security.md) |
| 6. Conformance | Fitness functions in CI; behavior in the evaluation harness | Section 8.7 and [`evaluation.md`](evaluation.md) |

## 1. Introduction and goals

### 1.1 What the system does

The assignment asks for an LLM application that reads an RFP and produces a structured solution summary of requirements, approach and risks. It must be a genuine agentic workflow, with an evaluation harness and tracing of tokens, latency and cost. At `v0.0`, Bidwright reads one PDF and writes:
- `solution_summary.md` and its JSON twin: submission hazards first, then requirements with verified quotes, approach items, risks and open questions;
- `proposal.md`: three short sections drafted from those records;
- `ledger.jsonl` and `run_manifest.json`: every LLM call's tokens, latency and cost, and the run's status and totals.

Every output carries the status `UNREVIEWED_DRAFT`.

### 1.2 Quality goals

In priority order. Section 10 states each one as a measurable scenario.

| Priority | Goal | Scenarios |
|---|---|---|
| 1 | Functional correctness: no mandatory requirement missed, and every requirement traced to a quote that code has checked | QS-1, QS-2, QS-8 |
| 2 | Security: tools are authorized outside the model, and document text never gains authority | QS-3, QS-4 |
| 3 | Transparency: an unsupported claim is marked, never asserted, and every number traces to a run | QS-5 |
| 4 | Controllability: people decide, and a run stops or waits when it should | QS-6 |
| 5 | Recoverability: provider faults are retried and failed over, and spend is never repeated | QS-7 |

### 1.3 Stakeholders

| Stakeholder | Needs from the architecture |
|---|---|
| The EY reviewers | The assignment's must-haves, visible and runnable without keys; trade-offs they can question |
| The owner | Sole approver of scope and decisions; a design the owner can explain and change live |
| The bid team the product serves, fictional here | A summary they can trust line by line, and drafts they can edit |
| Coding agents | Commands and boundaries, in [`AGENTS.md`](../AGENTS.md) |

## 2. Constraints

| Kind | Constraint |
|---|---|
| Assignment | Synthetic RFPs only; no real tender or client document enters the repository, a prompt or a test. `DECISIONS.md`, `ASSUMPTIONS.md`, rough timings and a 3-5 minute demo. |
| Models | Free tiers first. The owner's AI Studio limits, read 2026-11-02: 20 requests a day on `gemini-3.8-flash`, 500 on `gemini-3.5-flash-lite` (ADR-003). Free-tier prompts may be used by the provider, so `free` runs only on the synthetic corpus. |
| Machine | A Windows laptop whose 4 GB GPU the local models outgrow, so Ollama runs mostly on CPU (V-06 in [`verification_log.md`](verification_log.md)) |
| Toolchain | Python 3.12 and uv; ruff, pyright and pytest; GitHub Actions on a private repository |
| Conventions | Keys only in `.env`; ISO 8601 dates; one writer per output file; a design change needs an ADR |

## 3. Context and scope

### 3.1 Business context

```mermaid
flowchart LR
    team(["Bid team member"])
    reviewer(["EY reviewer"])
    rfp[/"RFP file in inputs/<br/>synthetic, listed in CORPUS.sha256"/]
    bw["Bidwright<br/>CLI and workflow"]
    gemini["Gemini API<br/>free tier"]
    ollama["Ollama<br/>local models"]
    phoenix["Phoenix<br/>trace collector"]
    out[/"outputs/run/<br/>summary, proposal, ledger, manifest"/]
    evalr["bidwright-eval<br/>separate scorer"]
    gold[/"evals/gold<br/>known answers"/]

    team -- "bidwright run" --> bw
    rfp --> bw
    bw -- "typed requests, HTTPS" --> gemini
    bw -- "typed requests, localhost" --> ollama
    bw -- "OTLP spans without prompt text" --> phoenix
    bw --> out
    reviewer -- "bidwright demo, scorecards" --> out
    out --> evalr
    gold --> evalr
```

| Interface | Direction | Form |
|---|---|---|
| RFP file | In | One PDF under `inputs/`. On `free`, its sha256 must be listed in `inputs/CORPUS.sha256`, or the run passes `--allow-non-corpus=i-accept-free-tier-terms`, which the manifest records. |
| Gemini | Out | The native `google-genai` SDK (ADR-001), with `GEMINI_API_KEY` from `.env` |
| Ollama | Out | HTTP to `OLLAMA_HOST`, `http://localhost:11434` by default |
| Phoenix | Out | OTLP over HTTP to `PHOENIX_ENDPOINT` when it is set and answers; otherwise spans go to `outputs/<run>/spans.jsonl` |
| Run folder | Out | `outputs/<run>/`, gitignored; one real run is committed under `samples/dev-free/` |
| Evaluation | Read only | `bidwright-eval score <run>` reads a finished run folder and the gold, and writes `evals/results/runs/<run>/` |

### 3.2 The LLM boundary

Everything a model writes crosses one boundary. Code sends a typed request built from a Pydantic model and receives text that must parse into a Pydantic model, and an acceptance check in code then decides what reaches the graph's state. The model never sees character offsets, never chooses the next step, and never runs a tool itself. Section 5.4 lists the contract for each call.

## 4. Solution strategy

**The thesis.** A deterministic shell around a probabilistic core: code checks everything code can check, and the LLM does only the judgment and generation that code cannot, inside those checks (ADR-005).

| Goal | Strategy at `v0.0` | ADR |
|---|---|---|
| Every requirement traceable | The PDF becomes passages with ids and offsets into a frozen text. The model cites passage ids and copies a quote, and code checks the quote. | ADR-006 |
| Agentic, yet testable | A LangGraph graph routes the run, with no LLM choosing the next step. One tool-using agent, `risk`; single-call functions elsewhere. | ADR-005 |
| No unauthorized action | Every tool call passes `ToolGateway` before it runs | ADR-009 |
| The assignment's output first | The solution summary is the first output of every run | ADR-007 |
| People decide | `DRAFT_ONLY`: nothing is submitted, and every output is `UNREVIEWED_DRAFT` | ADR-008 |
| Runs without keys | Recorded cassettes replay a whole run; the host path needs no Docker | ADR-016 |
| Measured, not asserted | A separate evaluation package; a ledger entry per call and spans per step | ADR-014, ADR-015 |
| Fits the free tier | Flash-Lite for both roles on `free`; no thinking on `local` | ADR-003, ADR-004 |

The workflow follows three phases: requirements and reality (`ingest`, `extract`, `verify`), engineering and evidence (`approach`, `risk`), and proposal (`draft`, `render`). `v0.0` runs a thin thread through all three. Of the planned control plane, `v0.0` has the tool gateway, the run budget and the checkpointer. The supervisor, policy and recovery components arrive in Iteration 2.

## 5. Building block view

### 5.1 Containers

Hexagons make LLM calls through the client. Everything else is code with no LLM.

```mermaid
flowchart TB
    cli["cli.py<br/>run, demo, record; corpus rule"]
    subgraph graph["graph/build.py: LangGraph graph with a SQLite checkpointer"]
        ingest["ingest"]
        extract{{"extract, one per batch"}}
        verify["verify"]
        approach{{"approach"}}
        risk{{"risk agent"}}
        draft{{"draft, three sections"}}
        render["render"]
    end
    client["llm/client.py<br/>model per role, retries, fallback, cassettes"]
    gateway["harness/gateway.py<br/>allowlist, arguments, repeats, call cap"]
    tools["tools.py<br/>search_rfp over FTS5, date_calc"]
    budget["harness/budget.py<br/>requests, tokens, active time"]
    obs["obs/<br/>ledger and spans"]
    genai["llm/genai.py"] --> gem[("Gemini")]
    oll["llm/ollama.py"] --> ol[("Ollama")]
    cass[("tests/cassettes")]

    cli --> graph
    ingest --> extract --> verify --> approach --> risk --> draft --> render
    extract & approach & risk & draft --> client
    risk -- "ToolRequest" --> gateway --> tools
    client --> budget
    client --> obs
    client --> genai
    client --> oll
    client <--> cass
```

### 5.2 Modules

| Module | Responsibility | Tested by |
|---|---|---|
| `cli.py` | The `run`, `demo` and `record` commands; the corpus rule | `test_cli.py`, `test_corpus_rule.py` |
| `config.py` | Loads and validates `config/*.yaml` with `yaml.safe_load` and Pydantic | `test_config.py` |
| `schemas.py` | Every record and every model-facing request and response, in [`reference/schemas.md`](reference/schemas.md) | `test_schemas.py` |
| `ingest.py` | pdfplumber words to frozen text and passages: headers and footers removed, headings, sentences, list items with their lead-ins, table rows with their header | `test_ingest.py` |
| `verify.py` | Quote checks: verbatim, normalized, or rejected | `test_verify.py` |
| `retrieval.py`, `tools.py` | The per-run FTS5 index; the `search_rfp` and `date_calc` tools | `test_tools.py` |
| `harness/gateway.py` | `ToolGateway` | `test_gateway.py` |
| `harness/budget.py` | Per-run limits on requests, tokens and active time | `test_budget.py` |
| `llm/client.py` | One `complete` call for every role: model choice, decoding, retries, fallback, record and replay, schema validation, ledger entries | `test_client_replay.py`, `test_simulator.py`, `test_cache_key.py` |
| `llm/genai.py`, `llm/ollama.py` | The Gemini and Ollama adapters | `test_adapters.py` |
| `llm/openai_compat.py` | An adapter for OpenAI-compatible providers, built for Cerebras and Groq from Iteration 3 and unused at `v0.0` | `test_adapters.py` |
| `llm/replay.py`, `llm/simulator.py` | Cassettes; a replay backend that injects scripted faults | `test_client_replay.py`, `test_simulator.py` |
| `llm/schema.py` | The provider form of a Pydantic schema, and hashes | `test_provider_schema.py` |
| `prompts.py` | Loads versioned prompts, renders them with `string.Template.substitute`, seeds delimiters from the run id | `test_prompts.py` |
| `graph/nodes.py`, `graph/state.py`, `graph/build.py` | The nodes, the graph state, the wiring and `execute` | `test_nodes.py`, `test_risk_loop.py`, `test_e2e_replay.py` |
| `render.py` | The outputs, after schema validation | `test_render_outputs.py` |
| `baselines.py` | EX0, the one-call extraction baseline | `test_e2e_replay.py` |
| `obs/ledger.py`, `obs/tracing.py` | Ledger totals; spans with a file fallback | `test_ledger.py`, `test_tracing.py` |
| `evals/` | The separate `bidwright-eval` package: corpus rendering, gold, matcher, scorer | `test_render.py`, `test_matcher.py`, `test_scorer_selftest.py` |

### 5.3 Agent view

[`agents.md`](agents.md) is generated from `config/agents.yaml`, `config/models.yaml`, the prompts' front matter, the tool specs and the compiled graph, so it cannot drift from the code. In summary:

| Role | Kind | Input to output | Model role | Tools | Limits |
|---|---|---|---|---|---|
| `extract` | Function, one per batch of 20 passages | `ExtractBatch` to `ExtractResult` | extract | None | 1 call, 1 repair |
| `approach` | Function | `ApproachInput` to `ApproachResult` | reason | None | 1 call, 1 repair |
| `risk` | Agent | `RiskInput` to `RiskRegister` | reason | `search_rfp`, `date_calc` | 4 turns, 6 tool calls, stop on no progress |
| `draft` | Function, once per section | `DraftTask` to `DraftResult` | reason | None | 1 call, 1 repair |

Agents never talk to each other. The graph passes each one a typed input built from verified records, and only checked output enters the state. Each `Send` worker returns its result through a reducer, so no two workers write the same key.

### 5.4 Boundary contracts

Each LLM call has a schema, an acceptance check in code, a pinned prompt and model, and a defined result when the check fails.

| Call | Pinned by | Acceptance check in code | When the check fails |
|---|---|---|---|
| `extract` | `extract@0.2.0`; the `extract` role's model | Each quote is found in a passage the item cites, from its own batch, verbatim or after normalization. Every passage of the batch appears in an item or in `no_obligation_src_ids`. At most 3 `src_ids`, quotes of at most 300 characters. | One repair, aimed at the failed quotes and missing ids, or at the format. What still fails goes to `rejected.jsonl`. A batch that breaks its schema twice is rejected whole, and the run ends `DEGRADED`. |
| `approach` | `approach@0.2.0`; `reason` | Requirement ids must name verified `BINDING` or `OPTIONAL` requirements; an item with none is dropped, and requirements left unmapped are listed | One format repair, then `UNRECOVERABLE_FAULT` |
| `risk`, tool turns | `risk@0.2.0`; `reason`; the allowlist in `config/agents.yaml` | `ToolGateway`: the tool is allowed and registered, the arguments validate, no third identical call, the call cap is not spent | A `DENIED` or `FAILED` result goes back to the model, and the tool never runs |
| `risk`, final register | The same | Each risk cites passages that exist and shares a content word with them, and carries no rating or probability | One retry for the rejected risks; a register that breaks its schema twice gives `UNRECOVERABLE_FAULT` |
| `draft` | `draft@0.2.0`; `reason` | Cited ids are kept only if they name the section's own records | One format repair, then the section is `FAILED` and the run `DEGRADED` |
| Every call | The cassette key | The response parses into its Pydantic model | Reported as a parse error for the node's repair |

`render` adds the last check: every record is validated against its schema before anything is written, and one failure blocks every output.

## 6. Runtime view

### 6.1 The graph

`ingest` → `extract`, fanned out with one `Send` per batch → `verify` → `approach` → `risk` → `draft` → `render`, with no branches. The diagram in [`agents.md`](agents.md) is drawn from the compiled graph. At most 2 `extract` workers run at once on `free` and 1 on `local`, because Ollama on this machine serves one request at a time (`config/limits.yaml`).

### 6.2 One run

```mermaid
sequenceDiagram
    autonumber
    participant CLI as cli.py and execute
    participant G as Graph nodes
    participant C as LLM client
    participant P as Provider or cassettes
    participant T as ToolGateway
    CLI->>G: start the run with its budget, prompts and tracing
    G->>G: ingest: frozen text, passages, FTS5 index, batches of 20
    par each batch, at most 2 at once on free
        G->>C: ExtractBatch
        C->>P: request, with retries and fallback
        P-->>C: ExtractResult
        G->>G: check quotes and ids, one repair
    end
    G->>G: verify: number accepted items REQ-0001 and on, write requirements and rejected quotes
    G->>C: ApproachInput
    loop risk: at most 4 turns and 6 tool calls
        G->>C: turn with the tool specs
        C-->>G: tool calls
        G->>T: ToolRequest
        T-->>G: ToolResult: OK, EMPTY, DENIED or FAILED
    end
    G->>C: final call with no tools, for the RiskRegister
    G->>G: screen generic and rated risks, one retry
    G->>C: DraftTask for each of three sections
    G->>G: render: validate every record, write the summary and proposal
    CLI->>CLI: write run_manifest.json and ledger.jsonl, whatever the outcome
```

Every LLM call first checks the run budget, then goes through the client, which records one ledger entry and one `LLM` span.

### 6.3 Failure behavior per step

| Step | Failure | Response | Limit | Test |
|---|---|---|---|---|
| CLI | A file not in the corpus, on `free` | Refused before the run starts; the consent override runs it and the manifest records it | None | `test_corpus_rule.py` |
| Any LLM call | 429, 5xx or timeout | Full-jitter backoff with a 2-second base and a 30-second cap, where `Retry-After` wins; then the role's fallback model, once | 3 retries | `test_fi01_*` in `test_simulator.py` |
| Any LLM call | A 429 that names a spent daily quota | No retry: the fallback model at once; with none left, the run ends `QUOTA_PAUSED` | 0 | `test_a_spent_daily_quota_moves_to_the_fallback_without_retrying` |
| Any LLM call | Request, token or active-time limit reached | Checked before each call; the run ends `BUDGET_EXCEEDED` | `config/limits.yaml` | `test_budget.py` |
| Any LLM call, replay | No cassette for the key | The run ends `UNRECOVERABLE_FAULT`, with its manifest and ledger | 0 | `test_a_missing_cassette_ends_the_run_as_a_fault` |
| `ingest`, or anywhere | An unexpected error, such as an unreadable PDF | The run is recorded as `UNRECOVERABLE_FAULT`, and the error propagates | 0 | `test_an_unexpected_error_is_recorded_as_a_fault` |
| `extract` | Malformed output | One format repair, then the whole batch is rejected and the run ends `DEGRADED` | 1 | `test_fi02_*` in `test_nodes.py` |
| `extract` | A quote not found, or passage ids missing | One targeted repair, then `REJECTED` in `rejected.jsonl` | 1 | `test_verify_repair_fixes_a_quote_and_a_missing_id` |
| `approach` | Malformed output twice | `UNRECOVERABLE_FAULT` | 1 | `test_approach_fails_after_two_schema_failures` |
| `risk` | A tool outside the allowlist, bad arguments, a third identical call, or the cap spent | `DENIED`, returned to the model | 0 | `test_gateway.py` |
| `risk` | A tool raises | `FAILED`, returned to the model | 0 | `test_a_tool_that_raises_returns_failed_to_the_model` |
| `risk` | A turn adds no new passage or date result, or the turn or call cap is reached | The loop ends, and a final call with no tools asks for the register | 4 turns, 6 calls | `test_loop_caps_*` in `test_risk_loop.py` |
| `risk` | A generic risk, or one with a rating or probability | Rejected, with one retry for the rejected risks | 1 | `test_risk_generic_*` |
| `draft` | Malformed output twice | That section is `FAILED`, the others continue, and the run ends `DEGRADED` | 1 | `test_nodes.py` |
| `render` | A record fails its schema | Nothing is written; `UNRECOVERABLE_FAULT` | 0 | `test_render_schema_failure_blocks_all_output` |
| Tracing | The collector is down or refuses a batch | Spans go to `spans.jsonl`, and the run never waits | None | `test_tracing.py` |

**Run statuses at `v0.0`.** A run ends `COMPLETED`, `DEGRADED` (with the shortfall in `status_reason`), `BUDGET_EXCEEDED`, `QUOTA_PAUSED` or `UNRECOVERABLE_FAULT`. The checkpointer saves each step's state in `checkpoints.sqlite`, but no command resumes a run yet. `bidwright resume` arrives in Iteration 2, so a stopped run is started again. The other statuses in `RunStatus` belong to later iterations.

## 7. Deployment view

Two ways to run, from one codebase.

| Path | Command | Needs |
|---|---|---|
| Host | `uv run bidwright demo`, `uv run bidwright run <file>`, `uv run pytest` | Python 3.12 and uv. The demo and the tests need no keys and no network; CI's `host-path` job proves it on a clean checkout. |
| Compose | `docker compose up -d`, `docker compose run --rm demo`, `docker compose run --rm test` | Docker, and `GEMINI_API_KEY` in `.env`, which Compose requires for every command (ADR-002) |

| Compose service | Image | Job | Network and mounts |
|---|---|---|---|
| `app` | Built from the `Dockerfile` in stages with uv, running as a non-root user | The `bidwright` CLI | `inputs/`, `config/` and `prompts/` read-only; `outputs/` read-write |
| `phoenix` | `arizephoenix/phoenix` 21.0.0, pinned by digest | Traces on port 6006 | Published on `127.0.0.1` only. Authentication starts off for this local collector of synthetic runs; `.env` can turn it on, and the app then sends `PHOENIX_API_KEY` as a bearer token. |
| `eval` | The same image, profile `eval` | `bidwright-eval` | The only service that mounts `evals/gold` and `evals/corpus`, read-only |
| `test` | The same image, profile `test` | `pytest -m "not gold"` | No network; cassettes read-only |
| `demo` | The same image, profile `demo` | `bidwright demo` | No network; cassettes read-only |
| `ollama` | `ollama/ollama` 0.40.13, pinned by digest, profile `local` | Local models | Published on `127.0.0.1` only |

**What stays out of the image.** `.dockerignore` keeps out `evals/corpus/`, `evals/gold/`, `evals/results/`, `evals/labels/`, `private/`, `outputs/` and `.env`, and CI's `docker` job checks that the image holds no gold and no corpus spec.

**Data by location.**

| Location | Holds | In Git |
|---|---|---|
| `inputs/` | Rendered synthetic RFPs and `CORPUS.sha256` | Yes |
| `evals/corpus/`, `evals/gold/` | Corpus specs and the gold generated from them, hashed in `MANIFEST.sha256` | Yes; never in the image |
| `outputs/` | Run folders | No |
| `samples/dev-free/` | One real development run on `free`, the sample the README cites | Yes |
| `tests/cassettes/` | Recorded responses for the demo and the replay tests | Yes |
| `.env` | Keys | No; `.env.example` holds names only |
| `private/` | Research reports, review reports, the assignment PDF | No |

## 8. Crosscutting concepts

### 8.1 What each call sees

Each node builds its own prompt from whole records, never from partial passages; a context manager arrives in Iteration 1. `extract` sees one batch of passages, each with its id, section path, text and list lead-in. `approach` sees the verified `BINDING` and `OPTIONAL` requirements. `risk` sees those, the approach items and the hazard ids, plus what its tools return. `draft` sees only its own section's records. Nothing carries over between runs.

Every prompt follows one layout: the system instruction first, with role, rules, output format and examples; then the data inside delimiter tags seeded from the run id; then the task, last. The model sees display text, with line breaks turned into spaces at the same offsets, so a quote can be checked against the frozen text.

### 8.2 Provenance

- Passages are half-open slices of `frozen.txt`, with ids `SRC-0001` and on.
- Each requirement cites at most 3 passage ids and quotes at most 300 characters, with the quote's status and its span in the frozen text.
- Approach items carry the source ids of their requirements and evidence class `ASSUMPTION`, since `v0.0` has no knowledge base. Risks cite the passages that support them.
- `run_manifest.json` records the commit, profile, models by role, prompt hashes, input file hashes, start and end, status and reason, overrides, and totals derived from the ledger.

### 8.3 Limits

From `config/limits.yaml` and `config/agents.yaml`:
- Per run on the development RFP: 60 requests and 300,000 tokens, with 20 active minutes on `free` and 60 on `local`. The clock counts only active time.
- Per call: a 120-second timeout on `free` and 300 seconds on `local`, with 3 retries.
- `extract` batches hold 20 passages. The `risk` loop is capped at 4 turns and 6 tool calls, and `search_rfp` returns at most 8 passages.

### 8.4 Human control

Bidwright drafts and never submits. Every summary and proposal opens with the `UNREVIEWED_DRAFT` status line. `v0.0` has no gate. The two human gates arrive in Iterations 3 and 4.

### 8.5 Observability

- **Ledger.** One `LedgerEntry` per call: model, prompt and input hashes, input, cached, output and thinking tokens, latency and the provider's own timings, retries, the real cost, and a shadow cost at the paid list price of the role's shadow model in `config/pricing.yaml`. Free and local calls cost nothing, so the shadow cost is what makes runs comparable.
- **Spans.** `run` and `node.<name>` are `CHAIN` spans, except `node.risk`, which is an `AGENT` span with its stop reason, turns and tool calls. Each call adds `llm.<node>` (`LLM`) and each tool call `tool.<name>` (`TOOL`). Spans carry hashes and counts, never prompt or response text.
- **Where spans go.** OTLP to Phoenix when `PHOENIX_ENDPOINT` answers, and `spans.jsonl` in the run folder otherwise, or for any batch the collector refuses. Spans are flushed when the run ends.

### 8.6 Replay

The client runs in `live`, `record` or `replay` mode. A cassette's key is a sha256 over the prompt hash, the schema hash, the tool definitions' hash, the model, the decoding settings, the input hash taken before delimiters are inserted, and the repeat index. A change to any of them misses its cassette, so replayed tests fail until the cassettes are recorded again and the run re-scored. `bidwright demo` replays `tests/cassettes/demo/`, which was recorded from the run in `samples/dev-free/`.

### 8.7 Conformance in CI

Structural rules are fitness functions that run on every push. Behavior is measured by the evaluation harness, replayed in CI and run live at each tag.

| CI job | What it proves |
|---|---|
| `lint`, `types` | ruff and pyright pass |
| `unit` | The fast tests, including the import rule (`src/bidwright` never imports `evals`), the gateway rules, the Compose lockdown and the repository hygiene checks |
| `replay` | Nodes and a whole run replay from cassettes with no network |
| `gold` | Corpus rendering, the matcher and the scorer self-test, against gold |
| `host-path` | `bidwright demo` runs on a clean checkout with no `.env` |
| `docs-generated` | [`agents.md`](agents.md) and the [CLI](reference/cli.md) and [schema](reference/schemas.md) references match the code |
| `docs-links` | Links and wikilinks resolve, dates are ISO, `context/` front matter is valid, and the documents keep a neutral voice |
| `docker` | The image builds, holds no gold, and passes the tests with no network |
| `secrets`, `deps` | gitleaks finds no secret; pip-audit finds no known vulnerability |

### 8.8 Configuration

`config/models.yaml`, `limits.yaml`, `agents.yaml`, `thresholds.yaml` and `pricing.yaml` are loaded with `yaml.safe_load` and validated by Pydantic in `config.py`, so a bad value fails at start-up. A prompt's decoding block may override only `thinking`, `think` and `num_ctx`.

## 9. Architecture decisions

[`DECISIONS.md`](../DECISIONS.md) holds the ADRs, with their index, and the failure modes hit while building. ADR-001 to ADR-004 were taken in Iteration 0a; ADR-005 to ADR-016 record the plan's product and architecture decisions. [`decision-matrix.md`](decision-matrix.md) maps the choices to a published taxonomy of architecture options for agent systems, with the quality trade-offs each implies.

## 10. Quality requirements

### 10.1 Quality scenarios

Each scenario is tagged with its ISO/IEC 25059 characteristic. An **invariant** must hold on every run, and code checks it. A **statistical** scenario is measured over the corpus, its seeds and repeats, with a sample size, a threshold and an action, block or warn.

| ID | Kind | Characteristic | Stimulus | Required response | Measure | Runs at | Status at `v0.0` |
|---|---|---|---|---|---|---|---|
| QS-1 | Invariant | Functional correctness | A model emits a quote that is not in the source | Repaired once or rejected, never accepted | Accepted quotes that are neither verbatim nor normalized: 0, block | Every run; CI on replay | **Holds.** `test_verify.py` with the S-07 cases and `test_nodes.py`; every quote in the committed runs is verbatim. |
| QS-2 | Statistical | Functional correctness | A mandatory clause anywhere in the RFP | Captured, with exact provenance | On the hero RFP: at most 2 of 45 missed in the median of 5 repeats, and no rise against the baseline; block | Iteration 3 exit and release, on 5 live hero repeats | **Not yet measured:** the hero RFP arrives in Iteration 1. On the development RFP, 0 of 8 missed in single runs on `free`, on `local` and by EX0. |
| QS-3 | Statistical | Robustness | An injected instruction with a unique marker and a detectable requested action, in a document or a research result; at least 6 per RFP | Flagged or quarantined, never obeyed | The requested action in an LLM-written field or a tool-call argument: 0, block | Iteration 3 exit and release, on 5 live hero repeats; CI on replay | **Not built:** traps enter the corpus and `guard` is built in Iteration 1. At `v0.0` the only control is delimiter tags, which are hygiene, not a boundary (ADR-010). |
| QS-4 | Invariant | Security | A tool request outside an allowlist or a rule | Stopped outside the model | Unauthorized calls allowed: 0, block | Every run; CI on replay | **Holds** for the `risk` agent's two tools: `test_gateway.py`, and every request and result is kept for the trace. |
| QS-5 | Statistical | Transparency | A capability the knowledge base cannot support; at least 4 seeded gaps per RFP | Marked `UNVERIFIED`, never asserted | Seeded gaps claimed: 0, block | Iteration 3 exit and release, on 5 live hero repeats | **Not built:** the knowledge base arrives in Iteration 1 and `assess` in Iteration 3. At `v0.0` every approach item carries the evidence class `ASSUMPTION`. |
| QS-6 | Invariant | Intervenability, user controllability | A stop command, an exhausted budget, or a gate with no person | Halts at the next step, or waits in `WAITING_HUMAN`; output stays `UNREVIEWED_DRAFT` | Fault-injection tests | CI | **Partly holds:** the budget stops a run before its next call (`test_budget.py`), and every output carries `UNREVIEWED_DRAFT` (`test_render_outputs.py`). The stop command arrives in Iteration 2 and the gates in Iterations 3 and 4. |
| QS-7 | Invariant | Recoverability | A provider 429, a timeout, malformed output or a crash | Retries, fails over and resumes, with no repeated spend | FI-01, FI-02 and a resume test | CI | **Partly holds:** FI-01 and FI-02 pass (`test_simulator.py`, `test_nodes.py`), and a spent daily quota moves to the fallback without retrying. Resume arrives in Iteration 2; until then a crashed run starts again. |
| QS-8 | Statistical | Functional correctness | The same RFP run 5 times | The requirement set and the tool path stay within tolerance | Median pairwise Jaccard over the gold clause ids each run captures: at least 0.85, warn | Iteration 3 exit and release, on 5 live hero repeats | **Not yet measured:** it needs repeats on the hero RFP. |

Modifiability is shown by the live-change rehearsal at release, not by a scenario.

### 10.2 How a statistical scenario blocks

At the Iteration 3 exit and in the release step, a failed statistical scenario holds the tag or the release until it passes, or until the owner accepts a recorded exception: an ADR giving the measured value and the reason, with the result reported in the README. CI blocks only on invariants and replayed checks, with the thresholds in `config/thresholds.yaml`.

### 10.3 When evidence goes stale

A change to a model, a prompt, a schema or a tool description changes the cassette keys, so replay fails until the cassettes are recorded again (section 8.6). The live evidence behind each statistical scenario is stale from that change until it is measured again.

[`evaluation.md`](evaluation.md) describes the harness that measures these scenarios.

## 11. Risks and technical debt

Project risks live in section 7 of [`context/Master-Plan.md`](../context/Master-Plan.md). Technical debt and known limits at `v0.0`:

| Item | Effect | Paid down in |
|---|---|---|
| No `guard`: hidden text in a PDF reaches the model, inside delimiters only | QS-3 is not met | Iteration 1 |
| pdfplumber and one PDF only; no DOCX, XLSX or package folder | The hero and held-out RFPs cannot run yet | Iteration 1 |
| `risk` found 1 of 3 planted risks on `free` and 0 of 3 on `local` | Weak risk recall | Iterations 1 and 3, measured by the RK ablation |
| The `risk` retry drops a rejected risk instead of rewording it | A real risk can be lost to a fixable rating phrase | Iteration 3 |
| Narrative passages come back as `BACKGROUND` items, and the invitation to bid was once recorded as `OPTIONAL` | Precision is a range until adjudicated | Iteration 1 |
| No resume command, although checkpoints are written | A stopped run starts again and spends again | Iteration 2 |
| `reason` runs on Flash-Lite on `free` (ADR-003) | Approach, risk and draft quality against Flash is unmeasured | The SO comparison; the paid budget decision at the Iteration 1 exit |
| The tool loop on `gemini-3.8-flash` and a cached-token reading are unverified (ADR-001) | Two open checks on the native adapter | The first recorded run on 3.8 Flash |
| A development run takes 17 minutes on `local`, on CPU | The local path is a privacy path, not a fast one | Iteration 6 bake-off |
| Compose needs a key even for the demo (ADR-002), and the `app` service exits after printing its help | Docker reviewers need a key; there is no long-running app service | ADR-002's reverse-if; Iteration 6 |
| One author writes both the corpus and the prompts | Scores may flatter the system | Iteration 1: the owner's held-out requirement list; external stage benchmarks |

## 12. Glossary

| Term | Meaning |
|---|---|
| RFP | The buyer's request for proposal |
| Passage | A sentence, list item, table header or table row, with an id `SRC-0001` and half-open offsets into `frozen.txt` |
| Requirement | One obligation, with an id `REQ-0001`, a modality, a disposition, cited passages and a verified quote |
| Disposition | `BINDING` (the supplier must do it if it bids), `OPTIONAL` (invited, not required), `BACKGROUND` (context that obliges no one), `NOT_BINDING` (reads like an obligation but is not one here), `OUT_OF_SCOPE` (an obligation on another party or a later stage) |
| Mandatory | True exactly when the disposition is `BINDING` |
| Hazard | A requirement whose breach can disqualify a bid: a deadline, a format rule, a mandatory form, an eligibility condition |
| Quote status | `VERBATIM_VERIFIED`, `NORMALIZED_MATCH` (equal after normalizing whitespace, ligatures, line-end hyphens and quote marks) or `REJECTED` |
| Profile | `free` (Gemini free tier, synthetic corpus only) or `local` (Ollama, nothing leaves the machine) |
| Model role | `extract` or `reason`, each mapped to a model and a fallback per profile |
| Agent | An LLM role that calls tools in a loop; at `v0.0`, only `risk` |
| `ToolGateway` | The code that authorizes every tool call before it runs |
| Cassette | A recorded response, keyed by everything that affects the call |
| Ledger | One entry per LLM call, in `ledger.jsonl` |
| Shadow cost | What a call would cost at the paid list price of its role's shadow model |
| Run manifest | `run_manifest.json`: the run's inputs, models, prompts, status and totals |
| `UNREVIEWED_DRAFT` | The status of every output until a person signs it off |
| Gold | The known answers for a synthetic RFP, generated from its spec |
| Seed | A planted item in the corpus, such as a risk, that a run should find |
| EX0 | The one-call extraction baseline |
| The owner | The project's sponsor and sole approver |
| Claude | The AI coding agent that builds Bidwright under the owner's direction |
