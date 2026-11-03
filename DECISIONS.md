# Decisions

Architecture and product decisions, recorded as short ADRs, and the failure modes hit while building, with their fixes. Process decisions live in the Master-Plan change log in `context/Master-Plan.md`, from Iteration 0b.

## ADR format

Each ADR gives:
- a number and title, and its status: `proposed`, `accepted` or `superseded`;
- context, decision and consequences;
- one line each for the options considered, the confirmation test, the reverse-if condition and the provenance.

Model and prompt ADRs also give the evaluation evidence and the model's expected lifetime. A rationale must make sense without private sources.

## ADRs

ADR-001 to ADR-004 were taken while building Iteration 0a. ADR-005 to ADR-016 record the product and architecture decisions of the plan, from the change log in `context/Master-Plan.md`, which marks each entry as an ADR or a process decision. ADR-017 to ADR-021 are proposed by the Iteration 1 design doc, `docs/designs/iteration-1.md`, and become accepted or change at its Stage 9 review.

| ADR | Decision | Status |
|---|---|---|
| 001 | Gemini through the native `google-genai` SDK | accepted |
| 002 | Compose requires the Gemini key | accepted |
| 003 | The free profile's `reason` model is Gemini 3.5 Flash-Lite | accepted |
| 004 | No thinking on the local profile | accepted |
| 005 | A supervised workflow, with agents only where they earn their place | accepted |
| 006 | Grounding by verified quotes, over lexical search | accepted |
| 007 | The solution summary first, then a proposal pack from one manifest | accepted |
| 008 | People decide; Bidwright drafts | accepted |
| 009 | Tools run behind a gateway outside the model | accepted |
| 010 | Untrusted inputs are screened before parsing, and the corpus is synthetic | accepted |
| 011 | Model roles, families and fallbacks | accepted |
| 012 | Prompts are versioned files, and method knowledge is loaded by code | accepted |
| 013 | Research runs as agent tools behind a provider interface | accepted |
| 014 | A separate harness scores frozen runs against known answers | accepted |
| 015 | Observability from a per-call ledger and OpenInference spans | accepted |
| 016 | Docker Compose, with a host path for the demo and tests | accepted |
| 017 | Every passage reaches `extract`; cues annotate and never filter | proposed |
| 018 | Six zones, assigned per section, with a keyword fallback | proposed |
| 019 | The `consolidate` cluster rule | proposed |
| 020 | Review files for quarantined text, small print and suspect passages | proposed |
| 021 | The compliance matrix layout | proposed |

### ADR-001: Gemini through the native `google-genai` SDK

**Status:** accepted, 2026-11-02.

**Context.** The Iteration 0a design sent Gemini calls through Google's OpenAI-compatible endpoint, so that one `openai`-based adapter would serve Gemini, Cerebras and Groq. The S-04 spike was the test. It asks whether each provider returns valid structured output, completes a tool loop and reports usage, cached and thinking token counts. If the token fields did not arrive, a native `google-genai` adapter would be added. S-04 ran on synthetic text on 2026-11-02:
- **Compatible endpoint, 3.5 Flash-Lite:**
  - Strict `json_schema` output was valid both with nested models in `$defs` and with them inlined.
  - Usage arrived with both token-detail objects null, and the compatibility docs list no detail fields.
  - Both 3.8 Flash calls on this endpoint failed, with a 503 and then a timeout.
- **Native SDK, 3.5 Flash-Lite, structured calls:**
  - 10 of 10 `extract` calls were schema-valid, accounted for every passage id and quoted verbatim, in 0.9 to 1.3 seconds each.
  - No call reported cached tokens. That is expected, because the prompts were about 1,390 tokens and implicit caching starts at 4,096 on Flash.
- **Native SDK, 3.5 Flash-Lite, tool loop:**
  - A tool turn sent back without its thought signature failed with a 400, "Function call is missing a thought_signature".
  - The same turn sent back exactly as the model returned it succeeded.
  - A final structured call after the tool history, with no tools, returned a valid `RiskRegister` citing both seeded passages.
- **Native SDK, 3.8 Flash:**
  - The first tool turn returned a signed function call and reported 37 thinking tokens.
  - The next two calls failed with a 504 and a 503, after 3 retries each.

**Decision.**
- Gemini calls go through `llm/genai.py`, which uses the native SDK.
- The model's turn is kept as `Response.native` and sent back unchanged.
- `llm/openai_compat.py` stays, for Cerebras and Groq from Iteration 3.
- Prompt front-matter states Gemini's reasoning setting as `thinking`, the name used in `config/models.yaml` and passed to the native `thinking_level`, not as `reasoning_effort`.

**Consequences.**
- There is one more runtime dependency and one provider-specific adapter.
- Thought signatures need no special handling. On the compatible endpoint they travel in a Gemini-only `extra_content.google.thought_signature` field on each tool call, which a provider-neutral adapter would have to carry.
- The ledger takes thinking, cached and tool-use token counts from the documented native fields.
- Cassettes store text, tool calls and usage, but not the native turn. A replayed run never sends a turn back to a provider.
- Two checks are still open: the full tool loop on 3.8 Flash, and a cached-token reading. Both are rechecked when the development run is recorded in step 10.

**Options.**
- The compatible endpoint for every provider. Rejected: it documents no token detail, and it would put Gemini-specific signature handling into the shared adapter.
- A gateway library such as LiteLLM. Rejected: two of its releases were compromised on 2026-03-24, and it adds a layer between the ledger and each provider's fields.

**Confirmation.** `tests/test_adapters.py` pins the field mapping and the unchanged return of the model's turn. A recorded 3.8 Flash run shows non-zero `tokens_thinking` in `ledger.jsonl`.

**Reverse if.** The compatible endpoint documents and returns the token details and carries signatures without provider-specific fields, or the native SDK stops reporting a field the ledger needs.

