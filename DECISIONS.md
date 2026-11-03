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

## Failure modes hit

Only failures that actually happened, logged as they happen. Scripted test faults never count.

| Date | Where | What failed | Trace id | Fix |
|---|---|---|---|---|
| 2026-11-02 | LLM client, `reason` role on `gemini-3.8-flash`, during S-04 | Two consecutive calls failed with a 504 ("Deadline expired") and a 503 ("high demand") after 3 retries each, so the client raised `UnrecoverableFault`. `reason` has no fallback model in 0a. | None: tracing arrives in step 11 | No code change: the retries and the fault path behaved as designed. The mitigation is the paid fallback on the same model, budgeted at the Iteration 1 exit. |
| 2026-11-02 | First live development runs, `reason` role on `gemini-3.8-flash` | In two runs, extraction on Flash-Lite finished and found all 12 gold requirements with verbatim quotes, but every `approach` call returned a 504 ("Deadline expired") on all 4 attempts, at a 60-second and then a 120-second timeout. Each run ended `UNRECOVERABLE_FAULT` with its manifest and ledger written. | None: the two runs predate tracing | The `free` call timeout is now 120 seconds. The demo cassettes were recorded on the `local` profile; recording on `free` waits until Flash answers again. |
| 2026-11-02 | Demo recording on the `local` profile, CPU only | Extraction, approach and two risk turns finished on `qwen3.5:4b`, at 1 to 4.5 minutes per call. The third risk turn ran past the 300-second timeout on all 4 attempts, so the client moved to the fallback `qwen3.5:2b`, which was never pulled, and Ollama answered 404. The run ended `UNRECOVERABLE_FAULT` after 40 minutes. | `outputs/20261102T231703Z-dev-rfp-3c582e4c-local/spans.jsonl` | Open: thinking on a 4B model on CPU is too slow for the risk loop at this timeout. The choice between thinking off for `local`, a longer timeout and pulling the fallback is the owner's. |
| 2026-11-02 | `reason` role on the free tier, after the failed runs | A direct call to `gemini-3.8-flash` returned 429 RESOURCE_EXHAUSTED: the free daily quota was spent, much of it by retried 504 attempts, since each retry counts as a request. | None: a direct probe | Open: the free Flash quota is too small for retried live runs. The paid fallback on the same model, or waiting for the reset, is the owner's choice. Iteration 2's recovery rules should stop retrying when a quota is exhausted. |
| 2026-11-02 | LLM client, `local` profile on CPU, during S-04 | 2 of 13 calls ran past the 60-second call timeout: the first call, while the model loaded, and a 506-token final answer at about 9 tokens a second. Each was retried, and the timed-out work was lost. | None: tracing arrives in step 11 | The call timeout is now set per profile in `config/limits.yaml`: 60 seconds on `free` and 300 on `local`. |
