"""The capability map (Iteration 3, step 5): each status by its rule, `GAP` checked first and
`PARTNER` before `COVERED`, and needs past the cap listed undecided."""

import json
from pathlib import Path

import pytest

from bidwright.graph.capability import build_map, write_map
from bidwright.graph.decide import NEED_CAP_REASON, plan_needs
from bidwright.schemas import (
    CapabilityClaim,
    Decision,
    EvidenceAssessment,
    NeedDecision,
    RequirementGroup,
)
from tests.node_fakes import requirement

REQUIREMENTS = [
    requirement(n, f"SRC-{n:04d}", f"The Supplier shall do thing {n}.") for n in range(1, 4)
]
GROUPS = [
    RequirementGroup(id=f"RG-00{n}", member_ids=[f"REQ-000{n}"], topic=f"Topic {n}", llm=False)
    for n in range(1, 4)
]


def _claim(n: int, need: str) -> CapabilityClaim:
    return CapabilityClaim(
        id=f"CL-00{n}",
        need_id=need,
        kind="capability",
        text="t",
        evidence_ids=["CAP-001"],
        src_ids=["SRC-0001"],
    )


def _assessed(n: int, disposition: str, partner: bool = False) -> EvidenceAssessment:
    return EvidenceAssessment.model_validate(
        {
            "claim_id": f"CL-00{n}",
            "disposition": disposition,
            "partner_only": partner,
            "called": False,
        }
    )


def _decision(need: str, decision: Decision, claims: list[str]) -> NeedDecision:
    return NeedDecision(need_id=need, origin="RFP", decision=decision, claim_ids=claims)


@pytest.mark.parametrize(
    ("decision", "dispositions", "partner", "expected"),
    [
        ("RETRIEVE_EVIDENCE", ["SUPPORTED", "SUPPORTED"], False, "COVERED"),
        ("RETRIEVE_EVIDENCE", ["SUPPORTED", "UNVERIFIED"], False, "PARTIAL"),
        ("RETRIEVE_EVIDENCE", ["PARTIALLY_SUPPORTED"], False, "PARTIAL"),
        ("PROCEED_WITH_GAP", ["SUPPORTED"], False, "PARTIAL"),
        ("RETRIEVE_EVIDENCE", ["SUPPORTED"], True, "PARTNER"),
        ("RETRIEVE_EVIDENCE", ["UNVERIFIED", "CONTRADICTED"], True, "GAP"),
        ("PROCEED_WITH_GAP", [], False, "GAP"),
    ],
)
def test_each_status_follows_its_rule(
    decision: Decision, dispositions: list[str], partner: bool, expected: str
) -> None:
    plan = plan_needs(GROUPS[:1], REQUIREMENTS, None, cap=24)
    claims = [_claim(n, "RG-001") for n in range(1, len(dispositions) + 1)]
    assessments = [_assessed(n, d, partner) for n, d in enumerate(dispositions, start=1)]
    built = build_map(
        plan, [_decision("RG-001", decision, [c.id for c in claims])], claims, assessments
    )
    assert built.rows[0].status == expected
    assert built.rows[0].claim_ids == [c.id for c in claims]


def test_needs_past_the_cap_are_gaps_left_undecided(tmp_path: Path) -> None:
    plan = plan_needs(GROUPS, REQUIREMENTS, None, cap=2)
    decisions = [_decision("RG-001", "PROCEED_WITH_GAP", []), _decision("RG-002", "ABSTAIN", [])]
    built = build_map(plan, decisions, [], [])
    assert [(r.need_id, r.status) for r in built.rows] == [
        ("RG-001", "GAP"),
        ("RG-002", "GAP"),
        ("RG-003", "GAP"),
    ]
    assert built.rows[2].decision is None and built.rows[2].reason == NEED_CAP_REASON
    assert built.counts == {"COVERED": 0, "PARTIAL": 0, "PARTNER": 0, "GAP": 3}
    write_map(tmp_path, built)
    stored = json.loads((tmp_path / "capability_map.json").read_text(encoding="utf-8"))
    assert stored["rows"][0]["text"] == "Topic 1"
