"""`assess` (Iteration 3, step 5): what the assessor sees, code's checks on its answer, the
serving route, and the same-family rule."""

from pathlib import Path

from bidwright.config import load_config
from bidwright.graph.assess import (
    NO_EVIDENCE,
    SAME_FAMILY,
    assess_claim,
    assessment_task,
    assessor_of,
    same_family_reason,
    write_assessments,
)
from bidwright.graph.decide import plan_needs
from bidwright.graph.nodes import CallManifests
from bidwright.harness.context import ContextManager
from bidwright.kb import load_kb
from bidwright.llm.client import route_config
from bidwright.schemas import CapabilityClaim, RequirementGroup
from tests.node_fakes import RuleBackend, ScriptBackend, context, dev_ingest, requirement, text

CONFIG = load_config()
KB = load_kb()
SIGNATURE = requirement(1, "SRC-0015", "The Supplier shall provide electronic signature of forms.")
PLAN = plan_needs(
    [RequirementGroup(id="RG-001", member_ids=["REQ-0001"], topic="Signature", llm=False)],
    [SIGNATURE],
    None,
    cap=24,
)
NEED = PLAN.needs[0]
CLAIM = CapabilityClaim(
    id="CL-001",
    need_id="RG-001",
    kind="capability",
    text="Forms are signed electronically through a partner e-signature product.",
    evidence_ids=["CAP-012"],
    src_ids=["SRC-0015"],
)
ASSESSOR = assessor_of(route_config(CONFIG, "free", "assess", "primary"), "assess@0.1.0")
DECIDE_REASON = "A record supports it, the decider argued at length."


def test_assess_no_evidence_makes_no_call() -> None:
    backend = ScriptBackend([])
    bare = CLAIM.model_copy(update={"evidence_ids": []})
    outcome = assess_claim(context(backend), bare, NEED, KB, assessor=ASSESSOR, same_family=False)
    assessment = outcome.assessment
    assert (assessment.disposition, assessment.reason, assessment.called) == (
        "UNVERIFIED",
        NO_EVIDENCE,
        False,
    )
    assert assessment.assessor is None and backend.requests == []


def test_assess_never_receives_the_authors_reasoning() -> None:
    backend = RuleBackend()
    assess_claim(context(backend), CLAIM, NEED, KB, assessor=ASSESSOR, same_family=False)
    sent = "\n".join(m.content for r in backend.requests for m in r.messages)
    assert DECIDE_REASON not in sent and "decider" not in sent
    task = assessment_task(CLAIM, NEED, {r.id: r for r in KB.records()})
    assert [e.id for e in task.evidence] == ["CAP-012"]
    assert "Tags: partner." in task.evidence[0].text
    assert task.need_text == SIGNATURE.statement


def test_an_uncited_id_is_dropped_and_supported_with_none_left_is_unverified() -> None:
    answer = {
        "reason": "CAP-001 states it.",
        "disposition": "SUPPORTED",
        "supporting_ids": ["CAP-001"],
    }
    backend = ScriptBackend([text(answer)])
    outcome = assess_claim(context(backend), CLAIM, NEED, KB, assessor=ASSESSOR, same_family=False)
    assert outcome.assessment.disposition == "UNVERIFIED"
    assert outcome.assessment.supporting_ids == []
    assert any("CAP-001 is not cited" in note for note in outcome.notes)
    assert any("becomes UNVERIFIED" in note for note in outcome.notes)


def test_partner_only_support_is_flagged_and_the_route_is_recorded() -> None:
    outcome = assess_claim(
        context(RuleBackend()), CLAIM, NEED, KB, assessor=ASSESSOR, same_family=False
    )
    assessment = outcome.assessment
    assert assessment.disposition == "SUPPORTED" and assessment.partner_only
    assert assessment.assessor is not None
    assert (assessment.assessor.provider, assessment.assessor.model) == ("cerebras", "gpt-oss-120b")
    assert assessment.assessor.base_url == "https://api.cerebras.ai/v1"
    own = CLAIM.model_copy(update={"evidence_ids": ["CAP-002"]})
    assert not assess_claim(
        context(RuleBackend()), own, NEED, KB, assessor=ASSESSOR, same_family=False
    ).assessment.partner_only


def test_a_same_family_route_flags_every_assessment_and_degrades_free_not_local() -> None:
    same = route_config(CONFIG, "free", "assess", "same")
    flagged = assess_claim(
        context(RuleBackend()),
        CLAIM,
        NEED,
        KB,
        assessor=assessor_of(same, "assess@0.1.0"),
        same_family=True,
    )
    assert flagged.assessment.same_family
    assert flagged.assessment.assessor is not None and flagged.assessment.assessor.base_url is None
    assert same_family_reason("same", CONFIG.models.role("free", "assess")) == SAME_FAMILY
    assert same_family_reason("primary", CONFIG.models.role("local", "assess")) is None
    assert same_family_reason("same", CONFIG.models.role("local", "assess")) is None


def test_context_manifests_name_the_claim(tmp_path: Path) -> None:
    manifests = CallManifests(
        ContextManager(tmp_path, CONFIG.limits.context, dev_ingest().passages),
        CONFIG.limits.context.budgets["assess"],
    )
    assess_claim(
        context(RuleBackend()),
        CLAIM,
        NEED,
        KB,
        assessor=ASSESSOR,
        same_family=False,
        manifests=manifests,
    )
    assert [p.name for p in (tmp_path / "context").glob("assess-*.json")] == ["assess-CL-001.json"]
    write_assessments(tmp_path, [])
    assert (tmp_path / "assessments.jsonl").read_text(encoding="utf-8") == ""