**Provenance.** The S-04 spike on 2026-11-02, and the documentation checks in `docs/verification_log.md`.

### ADR-002: Compose requires the Gemini key

**Status:** accepted, 2026-11-02.

**Context.** `compose.yaml` marks `GEMINI_API_KEY` as required with `${GEMINI_API_KEY:?}`. Checked with Docker Compose 2.27.0: when the variable is unset, Compose refuses every command, the keyless `demo` and `test` services included, with "required variable GEMINI_API_KEY is missing a value".

**Decision.** The key stays required in Compose.

**Consequences.**
- A missing key stops Compose at start-up with a clear message, instead of a live run failing partway.
- Docker users put a key in `.env` even for the demo and the tests.
- The host path stays keyless: `uv run bidwright demo` and `uv run pytest` need no `.env`. The CI `docker` job builds and runs the image with plain `docker`, not Compose, so it stays keyless too.
- The 0a exit check "`docker compose run --rm test` passes with no keys" is an accepted exception: it passes once `.env` holds a key.

**Options.** `${GEMINI_API_KEY:-}`, which would let `demo` and `test` run in Docker without a key and move the missing-key error to run time. Not chosen.

**Confirmation.** `tests/test_compose_lockdown.py` checks that every key in `compose.yaml` is a variable reference, never a literal.

**Reverse if.** Reviewers need to run the demo in Docker without creating a key.

**Provenance.** The owner's decision on 2026-11-02, after the check above (C7-13 in `docs/verification_log.md`).

### ADR-003: The free profile's `reason` model is Gemini 3.5 Flash-Lite

**Status:** accepted, 2026-11-02. It changes the planned choice of `gemini-3.8-flash` for `reason` on the `free` profile.

**Context.** The plan gave `reason` to Gemini Flash because solution quality outranks cost. The project's real free-tier limits, read in AI Studio on 2026-11-02, allow 20 requests a day on `gemini-3.8-flash` and on `gemini-3.6-flash`, against 500 on `gemini-3.5-flash-lite`. One development run needs about 10 to 14 `reason` calls, and retries count against the quota. On the same day, `gemini-3.8-flash` returned 504s on every attempt in two runs, and its quota was spent before the demo could be recorded. Gemma 4 allows 14,400 requests a day, but it accepts only 16K input tokens a minute, rejects a thinking level, and failed about half its probe calls.

**Decision.**
- On the `free` profile, `reason` runs `gemini-3.5-flash-lite`, with `gemini-3.1-flash-lite` as its fallback, the same class and the same fallback as `extract`.
- The shadow price for `reason` follows the model in use, so free and local runs are priced as this configuration would cost on the paid tier.
- A 429 that names a daily quota is no longer retried: the client moves to the fallback at once, and with no fallback left the run stops in `QUOTA_PAUSED`.

**Consequences.**
- Development runs and the demo fit the free tier, with room for repeats.
- Approach, risk and draft quality may fall, since Flash-Lite was not chosen for solution work. The planned SO comparison measures this, and `gemini-3.8-flash` stays available for quality runs, on its 20 free requests a day or on the paid key.
- Comparisons stay clean: the ledger records the model behind every call, and a run that used the fallback is marked as such.

**Options.**
- `gemini-3.8-flash`, as planned: 20 requests a day, unavailable for most of 2026-11-02.
- `gemini-3.6-flash` as the fallback: rejected by the owner, since it has the same 20-a-day quota and is a different model class.
- Gemma 4: unreliable on the day, and too small an input budget per minute for the Iteration 3 prompts.
- A non-Gemini model: needs new keys, and the plan keeps those families for independent assessment.

**Confirmation.** `tests/test_simulator.py` covers the fallback for `reason` and the no-retry rule for a spent daily quota. The ledger of a recorded run shows `reason` calls on `gemini-3.5-flash-lite`.

**Reverse if.** The SO comparison shows Flash-Lite below Flash by more than noise on approach or risk, or a paid budget makes Flash affordable for every run.

**Provenance.** The owner's decision on 2026-11-02, from the AI Studio limits and the probes in `docs/verification_log.md`.

### ADR-004: No thinking on the local profile

**Status:** accepted, 2026-11-02. It changes the planned `think: true` for `reason` on the `local` profile.

**Context.** The plan turns Ollama's thinking on for `reason` and off for `extract`. On this machine's 4 GB card, both `qwen3.5:4b` and `qwen3.5:2b` run mostly on CPU at a 16K context (V-06), generating about 7 to 20 tokens a second. With thinking on, the model writes thousands of thinking tokens before its answer, and the local call timeout is 300 seconds. In two local runs on 2026-11-02, `reason` calls ran out of time every time: in the second, all 4 attempts at `approach` on `qwen3.5:4b`, then the `qwen3.5:2b` fallback's attempts, each stopped at 5 minutes. With thinking off, the same model's extract calls took 2 to 4 minutes.

**Decision.** Thinking is off for every role on the `local` profile: `think: false` in `config/models.yaml` and in the Ollama decoding of `approach`, `risk` and `draft`, which move to version 0.2.0. The `free` profile is unchanged.

**Consequences.**
- The local thin thread can finish inside its 60-minute budget on a CPU-bound laptop.
- Local `reason` output may be weaker without thinking. The local profile proves the private path end to end; it is not scored against the corpus, and the Iteration 6 bake-off measures thinking and `reflect` on local models.
- The Gemini cassettes were re-recorded, because a prompt's hash covers its decoding for every provider.

**Options.**
- Raise the local call timeout and run budget, keeping thinking on: thinking length has no bound, so a run could take one to two hours and still fail.
- Accept an exception for the 0a check that the same run completes on a local Ollama model.

**Confirmation.** A development run on `--profile local` ends `COMPLETED`, with every call inside the timeout.

