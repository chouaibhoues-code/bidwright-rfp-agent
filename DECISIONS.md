# Decisions

Architecture and product decisions, recorded as short ADRs, and the failure modes hit while building, with their fixes. Process decisions live in the Master-Plan change log in `context/Master-Plan.md`, from Iteration 0b.

## ADR format

Each ADR gives:
- a number and title, and its status: `proposed`, `accepted` or `superseded`;
- context, decision and consequences;
- one line each for the options considered, the confirmation test, the reverse-if condition and the provenance.

Model and prompt ADRs also give the evaluation evidence and the model's expected lifetime. A rationale must make sense without private sources.

## ADRs

Decisions made while building are recorded here as they are made. The planning change log becomes ADRs in Iteration 0b.

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
| 2026-11-02 | LLM client, `local` profile on CPU, during S-04 | 2 of 13 calls ran past the 60-second call timeout: the first call, while the model loaded, and a 506-token final answer at about 9 tokens a second. Each was retried, and the timed-out work was lost. | None: tracing arrives in step 11 | The call timeout is now set per profile in `config/limits.yaml`: 60 seconds on `free` and 300 on `local`. |
