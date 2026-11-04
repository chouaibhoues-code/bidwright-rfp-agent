"""Render a run's records into its outputs, all labeled `UNREVIEWED_DRAFT`.

`render` is the only writer of `solution_summary.md` and `.json`, `proposal.md`,
`run_manifest.json`, `ledger.jsonl`, and from Iteration 1 `compliance_matrix.xlsx` and `.csv`
(`render_xlsx.py`), `clarification_questions.md`, `submission_checklist.md` and
`review/quarantine.md`. Every record is validated against its schema first, and a schema
failure in any list blocks all output. The summary lists hazards first, then the rest of the
binding requirements, then the optional ones, then the approach, the risks and the open
questions. Rejected quotes and the other dispositions are counted, not listed, and the summary
never repeats quarantined text.
"""

import dataclasses
import json
import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError

from bidwright.candidates import cut
from bidwright.ingest import display_text
from bidwright.render_xlsx import write_matrix
from bidwright.schemas import (
    ApproachItem,
    CandidateRow,
    ClarificationQuestion,
    ContractFlag,
    ControlRegister,
    CoverageReport,
    Discrepancy,
    LedgerEntry,
    LintFinding,
    OpenQuestion,
    Passage,
    ProposalSection,
    QuarantineRecord,
    Requirement,
    RequirementGroup,
    RfpProfile,
    Risk,
    RunManifest,
    SolutionSummary,
    SubmissionHazard,
)

STATUS_LINE = (
    "Status: UNREVIEWED_DRAFT. Every requirement below quotes the RFP, and a person must review"
    " this draft before anyone relies on it."
)


class RenderBlocked(Exception):
    """A record failed its schema, so nothing was written."""


@dataclass(frozen=True)
class RunRecords:
    """Everything `render` reads. The Iteration 1 records default to empty, so a `v0.0`-shaped
    call still renders."""

    run_id: str
    title: str
    requirements: list[Requirement]
    rejected: list[dict[str, Any]]
    approach: list[ApproachItem]
    unmapped: list[str]
    risks: list[Risk]
    questions: list[OpenQuestion]
    sections: list[ProposalSection]
    passages: dict[str, Passage] = field(default_factory=dict)
    register: ControlRegister | None = None
    profile: RfpProfile | None = None
    hazards: list[SubmissionHazard] = field(default_factory=list)
    candidates: list[CandidateRow] = field(default_factory=list)
    coverage: CoverageReport | None = None
    groups: list[RequirementGroup] = field(default_factory=list)
    discrepancies: list[Discrepancy] = field(default_factory=list)
    clarifications: list[ClarificationQuestion] = field(default_factory=list)
    lint_findings: list[LintFinding] = field(default_factory=list)
    contract_flags: list[ContractFlag] = field(default_factory=list)
    quarantine: list[QuarantineRecord] = field(default_factory=list)


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
    lines += [*review_lines(records), ""]
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


def _count(number: int, noun: str) -> str:
    return f"{number} {noun}" if number == 1 else f"{number} {noun}s"


def review_lines(records: RunRecords) -> list[str]:
    """Counts that point to the review files, never their text."""
    small = sum(1 for p in records.passages.values() if p.small_print)
    suspect = sum(1 for p in records.passages.values() if p.suspect)
    return [
        f"Hidden content quarantined: {_count(len(records.quarantine), 'item')}; small print:"
        f" {_count(small, 'passage')}; suspect passages: {suspect}; see `review/quarantine.md`.",
        f"Requirement groups: {len(records.groups)}, in `requirement_groups.jsonl`.",
        f"Discrepancies: {len(records.discrepancies)}, in `discrepancies.jsonl`.",
        f"Clarification questions: {len(records.clarifications)}, in `clarification_questions.md`.",
        f"Contract flags for legal review: {len(records.contract_flags)}, in"
        " `contract_flags.jsonl`.",
    ]


def _fence(text: str) -> list[str]:
    """A fenced block one backtick longer than the longest run of backticks in the text, so
    the text appears exactly as found."""
    longest = max((len(run) for run in re.findall(r"`+", text)), default=0)
    fence = "`" * max(3, longest + 1)
    return [f"    {fence}", *(f"    {line}" for line in text.splitlines() or [""]), f"    {fence}"]


def _cut_note(text: str, limit: int = 500) -> tuple[str, str]:
    if len(text) <= limit:
        return text, ""
    return text[:limit], f"  (cut at {limit} of {len(text)} characters)"