**Reverse if.** The local models fit a GPU on the machine that runs them, or the Iteration 6 bake-off shows thinking finishing inside the limits with better scores.

**Provenance.** The owner's decision on 2026-11-02, after the failed local runs in the failure log below.

### ADR-005: A supervised workflow, with agents only where they earn their place

**Status:** accepted, 2026-11-02. The graph and the `extract`, `approach`, `risk` and `draft` nodes are built in Iteration 0a; the other nodes arrive as the roadmap in `context/Master-Plan.md` lists.

**Context.** The assignment asks for a genuine agentic workflow, and a bid team needs every mandatory requirement found. When an LLM chooses the next step, runs are hard to test, resume and audit. Each extra agent also spends requests from small free quotas.

**Decision.**
- A deterministic shell around a probabilistic core: code checks everything code can check, and the LLM does only the judgment and generation that code cannot, inside those checks.
- A LangGraph graph routes the run, and no LLM chooses the next step. `Send` fans out batches and sections, and a SQLite checkpointer keeps state.
- Four tool-using agents (`discover`, `decide`, `risk`, `redteam`) and single-purpose LLM functions. Agents never talk to each other. Each gets a typed handoff, and its output passes a code check before it reaches state.
- Each agent must beat a fixed-pipeline control, the same evidence in one call with no loop, in a measured ablation, or its loop is dropped.
- Each run has limits on requests, tokens and active time, set per profile and RFP, and ends in exactly one status with a reason.

**Consequences.**
- Runs replay from cassettes, resume from checkpoints, and can be audited from their traces.
- Agentic depth has to be shown by measurement, not asserted.
- There are more nodes than in a single-prompt app, but each is small and tested on its own.

**Options.** CrewAI, whose role-led autonomy works against fixed routing; n8n or Flowise, whose flows are exported JSON or visual graphs that diff and test poorly; plain Python, with checkpoints and interrupts built by hand; one agent for everything.

**Confirmation.** `tests/test_e2e_replay.py` replays a whole run; `tests/test_risk_loop.py` covers the loop's caps and stops; `tests/test_budget.py` covers `BUDGET_EXCEEDED`; from Iteration 3, the SO, RK and PR ablations with their `-F` controls.

**Reverse if.** An agent fails to beat its fixed-pipeline control, or LangGraph cannot stop between nodes or resume reliably.

**Provenance.** The approved plan of 2026-11-02: CH-32, CH-55, CH-58 and CH-63 in the Master-Plan change log.

### ADR-006: Grounding by verified quotes, over lexical search

**Status:** accepted, 2026-11-02. Built in Iteration 0a.

**Context.** A requirement list is useful only if each item traces to the RFP's own words. Models misreport character offsets, and invented quotes look plausible. Whether a quote can be found in the source separates faithful output from unfaithful output at no inference cost.

**Decision.**
- Sentences, list items and table rows become passages `SRC-0001` and on, with half-open offsets into the frozen text. The model sees passage ids and text, never offsets.
- Each requirement carries a quote of at most 300 characters from a passage it cites. Code checks it: an exact match is `VERBATIM_VERIFIED`; a match after normalizing whitespace, ligatures, line-end hyphens and quote marks is `NORMALIZED_MATCH`; anything else gets one targeted repair, then becomes `REJECTED` and goes to `rejected.jsonl`.
- Agents search with SQLite FTS5 and BM25, with Porter stemming and function words dropped. A requirement id in a query returns the passages that requirement quotes.

**Consequences.**
- A reader can check every summary line against the RFP.
- A real obligation with a bad quote is lost after one repair, and the scorecard shows it.
- Lexical search needs no embedding model or vector store, but it misses paraphrases.

**Options.** Offsets emitted by the model; citations added after drafting; dense retrieval with a vector store, which Iteration 7 measures with reciprocal rank fusion.

**Confirmation.** `tests/test_verify.py` with the S-07 cases (every real quote accepted, none invented); `tests/test_tools.py`; the scorecard's verbatim and normalized rates.

**Reverse if.** Dense retrieval with reciprocal rank fusion beats BM25 on the hero RFP, or a quote rule rejects real obligations the scorecard shows.

**Provenance.** The approved plan; S-07 and the FTS5 checks in `docs/verification_log.md`.

### ADR-007: The solution summary first, then a proposal pack from one manifest

**Status:** accepted, 2026-11-02. The summary and a three-section proposal are built in Iteration 0a; the manifest arrives in Iteration 3 and the pack in Iteration 4.

**Context.** The assignment asks for a structured solution summary of requirements, approach and risks. A bid team then needs a solution it can defend and a proposal it can edit, and documents drafted separately drift apart.

**Decision.**
- Every run's first output is `solution_summary.md` and its JSON twin: submission hazards first, then requirements, approach, risks and open questions.
- From Iteration 3, one `SolutionManifest` is the single source for every proposal output. Each fact carries an evidence class and a source id, and a fact with no source becomes an `ASSUMPTION`. Each section stores the hash of its inputs, so a changed field marks only the sections that depend on it `STALE`.
- Risks are typed records (condition, event, effect, owner role, trigger, responses, residual exposure in words) that cite RFP passages. They carry no probabilities or ratings unless a person supplies them, and code rejects generic and rated risks.
- No prices, price-to-win or win probability. Effort estimates carry their basis and a maturity class.

**Consequences.**
- The extras never displace the assignment's output.
- A change in the manifest reaches every output the same way.
- Risks scan less easily than a rated heat map, but carry no invented precision.

**Options.** The summary alone; a free-text approach; a rated risk register.

**Confirmation.** `tests/test_render_outputs.py` (four parts, hazards first, and a schema failure blocks output); `tests/test_risk_loop.py` (generic and rated risks rejected); from Iteration 4, `test_drift_check.py` and the PR ablation.

