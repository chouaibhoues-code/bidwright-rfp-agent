"""`assess` (Iteration 3, step 5; ADR-045): one call per claim that cites evidence, on the
`assess` role's route, which is not the generator's family unless it fell back.

`assessment_task` builds what the assessor sees from the claim, its cited knowledge-base
records in full and its need's statements or text, and nothing else: never `decide`'s turns,
its reason or the other claims. `assess_claim` makes the call and applies code's checks: a
supporting id outside the cited ones is dropped, `SUPPORTED` or `PARTIALLY_SUPPORTED` with no
supporting id left becomes `UNVERIFIED`, and a claim is `partner_only` when every supporting
id names a capability tagged `partner`. A claim with no evidence is `UNVERIFIED` in code, with
no call. Each assessment records its serving route (Q-04): the provider, model, base URL and
prompt. `write_assessments` is the one writer of `assessments.jsonl`. Context manifests name
the claim: `context/assess-CL-004.json` (ADR-039's `UNIT_NODES`).
"""

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from bidwright.config import RoleConfig
from bidwright.graph.decide import cut
from bidwright.graph.nodes import CallManifests, RunContext
from bidwright.kb import Capability, CaseStudy, Certification, KnowledgeBase, Role, record_view
from bidwright.llm.client import OPENAI_COMPAT
from bidwright.schemas import (
    ASSESS_REASON_MAX_CHARS,
    MISSING_MAX_CHARS,
    AssessmentResult,
    AssessmentTask,
    Assessor,
    CapabilityClaim,
    EvidenceAssessment,
    EvidenceView,
    NeedView,
)

NODE = "assess"
NO_EVIDENCE = "no evidence cited"
SAME_FAMILY = "assess: SAME_FAMILY"
SUPPORTING = frozenset({"SUPPORTED", "PARTIALLY_SUPPORTED"})


def full_record(record: Capability | CaseStudy | Certification | Role) -> EvidenceView:
    """A record as the assessor sees it: every field that says what the supplier holds."""
    kind, name, text = record_view(record)
    if isinstance(record, Capability):
        text = f"{record.summary} Tags: {', '.join(record.tags)}."
    elif isinstance(record, CaseStudy):
        text = f"{record.client}, {record.sector}, {record.year}. {record.summary}"
    return EvidenceView(id=record.id, kind=kind, name=name, text=text)


def need_text(need: NeedView) -> str:
    if need.origin == "DOMAIN":
        return need.text
    return " ".join(r.statement for r in need.requirements)


def assessment_task(
    claim: CapabilityClaim,
    need: NeedView,
    records: Mapping[str, Capability | CaseStudy | Certification | Role],
) -> AssessmentTask:
    return AssessmentTask(
        claim_kind=claim.kind,
        claim_text=claim.text,
        evidence=[full_record(records[e]) for e in claim.evidence_ids if e in records],
        need_text=need_text(need),
    )


def assessor_of(role: RoleConfig, prompt_ref: str) -> Assessor:
    """The serving route of an assessment: the route's provider and model, with the base URL
    of an OpenAI-compatible provider, `None` for one with none here."""
    base = OPENAI_COMPAT.get(role.provider)
    return Assessor(
        provider=role.provider,
        model=role.model,
        base_url=base[0] if base else None,
        prompt=prompt_ref,
    )


def same_family_reason(route: str | None, role: RoleConfig | None) -> str | None:
    """The run's `DEGRADED` reason when `assess` fell back to the generator's family: route
    `same` on a profile whose `assess` names another family. On `local`, where the same family
    is configured, assessments are flagged and the run is not degraded."""
    if route == "same" and role is not None and not role.same_family:
        return SAME_FAMILY
    return None


@dataclass
class AssessOutcome:
    assessment: EvidenceAssessment
    notes: list[str] = field(default_factory=list)


