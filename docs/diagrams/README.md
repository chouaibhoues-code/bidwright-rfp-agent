# Submission diagrams

**Status: `UNREVIEWED_DRAFT`.** These editable views describe the accepted Iteration 3 target, prepared 2026-11-05. They do not establish that the final implementation or its quality gates have passed. The final release review checks the diagrams against the integrated graph, configuration and run evidence.

Open [bidwright.drawio](bidwright.drawio) in draw.io / diagrams.net. It contains four named pages. Shapes, labels, boundaries and connectors are native editable objects. Individual pages are also supplied as `.drawio` files, with SVG previews for documentation.

| Page | Editable page | Preview | Purpose |
|---|---|---|---|
| 01 System architecture | [draw.io](01-system-architecture.drawio) | [SVG](01-system-architecture.svg) | Inputs, local producer, external services, outputs and the separate evaluation boundary |
| 02 Iteration 3 workflow | [draw.io](02-iteration-3-workflow.drawio) | [SVG](02-iteration-3-workflow.svg) | Numbered execution path, revision, gate edits and blocked outcomes |
| 03 Evidence and approval | [draw.io](03-evidence-and-approval.drawio) | [SVG](03-evidence-and-approval.svg) | Claims, blind assessment, deterministic coverage and human decisions |
| 04 Evaluation and observability | [draw.io](04-evaluation-and-observability.drawio) | [SVG](04-evaluation-and-observability.svg) | Scorecards, controlled comparisons, ledger reconciliation and traces |

To open the master file in the web editor, visit [diagrams.net](https://app.diagrams.net/) and choose **File → Open From → Device**, then select `bidwright.drawio`. The page tabs select each view. Save changes as `.drawio` to retain editability. Use **File → Export as → SVG** or **PNG** for README images or the demo. These diagrams use native shapes and text, with no custom fonts, remote images or plugins.

The master file is the editing source. Individual files and previews are convenience copies; after an edit, export the affected page and refresh its copies. Each page uses a 1600 × 1000 landscape canvas. SVG previews remain sharp when scaled.

## Reading the diagrams

- Blue marks checked code and orchestration; purple marks LLM functions; green marks tool-using agents or permitted continuation; gold marks the human review surface; gray marks services; white marks artifacts.
- Solid arrows show the primary flow. Dashed arrows show revision or human-edit feedback. Grouped boxes summarize multiple implementation nodes; the design document owns the exact graph.
- Research is external context, not supplier capability evidence. `assess` receives cited records and the need, without the author's reasoning.
- `pack` avoids live documentation lookup; technology verdicts still use model calls. A keyless demo uses recorded responses.
- The producer reads no evaluation gold or corpus specifications. The UI reads score results, not gold; controls delegate to CLI functions.
- Gate approval permits drafting, while every product output stays `UNREVIEWED_DRAFT`. It never submits a bid.
- Method cards and `reflect` start disabled. The main workflow omits ablation switches, worker joins and bounded repair details for readability.

Use page 1 for a short architecture explanation, page 2 for the technical walk-through, page 3 beside the real approval capture, and page 4 beside evaluation and cost evidence. The [walk-through script](../demo_script_ui.md) keeps the working app and its actual run records at the center of the follow-up session.

## Source and release checks

The views follow [the Iteration 3 graph and contracts](../designs/iteration-3.md#41-graph), [the accepted decisions](../../DECISIONS.md), [the runtime architecture](../architecture.md) for the inherited components, and [the submission handoff](../submission.md).

Before submission, check the final graph, model routes and tool allowlists; the real approval/edit behavior; the evaluation boundary; and the active UI/API commands. Retain the target label until the implementation has been verified. Acceptance values on page 4 are targets, not measured results. The files were checked for valid XML, unique cell IDs, connector references, text fit and page bounds; the matching previews were visually reviewed. Opening and export in the actual draw.io editor remains a final check because browser control was unavailable during generation.