**Reverse if.** The PR ablation shows the pack adds nothing measured, or a rating policy supplied by a person arrives.

**Provenance.** CH-01, CH-03, CH-05, CH-06, CH-14, CH-15, CH-31, CH-39 and CH-50.

### ADR-008: People decide; Bidwright drafts

**Status:** accepted, 2026-11-02. The draft labels are built in Iteration 0a; the gates arrive in Iterations 3 and 4.

**Context.** Bid decisions carry legal and commercial weight, and overstating compliance creates liability. Automated scores overstate how often people would accept an output.

**Decision.**
- The mode is `DRAFT_ONLY`: nothing is submitted, and no agent approves anything binding.
- Every output is labeled `UNREVIEWED_DRAFT` until a person signs it off.
- Two human gates: `solution_gate` approves the manifest, with its research and validation log, before drafting; `review` is the final Gold review. With no one at a gate, the run waits in `WAITING_HUMAN`. `--auto-select` exists for evaluation only, and a blocked gate is never passed automatically.
- Compliance status starts as `UNVERIFIED`, and only a person changes it. Go or no-go and the choice of solution are never automatic.

**Consequences.** Unattended runs stop at the gates, and evaluation runs record `--auto-select` in their run manifest.

**Options.** A fully automatic pipeline; one final review only.

**Confirmation.** The status line of every Iteration 0a output; `test_gate_waiting_human` in Iteration 3 and `test_review_unreviewed` in Iteration 4.

**Reverse if.** None: an owner decision.

**Provenance.** CH-04, and the plan's workflow and output contract.

### ADR-009: Tools run behind a gateway outside the model

**Status:** accepted, 2026-11-02. A minimal gateway is built in Iteration 0a; the full rules arrive in Iteration 2 and the `reflect` tool in Iteration 3.

**Context.** Instructions in a prompt cannot enforce permissions, because injected text can steer a model's tool calls. Published agent-security studies report checks at the tool layer holding where decisions made by the model were manipulated (Q-07 in `context/Research-Register.md`).

**Decision.**
- Every tool call goes through `ToolGateway`, which checks the agent's allowlist from `config/agents.yaml`, the argument schema, repeated calls and the call budget. Results are typed: `OK`, `EMPTY`, `DENIED` or `FAILED`.
- From Iteration 2, rules take the form trigger, check and outcome, where the outcome is deny, return to the model, or pause for a person. RFP and research text can never raise authorization.
- A gated `reflect` tool, backed by the sequential-thinking MCP server, is offered only after a failure signal, allows at most 2 thoughts per invocation, starts switched off, and stays only if its ablation shows a gain.

**Consequences.**
- Code stops an unauthorized call before it runs.
- Agents see denials and can recover from them.
- Reflection costs nothing while switched off.

**Options.** Allowlists alone; safety instructions in the prompt; a thinking tool offered at every step.

**Confirmation.** `tests/test_gateway.py` (an unlisted tool, bad arguments and a third identical call are denied, with an allowed call as control); `test_fi09_unauthorized`; `test_reflect_gating` in Iteration 3.

**Reverse if.** Over a release cycle, the rules catch nothing the allowlists would miss; for `reflect`, the SO1-T and RK1-T rungs show no gain.

**Provenance.** CH-26 and CH-68; Q-07.

### ADR-010: Untrusted inputs are screened before parsing, and the corpus is synthetic

**Status:** accepted, 2026-11-02. The corpus rule is built in Iteration 0a; `guard` arrives in Iteration 1.

**Context.** An RFP file can carry hidden text aimed at the model. A scan of extracted text loses the structural evidence, such as render mode, color and position, that shows the text was invisible to a reader. Free-tier prompts may be used by the provider, and the assignment forbids real client data.

**Decision.**
- `guard` runs on the raw files before any parser: size, page, path and archive limits; detection of scanned PDFs; a scan of PDF content-stream operators; scans of DOCX and XLSX XML. Hidden content is removed from the copy that is parsed and kept in a quarantine file with its location, and review shows it as possible requirements. Visible small print stays in the parsed copy and is flagged.
- Delimiters seeded from the run id around document text are hygiene, not a boundary. Injection is measured per model.
- The corpus is synthetic. The `free` profile refuses files not listed in `inputs/CORPUS.sha256` unless the run passes an explicit consent override, which its run manifest records. Research queries never carry RFP text.
- Security events carry a causal attribution class.

**Consequences.** A hidden instruction is caught before it reaches a prompt and is never deleted silently. Real documents go to the `local` profile.

**Options.** Sanitizing after parsing; removing hidden content silently; relying on delimiters; allowing any file on `free`.

**Confirmation.** `tests/test_corpus_rule.py`; from Iteration 1, `test_guard_limits`, `test_guard_quarantine`, `test_guard_scanned` and the CrackedPDFs benchmark run; QS-3.

**Reverse if.** DR-03 shows that converting Office files to PDF before the scan is the safer design.

**Provenance.** CH-36, CH-40, CH-48, CH-57, CH-64 and CH-66; DR-03 and Q-07.

### ADR-011: Model roles, families and fallbacks

**Status:** accepted, 2026-11-02. ADR-003 refines it for the free `reason` role, and ADR-004 for the `local` profile.

**Context.** Free tiers differ in quota, latency and terms, and comparisons need stable models. An assessor from the same model family as the author may share its blind spots, though published results also report errors that persist across vendors.

**Decision.**
- `config/models.yaml` maps each role to a model per profile: Gemini Flash-Lite for `extract` and, since ADR-003, `reason` on `free`, each with a Flash-Lite fallback; Ollama models on `local`.
- Assessment, critique and judging use a different model family from the generator. A failover that breaks this rule marks the run `SAME_FAMILY` and `DEGRADED`.
- The paid fallback is paid Gemini on the same model, within a budget the owner sets.
- Gemini calls send no sampling parameters. Reasoning is set with a thinking level per role and prompt.
- The ledger records the model behind every call, and the scorer flags a run that used a fallback.

