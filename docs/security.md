# Security: threat model

A one-page threat model for Bidwright as built at `v0.2`, with the controls planned for later iterations marked. Iteration 5 completes this document. The controls are mapped to the OWASP Top 10 for Agentic Applications (version 2026, published December 2025) and the OWASP Top 10 for LLM Applications 2025. Both lists were read at the source on 2026-11-02 (V-01 in [`verification_log.md`](verification_log.md)).

## Classification

**Medium as built:** Bidwright only drafts, runs on synthetic RFPs, and submits nothing. **High for a real deployment,** where RFPs are confidential and a missed requirement can disqualify a bid. The classification is self-assessed, because no defining standard was available to the project.

## Assets

| Asset | What a breach would mean |
|---|---|
| RFP content | Confidential in real use. Free-tier prompts may be used by the provider, so `free` takes only the synthetic corpus, unless a run passes the consent override, which its manifest records (ADR-026). |
| The requirement list and its quotes | A wrong or missing obligation can disqualify a bid |
| API keys | Spend and quota on the owner's accounts |
| The NotebookLM login | A cookie-based login on the owner's personal Google account, held by the NotebookLM server on the host, which can also delete and share the owner's notebooks |
| Gold labels | If a producer could read them, every score would be meaningless |
| Research packs | Committed web research that a run's appendix shows; a changed pack would change what every run in its domain reports |
| Traces | Metadata about the documents processed |
| Run folders | The document's text and every record drawn from it |

## Trust boundaries

1. **The RFP file to `ingest`:** document text is untrusted, and may carry instructions aimed at the model.
2. **The app to outside services:** on `free` and `paid`, prompts go to Gemini, whose paid tier logs prompts for a limited period but does not train on them; on `local`, nothing leaves the machine. Whole documents go only to the local Docling service, and spans only to a local collector or to `spans.jsonl`. The egress register checks every destination against the run's data class before the run starts (ADR-026).
3. **Model output to code:** every response is untrusted until it parses and passes its acceptance check ([`architecture.md`](architecture.md), section 5.4).
4. **An agent to its tools:** every call passes `ToolGateway`'s checks and rules before it runs.
5. **Producer to evaluation:** `src/bidwright` never imports `evals`, and only the `eval` service mounts gold.
6. **The supply chain:** Python packages, container images, CI actions, and the pinned NotebookLM server package.
7. **Research, from Iteration 2:** in research mode `live`, queries leave for Google through the NotebookLM server, and its reports, answers and excerpts come back as untrusted web data. The server runs on the host, bound to loopback, only during live sessions; the egress register treats it as remote whatever its host, so a client run with research mode `live` is refused before its folder exists, and a stdio server entry is refused on every run (section 4.5 of [`designs/iteration-2.md`](designs/iteration-2.md)).

## Controls, by OWASP entry

