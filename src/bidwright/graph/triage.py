"""`triage`: one zone per section, the RFP's profile and its submission hazards (Iteration 1,
step 10; ADR-018).

A section is each distinct `(doc_id, section_path)` with at least one passage, in reading
order; the passages before the first heading form the section with the empty path. Each
section becomes one `SectionView`: its heading path, its document's role from the control
register (`main` without one), its first two passages as the text view shows them, each opened
by its id in square brackets so a hazard can cite it, its passage count, and how many of its
passages carry each cue kind. `ContextManager.pack_sections` packs the views into calls of the
`triage` budget, `T01` onward, each with its manifest, and each call goes through
`RunContext.structured`: one call, and one format repair.

Code then settles the answer:
- a section takes the model's zone when its confidence reaches the threshold of
  `config/zones.yaml`, and the keyword rule otherwise, with `source` saying which; a section
  the model omits takes the keyword rule, and a section the model invents is dropped;
- when a call breaks its schema twice, every section of that call takes the keyword rule, and
  the run is marked DEGRADED with "triage: zone fallback";
- the profile takes, field by field, the first value that is not `not_stated`, in call order;
- a hazard loses its ids outside the package, a hazard left with no id is dropped, and so is
  one whose ids repeat an earlier hazard's; the rest are numbered `HZ-001` onward.

The keyword rule matches the zones' keywords case-insensitively against the section's heading
text, its section path from the top, so a subsection with no keyword of its own takes its
parent's; zones are tried in the order the file lists them, the first match wins, and a
section with no match gets the default zone. `triage` writes `triage.json`, a `TriageRecord`,
and returns the hazards; `verify` writes `hazards.json`.
"""

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from bidwright.candidates import cut
from bidwright.config import ZonesConfig
from bidwright.graph.nodes import RunContext
from bidwright.harness.context import ContextManager, prompt_tokens
from bidwright.harness.view import IdentityView, TextView
from bidwright.schemas import (
    FIRST_TEXT_MAX_CHARS,
    ControlRegister,
    CueHit,
    CueKind,
    DocRole,
    Passage,
    RfpProfile,
    SectionView,
    SubmissionHazard,
    TriageInput,
    TriageRecord,
    TriageResult,
    ZoneAssignment,
    ZoneRecord,
)

NODE = "triage"
NOT_STATED = "not_stated"
FALLBACK_REASON = "triage: zone fallback"
FIRST_PASSAGES = 2


@dataclass(frozen=True)
class TriageOutcome:
    record: TriageRecord
    hazards: list[SubmissionHazard]
    degraded: str | None  # FALLBACK_REASON when a call broke its schema twice


def section_views(
    passages: Sequence[Passage],
    *,
    register: ControlRegister | None = None,
    cues: Sequence[CueHit] = (),
    view: TextView | None = None,
) -> list[SectionView]:
    """One view per section, in reading order."""
    shown = view or IdentityView(passages)
    roles: dict[str, DocRole] = (
        {entry.doc_id: entry.role for entry in register.documents} if register else {}
    )
    kinds: dict[str, list[CueKind]] = {hit.src_id: hit.kinds for hit in cues}
    members: dict[tuple[str, str], list[Passage]] = {}
    for passage in passages:
        members.setdefault((passage.doc_id, passage.section_path), []).append(passage)
    views = []
    for (doc_id, section_path), group in members.items():
        opening = " ".join(f"[{p.id}] {shown.text(p)}" for p in group[:FIRST_PASSAGES])
        counts: Counter[CueKind] = Counter(k for p in group for k in kinds.get(p.id, []))
        views.append(
            SectionView(
                section_path=section_path,
                doc_id=doc_id,
                role=roles.get(doc_id, "main"),
                first_text=cut(opening, FIRST_TEXT_MAX_CHARS),
                passages=len(group),
                cue_counts=dict(counts),
            )
        )
    return views


def keyword_zone(section_path: str, zones: ZonesConfig) -> tuple[str, str | None]:
    """The zone the heading keywords give, and the keyword that matched, if any."""
    heading = section_path.lower()
    for zone, definition in zones.zones.items():
        for keyword in definition.keywords:
            if keyword.lower() in heading:
                return zone, keyword
    return zones.default, None


