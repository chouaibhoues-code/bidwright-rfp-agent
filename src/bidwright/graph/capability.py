"""The capability map (Iteration 3, step 5; ADR-039): one row per need, its status set in code.

The status is checked in this order: `GAP` when no claim of the need is `SUPPORTED` or
`PARTIALLY_SUPPORTED`; else `PARTNER` when every supported claim is `partner_only`; else
`COVERED` when the decision is `RETRIEVE_EVIDENCE` and every claim is `SUPPORTED`; else
`PARTIAL`. A need past the need cap is `GAP`, undecided. `write_map` is the one writer of
`capability_map.json`.
"""

import json
from collections import Counter
from collections.abc import Sequence
from pathlib import Path

from bidwright.graph.decide import NEED_CAP_REASON, NeedPlan, cut
from bidwright.schemas import (
    ROW_TEXT_MAX_CHARS,
    CapabilityClaim,
    CapabilityMap,
    CapabilityRow,
    CoverageStatus,
    EvidenceAssessment,
    NeedDecision,
    NeedView,
)

SUPPORTING = frozenset({"SUPPORTED", "PARTIALLY_SUPPORTED"})


def row_text(need: NeedView) -> str:
    return cut(need.topic if need.origin == "RFP" else need.text, ROW_TEXT_MAX_CHARS)


def status(
    decision: NeedDecision, assessments: Sequence[EvidenceAssessment]
) -> tuple[CoverageStatus, str]:
    """A decided need's status and code's note on it."""
    supported = [a for a in assessments if a.disposition in SUPPORTING]
    if not supported:
        return "GAP", "no claim is supported"
    if all(a.partner_only for a in supported):
        return "PARTNER", "every supported claim rests on partner capabilities"
    if decision.decision == "RETRIEVE_EVIDENCE" and all(
        a.disposition == "SUPPORTED" for a in assessments
    ):
        return "COVERED", "every claim is supported"
    return "PARTIAL", "some claims are supported, or only in part"


def build_map(
    plan: NeedPlan,
    decisions: Sequence[NeedDecision],
    claims: Sequence[CapabilityClaim],
    assessments: Sequence[EvidenceAssessment],
) -> CapabilityMap:
    """One row per need in plan order, then the needs past the cap."""
    by_need = {d.need_id: d for d in decisions}
    by_claim = {a.claim_id: a for a in assessments}
    claims_of: dict[str, list[CapabilityClaim]] = {}
    for claim in claims:
        claims_of.setdefault(claim.need_id, []).append(claim)
    rows: list[CapabilityRow] = []
    for need in plan.needs:
        decision = by_need.get(need.need_id)
        own = claims_of.get(need.need_id, [])
        if decision is None:
            rows.append(
                CapabilityRow(
                    need_id=need.need_id,
                    origin=need.origin,
                    text=row_text(need),
                    status="GAP",
                    reason="not decided",
                )
            )
            continue
        found, reason = status(decision, [by_claim[c.id] for c in own if c.id in by_claim])
        rows.append(
            CapabilityRow(
                need_id=need.need_id,
                origin=need.origin,
                text=row_text(need),
                decision=decision.decision,
                status=found,
                claim_ids=[c.id for c in own],
                reason=reason,
            )
        )
    for need in plan.overflow:
        rows.append(
            CapabilityRow(
                need_id=need.need_id,
                origin=need.origin,
                text=row_text(need),
                status="GAP",
                reason=NEED_CAP_REASON,
            )
        )
    counts = Counter(row.status for row in rows)
    return CapabilityMap(
        rows=rows, counts={s: counts.get(s, 0) for s in ("COVERED", "PARTIAL", "PARTNER", "GAP")}
    )


def write_map(run_dir: Path, capability_map: CapabilityMap) -> None:
    """`capability_map.json`, written by this function only."""
    body = json.dumps(capability_map.model_dump(mode="json"), indent=1, ensure_ascii=False) + "\n"
    (run_dir / "capability_map.json").write_text(body, encoding="utf-8", newline="\n")