**Consequences.** Comparisons stay clean. From Iteration 3, the non-Gemini roles depend on a paid or trial provider.

**Options.** Ollama Cloud as the paid fallback; one family for every role.

**Confirmation.** `tests/test_simulator.py` (the fallback, and no retry on a spent daily quota); `tests/test_config.py`; the model column of the ledger.

**Reverse if.** The SO comparison shows Flash-Lite below Flash beyond noise, or Q-04 shows that changing family does not decorrelate errors.

**Model lifetime.** No shutdown date is announced for `gemini-3.5-flash-lite`; the earliest shutdown of `gemini-3.1-flash-lite` is 2027-05-07 (read 2026-11-02).

**Provenance.** CH-10, CH-34, CH-45 and CH-60; ADR-003; V-03 in `docs/verification_log.md`.

### ADR-012: Prompts are versioned files, and method knowledge is loaded by code

**Status:** accepted, 2026-11-02. Prompts are built in Iteration 0a; method cards arrive in Iteration 3 and skills in Iteration 4.

**Context.** Prompts are code: changes must be reviewable, replayable and tied to evidence. A rendering helper that escaped braces broke exact quotes and cut a long batch short without an error.

**Decision.**
- Each prompt is a Markdown file with front matter (SemVer, role, pattern, schema, decoding per provider, `last_tested`) and a "why it works" section. Its hash covers what the model sees and its decoding, and cassette keys include it.
- One skeleton: rules, output format and examples in the system instruction; document data inside delimiters seeded from the run id; the task last, with a short reminder.
- Rendering uses `string.Template.substitute`, which raises on a missing value and leaves braces and `$` in quotes untouched.
- On `extract`, a named prompt pattern stays only if S-10 shows it beats a plain prompt.
- Method cards, 18 short method rules, are loaded by code for the prompts mapped to them, behind a flag that starts off. Each family switches on only if S-12 shows fewer violations. A rule that must always hold is enforced in code, not left to a card.

**Consequences.** A prompt change fails CI until its cassettes are re-recorded, and prompts stay lean.

**Options.** A prompt registry service; f-strings or `safe_substitute`; retrieving method cards by search.

**Confirmation.** `tests/test_prompts.py` (a missing placeholder raises, braces and `$` survive, and the same run id gives the same tags); `tests/test_cache_key.py`; S-10 and S-12.

**Reverse if.** S-10 favors a named pattern, or S-12 shows that cards help.

**Provenance.** CH-07, CH-08, CH-09, CH-11, CH-38 and CH-51.

### ADR-013: Research runs as agent tools behind a provider interface

**Status:** accepted, 2026-11-02. Built from Iteration 2.

**Context.** A solution needs domain knowledge the RFP does not state. Deep research is slow and needs a personal login, which reviewers and CI do not have, and web content is untrusted.

**Decision.**
- `discover` researches the RFP's domain through NotebookLM over MCP, behind a `ResearchProvider` interface. `techcheck` checks technology claims against current documentation through Context7.
- The default mode is `pack`: a recorded, hashed research pack, so reviewers and CI need no login. `live` runs real jobs, and `off` runs none.
- Queries are built from the brief's topics, never from RFP passages. A gateway rule denies a query that shares 8 or more consecutive words with a passage. Results are tagged `EXTERNAL_RESEARCH` and never count as evidence of what the supplier can do.
- At most 2 jobs per run, one job per notebook, and a fresh notebook per job. Delete and share tools are never exposed, and tool descriptions are pinned by hash.

**Consequences.** Research reproduces in `pack` mode; `live` mode depends on a personal login.

**Options.** A web-search API; no research.

**Confirmation.** From Iteration 2: `test_discover_fallback`, `test_fi10_poisoned_source`, `test_fi11_tool_pin`, and the outbound overlap test.

**Reverse if.** The SO4 rung shows no gain from research, or the login proves unworkable.

**Provenance.** CH-02.

### ADR-014: A separate harness scores frozen runs against known answers

**Status:** accepted, 2026-11-02. The 0a scorecard and gold v1 are built in Iteration 0a; the rest follows the roadmap.

**Context.** "It looked right" is not evaluation. No public gold corpus of whole real RFPs was found, and averaged metrics hide the single miss that disqualifies a bid.

**Decision.**
- `bidwright-eval` is a separate package. It reads frozen run artifacts and never feeds a run: `src/bidwright` never imports it, and only the `eval` service mounts gold.
- Gold comes from the YAML specs that render the synthetic RFPs, so the labels are known by construction. Each gold version is hashed before any score against it.
- The headline is missed mandatory requirements per RFP, by gold-clause coverage: relaxed capture needs a verified quote inside the clause, and strict capture also needs the cited passages to cover the clause. IoU is reported for reference only.
- Ablations climb from one-shot baselines and fixed-pipeline controls, 5 repeats per rung, under a keep-or-drop rule fixed in advance: bootstrap intervals, non-inferiority for metrics near zero, and cost reported but never gating.
- A quality scenario is either an invariant, checked on every run and in CI, or statistical, measured over repeats. A missed statistical scenario holds the tag until it passes or the owner accepts a recorded exception.
- LLM judges are calibrated against the owner's labels and stay advisory: they never gate.
- The matrix runner that drives repeats is producer code; scoring is evaluation code.

**Consequences.** Whole-pipeline scores have no outside comparison, and one author writes both corpus and prompts. The owner's held-out requirement list and the external stage benchmarks reduce, but do not remove, that bias.

**Options.** DeepEval, RAGAS or TruLens, whose generic judged metrics do not fit gold scoring at the level of spans; a hand-labeled public tender, which the data rule excludes.

