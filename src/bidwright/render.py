"""Render a run's records into the 0a outputs, all labeled `UNREVIEWED_DRAFT`.

`render` is the only writer of `solution_summary.md` and `.json`, `proposal.md`,
`run_manifest.json` and `ledger.jsonl`. Every record is validated against its schema first,
and a schema failure blocks all output. The summary lists hazards first, then the rest of the
binding requirements, then the optional ones, then the approach, the risks and the open
questions. Rejected quotes and the other dispositions are counted, not listed.
"""

import json
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError

from bidwright.schemas import (
    ApproachItem,
    LedgerEntry,
    OpenQuestion,
    ProposalSection,
    Requirement,
    Risk,
    RunManifest,
    RunTotals,
    SolutionSummary,
)

STATUS_LINE = (
    "Status: UNREVIEWED_DRAFT. Every requirement below quotes the RFP, and a person must review"
    " this draft before anyone relies on it."
)


class RenderBlocked(Exception):
    """A record failed its schema, so nothing was written."""


@dataclass(frozen=True)
class RunRecords:
    run_id: str
    title: str
    requirements: list[Requirement]
    rejected: list[dict[str, Any]]
    approach: list[ApproachItem]
    unmapped: list[str]
    risks: list[Risk]
    questions: list[OpenQuestion]
    sections: list[ProposalSection]


def validated[ModelT: BaseModel](model: type[ModelT], rows: Sequence[Any]) -> list[ModelT]:
    """Validate every row from its data, so even an instance built without checks is checked."""
    try:
        return [
            model.model_validate(
                row.model_dump(warnings=False) if isinstance(row, BaseModel) else row
            )
            for row in rows
        ]
    except ValidationError as exc:
        raise RenderBlocked(f"{model.__name__} failed its schema: {exc}") from exc


def summary_of(records: RunRecords) -> SolutionSummary:
    listed = [r for r in records.requirements if r.disposition in ("BINDING", "OPTIONAL")]
    hazards = [r.id for r in listed if r.hazard]
    binding = [r.id for r in listed if r.disposition == "BINDING" and not r.hazard]
    optional = [r.id for r in listed if r.disposition == "OPTIONAL" and not r.hazard]
    status = Counter(r.quote_status for r in records.requirements)
    disposition = Counter(r.disposition for r in records.requirements)
    counts = {
        "verbatim_verified": status["VERBATIM_VERIFIED"],
        "normalized_match": status["NORMALIZED_MATCH"],
        "rejected": len(records.rejected),
        "background": disposition["BACKGROUND"],
        "not_binding": disposition["NOT_BINDING"],
        "out_of_scope": disposition["OUT_OF_SCOPE"],
        "unmapped": len(records.unmapped),
    }
    return SolutionSummary(
        run_id=records.run_id,
        hazards=hazards,
        requirements=binding + optional,
        approach=[a.id for a in records.approach],
        risks=[r.id for r in records.risks],
        open_questions=records.questions,
        counts=counts,
    )