| Threat | Control at `v0.2` | Planned | Checked by |
|---|---|---|---|
| ASI01 Agent Goal Hijack; LLM01 Prompt Injection | `guard` reads every raw file before any parser: hidden PDF text and hidden Office content are removed from the parsed copy and listed in `review/quarantine.md`; visible text that reads like an instruction is marked suspect. RFP text enters prompts only as data, inside delimiter tags seeded from the run id. The `brief` and `discover` prompts tell the model that a passage addressing it states nothing a bid must do (both changed after a live failure, `DECISIONS.md`, failure modes). Every research excerpt, answer and report paragraph is screened with the same suspect patterns: a suspect excerpt is quarantined, a suspect answer's text withheld, and a suspect paragraph removed, each with a security event attributed `injection-dominant`; a research pack is screened again each time it loads. The `discover` model never sees RFP passages, only the brief's topics, which code has checked. | Injection traps measured per model on live repeats (QS-3, at the Iteration 3 exit); render-and-compare for fonts that remap glyphs (S-06, Iteration 7) | `test_guard.py`, `test_prompts.py`, FI-10 in `test_pack.py`, `test_discover.py`; the gate's trap count on the hero replay; the CrackedPDFs run |
| ASI02 Tool Misuse and Exploitation; LLM06 Excessive Agency | `ToolGateway`: the agent's allowlist, argument schemas that refuse unknown keys, no third identical call, the call cap, then five rules written as trigger, check and outcome (ADR-032): G2 refuses an argument that names a notebook, task or source or holds an id; G4 a server whose tools did not match their pins; G1 a third research job or a second in one turn; G5 a seventh question; and G3 a query sharing 8 or more consecutive normalized words with a passage. A denial goes back to the model; a security event records G2 and G3 denials with their attribution. Research tools create only their own notebooks; delete and share tools are never listed. | Gated `reflect` (Iteration 3) | `test_gateway.py` (QS-4, FI-09), `test_outbound_rule_denies_every_copied_passage` |
| ASI03 Identity and Privilege Abuse | No agent holds a credential: keys stay in the client process, read from `.env`. Notebook and task ids are bound by code from `research.json`, never supplied by the model, and `start_research` returns a label, `J1` or `J2`. | Unchanged | `test_compose_lockdown.py`; the `secrets` CI job; G2 tests |
| ASI04 Agentic Supply Chain Vulnerabilities; LLM03 Supply Chain | A hash-locked `uv.lock`, `pip-audit` and gitleaks in CI; container images pinned by digest; no LLM gateway library. The NotebookLM server package is pinned at 0.15.8, audited in CI from `config/mcp_servers.txt`, and its six tools are pinned by the hash of their names, descriptions and schemas: a changed tool refuses the server (FI-11). | `npm audit` for the pinned reflection server (Iteration 3) | The `deps` and `secrets` CI jobs; `test_mcp_client.py` |
| ASI05 Unexpected Code Execution | No tool executes code. Configuration and pack manifests load with `yaml.safe_load`; model output is parsed as JSON into Pydantic models and never evaluated; prompts render with `string.Template`. `guard` refuses macro-enabled Office files and reads Office XML with entity resolution and network access off. Formula-leading cells are stored as text in the XLSX and quoted in the CSV. | Unchanged | `test_config.py`, `test_prompts.py`, `test_guard.py`, `test_compliance_matrix.py` |
| ASI06 Memory and Context Poisoning; LLM04 Data and Model Poisoning | No memory carries over between runs. Cassettes, the response cache and the run journal return a stored response only for an identical key. A research pack's `pack.yaml` holds the hash of each file, and `load_pack` refuses a pack whose files changed or that names what it lacks; each run records the hash of the pack it loaded. A pack leaves out quarantined text, sources the restricted-name check flags and sources the operator names, such as a published tender, and an entry that shares no word with the excerpts it cites is dropped (`DECISIONS.md`, failure modes). | Unchanged | `test_pack.py` (FI-10 and the tampered-file refusal), `test_builder.py`, `test_cache.py`, `test_resume.py` |
| ASI07 Insecure Inter-Agent Communication | Agents never talk to each other. The graph hands each role typed records that code has checked. | Unchanged | `test_e2e_replay.py` |
| ASI08 Cascading Failures | Each node's output is checked before the next node uses it; per-run budgets; a circuit breaker opens for 30 minutes after 5 consecutive failures on one model and tier, or on the research server; a dead-letter file holds what a node gave up on; a research failure in a live node falls back to the research pack and ends the run `DEGRADED`. | Unchanged | `test_recovery.py` (FI-01, FI-02), `test_discover.py` |
| ASI09 Human-Agent Trust Exploitation; LLM09 Misinformation | Every output is `UNREVIEWED_DRAFT`; each requirement shows its verified quote; risks cite passages and carry no invented rating. Domain research appears only in an appendix marked external and unverified, each item with its sources and their authority tiers. | Claims without evidence marked `UNVERIFIED` and `assess` on research items (Iteration 3); review gates (Iteration 4) | `test_verify.py`, `test_render_outputs.py` |
| ASI10 Rogue Agents | The graph routes every step; agent loops stop at their turn and call caps or on a turn with no progress. `bidwright stop` drains a run between steps, and a stop request is checked before every research poll. | Unchanged | `test_resume.py`, `test_discover.py` |
| LLM02 Sensitive Information Disclosure | As at `v0.1` (data classes, the egress register, purge, hashed ids for client documents, spans without text, planted personal data tested never to reach a span, ledger, manifest or log). Research queries are built from the brief's topics, which code checks for copied text, and G3 checks every query again; a client run gets no live research. | Metadata-only traces for real documents; masking through the text view (Iteration 5) | `test_preflight.py`, `test_egress.py`, `test_privacy_invariant.py`, `test_gateway.py` |
| LLM05 Improper Output Handling | Every response is validated against its schema; quotes, numbers and dates are verified against the cited passages; `render` validates every record before writing. | Unchanged | `test_tools.py`, `test_verify.py`, `test_render_outputs.py` |
| LLM07 System Prompt Leakage | The prompts are public in the repository and hold no secret | Unchanged | Inspection |
| LLM08 Vector and Embedding Weaknesses | Not applicable: retrieval is lexical, and research packs are scanned on content stems | Reassessed if Iteration 7 adds dense retrieval | None |
| LLM10 Unbounded Consumption | `guard`'s file limits; per-run limits on attempts, tokens and active time, kept across stop and resume, with a logged raise; a wait cap on each research job; limiters on each model's limits | Unchanged | `test_budget.py`, `test_limiter.py`, `test_supervisor.py` |