**Confirmation.** `tests/test_matcher.py` and `tests/test_scorer_selftest.py` (an oracle scores 100%, removing one mandatory requirement raises misses by one, shuffling changes nothing); `tests/test_isolation.py`; `evals/gold/MANIFEST.sha256`.

**Reverse if.** A framework supports gold scoring at the level of spans, or DR-06 finds a better matching rule.

**Provenance.** CH-12, CH-13, CH-27, CH-33, CH-54, CH-56, CH-62, CH-65 and CH-67.

### ADR-015: Observability from a per-call ledger and OpenInference spans

**Status:** accepted, 2026-11-02. Built in Iteration 0a.

**Context.** The assignment asks for token, latency and cost tracing around the run. Free and local runs cost nothing, which hides what the same run would cost on a paid tier.

**Decision.**
- One `LedgerEntry` per LLM call: the model, the prompt and input hashes, four token counts (input including cached, cached, output, thinking), latency and the provider's own timings, retries, the real cost, and a shadow cost at the paid list rate of the role's shadow model. The totals in `run_manifest.json` are derived from the ledger.
- OpenTelemetry spans with OpenInference attributes for each run, node, LLM call and tool call, carrying no prompt or response text. They go over OTLP to Phoenix when it answers, and to `spans.jsonl` when it does not or when it refuses a batch.
- Phoenix rather than Langfuse: one container against six.

**Consequences.** Every run carries its own cost and timing, and free, local and paid runs compare on shadow cost.

**Options.** Langfuse; a vendor's tracing SDK.

**Confirmation.** `tests/test_ledger.py` (ledger totals match the manifest); `tests/test_tracing.py` (spans land in `spans.jsonl` without a collector, refused batches fall back, failed calls leave error spans).

**Reverse if.** Phoenix cannot export what the scorecard needs.

**Provenance.** The plan's observability design; the Phoenix 21 checks in `docs/verification_log.md`.

### ADR-016: Docker Compose, with a host path for the demo and tests

**Status:** accepted, 2026-11-02. Built in Iteration 0a.

**Context.** Reviewers may not run Docker, and Docker was down on the build machine when the plan was made, yet reproducible services still matter.

**Decision.**
- One image, built in stages with uv and run as a non-root user, serves the `app`, `eval`, `test` and `demo` services. Phoenix and Ollama run from images pinned by digest, and only loopback ports are published.
- The host path, `uv run bidwright demo` and `uv run pytest`, needs neither Docker nor keys, and CI proves it on a clean checkout.
- Gold, corpus specs, results, `private/`, `outputs/` and `.env` stay out of the image.

**Consequences.** Two run paths have to keep working, and ADR-002 makes Compose need a key even for the demo.

**Options.** The host only; Docker only.

**Confirmation.** The CI jobs `docker` and `host-path`; `tests/test_compose_lockdown.py`.

**Reverse if.** None: an owner decision.

**Provenance.** CH-35; ADR-002.

### ADR-017: Every passage reaches `extract`; cues annotate and never filter

**Status:** proposed, 2026-11-02, in `docs/designs/iteration-1.md`. It would change the plan's `candidates` step, which sent only flagged passages and a 10% sample of the rest to `extract`. The owner decides at the Stage 9 review.

**Context.** Research job DR-01 tested whether cue words flag nearly every mandatory obligation in an RFP, and refuted it. Obligations also appear as passive predicates ("is responsible for"), table cells that take their force from a header, declarative submission rules, conditions, rights the buyer reserves, cross-references and definitions. By the rule of three, a 10% sample of 600 unflagged passages, with no miss found, bounds the miss rate only below 5% at 95% confidence, which could leave dozens of obligations unseen. At this project's scale, sending every passage costs a few more calls per run: the 4-page development RFP has 37 passages, and its two extraction calls used about 2,600 input tokens each.

**Decision.**
- Every passage goes to `extract`, and each must end with a disposition, as in Iteration 0a.
- `candidates` annotates passages with cue kinds from `config/cues.yaml` (modal, prohibition, condition, right, deadline, rejection, reference, amount, date, table row) and builds the defined-term registry. `extract` sees the cues as hints.
- Cues drive B0, the rule-only baseline, and the scorecard reports cue recall as a diagnostic.
- The unflagged sample is dropped, because no passage is left unflagged for `extract`.

**Consequences.**
- No obligation can be lost by a filter before the model reads it.
- A hero run makes a few more extraction calls, and precision may fall, which the precision range shows.
- The funnel no longer charges misses to `candidates`.

**Options.** The plan's filter with a 10% sample; the filter plus a second LLM pass over all unflagged passages, the plan's fallback for a failed DR-01, which costs about as much as this decision with two prompts to maintain.

**Confirmation.** `candidates.jsonl` gives every passage a disposition; `coverage.json` reports no unaccounted passage; the scorecard's funnel shows no loss before `extract`.

**Reverse if.** Hero runs no longer fit their request limit, and cue recall on gold v2 shows a filter would lose no mandatory requirement.

**Provenance.** DR-01, read 2026-11-02; the rule-of-three bound is standard statistics, while the report's estimate of how common cue-less obligations are rests on weaker sources and is not relied on.

### ADR-018: Six zones, assigned per section, with a keyword fallback

**Status:** proposed, 2026-11-02, in `docs/designs/iteration-1.md`.

**Context.** Bid practice separates instructions, evaluation criteria and contract obligations, and only obligations survive into the contract. Zones decide hazard ordering, the compliance matrix's zone column, the second extraction pass of S-13 and, from Iteration 2, the brief. A zone per passage would need a call per batch; a zone per section needs one small call for the whole outline.