def quarantine_markdown(records: RunRecords) -> str:
    """`review/quarantine.md`: hidden content removed, small print kept, suspect passages."""
    lines = [f"# Review: {records.title}", "", STATUS_LINE, ""]
    lines += [
        "## Hidden content removed before parsing",
        "These were hidden from a reader of the file and never reached a model. If one states a",
        "real obligation, raise a clarification question with the buyer.",
        "",
    ]
    for record in records.quarantine:
        text, note = _cut_note(record.text)
        lines += [f"- {record.id}, {record.file}, {record.location}", f"  ({record.kind}){note}"]
        lines += [*_fence(text), ""]
    if not records.quarantine:
        lines += ["None.", ""]
    for heading, intro, flag in (
        (
            "## Small print kept in the text",
            "These passages are set in type smaller than 6 pt. They stay in the requirement list.",
            "small_print",
        ),
        (
            "## Visible text that reads like an instruction to a model",
            "These passages stay in the text and are classified like any other.",
            "suspect",
        ),
    ):
        lines += [heading, intro, ""]
        chosen = [p for p in records.passages.values() if getattr(p, flag)]
        for passage in chosen:
            text, note = _cut_note(display_text(passage.text))
            lines += [f"- {passage.id}, {passage.section_path or passage.doc_id}{note}"]
            lines += [*_fence(text), ""]
        if not chosen:
            lines += ["None.", ""]
    return "\n".join(lines)


def clarifications_markdown(records: RunRecords) -> str:
    """`clarification_questions.md`: questions grouped by their group's topic."""
    by_id = {r.id: r for r in records.requirements}
    lines = [f"# Clarification questions: {records.title}", "", STATUS_LINE, ""]
    for group in records.groups:
        asked = [q for q in records.clarifications if q.group_id == group.id]
        if not asked:
            continue
        lines += [f"## {group.topic} ({group.id})", ""]
        for question in asked:
            lines.append(f"- **{question.id}** {question.text}")
            ids = ", ".join(question.requirement_ids) or "none"
            lines.append(f"  Requirements: {ids}. Origin: {question.origin}.")
            for rid in question.requirement_ids:
                if rid in by_id:
                    lines.append(f'  > {rid}: "{cut(by_id[rid].quote, 200)}"')
        lines.append("")
    if not records.clarifications:
        lines += ["No clarification questions.", ""]
    return "\n".join(lines)


def checklist_markdown(records: RunRecords) -> str:
    """`submission_checklist.md`: the deadline and format, then one box per hazard."""
    by_id = {r.id: r for r in records.requirements}
    profile = records.profile or RfpProfile()
    lines = [f"# Submission checklist: {records.title}", "", STATUS_LINE, ""]
    lines += [
        f"Deadline: {profile.submission_deadline}",
        f"Format: {profile.submission_format}",
        "",
    ]
    covered: set[str] = set()
    for kind in dict.fromkeys(h.kind for h in records.hazards):
        lines += [f"## {kind}", ""]
        for hazard in (h for h in records.hazards if h.kind == kind):
            covered.update(hazard.requirement_ids)
            ids = ", ".join(hazard.requirement_ids) or "no requirement yet"
            quote = _hazard_quote(hazard, by_id, records.passages)
            lines.append(f'- [ ] **{hazard.id}** {hazard.summary} ({ids}) "{quote}"')
        lines.append("")
    others = [r for r in records.requirements if r.hazard and r.id not in covered]
    if others:
        lines += ["## Other requirements flagged as hazards", ""]
        lines += [f'- [ ] **{r.id}** {r.statement} "{cut(r.quote, 200)}"' for r in others]
        lines.append("")
    if not records.hazards and not others:
        lines += ["No submission hazards found.", ""]
    return "\n".join(lines)


def _hazard_quote(
    hazard: SubmissionHazard, by_id: dict[str, Requirement], passages: dict[str, Passage]
) -> str:
    for rid in hazard.requirement_ids:
        if rid in by_id:
            return cut(by_id[rid].quote, 200)
    passage = passages.get(hazard.src_ids[0])
    return cut(display_text(passage.text), 200) if passage else ""


def proposal_markdown(records: RunRecords) -> str:
    lines = [f"# Proposal draft: {records.title}", "", STATUS_LINE, ""]
    for section in records.sections:
        lines += [f"## {section.title}", ""]
        lines.append(
            section.text if section.status == "CURRENT" else "_This section failed to draft._"
        )
        lines.append("")
    return "\n".join(lines)


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
    if records.profile is not None:
        validated(RfpProfile, [records.profile])
    if records.coverage is not None:
        validated(CoverageReport, [records.coverage])
    if records.register is not None:
        validated(ControlRegister, [records.register])
    checked = dataclasses.replace(
        records,
        requirements=requirements,
        approach=approach,
        risks=risks,
        questions=questions,
        sections=sections,
        passages={p.id: p for p in validated(Passage, list(records.passages.values()))},
        hazards=validated(SubmissionHazard, records.hazards),
        candidates=validated(CandidateRow, records.candidates),
        groups=validated(RequirementGroup, records.groups),
        discrepancies=validated(Discrepancy, records.discrepancies),
        clarifications=validated(ClarificationQuestion, records.clarifications),
        lint_findings=validated(LintFinding, records.lint_findings),
        contract_flags=validated(ContractFlag, records.contract_flags),
        quarantine=validated(QuarantineRecord, records.quarantine),
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
    write_matrix(run_dir, checked, STATUS_LINE)
    for name, body in (
        ("clarification_questions.md", clarifications_markdown(checked)),
        ("submission_checklist.md", checklist_markdown(checked)),
        ("review/quarantine.md", quarantine_markdown(checked)),
    ):
        path = run_dir / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8", newline="\n")
    return summary
