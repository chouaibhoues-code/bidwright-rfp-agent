---
title: Research Register
type: register
applies-to: bidwright
related: ["[[Master-Plan]]", "[[Decision-Form]]", "[[Project-Backlog]]"]
date: 2026-11-02
status: current
tags: [bidwright, research, validation, register]
---

# Research Register

> [!info] What this holds
> The research behind Bidwright's design: deep research jobs, documentation checks, spikes, queries, environment checks, and what each changed. Findings are [T] team documents until checked at their source. A figure enters a deliverable only after V-01 checks it in the primary paper, so this register states unchecked findings in words and quotes only figures confirmed at source.

Raw reports, notebook answers and research envelopes are kept privately, outside the repository. The owner's NotebookLM notebooks are private to the owner's account, so this register names notebooks and never links them.

## 1. How research runs

- A job launches only if a plausible answer would change a named decision.
- Each deep research job runs in a fresh notebook, with one job per notebook. A follow-up on the same assumption may reuse its notebook, with the reason recorded.
- Queries name topics, never documents, and never carry RFP or corpus text.
- The launch envelope is adversarial for a high-severity assumption: it asks for evidence that refutes the assumption first, then the strongest evidence in favor. Sources are limited to canonical and academic material unless a job notes otherwise.
- Reports run unattended and are read at iteration boundaries. Every figure planned for quoting gets a number audit (H-01) and a check in the primary paper (V-01).
- Dates are ISO 8601.

## 2. Research log