**Decision.**
- Six zones, defined in `config/zones.yaml`: `INSTRUCTION`, `EVALUATION`, `ELIGIBILITY`, `OBLIGATION`, `CONTRACT` and `BACKGROUND`.
- `triage` assigns one zone per section, with a confidence. Below 0.7, or when its output fails twice, the zone comes from heading keywords in the same file, and the run records the fallback.
- A passage takes its section's zone.

**Consequences.** A section that mixes zones gets one zone, and its passages still get their own dispositions. Adding a zone is a data change with a test, one of the rehearsed live changes.

**Options.** The plan's four zones, without `CONTRACT` and `BACKGROUND`; a zone per passage.

**Confirmation.** `test_triage.py`; the scorecard's zone accuracy against gold v2.

**Reverse if.** Zone accuracy on gold v2 is low enough that per-passage zones would change hazards or the second pass.

**Provenance.** The plan's `triage` design; the bid-practice sources in the research register.

### ADR-019: The `consolidate` cluster rule

**Status:** proposed, 2026-11-02, in `docs/designs/iteration-1.md`.

**Context.** `consolidate` resolves references, precedence, duplicates and discrepancies one cluster at a time, so the cluster rule decides what each call can see. Aggressive merging loses exceptions, and published contract work finds cross-reference recall falling when linked clauses sit far apart.

**Decision.**
- In code: clusters by document and top-level section, split above 12 members.
- Clusters are joined by addendum links, cross-references and near-duplicates (a content-word Jaccard of 0.6 or more) when the union stays within 12 members. Otherwise the linked requirements join as read-only context, at most 8.
- A cluster of one requirement with no link becomes a group in code, with no LLM call.
- The LLM may mark duplicates and discrepancies and ask questions, but no output can remove a requirement: every one appears in exactly one group.
- A discrepancy between requirements in different zones stays `conditional`.

**Consequences.** Calls stay small and bounded, singletons cost nothing, and source fidelity beats deduplication.

**Options.** Clustering by embedding similarity; one call for the whole requirement list; letting the model merge records.

**Confirmation.** `test_clusters.py`; `test_consolidate_anchors`; the scorecard's discrepancy and duplicate seeds.

**Reverse if.** Discrepancy seeds are missed because their requirements fall into different clusters that the links did not join.

**Provenance.** The plan's `consolidate` design and its failure table.

### ADR-020: Review files for quarantined text, small print and suspect passages

**Status:** proposed, 2026-11-02, in `docs/designs/iteration-1.md`. It extends ADR-010.

**Context.** `guard` removes hidden content before any model sees it, but hidden text can hold a real obligation, so a person must see it. DR-03 found that Docling, python-docx and openpyxl keep hidden content by default, and that converting Office files to PDF drops content without a record. pikepdf's documentation warns against rebuilding a PDF content stream from its parser.

**Decision.**
- `guard` writes `quarantine.jsonl`, one record per hidden item, with its kind, location and full text.
- DOCX and XLSX files are sanitized into copies, which Docling reads.
- Hidden PDF text is removed at parse time: `pdfplumber` filters the hidden characters, and the Docling path removes hidden runs from the items they overlap. The PDF itself is never rewritten.
- `render` writes `review/quarantine.md` in three sections: hidden content removed, small print kept, and visible text that reads like an instruction to a model. Each text is shown exactly, in a fenced block.
- The summary gives only counts and never repeats quarantined text.

**Consequences.** Nothing hidden reaches a prompt, and nothing is deleted without a record. The review gate of Iteration 4 reads the same file.

**Options.** Silent removal; converting Office files to PDF; rewriting PDF content streams; listing quarantined text in the summary.

**Confirmation.** `test_guard_quarantine` (every hidden kind found, absent from the parsed text, a visible control kept); the scorecard's quarantined gold clauses.

**Reverse if.** Review shows the file is not read, or a hidden kind is found that this format cannot show exactly.

**Provenance.** DR-03; the Context7 checks C7-08 to C7-10 in `docs/verification_log.md`.

### ADR-021: The compliance matrix layout

**Status:** proposed, 2026-11-02, in `docs/designs/iteration-1.md`.

**Context.** A bid manager works from a compliance matrix, often in a spreadsheet, and later iterations add response sections, delivery modes and evidence. A spreadsheet cell that starts with `=` can run as a formula when opened.

**Decision.**
- `compliance_matrix.xlsx` has three sheets. "Compliance matrix" holds one row per binding or optional requirement, hazards first, in 24 fixed columns, from the requirement id through the reviewer note. "Other records" holds the other dispositions, so a reviewer can promote one. "About" holds the run id, the status line and the column definitions.
- Columns filled by later iterations stay blank until then. Compliance status is always `UNVERIFIED`, which only a person changes.
- A CSV twin carries the first sheet.
- Cells starting with `=`, `+`, `-`, `@`, a tab or a carriage return are stored as text in the XLSX and prefixed with a single quote in the CSV.

**Consequences.** One layout from `v0.1` to the release, with no column added later, and no formula can run from RFP text.

**Options.** CSV only; a Markdown table; adding columns as iterations fill them.

**Confirmation.** `test_compliance_matrix.py`, including a quote that starts with `=`.

**Reverse if.** The owner's review of the matrix finds a column missing or unused.

**Provenance.** The plan's compliance matrix columns; OWASP guidance on CSV injection.

## Failure modes hit

Only failures that actually happened, logged as they happen. Scripted test faults never count.