def check(
    claim: CapabilityClaim,
    result: AssessmentResult,
    records: Mapping[str, Capability | CaseStudy | Certification | Role],
) -> tuple[AssessmentResult, bool, list[str]]:
    """The answer after code's checks, whether the claim is partner-only, and the notes."""
    cited = set(claim.evidence_ids)
    notes = [
        f"{claim.id}: supporting id {i} is not cited, dropped"
        for i in result.supporting_ids
        if i not in cited
    ]
    supporting = [i for i in dict.fromkeys(result.supporting_ids) if i in cited]
    disposition = result.disposition
    if disposition in SUPPORTING and not supporting:
        notes.append(f"{claim.id}: {disposition} with no supporting record becomes UNVERIFIED")
        disposition = "UNVERIFIED"
    if disposition not in SUPPORTING:
        supporting = []
    partner_only = bool(supporting) and all(
        isinstance(records.get(i), Capability) and "partner" in records[i].tags  # type: ignore[union-attr]
        for i in supporting
    )
    checked = AssessmentResult(
        reason=cut(result.reason, ASSESS_REASON_MAX_CHARS),
        disposition=disposition,
        supporting_ids=supporting,
        missing=cut(result.missing, MISSING_MAX_CHARS),
    )
    return checked, partner_only, notes


def assess_claim(
    ctx: RunContext,
    claim: CapabilityClaim,
    need: NeedView,
    kb: KnowledgeBase,
    *,
    assessor: Assessor,
    same_family: bool,
    manifests: CallManifests | None = None,
) -> AssessOutcome:
    """One claim's assessment: in code when it cites no evidence, else one call and one format
    repair, `<claim id>` and `<claim id>-repair`."""
    if not claim.evidence_ids:
        return AssessOutcome(
            EvidenceAssessment(
                claim_id=claim.id,
                disposition="UNVERIFIED",
                reason=NO_EVIDENCE,
                called=False,
                same_family=same_family,
            )
        )
    records = {r.id: r for r in kb.records()}
    prompt = ctx.prompts[NODE]
    data = assessment_task(claim, need, records).model_dump_json()
    rendered = prompt.render(data, run_id=ctx.run_id)
    cited = [claim.id, *claim.evidence_ids]

    def record(call_id: str, history: Sequence[object]) -> None:
        if manifests is not None:
            turns = list(history[len(rendered.messages) :])
            manifests.record(prompt, NODE, call_id, cited, data, turns)  # type: ignore[arg-type]

    record(claim.id, rendered.messages)
    parsed, _ = ctx.structured(
        prompt,
        list(rendered.messages),
        AssessmentResult,
        node=NODE,
        input_hash=rendered.input_hash,
        on_repair=lambda sent: record(f"{claim.id}-repair", sent),
    )
    if not isinstance(parsed, AssessmentResult):
        return AssessOutcome(
            EvidenceAssessment(
                claim_id=claim.id,
                disposition="UNVERIFIED",
                reason="the assessment broke its schema twice",
                assessor=assessor,
                same_family=same_family,
            ),
            [f"{claim.id}: the assessment broke its schema twice"],
        )
    checked, partner_only, notes = check(claim, parsed, records)
    return AssessOutcome(
        EvidenceAssessment(
            claim_id=claim.id,
            disposition=checked.disposition,
            reason=checked.reason,
            supporting_ids=checked.supporting_ids,
            missing=checked.missing,
            partner_only=partner_only,
            assessor=assessor,
            same_family=same_family,
        ),
        notes,
    )


def write_assessments(run_dir: Path, assessments: Sequence[EvidenceAssessment]) -> None:
    """`assessments.jsonl`, written by this function only, in claim order."""
    rows = sorted(assessments, key=lambda a: a.claim_id)
    body = "".join(json.dumps(a.model_dump(mode="json"), ensure_ascii=False) + "\n" for a in rows)
    (run_dir / "assessments.jsonl").write_text(body, encoding="utf-8", newline="\n")
