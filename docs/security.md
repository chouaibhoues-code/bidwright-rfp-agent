# Security: threat model

A one-page threat model for Bidwright as built at `v0.1`, with the controls planned for later iterations marked. Iteration 5 completes this document. The controls are mapped to the OWASP Top 10 for Agentic Applications (version 2026, published December 2025) and the OWASP Top 10 for LLM Applications 2025. Both lists were read at the source on 2026-11-02 (V-01 in [`verification_log.md`](verification_log.md)).

## Classification

**Medium as built:** Bidwright only drafts, runs on synthetic RFPs, and submits nothing. **High for a real deployment,** where RFPs are confidential and a missed requirement can disqualify a bid. The classification is self-assessed, because no defining standard was available to the project.

## Assets

| Asset | What a breach would mean |
|---|---|
| RFP content | Confidential in real use. Free-tier prompts may be used by the provider, so `free` takes only the synthetic corpus, unless a run passes the consent override, which its manifest records (ADR-026). |
| The requirement list and its quotes | A wrong or missing obligation can disqualify a bid |
| API keys | Spend and quota on the owner's accounts |
| Gold labels | If a producer could read them, every score would be meaningless |
| Traces | Metadata about the documents processed |
| Run folders | The document's text and every record drawn from it |

## Trust boundaries

1. **The RFP file to `ingest`:** document text is untrusted, and may carry instructions aimed at the model.
2. **The app to outside services:** on `free` and `paid`, prompts go to Gemini, whose paid tier logs prompts for a limited period but does not train on them; on `local`, nothing leaves the machine. Whole documents go only to the local Docling service, and spans only to a local collector or to `spans.jsonl`. The egress register checks every destination against the run's data class before the run starts (ADR-026).
3. **Model output to code:** every response is untrusted until it parses and passes its acceptance check ([`architecture.md`](architecture.md), section 5.4).
4. **An agent to its tools:** every call passes `ToolGateway` before it runs.
5. **Producer to evaluation:** `src/bidwright` never imports `evals`, and only the `eval` service mounts gold.
6. **The supply chain:** Python packages, container images and CI actions.

Research results become a seventh boundary in Iteration 2.

## Controls, by OWASP entry