| Date | Where | What failed | Trace id | Fix |
|---|---|---|---|---|
| 2026-11-02 | LLM client, `reason` role on `gemini-3.8-flash`, during S-04 | Two consecutive calls failed with a 504 ("Deadline expired") and a 503 ("high demand") after 3 retries each, so the client raised `UnrecoverableFault`. `reason` has no fallback model in 0a. | None: tracing arrives in step 11 | No code change: the retries and the fault path behaved as designed. The mitigation is the paid fallback on the same model, budgeted at the Iteration 1 exit. |
| 2026-11-02 | First live development runs, `reason` role on `gemini-3.8-flash` | In two runs, extraction on Flash-Lite finished and found all 12 gold requirements with verbatim quotes, but every `approach` call returned a 504 ("Deadline expired") on all 4 attempts, at a 60-second and then a 120-second timeout. Each run ended `UNRECOVERABLE_FAULT` with its manifest and ledger written. | None: the two runs predate tracing | The `free` call timeout is now 120 seconds. The demo cassettes were recorded on the `local` profile; recording on `free` waits until Flash answers again. |
| 2026-11-02 | `risk` agent, first complete live run on `free` | The agent searched only for requirement ids ("REQ-0011"), which match no RFP words, so all four searches came back `EMPTY`, the loop stopped for lack of progress, and every risk was rejected for citing no passage. The run produced no risks. | `outputs/20261103T011009Z-dev-rfp-3c582e4c-free/spans.jsonl` | `search_rfp` now resolves a requirement id to the passages that requirement quotes, its description says so, and the risk prompt asks for plain words or ids. Covered in `tests/test_tools.py`. |
| 2026-11-02 | `draft` node, first complete live run on `free` | All three sections failed twice and the run ended `DEGRADED`. The schema cleaner in `llm/schema.py` dropped every key named `title`, including the `title` field of `DraftResult`, so the model never returned it and validation failed. | `outputs/20261103T010756Z-dev-rfp-3c582e4c-free/spans.jsonl` | The cleaner keeps the field names under `properties`; `tests/test_provider_schema.py` covers it. The same fix applies to tool parameters. |
| 2026-11-02 | Demo recording on the `local` profile, CPU only | Extraction, approach and two risk turns finished on `qwen3.5:4b`, at 1 to 4.5 minutes per call. The third risk turn ran past the 300-second timeout on all 4 attempts, so the client moved to the fallback `qwen3.5:2b`, which was never pulled, and Ollama answered 404. The run ended `UNRECOVERABLE_FAULT` after 40 minutes. | `outputs/20261102T231703Z-dev-rfp-3c582e4c-local/spans.jsonl` | Open: thinking on a 4B model on CPU is too slow for the risk loop at this timeout. The choice between thinking off for `local`, a longer timeout and pulling the fallback is the owner's. |
| 2026-11-02 | `reason` role on the free tier, after the failed runs | A direct call to `gemini-3.8-flash` returned 429 RESOURCE_EXHAUSTED: the free daily quota was spent, much of it by retried 504 attempts, since each retry counts as a request. | None: a direct probe | Open: the free Flash quota is too small for retried live runs. The paid fallback on the same model, or waiting for the reset, is the owner's choice. Iteration 2's recovery rules should stop retrying when a quota is exhausted. |
| 2026-11-02 | `risk` agent, live development runs after ADR-003 | A risk's residual exposure opened with a rating, "Low if tested early", which the prompt's rule 5 forbids. The screen rejected only an exposure that was a bare rating word, so the register kept it. Once the screen caught it, the retry dropped that risk, the submission-portal one, instead of rewording it. | `outputs/20261103T021308Z-dev-rfp-3c582e4c-free/spans.jsonl`; the retry in `samples/dev-free/spans.jsonl` | `RATING_PHRASE` in `graph/nodes.py` now rejects an exposure that opens with a scale level or attaches one to risk or exposure, with plain-word controls in `test_risk_loop.py`. Open: a retry that drops a risk instead of fixing it, for the full `risk` agent in Iteration 3. |
| 2026-11-02 | Tracing, the Compose stack with Phoenix 21.0.0 | Phoenix 21 starts with authentication on, so every span export got 401. The run ended `COMPLETED` with no trace anywhere: once a collector answered, spans went only to it, and the exporter reported the refusal only as a failed export. Phoenix also kept its database outside the mounted volume. | None: the trace is what was lost (`outputs/20261103T021839Z-dev-rfp-3c582e4c-free`) | A batch the collector refuses now goes to `spans.jsonl` (`FallbackExporter`, tested), `PHOENIX_API_KEY` is sent as a bearer token when set, and Compose sets `PHOENIX_WORKING_DIR` and starts this loopback-only local Phoenix with authentication off, which `.env` can turn back on. |
| 2026-11-02 | Second development run on the `local` profile, with thinking on for `reason` | Extraction finished on `qwen3.5:4b` in 2m20s and 3m40s, but all 4 attempts at `approach` ran past the 300-second timeout, as did the `qwen3.5:2b` fallback's attempts, which generated over 3,000 tokens each before the cut. The run was stopped after 35 minutes, since it could only end in `UNRECOVERABLE_FAULT`. | `outputs/20261103T023031Z-dev-rfp-3c582e4c-local/spans.jsonl`; Ollama's `server.log` shows each `POST /api/chat` ending 500 after 5m0s | ADR-004: thinking off on the `local` profile. |
| 2026-11-02 | Third development run on the `local` profile, thinking off | The two extract batches went out together, but Ollama on this machine serves one request at a time, so the second waited behind the first, and the wait counted against its 300-second timeout. It timed out once; the retry, running alone, took 1m50s. | Ollama's `server.log`: one slot, and the second `POST /api/chat` ending 500 after 5m0s | `concurrency` is now set per profile in `config/limits.yaml`: 2 on `free`, 1 on `local`, with a test. |
| 2026-11-02 | LLM client, `local` profile on CPU, during S-04 | 2 of 13 calls ran past the 60-second call timeout: the first call, while the model loaded, and a 506-token final answer at about 9 tokens a second. Each was retried, and the timed-out work was lost. | None: tracing arrives in step 11 | The call timeout is now set per profile in `config/limits.yaml`: 60 seconds on `free` and 300 on `local`. |