| Date | ID | Notebook | Topic | Decision it controls | Status |
|---|---|---|---|---|---|
| 2026-10-30 | G-RFP-20261030-001 | RFP SOTA, Real-Tender Evaluation Gap | Whether benchmark results transfer to whole real RFPs | The headline metric and the recall-first design | Complete, 60 sources, audited |
| 2026-11-01 | DR-19a | RFP SOTA, DR-19 Agentic Architecture Method | The architecture method for a small agentic LLM system | The elements of the architecture method | Complete, 51 sources, audited |
| 2026-11-01 | DR-19b | The same notebook, reused for a follow-up on the same assumption | Reference architectures, pattern catalogs, agent specification languages, model-based systems engineering | The same | Complete, 49 sources, audited |
| 2026-11-02 | DR-01 | RFP SOTA, DR-01 Cue Recall for Obligations | Cue-word recall for mandatory obligations in whole RFPs | Whether `candidates` gets an LLM recall pass over unflagged passages | Complete, 56 sources; read 2026-11-02 for the Iteration 1 design |
| 2026-11-02 | DR-03 | RFP SOTA, DR-03 Office Hidden Content | Hidden content and injection in DOCX and XLSX | The Office scans in `guard`, or conversion to PDF first | Complete, 65 sources; read 2026-11-02 for the Iteration 1 design |
| 2026-11-02 | DR-16 | RFP SOTA, DR-16 Prompting 2026 Reasoning Models | Prompt patterns, context order and constraint rules on 2026 reasoning models | Prompt simplification and the "why it works" notes | Complete, 41 sources; read 2026-11-02 for the Iteration 1 design |
| 2026-11-02 | DR-17 | RFP SOTA, DR-17 Sectioned Drafting and LLM Evaluators | Section-by-section drafting and the validity of LLM evaluators | Drafting granularity; whether Red Team ratings are shown | Complete, 60 sources; read in Iteration 4 |
| 2026-11-02 | Q-07 | L1 Prompt, L2 Context, HNS Runtime Harness | What prompt-layer and tool-layer defenses stop | The threat model in `docs/security.md` | Answered; section 7 |
| 2026-11-03 | Q-11 | RFP SOTA, EY FDE & Enterprise AI Consulting (the owner's notebook) | The FDE role, EY's governance material for AI, and vendor architecture guidance | CH-74; `docs/brief.md` and `docs/governance.md` | Answered; the claims used were read at source |
| 2026-11-03 | DR-20 | RFP SOTA, DR-20 Personal data detection and pseudonymization | Detection and pseudonymization of personal data before LLM calls, and leak paths in agentic pipelines | D-05 | Complete, 49 sources, 30 cited imported; section 17 |
| 2026-11-03 | DR-21 | RFP SOTA, DR-21 Tender confidentiality and LLM providers | Data protection, tender confidentiality and provider terms for sending tender documents to LLM services | D-05 | Complete, 33 sources, 27 cited imported; section 17 |
| 2026-11-03 | DR-05 | RFP SOTA, DR-05 Judged Rubrics for Plans, WBS and Risks | Whether an LLM-judged rubric validly scores a generated approach, work breakdown structure and risk register | Whether the solution and proposal quality layers rest on judged rubrics or on structural checks plus human rating | Launched 2026-11-03 in deep mode, adversarial envelope; read in Iteration 3 |
| 2026-11-03 | DR-18 | RFP SOTA, DR-18 Local Government Case Management Domain | The patterns, standards and pitfalls of local-government digital case-management services and their procurement | The first research pack, which `discover` loads in `pack` mode | Launched 2026-11-03 in deep mode, balanced envelope; read in Iteration 2 |

## 3. Deep research jobs

| ID | Assumption under test | What changes if it fails | Priority | When |
|---|---|---|---|---|
| DR-19 | Established architecture methods, lightly extended, are sufficient and proportionate for a small agentic LLM system | Elements of the architecture method change or are dropped | High | Done 2026-11-01 |
| DR-01 | Code cues flag nearly every mandatory obligation in a whole RFP | `candidates` gets an LLM recall pass over unflagged passages, beyond the planned sample | High | Read 2026-11-02: refuted; ADR-017, proposed, sends every passage to `extract` |
| DR-03 | A guard that scans only PDF structure is enough, though two corpus RFPs are DOCX | The DOCX and XLSX scans grow, or every file converts to PDF before `guard` | High | Read 2026-11-02: refuted; per-format scans and sanitized copies in the Iteration 1 design, ADR-010 confirmed |
| DR-20 | Detection of personal data plus reversible pseudonymization before LLM calls protects personal data in business documents without hurting extraction | Whether detection may gate routing, and whether to pseudonymize before hosted calls | High | Done 2026-11-03: refuted; section 17 |
| DR-21 | A bidder may send confidential tender documents with personal data to a third-party LLM API under a processor agreement, with no training, regional processing and short retention; pseudonymizing first lightens the bidder's duties | Which providers and tiers may receive a client document; whether pseudonymization has legal value | High | Done 2026-11-03: partly refuted; section 17 |
| DR-16 | Prompt patterns, context-order rules and constraint-style rules hold on 2026 reasoning models and outside coding tasks | Prompts get simpler, patterns are dropped, and the "why it works" notes cite current evidence | High | Read 2026-11-02: positive directives, correct-output examples and zero-shot baselines; `extract@0.3.0` and the S-10 change in the Iteration 1 design |
| DR-17 | Section-by-section drafting from a structured manifest stays grounded and specific, and LLM evaluator simulation tracks how people score proposals | Drafting granularity, and whether Red Team ratings are shown or only its findings | High | Launched 2026-11-02; read in Iteration 4 |
| DR-18 | Domain discovery for the hero RFP's domain: the patterns, standards and pitfalls a bid should cover | Becomes the first research pack. It feeds the pack only: research seeds come from an independent source, so the gain with research is not built in. | High | Launched 2026-11-03 (Iteration 1, step 1); read in Iteration 2 |
| DR-05 | A judged rubric can validly score a generated approach, WBS and risks | The solution and proposal move to structural checks plus human rating | High | Launched 2026-11-03 (Iteration 1, step 1); read in Iteration 3 |
| DR-02 | Batching many candidates in one request loses nothing | Smaller batches and more requests, with capacity and budget recomputed | High | Only if S-03 is inconclusive |
| DR-04 | Docling keeps multi-column and nested-table text exact enough for quote checks | Swap the parser or add a fallback | High | Only if S-01 is inconclusive |
| DR-06 | "One obligation per record" has a defensible boundary and scoring rule | The gold format and the matcher | Medium | Only if matching disputes appear in Iteration 1 |
| DR-07 | Agentic steps beat a fixed pipeline on document work | `decide` shrinks, and the defense gets stronger either way | Medium | Iteration 5, beside the ablation that measures it |
| DR-09 | A few RFPs support inference, and few labels can correct judge error | Ablation statistics and calibration size | Medium | Iteration 5, before the full ablations |
| DR-12 | Commercial RFP tools leave the gap the project claims; sources unfiltered, because this job needs vendor material, and findings only describe the market | `docs/product.md` positioning | Low | Iteration 5 |
| DR-08 | Review with a sample of the negative space catches omissions | Review UI and review-health metrics | Medium | Before Iteration 6 |
| DR-10 | Synthetic RFPs stress the pipeline like real packages | Stated limits, and the third RFP's design | Medium | Before Iteration 6 |
| DR-11 | Models under 4 GB can run tool loops | The bake-off suite and what `local` may do | Medium | Before Iteration 6 |
| DR-14 | A curated capability library supports verifiable claims | The knowledge base's shape and `assess` evidence rules | Low | Backlog |
| DR-15 | English-only is acceptable | Language scope, which the assignment does not set | Low | Backlog, unless non-English briefs are expected |

**DR-19 record.** Gap `G-RFP-20261101-001`, severity high: two deep adversarial jobs on 2026-11-01, canonical and academic sources, 75 sources imported. The second job reused the notebook because it followed up the same assumption: the first report skipped reference architectures, pattern catalogs, specification languages and model-based systems engineering.

**DR-19 result.** The method was not refuted, and seven changes went in (section 14). Both reports were audited against the papers.
- **Errors found:** the wrong ADR fields for RAD-AI; a count of EU AI Act Annex IV requirements where the annex lists categories; every ISO/IEC 25059 change called new, when one is a modification; RAD-AI said to "prove" audit failure, when it reports a preliminary six-rater score; and return-on-investment thresholds for model-based systems engineering that are the report's own extrapolation.
- **Source rules broken:** vendor blogs back several "high strength" claims in the first report, so no figure comes from either report without a paper check.
- **Best evidence:** AgentSpec is peer-reviewed at ICSE, but its authors ran the evaluation and did not test prompt injection. AgentArcEval, the architecture-options taxonomy, EPIC, Beyond Component Testing and the ADR template study are preprints.
- **Not adopted:** RAD-AI's seven ADR fields, which target classical ML; the reports' numeric acceptance thresholds, which have no basis here; LLM judges as CI gates, which 40 labels cannot support; and MAESTRO, reference architectures, model-based systems engineering, spec-driven toolkits and guardrail classifiers, which show no measured benefit at this size.

## 4. Context7 groups

About 90 one-sentence technical claims, each checked just before the module that needs it, with results in `docs/verification_log.md`.

| ID | Scope | Library IDs | Claims | When | Status |
|---|---|---|---|---|---|
| C7-01 | Gemini structured output, thinking defaults by model, cached usage, ignored sampling parameters; also read Google's 3.6 and 3.5 Flash-Lite guide directly | `/googleapis/python-genai`, `/websites/googleapis_github_io_python-genai` | 8 | 0a | Done 2026-11-02 |
| C7-04 | Ollama `format` with `think`, `num_ctx`, usage fields, memory | `/llmstxt/ollama_llms-full_txt`, `/ollama/ollama-python`, `/websites/ollama_api` | 7 | Basics in 0a, full in 6 | Basics done 2026-11-02; full in Iteration 6 |
| C7-05 | OpenAI SDK raw headers, retries, `base_url`, parse helper | `/openai/openai-python` | 4 | 0a | Done 2026-11-02 |
| C7-06 | LangGraph `Send`, interrupts, durability, policies, concurrency, stopping a run between nodes, fork issue #6663 | `/websites/langchain_oss_python_langgraph`, `/langchain-ai/langgraph` | 11 | 0a, with stop and interrupts rechecked in 2 | Done 2026-11-02 |
| C7-07 | Pydantic schema output, `$ref` inlining, field order | `/pydantic/pydantic` | 5 | 0a | Done 2026-11-02 |
| C7-11 | SQLite FTS5 tokenizers, `bm25()` weights, query escaping | `/websites/sqlite_docs` | 4 | 0a | Done 2026-11-02 |
| C7-12 | Phoenix, OpenInference, `gen_ai.*`, flush on exit, hiding prompt content | `/websites/arize_phoenix`, `/arize-ai/phoenix`, `/arize-ai/openinference`, `/open-telemetry/semantic-conventions` | 8 | 0a | Done 2026-11-02, with the Phoenix 21 checks |
| C7-13 | Compose profiles, watch, `gpus`, healthchecks, and `${VAR:?}` with unset or empty variables; uv in Docker | `/docker/compose`, `/websites/docker_compose`, `/astral-sh/uv`, `/astral-sh/uv-docker-example` | 8 | 0a | Done 2026-11-02 |
| C7-08 | docling-serve options, provenance, tables, DOCX and XLSX input | `/docling-project/docling-serve`, `/docling-project/docling` | 6 | 1 | Endpoint, options and document structure done 2026-11-02; the rest at the build |
| C7-09 | pikepdf operators, pdfplumber chars, ReportLab hidden text | `/pikepdf/pikepdf`, `/jsvine/pdfplumber`, `/websites/reportlab` | 3 | 1 | pikepdf and pdfplumber done 2026-11-02; ReportLab at the build |
| C7-10 | python-docx and openpyxl hidden content | `/python-openxml/python-docx`, `/websites/openpyxl_readthedocs_io_en_stable` | 3 | 1 | Hidden runs and sheet states done 2026-11-02; writing formula-safe cells at the build |
| C7-14 | Hypothesis strategies and CI setup; Streamlit selection and fragments | `/websites/hypothesis_readthedocs_io_en`, `/astral-sh/setup-uv`, `/streamlit/docs` | 5 | Hypothesis in 1, Streamlit in 6 | Planned |
| C7-16 | MCP Python client over streamable HTTP and stdio: `Client`, `list_tools`, `call_tool`, headers and timeouts | `/modelcontextprotocol/python-sdk` | 5 | 2 | Planned |
| C7-17 | The reference sequential-thinking server: the `sequentialthinking` tool schema, stdio launch, `DISABLE_THOUGHT_LOGGING` | `/modelcontextprotocol/servers` | 3 | Checked 2026-11-02; rechecked at version lock in 2 | Done 2026-11-02 |
| C7-02 | Cerebras schema limits, tools, caching, rate headers, prompting guidance for `gpt-oss` and Qwen | `/websites/inference-docs_cerebras_ai`, `/cerebras/cerebras-cloud-sdk-python` | 5 | 3 | Planned |
| C7-03 | Groq schema, tools, rate headers | `/websites/console_groq`, `/groq/groq-python` | 3 | 3 | Planned |
| C7-15 | python-docx generation: styles, tables, headers, page control; python-pptx for the deck | Not yet resolved | 4 | 4 | Planned |
| C7-18 | Masking libraries: LangChain's PII middleware and its integrations list; Presidio's reversible sample and its recognizers backed by language models; LlamaIndex's PII postprocessors; DSPy's PAPILLON tutorial | `/websites/langchain_oss_python`, `/data-privacy-stack/presidio`, `/run-llama/llama_index`, `/stanfordnlp/dspy` | 5 | 0b, for D-05 | Done 2026-11-03 (section 17) |

## 5. Queries, spikes and checks

| ID | Route | Area | When | Status |
|---|---|---|---|---|
| Q-01 to Q-06 | Notebook query, when the design needs it | Topics 4, 14, 16, 17, 18 and 19 of the coverage check | Q-04 in 2, Q-01 in 3, the others on demand | Planned |
| Q-07 | Notebook query | How much delimiters and other prompt-layer defenses stop (L1, L2, HNS) | 0b, for the threat model; reused in 5 | Done 2026-11-02 (section 7) |
| Q-08 | Notebook query | Metamorphic relations for document pipelines (L4) | 7 | Planned |
| Q-09 | Notebook query | Evidence on LLM effort estimation and estimate maturity (PMI, ART, REP) | 3 | Planned |
| Q-10 | Notebook query | Second passes and test-time compute for extraction recall (L3, L2) | 1 | Planned |
| S-04 | Spike | The same schema and tool call on Gemini, Ollama and later Cerebras, including temperature behavior | 0a, Cerebras in 3 | Done for Gemini and Ollama |
| S-05 | Spike | Reasoning placement: schema only, thinking plus schema, two-step | 0a | Done |
| S-07 | Spike | Quote verification under PDF noise: ligatures, hyphenation, curly quotes, whitespace | 0a | Done |
| S-09 | Spike | Relative deadlines and time zones in `date_calc` | 0a | Done |
| S-14 | Spike | A long prompt on Ollama's default context and on an explicit `num_ctx`, on CPU | 0a | Done |
| S-01 | Spike | Parse fidelity on a two-column PDF with nested tables | 1 | Planned |
| S-02 | Spike | Docling output mapped to frozen-text offsets | 1 | Planned |
| S-03 | Spike | Recall against batch size on the hero RFP | 1 | Planned |
| S-10 | Spike | A plain prompt against a structured `extract` prompt | 1 | Planned |
| S-13 | Spike | A second extraction pass on `OBLIGATION` zones: recall gain against false positives | 1 | Planned |
| S-11 | Spike, time-boxed to 1 hour | The `app` container reaching the NotebookLM MCP server on the host, and Context7 remotely | 2 | Planned |
| S-12 | Spike | Method cards on and off, per family | 3 | Planned |
| S-08 | Spike | GPU passthrough on WSL2 | 6 | Planned |
| S-06 | Spike | Hidden-text detection by comparing extracted text with OCR of the rendered page | 7 | Planned |
| S-15 | Spike | Typed placeholders against realistic surrogates, on the hero with planted personal data | 5, if D-05 takes C8 | Planned |
| V-03 | Limits and prices | Real Gemini limits, paid-tier prices, the Cerebras trial, model retirement, the dated price list, Context7 auth and limits, the NotebookLM quota, and the current free-tier terms | 0a | Done 2026-11-02 |
| V-06 | Environment | The GPU's state and the local generation speed | 0a | Done 2026-11-02 |
| V-08 | Versions | The library and image versions at lock time | 0a | Done 2026-11-02 |
| V-02 | Access check | Download and license for CrackedPDFs, ContractScrub, ContractNLI, QuRE, CUAD and FedProc-Bench | 1 | CrackedPDFs read 2026-11-04 from its Hugging Face card (`volkthienpreecha/crackedpdfs`): MIT License for the paper-release code and dataset, no access gating seen, 651 MB in all, a test split of 2,919 rows assigned in `data/splits.json`, and an integer `label` per file in `data/metadata.jsonl`. The card's `LICENSE` file and the Zenodo record were not opened. The owner confirms before step 19 runs. The other five datasets are checked before Iteration 5. |
| V-01 | Paper check | The primary source of every figure that may enter a deliverable: ORCS first, then MAUD, REGen, The Power of Noise and the Cortex full text, and the OWASP lists | 5 and release | Partly done: the OWASP Agentic Top 10 and LLM Top 10 read at source on 2026-11-02 |
| V-04 | The owner | RFP-SPEC-001 and the repository the owner's notes mention, if they exist; until then the boundary notes are the baseline | Any time | Open |
| V-09 | Source check | The UK GDPR on pseudonymization (Articles 4, 25 and 32), and Carrell et al. 2013 on realistic surrogates | 0b, for D-05 | Done 2026-11-03 (section 17) |
| H-06 | Save | Raw reports and answers kept privately | 0a | Done 2026-11-02 |
| H-01 | Audit | Numeric-claim audit of any report to be quoted | Before quoting | As needed |
| H-02 | Repair | Re-add the INCOSE guide, the APMP Body of Knowledge, OWASP AISVS, and the PyMuPDF and pypdf docs to their notebooks | Backlog | Backlog |
| H-03 | Trace | L2's "RFP benchmark" column | Backlog | Backlog |
| H-04 | Mind maps | Report-only maps for the other reports, with a coverage check | Backlog | Backlog |
| H-05 | Source audit | REP and Gap, because of a weak portfolio source | Backlog | Backlog |

## 6. Spike decisions

Each spike decides one design question, with its pass mark fixed before it runs. If a spike is inconclusive, its default stands and the result is still recorded. "Noise" means the spread across the baseline's repeats ([[Master-Plan]], section 10.9).

| Spike | Metric | Pass mark | Default | Decision it controls | Result |
|---|---|---|---|---|---|
| S-04 | Schema-valid responses on 10 calls per provider, one multi-turn tool loop, and every token field present | 100% valid, the loop completes, every token field arrives | Gemini through the OpenAI-compatible endpoint | The client design | Gemini and Ollama valid; the compatible endpoint dropped Gemini's token details, so ADR-001 moved Gemini to the native SDK |
| S-05 | Missed mandatory and verified-quote rate for schema only, thinking plus schema, and two-step, 5 repeats each | The cheapest variant within noise of the best | Thinking plus schema | Reasoning placement per role | All variants missed 0 of 8 in two runs; one call at `medium` was the cheapest, so `extract` uses it (CH-71) |
| S-07 | Seeded noise cases and quotes not in the source | Every real quote accepted as verbatim or normalized, and 0 false accepts | The `verify` rules | `verify` normalization | 9 of 9 real quotes accepted, 0 of 7 false accepts; the rules stand |
| S-09 | Deadline cases with relative dates and time zones | 20 of 20 correct | `zoneinfo` arithmetic in code | `date_calc` design | 20 of 20 |
| S-14 | Truncation of a long prompt at Ollama's default and at `num_ctx` 16384 | Truncation at the default and none at 16384 | `num_ctx: 16384` on every call | Ollama context settings | A 5,606-token prompt was cut to 2,050 tokens at the default and kept whole at 16384; `num_ctx` stays required |
| S-01 | Share of gold clauses whose exact text is locatable in the parsed output | At least 98% | `docling-serve`, compared with pdfplumber | Parser choice | Planned |
| S-02 | Docling passages mapped back to frozen-text offsets | 100% of passages | Exact search in the frozen text | Whether Docling output can feed `verify` directly | Planned |
| S-03 | Missed mandatory on the hero at batch sizes 10, 20 and 40, 5 repeats each | The largest batch within noise of batch 10 | 20 | Batch size, and so capacity | Planned |
| S-10 | Missed mandatory for a plain prompt against a CARE prompt, 5 repeats each | CARE stays only if its median beats the plain prompt's by more than noise | Plain prompt | The `extract` prompt | Planned |
| S-13 | Missed mandatory and precision, with and without a second pass | Misses fall, and precision drops no more than 3 points | Off | Whether the second pass runs | Planned |
| S-11 | The `app` container reaches the host MCP server, and Context7 answers | Both work inside the 1-hour box | A host-side command that writes packs | How `live` runs | Planned |
| S-12 | Negative-case violations per card family, cards off and on, plus the scorecard | A family switches on only if violations fall beyond noise and the scorecard holds | Every family off | `methods.enabled` per family | Planned |
| S-08 | `ollama ps` shows GPU use inside Docker | GPU in use | CPU, or the host's Ollama | The GPU path | Planned |
| S-06 | Hidden-text recall, render-and-compare against the operator scan | Higher recall with no more false positives | Off | Whether render-and-compare joins `guard` | Planned |
| S-15 | Quotes restored, values left unrestored in model-written text, and missed mandatory, for typed placeholders and for realistic surrogates, 5 repeats each | Every quote restored; the style with fewer unrestored values wins, unless its misses rise beyond noise | Realistic surrogates | The surrogate style in C8 | Planned |

## 7. Q-07: what prompt-layer and tool-layer defenses stop

Asked on 2026-11-02 of the L1 Prompt, L2 Context and HNS Runtime Harness notebooks [T]. Findings are stated in words, with each study's publication status; only the CrackedPDFs figures are confirmed at source.

- **Prompt-layer defenses reduce indirect injection but do not remove it, and the effect varies by model.** BIPIA (KDD 2025, peer-reviewed) found black-box boundary markers and reminders lowered attack success on the models tested without making any of them robust; only fine-tuning with special boundary tokens drove it near zero, which hosted models do not allow. A 2026 preprint benchmark reported static and randomized delimiters still leaving substantial attack success on a Gemini Flash configuration, with large differences between models. A datamarking ablation (MDPI Applied Sciences, 2026) cut attack success but collapsed success on benign tasks.
- **Controls outside the model hold where the model fails.** A 2026 preprint (DGF-Bench) reports a tool-level authorization guard executing no forged approval while model-level decisions were manipulated. A simulation study (MDPI Computation, 2026) found least-privilege permissions the strongest single control, retrieval allowlists effective only on their own channel, and human approval strong but weakened by confirmation fatigue. InjecAgent (preprint) found agents prompted with ReAct text far more vulnerable than agents fine-tuned for native function calling.
- **Screening document structure before parsing beats screening extracted text.** CrackedPDFs (preprint, confirmed at source): a hybrid structural detector reached F1 0.960 on held-out PDFs, against 0.623 for a rule baseline and 0.390 for PromptGuard on extracted text alone.
- **Causal attribution of security events is recommended in the sources but not measured.**

**What it changed.** Delimiters stay as hygiene; the weight sits on `guard` before parsing, `ToolGateway` outside the model, least privilege per agent, and `DRAFT_ONLY` (ADR-008, ADR-009, ADR-010). Injection is measured per model (QS-3), because results differ by model.

## 8. Coverage check, 2026-10-30

One 21-topic checklist went to all ten research notebooks, so that no job repeats what they already hold. NotebookLM's `COVERED` label is generous, so the verdicts are Claude's, made from one-line answers without citations. This matrix is triage only.

| # | Topic | Verdict | Best evidence so far | Route |
|---|---|---|---|---|
| 1 | Obligations without modals; limits of rule-based recall | **Gap** | One non-peer-reviewed portfolio page only | DR-01 |
| 2 | Atomic decomposition; many-to-one scoring | Partial | Split rules exist (L4, L5); nothing on scoring credit | DR-06 |
| 3 | Batch size and omission | **Thin** | One adjacent-task benchmark reports recall falling sharply as batches grow (L4); batch truncation (L1) | DR-02, S-03 |
| 4 | Agent trajectory metrics | Covered, scattered | Tools in order, tool-call precision, pass^k, tool-selection accuracy | Q-01 |
| 5 | Agentic against fixed pipeline | Mixed | A recall gain with agents in one setting (L1); ReAct against a fixed DAG splits by task (L2); "no gain" only on a portfolio page | DR-07 |
| 6 | Statistics for small evaluations | Covered, except few clusters | Cluster bootstrap (L3), design effects (L1), exact McNemar with Holm correction (L4) | DR-09 |
| 7 | Synthetic validity | Partial | Sentence-level only: QuRE length and depth (Gap), Self-BLEU (L4) | DR-10 |
| 8 | Correcting judge error | Partial | Predictive-value correction on a large audit (L1); prediction-powered inference only on a portfolio page | DR-09 |
| 9 | Judging plans, approaches and WBS | Partial | A practitioner checklist (L2); low overlap with reference plans (REP); the 100% rule (ART) | DR-05 |
| 10 | Judging LLM risk identification | Partial | Review gates with hidden ground truth (L2); ContractEval (L5, Gap) | DR-05 |
| 11 | Automation bias and omission blindness | **Thin** | One prospective trial in which missed items were the main error (L1); the rest is simulation or vendor blogs | DR-08 |
| 12 | Hidden content in DOCX and XLSX | **Gap** | One DOCX metadata case (L2), one enterprise guide (HNS) | DR-03 |
| 13 | PDF parsers head to head | **Gap** | One vendor parser result (L1) | DR-04, S-01 |
| 14 | Addenda, precedence and cross-references | Covered for design | Measured priority-extraction errors (L1); precedence dossiers (L2) | Q-02 |
| 15 | Small local models | Schema covered, tools thin | Small models on consumer hardware with valid structured output (L5) | DR-11 |
| 16 | Reasoning before the schema | Covered | Large gains from reasoning before the schema (L1); a recall gain on ContractScrub (Gap) | Q-03, S-05 |
| 17 | A different vendor decorrelates errors | **Covered, and it undercuts an assumption** | Errors cluster by lab family (L1); correlated errors persist across vendors (L4, L5) | Q-04 |
| 18 | Critics without ground truth | Covered | CRITIC (L3); unanchored judges cannot verify meaning (L4); a consensus signal (L1) | Q-05 |
| 19 | Few-shot and negative examples | Covered | Examples with rules lift F1 far above zero-shot (Gap) | Q-06 |
| 20 | Commercial RFP tools | Vendor sources only | Hallucination rates reported through a blog (REP) | DR-12 |
| 21 | Regulation of bid tools | **Gap**, low stakes | Passing mentions only | One paragraph in `ASSUMPTIONS.md` |

**Three warnings.**
- One personal portfolio page is the strongest source for several REP and Gap answers, which stay weak until traced to a primary source.
- The Gap notebook again gave recall figures for Siemens ORCS, attributed to the paper itself, which Claude's audit of the gap report had rejected. V-01 reads the paper, and the figures stay excluded until then.
- Some `COVERED` answers rested on a Reddit thread (L5) and vendor blogs (L3, Gap), and were discounted.

## 9. Design areas check, 2026-10-31

Fifteen design topics went to the notebooks, mostly L1, L2, L3, L4, HNS and Gap, alongside Google's current Gemini documentation and web searches. Triage again: one-line answers, no citations.

| Area | Verdict | What it changed | Research left |
|---|---|---|---|
| Method knowledge | Covered for coding agents only | Cards load by code, with only two new skills | S-12, paper check |
| Prompt format | Vendor guidance only; no study in any notebook | One format, XML-style tags, task last | None |
| Prompt patterns | **Old evidence** | Most studies use 2023-2025 models, and Google warns that verbose techniques may cause over-analysis | **DR-16, S-10** |
| Few-shot and negative examples | Covered | `extract` gained a plain-language decision table | None |
| Context order and size | Covered, mixed age | The strongest evidence sits last, and linked clauses are packed together | **DR-16** |
| Passage enrichment | Covered | Section paths stay, since a notebook study reports better search with fewer tool calls (L1) | None |
| Agent pattern | Covered | Deterministic routing and an independent assessor confirmed. L2 notes that ReAct recovers better from failures, which `RecoveryController` must cover. | None |
| Tools and limits | Covered | Small allowlists kept, and a no-progress stop added | None |
| Stop control | Covered in principle | Needs a concrete LangGraph mechanism | C7-06 |
| Span matching | Covered | Gold-clause coverage with the verified quote inside the clause, and IoU reported for reference (CH-33, CH-56) | DR-06, only if disputes appear |
| Replay and scorer testing | Covered | The scorer self-test confirmed and extended to judges | None |
| Judge calibration | Thin | 40 labels is far below the published audits, so judges stay advisory | DR-09 |
| Consistency | Covered | 5 repeats stay; Gemini gives no temperature control, so variance between runs is real | None |
| Solution and proposal generation | Human practice covered (ART, REP, PMI); evidence on LLM generation thin | The E and P stages redesigned, with research as agent tools | **DR-17, DR-18** |
| Architecture method | Mostly absent from the notebooks; REP supports ISO 42010, C4 and decision rationale, and HNS supports agent specifications and threat models | A six-step method, tested and changed by DR-19 | None |

## 10. Mind-map reconciliation, 2026-11-01

Every top-level branch of the nine notebook mind maps, checked once against the design. Whole-notebook maps are shallow, so report-only maps (H-04) may add branches.

| Notebook | Branch | Verdict | Why |
|---|---|---|---|
| L1 | ACORD Benchmark | Deferred | Clause retrieval benchmark, a candidate when dense retrieval arrives in Iteration 7 |
| L1 | REASONS Benchmark | Used | Citation evidence behind the grounding axis |
| L1 | Contractual Extraction & Security | Used | `extract`, `verify`, `guard` |
| L1 | BIPIA Benchmark | Used | Injection traps, including end-of-content placement |
| L2 | Cross-Encoder Query Expansion | Deferred | Lexical retrieval stands until Iteration 7 measures alternatives |
| L2 | ALCE Benchmark | Used | Citation recall and precision |
| L2 | ALiiCE Evaluation Framework | Used | Sentence-level citation, which supports the stronger `validate` |
| L3 | Foundational Concepts | Used | Bounded loops |
| L3 | 10 Loop Design Patterns | Used | `decide`, `risk`, `repair` loop limits |
| L3 | Test-Time Compute Allocation | **New use** | Second extraction pass, S-13 |
| L3 | Training Paradigms for Self-Correction | Dropped | No model training in this project |
| L3 | Enterprise State Machine Topologies | Used | LangGraph workflow and the run state machine |
| L4 | Graph Query Languages for Traceability | Deferred | Typed graph gate, Iteration 7 |
| L4 | LLM-Based Property-Based Testing | Used | Hypothesis invariants |
| L4 | TRACE-KG Framework | Deferred | Typed graph gate, Iteration 7 |
| L4 | Requirements & Code Analysis | Used | `lint` |
| L5 | Core Dilemma in High-Stakes AI | Used | The deterministic-shell thesis |
| L5 | Neuro-Symbolic Paradigm | Used | Same thesis. Z3 stays not planned. |
| L5 | Architectural Frameworks | Used | Hard invariants checked in code |
| L5 | Assurance Cases for System Safety | **New use** | One-page assurance case in Iteration 5, linking trust claims to evaluation evidence |
| HNS | Causal Attribution Framework | **New use** | Security events classified as injection-dominant, authorization-dominant, combined or indeterminate |
| HNS | Resume Contract | Used | Checkpoint, interrupt and resume tests |
| HNS | Enterprise Agentic Stack | Used | Control plane structure |
| REP | International RE Standards | Used | ISO 29148 verification methods, `lint` rules |
| REP | AI-Assisted RE and Fine-Tuning SLMs | Dropped | No model training. Small models appear only in the bake-off. |
| REP | Strategic Public Procurement | **New use** | The hero RFP names a fictional procurement regime, recorded in `ASSUMPTIONS.md` |
| ART | MBSE Integration | Dropped | The manifest trace covers this project's need, and no system model exists |
| ART | Shipley Business Development Lifecycle | Used | Gates and color reviews |
| ART | Price to Win Operating Model | Dropped | No price or competitor data |
| ART | AACE Cost Estimate Classification | **New use** | Effort estimates carry a maturity class |
| PMI | Benefits Realization Management | Used | Benefits as testable hypotheses |
| PMI | Cost Estimating & Assessment | Partly used | Effort basis only, no cost |
| PMI | EVM & Scheduling | Used | Earned-value fundamentals at each tag, with no EVM system, and schedule logic in the manifest |

## 11. What the research changed

Findings are notebook answers [T] unless marked confirmed at source.

| Finding | From | Design change |
|---|---|---|
| **No audit found a peer-reviewed evaluation on real RFPs.** Each names transfer from adjacent benchmarks as the fatal assumption, and a high F1 does not mean zero missed mandatory requirements. | All | The headline metric is **missed mandatory requirements** |
| Whole-document review is far harder than chunk benchmarks suggest: best macro recall 0.750 and best F1 0.655 on ContractScrub (confirmed in the paper), with models weakest on undefined terms and party references | New | `lint` keeps a registry of defined terms and parties in code |
| The closest real-RFP study (Siemens ORCS) reached high but incomplete recall against a stated goal of every requirement, and specificity fell where experts ruled whole sections out of scope. **Disputed** until V-01 reads the paper. | New | A recall-first design; recall and specificity reported separately |
| An omitted requirement produces no matrix row, so a reviewer cannot see it | New | Every candidate gets a recorded disposition, and review samples the negative space |
| One missed mandatory item can disqualify a bid regardless of quality. Experts separate instructions, evaluation criteria and contract obligations, and only obligations survive into the contract. | ART, REP | Every clause gets a zone; submission hazards lead the summary |
| Retrieval should be model-driven and depend on the input, not a fixed RAG DAG | L2 | A model-authored `ToolDecision`, with contrast shown on live runs |
| Tool-level authorization stopped every forged approval in one benchmark's attacked gates, where safety prompts failed (Q-07) | L2, L1 | `ToolGateway` sits outside the model and authorizes before execution |
| Self-critique without an external signal is net negative; critique grounded in tools gains, and two or three rounds capture nearly all of it | L3 | Red Team gets tools and verifier results, with at most 2 cycles |
| Regeneration corrupts correct content, and patch indexes shift; repair scoped to one entity, with version checks and rollback, is safest | L3 | Transactional repair, with correct-to-incorrect flips measured |
| BM25 beat dense search on documents mixing text and tables, and HyDE hurt (finance only) | L2 | Lexical search first; dense retrieval with fusion measured in Iteration 7 |
| Retrieval recall does not predict answers under a token budget: perfectly retrieved answers were lost in packing | L2 | Answer-in-Context measured; evidence first, requirement last |
| Whether a quote can be found in the source separates faithful from unfaithful outputs at no inference cost, and ungrounded outputs mostly quote text that does not exist | L1 | Exact quote checking is the core gate |
| Offsets emitted by a model are error-prone, sentence-level citation beats chunks, and citation added afterwards is worse than inline | L1 | The model cites passage ids, and the app owns offsets |
| Correctness and grounding are nearly uncorrelated | L1 | Reported as separate axes |
| Reasoning inside JSON is what hurts; under matched prompts, constrained decoding matches or beats free generation | L1 | Free reasoning first, the schema second, and no `reasoning` field |
| Constrained decoding fixes syntax in small models but not semantics, so schema-valid filler passes | L1 | The bake-off reports schema, semantics and grounding separately |
| A text-only injection guardrail reached F1 0.390, rules 0.623, and a structural hybrid 0.960 (confirmed in the CrackedPDFs paper) | L1 | **A text-only scan is the weak design,** so `guard` scans PDF structure before parsing |
| NLI judges agree poorly with people; LLM judges do better but run lenient, and context size flipped verdicts | L1 | Judges are calibrated on the owner's labels, with leniency and context sensitivity measured |
| Retrieval suppresses abstention, and prompting alone does not restore it | L1 | Code forces `UNVERIFIED` on any capability claim without knowledge-base evidence |
| Graph connectivity is not truth, and flat metrics missed every drift type in one study | L4 | Four closure checks on flat records; a typed graph gate must beat them in Iteration 7 to stay |
| Vague terms, escape clauses, open-ended lists, passive voice and missing units are detectable without an LLM | L4 | `lint` feeds clarification questions |
| Multiplying ordinal risk ranks is pseudo-precision, and risk, issue, assumption and constraint differ | PMI | Typed records, and no ratings unless a person supplies them (method card RISK-002) |
| A conflict needs a shared scope, time and data check, and aggressive deduplication loses exceptions | PMI | `conditional` and `established` discrepancies; source fidelity beats deduplication |
| Crash recovery in LangGraph is at-least-once, and interrupts re-run the node | HNS | Idempotent LLM calls through the response cache |
| Overstating compliance creates legal exposure, and False Claims Act liability needs no intent to defraud [R] | REP | Compliance status starts `UNVERIFIED`, and only a person changes it |
| Parsing errors explain a large share of failures in a table-heavy benchmark | L1 | Parse fidelity is measured on its own |

**Excluded from every deliverable.**
- The PMI report's numeric thresholds, none of which another source in the notebook supports.
- The L1 report's uncited condition table.
- L2's "RFP benchmark" column, until traced to a paper.
- Vendor claims of coverage and win-rate lifts, which the ART audit traces to marketing.
- From the gap report, after audit: the ORCS recall and specificity figures, the claim that ORCS "failed in production", a vendor's override threshold that its own source disclaims, an unverifiable BERTScore figure, and an unrelated LeetCode comparison.
- Any PMI book text; only the owner's original method cards are used.

**Corpus health.** 45 sources across eight notebooks failed to load, including the INCOSE requirements guide (L4), the APMP Body of Knowledge (ART), and the PyMuPDF and pypdf docs (L1), so source counts overstate what those notebooks can retrieve.

## 12. The gap researched first

The first adversarial job tested the assumption all nine notebooks rested on:

```yaml
gap_id: G-RFP-20261030-001
severity: HIGH
core_assumption: Results on pre-segmented legal text, scientific papers and synthetic benchmarks transfer to whole, unsegmented RFP packages, so an LLM pipeline can capture every mandatory requirement.
analytical_vulnerability: The notebooks rest on this and none holds a peer-reviewed evaluation on real RFPs. If false, mandatory misses cause disqualification and scorecards give false assurance.
```

**Outcome.** The assumption is refuted in direction, on thin evidence, and no public gold corpus of whole real RFPs was found. The Siemens corpus is closed. FedProc-Bench is not a real-tender evaluation: its real solicitations are metadata only, and it is a single-author preprint.

**Residual gaps, and what closes each.**

| Gap | Closed by |
|---|---|
| No precommitted RFP gold | Gold hashed before the first score against it, from Iteration 0a |
| No measured recall and precision | Gold scoring and the ablations |
| Exact offsets on multi-column and table PDFs | Parse fidelity measured by layout |
| No contrast between tool decisions | A decision contrast test on live runs |
| No evidence for a critic switched off and on, or for repair that fails and reverts | The PR ablation and the repair tests |
| No evidence for a graph gate switched off and on | Iteration 7 |
| Unknown false-accept and false-reject rates for assessment | Assessment scored against labeled claims |
| Fault-injection tests and live defects not yet run | The fault-injection tests, plus two logged live defects |

## 13. Standards review, 2026-10-30

The owner's engineering standards were scored on two tests: does an item improve the engineering, design, governance or security of this submission, and is it still current? The prompt standards rest on 2024-2025 sources.

**Verdict.** The design covers the intent of the standards on verification, least privilege and evaluation. Twelve additions close the remaining gaps, seven items are stale or harmful here and are replaced, and the research-harness process is not adopted for this project.

**Adopted.**

| Item | Aspect | In Bidwright |
|---|---|---|
| Risk and data classification | Governance | Medium as built (draft-only, synthetic, no external submission); High for real deployment. `free` refuses non-corpus files without an override, and real documents get metadata-only traces. Self-classified, because `risk-classification.md` is missing. |
| Workflow skeleton, per-step error table | Design | `docs/architecture.md`, runtime view |
| Stop control, tested by fault injection | Governance | `bidwright stop <run>`, checked between nodes |
| Mandatory human gates | Governance | Output stays `UNREVIEWED_DRAFT` until sign-off |
| Named pattern, agent role table | Design | Supervisor with deterministic routing. Why one domain still gets several agents goes in `DECISIONS.md`. |
| Prompt skeleton and named patterns | Engineering | Role, rules and output format first, data next, and the task last with a short reminder. `risk` uses one-call Multi-Perspective with the pre-mortem, and `redteam` uses Designer-Critic. Patterns on `extract` must pass S-10; elsewhere they are judgment until measured. |
| Prompt versioning | Engineering | SemVer, role, decoding and rubric in each prompt's front-matter, the pattern that `standards/prompt-engineering/operations/versioning.md` treats as equal to a registry |
| Input limits | Security | Size, page and path caps, a zip-bomb check, DOCX and XLSX hidden-content scans, and formula-leading cells escaped in XLSX output |
| Threat model | Security | One page in Iteration 0b, then `docs/security.md` |
| Hypotheses and numeric thresholds per rung | Engineering | Committed with the gold hash |
| Judge rubric rules | Engineering | 5-7 criteria, 0-10 with anchors, a pass at an average of 7 out of 10, reasons before scores. Code checks such as the WBS 100% rule run first. |
| ADR shape and recovery limits | Governance, engineering | `DECISIONS.md` entries follow the short ADR form. 3 retries, a breaker at 5 failures with a 30-minute cooldown, and a dead-letter file for failed batches. |

**Replaced, as stale or harmful here.**

| The standard says | Problem | Instead |
|---|---|---|
| `safe_render` is mandatory | Tested 2026-10-30 [M]: it doubles braces, so exact-quote checks fail, and it cut a 13,600-character batch to 4,000 with no error, which would silently lose requirements. Escaping protects nothing, because `format` does not re-parse values. | `string.Template.substitute`, which raises on a missing value and keeps quotes exact |
| The `deterministic` and `critic` presets use temperature 0.0 | Google's documentation says Gemini 3.6 and later ignore `temperature`, `top_p` and `top_k` and advises removing them, and advises keeping defaults on earlier Gemini 3 models | Send none to Gemini, and steer with thinking levels and explicit rules; 0.0 only on Cerebras, Groq and Ollama, once checked |
| Security maps to OWASP LLM01:2025 | The OWASP Top 10 for Agentic Applications 2026 fits this system better | `docs/security.md` maps controls to ASI01-ASI10 and the LLM Top 10, both read at source |
| Delimiters are the first defense | Their effect varies by model, from large to none in the studies the notebooks hold (Q-07) | Randomized delimiters as cheap hygiene, with injection measured per model; `guard`, `ToolGateway` and `DRAFT_ONLY` carry the weight. Paraphrasing input, a strong defense in one preprint, cannot work here because quotes must stay verbatim. |
| Judges: one named model, kappa of at least 0.8 | The model named is dated, and the published audits report a wide range of agreement from far larger label sets than 40 | Judges chosen by calibration, kappa reported with its interval, and judges advisory |
| Stay under 40% of the context window | A heuristic from a 2024 benchmark, not a platform limit | Logged as a signal, and truncation tested directly on Ollama (S-14) |
| Calibrated Confidence puts `reasoning` in the schema | Reasoning inside JSON hurts (L1), and `verify` is a stronger signal for records | Free reasoning before the schema, and `confidence` on `triage` only, where the fallback needs it |

**Not adopted for this project.**

| Item | Why |
|---|---|
| `memory/` layers and harness hooks | They guard the research substrate, not the product. **Enforcement here is CI:** ruff, pyright, replay tests, the regression gate, the gold hash, secret scanning and the dependency audit. |
| Formal research gates (M13 steps 6-7, M14, M15, M16, M19, M21 report, M23, M25, rule 20) | They gate substrate positions, and this project has none. The intent stays: every quoted figure is checked, and `docs/verification_log.md` records what was verified. Rules 1 (ISO dates), 13 (a fresh notebook per research job by default) and 18 (one active research job per notebook) still apply. Bidwright's own runtime rule, one job per notebook, is stricter than rule 18. |
| Full M41 vault install | The `context/` vault in the owner's format serves the purpose |
| Registry, pre-deployment checklist | The files are missing. `docs/agents.md` and `docs/architecture.md` stand in. |
| Canary, shadow runs, consistent hashing, P99 under 10 s, thumbs ratings, edit distance | They need live traffic or users |
| `effort`, adaptive thinking | Claude-only, and no Claude model is in the stack |
| DeepEval, RAGAS, TruLens | `standards/prompt-engineering/evaluation/framework-comparison.md` predates this stack, and the metrics here are domain code. Recorded in `DECISIONS.md`. |
| Separate regulation research (the former DR-13) | No design decision depends on it. Instead, one dated paragraph in `ASSUMPTIONS.md`, based on secondary sources and not yet checked against the Official Journal: Regulation (EU) 2026/1744 defers standalone high-risk duties to 2027-12-02, and Article 50 applies from 2026-08-02. |

## 14. The architecture method, reviewed (DR-19)

The method is the owner's choice, reviewed against the literature by DR-19 and changed where the evidence required. No agreed standard was found for agentic systems, and no controlled study compares these methods, so the method is a synthesis of arc42, C4 and ADRs, not an established method: not refuted, which differs from proven. `docs/architecture.md` sets it out.

DR-19's seven changes:
1. Two kinds of quality scenario: invariants and statistical scenarios.
2. A short ADR form.
3. Boundary contracts in code.
4. Gateway rules written as trigger, check and outcome.
5. Marked-up views, with arc42 as an index.
6. Revalidation triggers.
7. A Goldfish architecture review at two gates.

## 15. How the owner's terms map

The owner's `RFP SOTA` notebooks are written around a specification, RFP-SPEC-001 v1.3, that no notebook holds, so the design follows its boundary notes, the owner's closeout notes, the 14-gate playbook and the PMI charter.

| Term | In Bidwright |
|---|---|
| REP | The three workflow phases |
| Ladder L1-L5 | The EX rungs climb it: EX1 the prompt contract (L1), EX2 context (L2), EX3 the coverage loop (L3). L4's typed graph gate waits for Iteration 7, and L5's formal methods are not planned. |
| HNS | The `harness/` package wrapping the graph |
| E90 | `evals/` and `bidwright-eval`, with their own budget and ledger |
| EAS | The `assess` node's output |
| R0 | The release target: Iterations 0a to 5 |
| R0+ | Red Team and repair, built in Iteration 4 and kept only if PR3 and PR4 earn them; Iterations 6 and 7 |
| R1 | Formal methods (Z3), not planned |

## 16. Environment findings

| Finding | Consequence |
|---|---|
| On 2026-11-02 Docker runs (26.1.1, Compose 2.27, WSL 2.1.5), and `nvidia-smi` reaches the GTX 1650 Max-Q with 4 GB (V-06) | Docker and the host path both work; neither local model fits the card at a 16K context, so `local` runs mostly on CPU |
| Gemini is not on Ollama Cloud, and its retired preview page lists no Gemini | Gemini goes direct to Google AI Studio |
| Free limits on this project: Flash models 20 requests a day, 3.5 Flash-Lite 500, Gemma 4 14,400; Gemini 4 Argon none (V-03) | ADR-003: Flash-Lite for `reason` on `free` |
| Free-tier content may be used to improve Google's products and read by human reviewers; apps offered to users in the EEA, Switzerland or the UK must use paid services (V-03, terms effective 2026-03-23) | Synthetic data only, enforced on `free`; `ASSUMPTIONS.md` records the reading |
| The Cerebras trial is $5 of credits that expire 30 days after they are granted, need a payment method, and give 5 requests a minute and 1M tokens a day per model (V-03) | The second model family for large prompts, with the key created at the start of Iteration 3 |
| One cold sample of `llama3:8b` on this laptop measured about 8.6 tokens a second | `local` runs the thin thread on the development RFP only |
| Ollama Cloud's free plan is pay per token, GitHub Models retired in 2026, and OpenCode's free models need its own client | None is a fallback; paid Gemini on the same model is (CH-45) |
| LiteLLM 1.82.7 and 1.82.8 were compromised on 2026-03-24 | No gateway dependency, a hash-locked `uv.lock`, and a dependency audit in CI |
| The NotebookLM MCP server serves over HTTP on localhost, and Context7 has a remote endpoint that takes its key as `Authorization: Bearer` (V-03) | `live` research looks feasible; S-11 checks it from the container |

## 17. Sensitive information: DR-20 and DR-21

Two adversarial deep-research jobs ran on 2026-11-03, each in a fresh notebook. They tested the assumptions behind the first proposals for D-05 in [[Decision-Form]]. Their reports are kept privately and are not audited as a whole. The findings below are stated in words, and each one says whether it was checked at source.

**DR-20: detection, pseudonymization and leak paths.** 49 sources, 30 cited and imported.
- **A scan that finds nothing cannot clear a document.** Confirmed at source: Presidio's documentation warns that, because it uses automated detection, there is no guarantee that it will find all sensitive information, and that other systems and protections should be used. The report's benchmark figures show detectors missing a large share of entities in business text. They are not quoted, because several rest on blogs and none was checked at source.
- **Reversible pseudonymization is fragile on a round trip through a model.** Confirmed at source, in a 2026 preprint that evaluates its authors' own engine on English and Russian documents: models return placeholders with their form altered, merged or invented, and some placeholders fail to be restored.
- **Pseudonymization and exact-quote checks.** The report says pseudonymization breaks exact-quote checks. That paper does not say so: the claim is the report's inference. It is plausible for Bidwright, where a placeholder altered inside a quote would get a true requirement rejected.
- **Context leaks identity.** The report cites peer-reviewed work showing that models infer personal attributes from text whose direct identifiers were removed. Not checked at source.
- **Leak paths beyond the provider.** Traces and logs, caches, vector stores, checkpoints, memory, test fixtures and tool calls. This is the report's account, partly from framework summaries and blogs. It agrees with OWASP LLM02 as read for `docs/security.md`.
- **The report's verdict.** Routing gated by detection, and pseudonymization before hosted calls, are unsupported. Treating every client document as confidential by default, and processing locally or in the client's tenant, are strongly supported.

**DR-21: law, procurement confidentiality and provider terms.** 33 sources, 27 cited and imported.
- **Pseudonymised data.** Confirmed at source, in the Court of Justice's press release on EDPS v SRB (C-413/23 P, 2025-09-04). Pseudonymised data are not personal data in every case and for every person, and pseudonymisation may stop persons other than the controller from identifying the data subject. But the controller's duty to inform is assessed at collection and from the controller's point of view, whatever the data are for the recipient. Pseudonymizing before sending text to a provider therefore leaves the sender's own duties in place.
- **Procurement confidentiality.** The report overstated it. Confirmed at source, in regulation 21 of the UK Public Contracts Regulations 2015 as made, revoked on 2025-02-24 by the Procurement Act 2023: the duty not to disclose binds the contracting authority, and authorities "may impose on economic operators requirements" that protect the confidentiality of what they make available. A bidder's duty therefore comes from each tender's own terms. Article 21 of Directive 2014/24/EU could not be retrieved from EUR-Lex, so its text is not stated here.
- **UK guidance on AI in bids.** Confirmed at source, in PPN 017 (2025-02-17), which applies to central government. Suppliers' use of AI "is not prohibited". Authorities may ask suppliers to disclose it, and put in place controls so that confidential authority information is not used as training data for AI systems. The report's claim that sending tender text to an AI service needs the buyer's consent is not in the note.
- **Gemini API terms**, effective 2026-03-23. Confirmed at source:
  - On unpaid services, Google uses content to improve its products, human reviewers may read it, and the terms say not to submit sensitive, confidential or personal information.
  - On paid services, prompts and responses are not used to improve products and are processed under Google's data processing addendum. They are logged for a limited period, solely to detect abuse and for legal disclosures, and may be stored transiently or cached in any country where Google or its agents have facilities.
  - In the EEA, Switzerland and the UK, the paid-service data terms apply to all services, including the unpaid quota.
- **Other providers.** The report covers abuse-monitoring retention and zero-retention options for Azure OpenAI, OpenAI, Anthropic and AWS Bedrock. Not checked at source, and not quoted.

**What it changed.** D-05 was revised:
- No detector gates routing, and pseudonymization was dropped.
- Every client document is treated as confidential by default.
- Routing follows the providers' terms.
- The consent override that lets a client document reach the free tier conflicts with Google's terms for that tier.

### Masking around hosted calls: follow-up, 2026-11-03

The owner asked whether a local model could mask sensitive values before hosted calls, with a local pass afterwards, as a bridge until local models do well enough on their own. Library documentation (C7-18) and two sources (V-09) were checked.

- **Similar implementations.**
  - LangChain's built-in PII middleware redacts, masks, hashes or blocks values in agent input and output. Its documentation describes no restoration.
  - Presidio's sample for hosted models replaces values with numbered placeholders, keeps one mapping across a session's requests, and restores the reply. Its recognizers backed by language models, which can run on Ollama, are marked experimental.
  - LlamaIndex masks retrieved text with a local entity model or an LLM, and keeps the mapping out of the model's input.
  - DSPy's PAPILLON tutorial has a local model write a redacted request to an untrusted hosted model, then compose the final answer from the private context. It scores quality and leakage together.
  - LangChain's integrations list adds two community packages, piighost and MaskFlow. Both restore values, and can stop a call when personal data reaches the model. Neither was evaluated.
- **What none of them does.** In the documentation read, each restores values by replacing text in the model's output. None maps evidence back to the original by offsets. Bidwright can, because its quotes are verified spans of frozen text.
- **Pseudonymization in law.** Confirmed at source in the UK GDPR, as revised, on legislation.gov.uk. Article 25(1) names "pseudonymisation" among the measures that implement data-protection principles "such as data minimisation". Article 32(1)(a) lists "the pseudonymisation and encryption of personal data". The definition in Article 4 requires the information that reverses it to be "kept separately" under "technical and organisational measures". The EU text was not fetched.
- **Realistic surrogates.** Confirmed at source in the abstract of Carrell et al. (JAMIA, 2013), through Europe PMC. Replacing the identifiers a detector found with realistic synthetic surrogates makes the few it missed hard to tell apart. In a pilot on 81 clinical notes, about 90% of the identifiers left behind were concealed, in text with average and high densities of identifiers. The authors ask for larger tests.
- **What it changed.** D-05 gained two options:
  - C8, masking around hosted calls as minimization on an allowed path, with privacy tiers measured on the gold.
  - C9, one egress rule for every outbound channel, including MCP servers, the trace collector, coding assistants and metadata.

## 18. Sources

- **The owner's research notebooks**, private to the owner's account: L1 Prompt, L2 Context, L3 Loop, L4 Graph, L5 Neuro-Symbolic, HNS Runtime Harness, REP Framework, The Art of RFP Treatment, PMI Domain Methods, Real-Tender Evaluation Gap, and the `RFP SOTA` notebooks for DR-19, DR-01, DR-03, DR-16 and DR-17.
- **Read through those notebooks, not yet at source unless V-01 says so:** NASA Systems Engineering Handbook; GAO Cost Estimating and Assessment Guide; PMI's business analysis and requirements guides; MAUD; the PoliticalNLP span study; The Power of Noise; BIPIA; InjecAgent; FedProc-Bench; Bass, Clements and Kazman, *Software Architecture in Practice*, 4th edition.
- **Datasets:** [QuRE](https://doi.org/10.5281/zenodo.15656471), [PURE](https://doi.org/10.5281/zenodo.1414117), [Falkner et al., Identifying Requirements in RFPs](https://upcommons.upc.edu/bitstreams/ee577bde-0778-4db0-b202-428b34dc63c2/download), [ContractScrub](https://arxiv.org/abs/2608.20204).
- **Gemini:** [pricing](https://ai.google.dev/gemini-api/docs/pricing), [rate limits](https://ai.google.dev/gemini-api/docs/rate-limits), [models](https://ai.google.dev/gemini-api/docs/models), [deprecations](https://ai.google.dev/gemini-api/docs/deprecations), [terms](https://ai.google.dev/gemini-api/terms), [structured outputs](https://ai.google.dev/gemini-api/docs/structured-output), [Gemini 3 guide](https://ai.google.dev/gemini-api/docs/gemini-3), [prompt design strategies](https://ai.google.dev/gemini-api/docs/prompting-strategies).
- **Ollama:** [pricing](https://ollama.com/pricing), [Cloud docs](https://docs.ollama.com/cloud), [Docker](https://docs.ollama.com/docker).
- **Other inference:** [Cerebras rate limits](https://inference-docs.cerebras.ai/support/rate-limits), [Cerebras pricing](https://www.cerebras.ai/pricing), [Groq rate limits](https://console.groq.com/docs/rate-limits), [OpenCode models](https://opencode.ai/docs/zen/), [GitHub Models](https://docs.github.com/en/github-models).
- **Docker and parsing:** [Docker Desktop GPU](https://docs.docker.com/desktop/features/gpu/), [docling-serve](https://github.com/docling-project/docling-serve).
- **Observability:** [Phoenix Docker](https://arize.com/docs/phoenix/self-hosting/deployment-options/docker), [Phoenix cost tracking](https://arize.com/docs/phoenix/tracing/how-to-tracing/cost-tracking), [Langfuse Docker Compose](https://langfuse.com/self-hosting/deployment/docker-compose).
- **Agents:** [LangGraph interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts), [LangGraph graph API](https://docs.langchain.com/oss/python/langgraph/graph-api).
- **Security:** [OWASP Top 10 for Agentic Applications 2026](https://genai.owasp.org/resource/owasp-top-10-for-agentic-applications-for-2026/), [OWASP Top 10 for LLM Applications 2025](https://genai.owasp.org/llm-top-10/), [CrackedPDFs](https://arxiv.org/abs/2607.19396), [InjecAgent](https://arxiv.org/abs/2403.02691), [Spotlighting](https://arxiv.org/abs/2403.14720v1), [LiteLLM compromise analysis](https://www.netspi.com/blog/executive-blog/ai-ml-pentesting/litellm-supply-chain-compromise/).
- **Benchmarks:** [ContractNLI](https://arxiv.org/abs/2110.01799v1), [CUAD](https://huggingface.co/datasets/theatticusproject/cuad-qa).
- **Research tools:** [Context7](https://github.com/upstash/context7), [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk).
- **Method knowledge:** [SkillsBench](https://arxiv.org/html/2602.12670v1), [Guardrails Beat Guidance](https://arxiv.org/abs/2604.11088), [Cortex](https://arxiv.org/abs/2610.14216).
- **Independent review:** [EGM repository](https://github.com/google/elephant-goldfish-model), and the installed plugin's documentation, version 0.1.0, read 2026-11-01.
- **Project and architecture methods:** [PMBOK 8 summary](https://pmstudycircle.com/pmbok-guide-8th-edition/), [arc42](https://arc42.org/overview), [C4 diagrams](https://c4model.com/diagrams), [MADR](https://adr.github.io/madr/), [Diátaxis](https://diataxis.fr/), [ISO 42010 summary](https://quality.arc42.org/standards/iso-42010), [RAD-AI](https://arxiv.org/abs/2603.28735), [C4 for agentic AI systems](https://arxiv.org/html/2603.15021v1), [ADR template study](https://arxiv.org/abs/2604.27333), [Beyond Component Testing](https://arxiv.org/html/2607.29405v2), [ISO/IEC 25059 sample](https://cdn.standards.iteh.ai/samples/80655/168addf09e0a4d8181b9172dc7404fab/ISO-IEC-25059-2023.pdf), [AgentSpec](https://arxiv.org/abs/2503.18666), [AgentArcEval](https://arxiv.org/html/2510.21031v1), [architecture options taxonomy](https://arxiv.org/html/2408.02920v2), [EPIC](https://arxiv.org/html/2610.07534v1).
- **Procurement model for the hero RFP:** [Directive 2014/24/EU](https://eur-lex.europa.eu/eli/dir/2014/24/oj), a model only, with no real citations in the corpus.
- **Design checks:** [REGen](https://arxiv.org/html/2502.16838v2), [span-oriented IE survey](https://arxiv.org/pdf/2403.15453).
- **Masking and data protection:** [LangChain built-in middleware](https://docs.langchain.com/oss/python/langchain/middleware/built-in), [LangChain middleware integrations](https://docs.langchain.com/oss/python/integrations/middleware), [Presidio's sample for hosted models](https://github.com/data-privacy-stack/presidio/blob/main/docs/samples/deployments/openai-anonymaztion-and-deanonymaztion-best-practices/index.md), [LlamaIndex](https://github.com/run-llama/llama_index), [DSPy](https://github.com/stanfordnlp/dspy), [UK GDPR Article 4](https://www.legislation.gov.uk/eur/2016/679/article/4), [Article 25](https://www.legislation.gov.uk/eur/2016/679/article/25), [Article 32](https://www.legislation.gov.uk/eur/2016/679/article/32), [Carrell et al. 2013](https://doi.org/10.1136/amiajnl-2012-001034).