| Threat | Control at `v0.1` | Planned | Checked by |
|---|---|---|---|
| ASI01 Agent Goal Hijack; LLM01 Prompt Injection | `guard` reads every raw file before any parser: hidden PDF text and hidden Office content, such as hidden runs and sheets, tracked deletions, comments and alternative text, are removed from the parsed copy and listed in `review/quarantine.md`; visible text that reads like an instruction is marked suspect and classified like any other. RFP text enters prompts only as data, inside delimiter tags seeded from the run id, which are hygiene and not a boundary. Agents can reach only two read-only tools, every output must fit its schema, and nothing is submitted. | Injection traps measured per model on live repeats (QS-3, at the Iteration 3 exit); render-and-compare for fonts that remap glyphs (S-06, Iteration 7); security events carry a causal attribution class | `test_guard.py`, `test_prompts.py`; the gate's trap count on the hero replay (`test_hero_replay.py`); the CrackedPDFs run |
| ASI02 Tool Misuse and Exploitation; LLM06 Excessive Agency | `ToolGateway`: the agent's allowlist, argument schemas, no third identical call, a cap of 6 calls; both tools are read-only | Rules written as trigger, check and outcome; an outbound rule that denies research queries copying RFP text (Iteration 2) | `test_gateway.py` (QS-4) |
| ASI03 Identity and Privilege Abuse | No agent holds a credential: keys stay in the client process, read from `.env`, and document text cannot raise any permission | Notebook ids for research bound by code, never supplied by the model (Iteration 2) | `test_compose_lockdown.py`; the `secrets` CI job |
| ASI04 Agentic Supply Chain Vulnerabilities; LLM03 Supply Chain | A hash-locked `uv.lock`, `pip-audit` and gitleaks in CI; container images pinned by digest; no LLM gateway library, after two compromised LiteLLM releases on 2026-03-24 | MCP tool descriptions pinned by hash (Iteration 2); `npm audit` for the pinned reflection server (Iteration 3) | The `deps` and `secrets` CI jobs |
| ASI05 Unexpected Code Execution | No tool executes code. Configuration loads with `yaml.safe_load`; model output is parsed as JSON into Pydantic models and never evaluated; prompts render with `string.Template`. `guard` refuses macro-enabled DOCX and XLSX files and reads Office XML with entity resolution and network access off. Formula-leading cells are stored as text in the XLSX and quoted in the CSV. | Unchanged | `test_config.py`, `test_prompts.py`, `test_guard.py`, `test_compliance_matrix.py` |
| ASI06 Memory and Context Poisoning; LLM04 Data and Model Poisoning | No memory carries over between runs, and no model is trained. Cassettes and the response cache return a stored response only for an identical key, and `bidwright purge` deletes a run's cache entries with its folder. Gold is hashed before any score against it. | Research packs hashed, with a poisoned-source test, FI-10 (Iteration 2) | `test_cache_key.py`, `test_cache.py`, `test_purge.py`; `evals/gold/MANIFEST.sha256` |
| ASI07 Insecure Inter-Agent Communication | Agents never talk to each other. The graph hands each role typed records that code has checked. | Unchanged | `test_e2e_replay.py` |
| ASI08 Cascading Failures | Each node's output is checked before the next node uses it; per-run budgets; one fallback per role; a spent daily quota is not retried; every failure has a defined run status | A circuit breaker and a dead-letter file (Iteration 2) | `test_simulator.py`, `test_budget.py` |
| ASI09 Human-Agent Trust Exploitation; LLM09 Misinformation | Every output is `UNREVIEWED_DRAFT`; each requirement shows its verified quote; rejected quotes are counted; risks must cite passages and carry no invented rating; every compliance status starts `UNVERIFIED` and every contract flag `NEEDS_LEGAL_REVIEW`; `review/quarantine.md` puts hidden content, small print and suspect passages before a person | Claims without evidence marked `UNVERIFIED` (Iteration 3); review gates with the source beside each record and a sample of what was not flagged (Iteration 4) | `test_verify.py`, `test_risk_loop.py`, `test_render_outputs.py`, `test_compliance_matrix.py` |
| ASI10 Rogue Agents | The graph routes every step; the `risk` loop stops at 4 turns, at 6 tool calls, or on a turn with no progress | A stop command between nodes (Iteration 2) | `test_risk_loop.py` |
| LLM02 Sensitive Information Disclosure | Each run has a data class: a file whose sha256 is not listed in `inputs/CORPUS.sha256` is a client document. `free` refuses client documents unless the run passes the consent override, which the manifest records. A client document's ids come from its hash, so its name reaches no run id, span or folder name, and client documents must sit under a data root outside the repository. The egress register checks every model backend, the trace endpoint and the parser before a run: a client run reaches only local destinations, except Gemini on a `free` run that passed the consent override. Every prompt and tool result is built through the text view. `bidwright purge --expired` deletes client runs past a 30-day retention period. Spans carry hashes and counts, never prompt or response text, and planted personal data is tested never to reach a span, the ledger, the manifest or a log. Keys stay in `.env`; `private/` and `outputs/` are gitignored. | Metadata-only traces for real documents; the AI-use disclosure (Iteration 4); masking through the text view, with a hosted path under client terms (Iteration 5) | `test_preflight.py`, `test_corpus_rule.py`, `test_egress.py`, `test_text_view.py`, `test_purge.py`, `test_privacy_invariant.py`, `test_tracing.py`, `test_repo_hygiene.py` |
| LLM05 Improper Output Handling | Every response is validated against its schema; quotes, and the numbers and dates in each statement, are verified against the cited passages; `render` validates every record before writing; search terms from a model are stripped of FTS5 operators and quoted; formula-leading cells are stored as text in the XLSX and quoted in the CSV | Unchanged | `test_tools.py`, `test_verify.py`, `test_render_outputs.py`, `test_compliance_matrix.py` |
| LLM07 System Prompt Leakage | The prompts are public in the repository and hold no secret | Unchanged | Inspection |
| LLM08 Vector and Embedding Weaknesses | Not applicable: retrieval is lexical | Reassessed if Iteration 7 adds dense retrieval | None |
| LLM10 Unbounded Consumption | `guard`'s limits on file size, pages, files per package and archive expansion, checked before parsing; per-run limits on requests, tokens and active time; a per-call timeout; 3 retries; loop caps; concurrency per profile; a limiter on each model's per-minute limits and, on `paid`, its daily limit | Full budget controller (Iteration 2) | `test_guard.py`, `test_budget.py`, `test_limiter.py`, `test_risk_loop.py` |

## Evidence behind the design

Q-07 ([`context/Research-Register.md`](../context/Research-Register.md), section 7) found that prompt-layer defenses such as delimiters reduce indirect injection without removing it, and that the effect varies by model. Controls outside the model held where model decisions were manipulated. So delimiters stay as hygiene, and the weight sits on screening before parsing, the gateway, least privilege and `DRAFT_ONLY`. CrackedPDFs, confirmed at source, shows why screening must read the PDF's structure. Its hybrid structural detector reached F1 0.960 on held-out PDFs, against 0.623 for a rule baseline and 0.390 for PromptGuard on extracted text alone. On the same test split, `guard`'s PDF scan flagged every injected file and every benign file built to hide harmless text the same way, and no untouched original (F1 0.667, [`evaluation.md`](evaluation.md)): it detects hidden text, not intent, which is why a flagged file goes to a person's review instead of being rejected.

## Residual risks at `v0.1`

- `guard` reads a PDF's drawing operations, not the rendered page, so a font that maps glyphs to other characters escapes it; and on the Docling path, a hidden word that repeats a visible word earlier in the same item removes the visible one instead ([`architecture.md`](architecture.md), section 11).
- The egress register treats `ollama`, `phoenix`, `docling` and `host.docker.internal` as local everywhere, though they name this machine only inside a container. On the host, a Compose address copied into `.env` could send a client run's documents or prompts to another computer while the register calls it local. D-06 decides the fix before the first run on client documents.
- The consent override lets a client document run on `free`, against the free tier's terms; the owner accepted that risk (ADR-026), and the manifest records each use.
- A paraphrased injection can still steer what an agent writes inside its schema; only measurement per model (QS-3) shows how often.
- CI actions are pinned by version tag, not by commit hash.
- Human review is subject to fatigue and automation bias, which DR-08 studies before the review interface is built.
