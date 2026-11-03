---
title: Project Backlog
type: backlog
applies-to: bidwright
related: ["[[Master-Plan]]", "[[Decision-Form]]", "[[Research-Register]]"]
date: 2026-11-02
status: current
tags: [bidwright, backlog]
---

# Project Backlog

> [!info] What this holds
> Work that is known but not in the current iteration: items deferred to a later iteration, research held in reserve, and items not planned, each with its reason. Scheduled work lives in the work-package register of [[Master-Plan]].

## Deferred, with a target

| Item | Found in | Target | Why it waits |
|---|---|---|---|
| The `risk` retry drops a rejected risk instead of rewording it | The failure log, 2026-11-02 | Iteration 3 | The full `risk` agent reworks the loop and its prompt |
| Risk-seed recall: 1 of 3 on `free`, 0 of 3 on `local` | The 0a scorecards | Iterations 1 and 3 | Prompt and loop work, judged by the RK ablation against its fixed control |
| Narrative passages come back as `BACKGROUND` items, and the invitation to bid was once recorded as `OPTIONAL` | The 0a samples | Iteration 1 | `triage` zones and `candidates` change what reaches `extract` |
| S-04 on Cerebras | The spike register | Iteration 3 | No Cerebras key before Iteration 3 (D-03) |
| C7-04 in full and C7-14 for Streamlit | The Context7 register | Iteration 6 | Needed only by the bake-off and the UI |
| The `app` service exits after printing its help under `docker compose up -d` | The 0a Docker check | Iteration 6 | Iteration 0a has no long-running app service; Streamlit arrives in Iteration 6 |
| The IDE's type checker flags LangGraph's `add_node` overload with `input_schema`; pyright, which CI runs, passes | The editor | When LangGraph's type stubs change | No runtime effect |
| A plan for better results from local models, the long-term aim behind D-05's privacy tiers | The owner, 2026-11-03 | The Iteration 5 exit, before the Iteration 6 design doc | It needs measured gaps between hosted and local runs: Iteration 5's PV0, PV1 and PV3 tiers if D-05 takes C8, or the Iteration 6 bake-off otherwise. Levers to weigh: model choice per role, smaller tasks per call, prompts optimized on quality and leakage together as in DSPy's PAPILLON, structured output, context size and the GPU path. Training or fine-tuning is a non-goal, and would need an ADR. |

## Research in reserve

| Item | Runs when |
|---|---|
| DR-02, batching | Only if S-03 is inconclusive |
| DR-04, Docling fidelity | Only if S-01 is inconclusive |
| DR-06, the boundary of one obligation per record | Only if matching disputes appear |
| DR-14, a curated capability library | Backlog |
| DR-15, English-only scope | Backlog, unless non-English briefs are expected |
| H-02 to H-05: notebook repairs, a trace, report-only mind maps, a source audit | Backlog |

## Not planned, on merit

| Item | Why |
|---|---|
| A win-probability (Pwin) model | No rate or competitor data exists, and an invented probability is pseudo-precision |
| A reranker | Lexical retrieval comes first, and Iteration 7 measures dense retrieval with fusion; a reranker only if that fails |
| A vector database | No measured need; the same Iteration 7 comparison decides |
| Grammar-engine tuning | Providers' structured output suffices, and code validates every response |
| Formal methods with Z3 | No measured benefit at this size |
| Drift monitoring, canary and shadow runs, latency SLOs, user ratings | They need live traffic or users |
| Authentication, multi-tenancy, Kubernetes | Production concerns, covered as the production path in `docs/product.md` in Iteration 5 |