def _by_keywords(view: SectionView, zones: ZonesConfig, confidence: float = 0.0) -> ZoneRecord:
    zone, keyword = keyword_zone(view.section_path, zones)
    reason = (
        f'heading keyword "{keyword}"' if keyword else "no heading keyword, so the default zone"
    )
    return ZoneRecord.model_validate(
        {
            "section_path": view.section_path,
            "doc_id": view.doc_id,
            "zone": zone,
            "confidence": confidence,
            "reason": reason,
            "source": "keywords",
        }
    )


def _settle(
    views: Sequence[SectionView], result: TriageResult, zones: ZonesConfig
) -> list[ZoneRecord]:
    answered: dict[tuple[str, str], ZoneAssignment] = {}
    for assignment in result.zones:
        answered.setdefault((assignment.doc_id, assignment.section_path), assignment)
    records = []
    for view in views:
        assignment = answered.get((view.doc_id, view.section_path))
        if assignment is None:
            records.append(_by_keywords(view, zones))
        elif assignment.confidence >= zones.confidence_threshold:
            records.append(ZoneRecord(**assignment.model_dump(), source="model"))
        else:
            records.append(_by_keywords(view, zones, assignment.confidence))
    return records


def merge_profiles(profiles: Sequence[RfpProfile]) -> RfpProfile:
    """Field by field, the first value that is not `not_stated`, in call order."""
    merged: dict[str, str] = {}
    for name in RfpProfile.model_fields:
        values = [getattr(p, name) for p in profiles if getattr(p, name) != NOT_STATED]
        merged[name] = values[0] if values else NOT_STATED
    return RfpProfile(**merged)


def merge_hazards(results: Sequence[TriageResult], package: set[str]) -> list[SubmissionHazard]:
    """Hazards in call order, with ids outside the package dropped, empty and repeated
    hazards dropped, numbered `HZ-001` onward."""
    hazards: list[SubmissionHazard] = []
    seen: set[frozenset[str]] = set()
    for result in results:
        for proposal in result.hazards:
            ids = [s for s in dict.fromkeys(proposal.src_ids) if s in package]
            if not ids or frozenset(ids) in seen:
                continue
            seen.add(frozenset(ids))
            hazards.append(
                SubmissionHazard(
                    id=f"HZ-{len(hazards) + 1:03d}",
                    kind=proposal.kind,
                    src_ids=ids,
                    summary=proposal.summary,
                )
            )
    return hazards


def triage(
    ctx: RunContext,
    passages: Sequence[Passage],
    *,
    manager: ContextManager,
    zones: ZonesConfig,
    budget_tokens: int,
    run_dir: Path,
    register: ControlRegister | None = None,
    cues: Sequence[CueHit] = (),
    view: TextView | None = None,
) -> TriageOutcome:
    """Zone every section, merge the profile and hazards, and write `triage.json`."""
    prompt = ctx.prompts[NODE]
    views = section_views(passages, register=register, cues=cues, view=view)
    packs = manager.pack_sections(
        views,
        fixed_tokens=prompt_tokens(prompt, manager.limits.chars_per_token),
        budget_tokens=budget_tokens,
    )
    records: list[ZoneRecord] = []
    results: list[TriageResult] = []
    degraded = None
    for pack in packs:
        members = manager.sections_in(pack, views)
        data = TriageInput(sections=members).model_dump_json()
        rendered = prompt.render(data, run_id=ctx.run_id, call_id=pack.call_id)
        result, _ = ctx.structured(
            prompt, rendered.messages, TriageResult, node=NODE, input_hash=rendered.input_hash
        )
        if not isinstance(result, TriageResult):
            degraded = FALLBACK_REASON
            records += [_by_keywords(member, zones) for member in members]
            continue
        results.append(result)
        records += _settle(members, result, zones)
    record = TriageRecord(
        zones=records,
        profile=merge_profiles([r.profile for r in results]),
        fallback_sections=sum(1 for r in records if r.source == "keywords"),
    )
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "triage.json").write_text(
        record.model_dump_json(indent=1) + "\n", encoding="utf-8", newline="\n"
    )
    hazards = merge_hazards(results, {p.id for p in passages})
    return TriageOutcome(record=record, hazards=hazards, degraded=degraded)


__all__ = [
    "FALLBACK_REASON",
    "TriageOutcome",
    "keyword_zone",
    "merge_hazards",
    "merge_profiles",
    "section_views",
    "triage",
]