def summary_markdown(records: RunRecords, summary: SolutionSummary) -> str:
    by_id = {r.id: r for r in records.requirements}
    lines = [
        f"# Solution summary: {records.title}",
        "",
        STATUS_LINE,
        "",
        f"Run `{records.run_id}`.",
        "",
    ]
    lines += ["## 1. Requirements", ""]

    def requirement_lines(heading: str, ids: list[str]) -> None:
        lines.extend([f"### {heading}", ""])
        if not ids:
            lines.extend(["None found.", ""])
            return
        for req_id in ids:
            r = by_id[req_id]
            lines.append(
                f'- **{r.id}** ({r.modality}): {r.statement} Source {r.src_ids[0]}: "{r.quote}"'
            )
        lines.append("")

    requirement_lines("Submission hazards", summary.hazards)
    binding = [i for i in summary.requirements if by_id[i].disposition == "BINDING"]
    optional = [i for i in summary.requirements if by_id[i].disposition == "OPTIONAL"]
    requirement_lines("Mandatory requirements", binding)
    requirement_lines("Optional requirements", optional)
    c = summary.counts
    lines += [
        f"Quotes: {c['verbatim_verified']} verbatim, {c['normalized_match']} normalized,"
        f" {c['rejected']} rejected (listed in `rejected.jsonl`). Also found, not listed:"
        f" {c['background']} background, {c['not_binding']} not binding,"
        f" {c['out_of_scope']} out of scope.",
        "",
        "## 2. Approach",
        "",
    ]
    for item in records.approach:
        lines.append(
            f"- **{item.id}** ({', '.join(item.requirement_ids)}): {item.text} Basis: {item.basis}"
        )
    if not records.approach:
        lines.append("No approach items.")
    if records.unmapped:
        lines.append(f"\nNot yet mapped to an approach item: {', '.join(records.unmapped)}.")
    lines += ["", "## 3. Risks", ""]
    for risk in records.risks:
        lines += [
            f"- **{risk.id}**: {risk.event}",
            f"  Condition: {risk.condition} Effect: {risk.effect}",
            f"  Owner: {risk.owner_role}. Trigger: {risk.trigger}"
            f" Responses: {' '.join(risk.responses)} Residual: {risk.residual_exposure}"
            f" Evidence: {', '.join(risk.evidence_src_ids)}.",
        ]
    if not records.risks:
        lines.append("No risks passed the checks.")
    lines += ["", "## 4. Open questions", ""]
    for question in records.questions:
        sources = f" ({', '.join(question.src_ids)})" if question.src_ids else ""
        lines.append(f"- {question.text}{sources}")
    if not records.questions:
        lines.append("None.")
    return "\n".join(lines) + "\n"


def proposal_markdown(records: RunRecords) -> str:
    lines = [f"# Proposal draft: {records.title}", "", STATUS_LINE, ""]
    for section in records.sections:
        lines += [f"## {section.title}", ""]
        lines.append(
            section.text if section.status == "CURRENT" else "_This section failed to draft._"
        )
        lines.append("")
    return "\n".join(lines)


def totals_of(ledger: Sequence[LedgerEntry], active_seconds: float) -> RunTotals:
    return RunTotals(
        requests=len(ledger),
        tokens_in=sum(e.tokens_in for e in ledger),
        tokens_out=sum(e.tokens_out for e in ledger),
        tokens_cached=sum(e.tokens_cached for e in ledger),
        tokens_thinking=sum(e.tokens_thinking for e in ledger),
        cost_usd=round(sum(e.cost_usd for e in ledger), 8),
        shadow_cost_usd=round(sum(e.shadow_cost_usd for e in ledger), 8),
        active_seconds=round(active_seconds, 3),
    )


def write_manifest(run_dir: Path, manifest: RunManifest, ledger: Sequence[LedgerEntry]) -> None:
    """Also used when a run stops early, so a failed run still leaves its manifest and ledger."""
    run_dir.mkdir(parents=True, exist_ok=True)
    body = "".join(entry.model_dump_json() + "\n" for entry in ledger)
    (run_dir / "ledger.jsonl").write_text(body, encoding="utf-8", newline="\n")
    (run_dir / "run_manifest.json").write_text(
        manifest.model_dump_json(indent=1) + "\n", encoding="utf-8", newline="\n"
    )


def render(run_dir: Path, records: RunRecords) -> SolutionSummary:
    """Validate everything, then write the summary, its JSON twin and the proposal."""
    requirements = validated(Requirement, records.requirements)
    approach = validated(ApproachItem, records.approach)
    risks = validated(Risk, records.risks)
    questions = validated(OpenQuestion, records.questions)
    sections = validated(ProposalSection, records.sections)
    checked = RunRecords(
        records.run_id,
        records.title,
        requirements,
        records.rejected,
        approach,
        records.unmapped,
        risks,
        questions,
        sections,
    )
    summary = summary_of(checked)
    twin = {
        "summary": summary.model_dump(mode="json"),
        "requirements": [r.model_dump(mode="json") for r in requirements],
        "approach": [a.model_dump(mode="json") for a in approach],
        "unmapped_requirement_ids": records.unmapped,
        "risks": [r.model_dump(mode="json") for r in risks],
    }
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "solution_summary.md").write_text(
        summary_markdown(checked, summary), encoding="utf-8", newline="\n"
    )
    (run_dir / "solution_summary.json").write_text(
        json.dumps(twin, indent=1, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n"
    )
    (run_dir / "proposal.md").write_text(proposal_markdown(checked), encoding="utf-8", newline="\n")
    return summary