## Run control

`RunSupervisor` (ADR-031) takes an exclusive lock on `control/run.lock` for each part of a run, records every status in the manifest and `events.jsonl`, and refuses a resume of a finished run, a run that predates `v0.2`, a run in `record` or `replay` mode, one started in another environment, one whose prompts or input files changed, and a profile change other than `free` to `paid` after a spent quota. A resume cuts a line a kill left unfinished from each line file before appending to it. Locks taken on the host and in a container do not see each other on the bind-mounted `outputs/`, so a run records where it started and is resumed only there; a container run is resumed only after its container has exited.

## Evidence behind the design

Q-07 ([`context/Research-Register.md`](../context/Research-Register.md), section 7) found that prompt-layer defenses such as delimiters reduce indirect injection without removing it, and that the effect varies by model. Controls outside the model held where model decisions were manipulated. So delimiters stay as hygiene, and the weight sits on screening before parsing, the gateway, least privilege and `DRAFT_ONLY`. CrackedPDFs, confirmed at source, shows why screening must read the PDF's structure ([`evaluation.md`](evaluation.md)).

## Reviews at `v0.2`

A security review of the Iteration 2 changes (`v0.1` to `v0.2`) on 2026-11-05 found no vulnerability at high confidence. It traced file paths, the gateway's rules, deserialization, secrets and the research server as an untrusted party. It noted two weaknesses without a security impact, listed below. A code review at medium effort the same day raised ten findings, eight fixed before the tag (the commit of 2026-11-05 "fix the code review's findings").

## Residual risks at `v0.2`

- `guard` reads a PDF's drawing operations, not the rendered page, so a font that maps glyphs to other characters escapes it ([`architecture.md`](architecture.md), section 11).
- The egress register treats `ollama`, `phoenix`, `docling` and `host.docker.internal` as local everywhere, though they name this machine only inside a container (D-06, deferred).
- The consent override lets a client document run on `free`, against the free tier's terms; the owner accepted that risk (ADR-026), and the manifest records each use.
- A paraphrased injection can still steer what an agent writes inside its schema; only measurement per model (QS-3) shows how often.
- G3 stops a copied passage, not a paraphrase: on the outbound test set it let through no verbatim copy, no lightly edited copy, and every paraphrase ([`evaluation.md`](evaluation.md)). Short identifying phrases in topics are not detected; a client run gets no live research.
- In research mode `live`, a source the web search finds, such as a published tender, reaches the extraction prompt before anyone sees it; only the pack builder leaves such a source out (D-08).
- A research pack's hashes sit in its own `pack.yaml`, so they catch a file that changed by accident, not a pack rewritten on purpose; packs change only by reviewed commits.
- Research items, answers and source titles are written into `solution_summary.md` without Markdown escaping; the summary is a draft read by people, and nothing acts on it.
- G2 refuses a run of 30 or more letters, digits, hyphens and underscores, so a long hyphenated phrase in a question is denied as an id, with a security event; this false positive is accepted by ADR-032.
- A `research_status` error result fails the job, since the server has no failed state, so one transient error sends a live run to its research pack.
- The NotebookLM login is a personal cookie session, acceptable for synthetic research only; the server also offers delete and share tools to any local client while it runs.
- CI actions are pinned by version tag, not by commit hash.
- Human review is subject to fatigue and automation bias, which DR-08 studies before the review interface is built.
