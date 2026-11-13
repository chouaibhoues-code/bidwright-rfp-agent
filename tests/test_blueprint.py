"""`blueprint` (Iteration 3, step 7; ADR-043): P01's tree and closure repairs, P02's detail,
code's checks on the manifest, P03's revision and the manifest's view as `approach.json`."""

import json
from pathlib import Path
from typing import Any

import pytest

from bidwright.config import compile_patterns, load_config
from bidwright.graph.blueprint import (
    REMOVED,
    SCHEMA_FAILED,
    TREE_FAILED,
    BlueprintOutcome,
    Sources,
    approach_view,
    blueprint,
    plan_task,
    revise,
    sources,
    tree_problems,
    write_manifest,
)
from bidwright.graph.decide import plan_needs
from bidwright.graph.nodes import CallManifests, write_approach
from bidwright.harness.context import ContextManager
from bidwright.kb import load_kb
from bidwright.schemas import (
    BlueprintPlan,
    BlueprintPlanTask,
    BriefItem,
    CapabilityClaim,
    CapabilityMap,
    CapabilityRow,
    EvidenceAssessment,
    InvalidatedView,
    ManifestGap,
    OpportunityBrief,
    RequirementGroup,
    SolutionManifest,
    SolutionOption,
    StoredApproach,
)
from tests.node_fakes import ScriptBackend, context, dev_ingest, requirement, text
from tests.recordings import replay

CONFIG = load_config()
KB = load_kb()
AMOUNTS = compile_patterns(CONFIG.cues.kinds["AMOUNT"], "AMOUNT")
REQUIREMENTS = [
    requirement(1, "SRC-0015", "The Supplier shall provide electronic signature of forms."),
    requirement(2, "SRC-0016", "The Supplier shall integrate with the student record system."),
    requirement(
        3,
        "SRC-0017",
        "Bidders may offer an archive.",
        disposition="OPTIONAL",
        mandatory=False,
        modality="may",
    ),
]
GROUPS = [
    RequirementGroup(id=f"RG-00{n}", member_ids=[f"REQ-000{n}"], topic=f"Topic {n}", llm=False)
    for n in (1, 2, 3)
]
PLAN = plan_needs(GROUPS, REQUIREMENTS, None, cap=24)
CMAP = CapabilityMap(
    rows=[
        CapabilityRow(need_id="RG-001", origin="RFP", text="Topic 1", status="COVERED"),
        CapabilityRow(need_id="RG-002", origin="RFP", text="Topic 2", status="GAP"),
        CapabilityRow(need_id="RG-003", origin="RFP", text="Topic 3", status="PARTIAL"),
    ]
)


def _claim(n: int, need: str) -> CapabilityClaim:
    return CapabilityClaim(
        id=f"CL-00{n}",
        need_id=need,
        kind="capability",
        text=f"Claim {n}.",
        evidence_ids=["CAP-001"],
        src_ids=["SRC-0015"],
    )


CLAIMS = [_claim(1, "RG-001"), _claim(2, "RG-003"), _claim(3, "RG-003")]
ASSESSMENTS = [
    EvidenceAssessment(claim_id="CL-001", disposition="SUPPORTED", called=False),
    EvidenceAssessment(claim_id="CL-002", disposition="UNVERIFIED", called=False),
    EvidenceAssessment(claim_id="CL-003", disposition="PARTIALLY_SUPPORTED", called=False),
]


def option(gap_mode: str = "EXCLUDED") -> SolutionOption:
    return SolutionOption(
        id="OPT-1",
        name="Configured",
        approach=[
            StoredApproach(need_id="RG-001", delivery_mode="CONFIG", claim_ids=["CL-001"]),
            StoredApproach(need_id="RG-002", delivery_mode=gap_mode),  # type: ignore[arg-type]
            StoredApproach(need_id="RG-003", delivery_mode="CUSTOM", claim_ids=["CL-002"]),
        ],
    )


def src_for(gap_mode: str = "EXCLUDED") -> Sources:
    passages = {p.id: p for p in dev_ingest().passages}
    return sources(
        passages,
        REQUIREMENTS,
        PLAN,
        CMAP,
        option(gap_mode),
        CLAIMS,
        ASSESSMENTS,
        ["DI-001"],
        KB.roles,
        AMOUNTS,
    )


SRC = src_for()
TASK = plan_task(option(), PLAN, CLAIMS, ASSESSMENTS, None)


def node(code: str, *ids: str, name: str = "", deliverable: str = "") -> dict[str, Any]:
    return {
        "code": code,
        "name": name or f"Node {code}",
        "deliverable": deliverable,
        "requirement_ids": [i for i in ids if i.startswith("REQ")],
        "need_ids": [i for i in ids if i.startswith("RG")],
        "claim_ids": [i for i in ids if i.startswith("CL")],
    }


def plan(**changes: Any) -> dict[str, Any]:
    base = {
        "current_state": [],
        "target_state": [],
        "workstreams": [{"name": "Delivery", "objective": "Deliver the option."}],
        "wbs": [
            node("1", name="Delivery"),
            node("1.1", "REQ-0001", "RG-001", "CL-001"),
            node("1.2", "REQ-0003", "RG-003", "CL-002"),
        ],
        "assumptions": [],
        "ground_rules": [],
        "tech_claims": [],
    }
    return base | changes


def package(code: str, **changes: Any) -> dict[str, Any]:
    effort = {
        "low_days": 5,
        "high_days": 10,
        "basis": "analogy",
        "basis_text": "Similar work.",
        "role_ids": ["ROLE-001"],
        "uncertainty": "Moderate.",
    }
    base = {
        "code": code,
        "scope": f"Scope of {code}.",
        "exclusions": "Nothing else.",
        "acceptance": "The buyer's tests pass.",
        "effort": effort | changes.pop("effort", {}),
        "verification": [],
        "predecessors": [],
    }
    return base | changes


def detail(*packages: dict[str, Any], **changes: Any) -> dict[str, Any]:
    chosen = list(packages) or [package("1.1"), package("1.2")]
    base = {"packages": chosen, "pdca": [], "benefits": [], "win_themes": []}
    return base | changes


def manifests(tmp_path: Path) -> CallManifests:
    return CallManifests(
        ContextManager(tmp_path, CONFIG.limits.context, dev_ingest().passages),
        CONFIG.limits.context.budgets["blueprint"],
    )


def run(
    replies: list[Any],
    *,
    src: Sources = SRC,
    task: BlueprintPlanTask = TASK,
    tmp_path: Path | None = None,
) -> tuple[BlueprintOutcome, ScriptBackend]:
    backend = ScriptBackend([text(r) if isinstance(r, dict) else r for r in replies])
    calls = manifests(tmp_path) if tmp_path is not None else None
    return blueprint(context(backend), task, src, calls), backend


def check(manifest: SolutionManifest, name: str) -> tuple[bool, str]:
    found = next(c for c in manifest.checks if c.name == name)
    return found.passed, found.detail


def test_blueprint_closure(tmp_path: Path) -> None:
    src = src_for("PARTNER")  # RG-002 is not excluded, so its requirement must be placed
    second = plan(wbs=[*plan()["wbs"], node("1.3", name="Governance")])
    outcome, backend = run(
        [plan(), second, detail(package("1.1"), package("1.2"), package("1.3"))],
        src=src,
        task=plan_task(option("PARTNER"), PLAN, CLAIMS, ASSESSMENTS, None),
        tmp_path=tmp_path,
    )
    assert len(backend.requests) == 3
    closure = backend.requests[1].messages[-1].content
    assert "REQ-0002" in closure and "in no work package" in closure
    assert "REQ-0001" not in closure
    manifest = outcome.manifest
    assert manifest.gaps == [ManifestGap(requirement_id="REQ-0002", need_id="RG-002", status="GAP")]
    assert check(manifest, "hundred_percent") == (False, "REQ-0002")
    untraced = {p.code: p.untraced for p in manifest.work_packages}
    assert untraced == {"1.1": False, "1.2": False, "1.3": True}
    assert check(manifest, "backward_trace") == (False, "1.3")
    names = sorted(p.name for p in (tmp_path / "context").glob("blueprint-*.json"))
    assert names == ["blueprint-P01-closure.json", "blueprint-P01.json", "blueprint-P02.json"]


def test_an_excluded_need_goes_to_gaps_with_no_closure_repair() -> None:
    outcome, backend = run([plan(), detail()])
    assert len(backend.requests) == 2 and outcome.failure is None
    assert [g.requirement_id for g in outcome.manifest.gaps] == ["REQ-0002"]
    assert outcome.manifest.option_id == "OPT-1" and outcome.manifest.revision == 0


@pytest.mark.parametrize(
    ("wbs", "workstreams", "problem"),
    [
        ([node("1"), node("1.1"), node("1.1")], 1, "code 1.1 appears twice"),
        ([node("1"), node("1.2.1")], 1, "the parent 1.2 of 1.2.1 is missing"),
        ([node("1")], 1, "the breakdown is one level deep"),
        ([node("1"), node("1.1")], 2, "workstream 2 has no top-level node 2"),
        ([node("1"), node("1.1"), node("2"), node("2.1")], 1, "top-level node 2 has no workstream"),
        ([node("1"), node("1.a")], 1, "'1.a' is not a code"),
        ([], 1, "the breakdown is empty"),
    ],
)
def test_each_tree_problem_is_named(
    wbs: list[dict[str, Any]], workstreams: int, problem: str
) -> None:
    streams = [{"name": f"W{n}"} for n in range(workstreams)]
    found = tree_problems(BlueprintPlan.model_validate(plan(wbs=wbs, workstreams=streams)))
    assert any(problem in p for p in found), found
    assert tree_problems(BlueprintPlan.model_validate(plan())) == []


def test_a_tree_failure_gets_the_format_repair_and_a_second_is_a_blueprint_failure() -> None:
    twice = plan(wbs=[node("1"), node("1.1"), node("1.1")])
    outcome, backend = run([twice, plan(wbs=[node("1"), node("1.2.1")])])
    assert outcome.failure == TREE_FAILED and outcome.degraded() == TREE_FAILED
    assert outcome.plan is None and outcome.manifest.failed
    assert "code 1.1 appears twice" in backend.requests[1].messages[-1].content
    assert check(outcome.manifest, "tree") == (False, "the parent 1.2 of 1.2.1 is missing")
    assert [g.requirement_id for g in outcome.manifest.gaps] == ["REQ-0001", "REQ-0002"]

    repaired, backend = run([twice, plan(), detail()])
    assert repaired.failure is None and len(backend.requests) == 3


def test_a_schema_failure_twice_sets_blueprint_failed_and_keeps_what_settled() -> None:
    p01, _ = run(["not json", "still not json"])
    assert p01.failure == SCHEMA_FAILED and p01.manifest.failed and p01.manifest.work_packages == []

    p02, backend = run([plan(), "not json", "still not json"])
    assert p02.failure == SCHEMA_FAILED and p02.degraded() == SCHEMA_FAILED
    manifest = p02.manifest
    assert manifest.failed and [p.code for p in manifest.work_packages] == ["1.1", "1.2"]
    assert all(p.effort is None for p in manifest.work_packages)
    assert check(manifest, "dictionary") == (False, "no detail: P02 failed")
    assert any("P02" in note for note in manifest.notes)
    assert p02.plan is not None and len(backend.requests) == 3


def test_a_cycle_loses_its_closing_edge_and_an_unknown_predecessor_is_dropped() -> None:
    answer = detail(
        package("1.1", predecessors=["1.2"]),
        package("1.2", predecessors=["1.1", "9.9"]),
    )
    outcome, _ = run([plan(), answer])
    by_code = {p.code: p.predecessors for p in outcome.manifest.work_packages}
    assert by_code == {"1.1": ["1.2"], "1.2": []}
    passed, found = check(outcome.manifest, "schedule")
    assert not passed and "1.2 predecessors: 9.9" in found and "cycle: 1.2 after 1.1" in found


def test_effort_checks_fail_but_the_manifest_is_written(tmp_path: Path) -> None:
    answer = detail(
        package("1.1", effort={"low_days": 12, "high_days": 4}),
        package("1.2", effort={"role_ids": ["ROLE-999"]}),
    )
    outcome, _ = run([plan(), answer])
    passed, found = check(outcome.manifest, "effort")
    assert not passed
    assert "1.1: low_days above high_days" in found
    assert "1.2: no role the knowledge base holds" in found
    efforts = [p.effort for p in outcome.manifest.work_packages]
    assert all(e is not None and e.maturity == "CLASS_5" and e.provisional for e in efforts)
    write_manifest(tmp_path, outcome.manifest)
    stored = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert SolutionManifest.model_validate(stored) == outcome.manifest


def test_a_facts_class_is_its_strongest_sources_and_an_unsupported_claim_needs_proof() -> None:
    def fact(text: str, **ids: list[str]) -> dict[str, Any]:
        return {"text": text} | ids

    facts = plan(
        current_state=[
            fact("Signing is on paper.", src_ids=["SRC-9999"], requirement_ids=["REQ-0999"])
        ],
        target_state=[
            fact(
                "Forms are signed online.",
                requirement_ids=["REQ-0001"],
                claim_ids=["CL-001"],
                domain_item_ids=["DI-001"],
            )
        ],
        assumptions=[
            fact("The product signs forms.", claim_ids=["CL-001"]),
            fact("Colleges sign forms online.", domain_item_ids=["DI-001"]),
        ],
        ground_rules=[fact("Archives are built.", src_ids=["SRC-0017"], claim_ids=["CL-002"])],
    )
    outcome, _ = run([facts, detail()])
    m = outcome.manifest
    assert (m.current_state[0].evidence_class, m.current_state[0].source_ids) == ("ASSUMPTION", [])
    assert m.target_state[0].evidence_class == "RFP_SOURCE"
    assert m.target_state[0].source_ids == ["REQ-0001", "CL-001", "DI-001"]
    assert [a.evidence_class for a in m.assumptions] == ["CAPABILITY_EVIDENCE", "EXTERNAL_RESEARCH"]
    rule = m.ground_rules[0]
    assert (rule.evidence_class, rule.needs_proof) == ("ASSUMPTION", True)
    passed, found = check(m, "provenance")
    assert not passed and "SRC-9999" in found and "REQ-0999" in found


def test_a_work_packages_class_rests_on_its_claims() -> None:
    wbs = [
        node("1"),
        node("1.1", "REQ-0001", "RG-001", "CL-001"),
        node("1.2", "REQ-0003", "RG-003", "CL-002"),
        node("1.3", "RG-003", "CL-003"),
        node("1.4", "REQ-0001"),
    ]
    answer = detail(*(package(c) for c in ("1.1", "1.2", "1.3", "1.4")))
    outcome, _ = run([plan(wbs=wbs), answer])
    classes = {p.code: (p.evidence_class, p.needs_proof) for p in outcome.manifest.work_packages}
    assert classes == {
        "1.1": ("CAPABILITY_EVIDENCE", False),
        "1.2": ("ASSUMPTION", True),
        "1.3": ("CAPABILITY_EVIDENCE", False),
        "1.4": ("ASSUMPTION", False),
    }


def test_a_win_theme_without_a_supported_proof_is_no_proof() -> None:
    themes = [
        {"feature": "Signing", "metric": "Every form", "benefit": "Less paper", "proof_claim_id": p}
        for p in ("CL-001", "CL-002", None, "CL-999")
    ]
    outcome, _ = run([plan(), detail(win_themes=themes)])
    proofs = [(t.proof_claim_id, t.proof) for t in outcome.manifest.win_themes]
    assert proofs == [
        ("CL-001", "CL-001"),
        ("CL-002", "NO_PROOF"),
        (None, "NO_PROOF"),
        (None, "NO_PROOF"),
    ]
    assert not check(outcome.manifest, "win_theme_proof")[0]


def test_amounts_and_unheld_dates_are_dropped_from_facts_and_removed_from_text() -> None:
    held = min(SRC.known_dates).isoformat()
    facts = plan(
        assumptions=[
            {"text": "The service costs £40,000 a year."},
            {"text": "Go-live is on 2031-05-04."},
            {"text": f"The RFP names {held}."},
        ]
    )
    answer = detail(
        package("1.1", scope="Configure signing for $12,000 by 2031-05-04."), package("1.2")
    )
    outcome, _ = run([facts, answer])
    m = outcome.manifest
    assert [a.text for a in m.assumptions] == [f"The RFP names {held}."]
    scope = next(p.scope for p in m.work_packages if p.code == "1.1")
    assert scope == f"Configure signing for {REMOVED} by {REMOVED}."
    assert not check(m, "no_prices_or_dates")[0]
    assert sum("an amount or a date" in note for note in m.notes) == 2


def test_technology_claims_get_ids_kinds_and_their_work_package() -> None:
    claims = [
        {"text": "Uses pdfplumber.", "library": "pdfplumber", "version": "0.11", "wbs_code": "1.1"},
        {"text": "Forms are configured.", "library": None, "version": "2", "wbs_code": "1"},
        {"text": " ", "library": None},
    ]
    outcome, _ = run([plan(tech_claims=claims), detail()])
    found = [(t.id, t.kind, t.version, t.wbs_code) for t in outcome.manifest.tech_claims]
    assert found == [("TC-01", "LIBRARY", "0.11", "1.1"), ("TC-02", "NOT_CHECKABLE", None, None)]
    assert any("1 is not a work package" in note for note in outcome.manifest.notes)


def test_p03s_plan_is_settled_and_p02_runs_again_giving_revision_1(tmp_path: Path) -> None:
    wrong = {
        "text": "PDFs become PDF/A with to_pdfa().",
        "library": "pdfplumber",
        "wbs_code": "1.1",
    }
    first, _ = run([plan(tech_claims=[wrong]), detail()])
    assert first.plan is not None and len(first.manifest.tech_claims) == 1
    backend = ScriptBackend([text(plan()), text(detail())])
    invalid = InvalidatedView(text=wrong["text"], library="pdfplumber", reason="No such method.")
    revised = revise(
        context(backend),
        first.plan,
        [invalid],
        first.manifest,
        TASK.claims,
        SRC,
        manifests(tmp_path),
    )
    assert revised.manifest.revision == 1 and revised.manifest.tech_claims == []
    sent = backend.requests[0].messages[-1].content
    assert "current documentation contradicts" in sent and "to_pdfa" in sent
    names = sorted(p.name for p in (tmp_path / "context").glob("blueprint-*.json"))
    assert names == ["blueprint-P02-revision.json", "blueprint-P03.json"]

    failing = ScriptBackend(["not json", "still not json"])
    kept = revise(context(failing), first.plan, [invalid], first.manifest, TASK.claims, SRC)
    # The kept revision 0 counts as revised, so techcheck does not send it back again
    # (drift report 2026-11-12).
    assert kept.failure is None and kept.manifest.revision == 1
    assert kept.manifest.tech_claims == first.manifest.tech_claims
    assert "the revision failed" in kept.manifest.notes[-1]


def test_the_view_has_one_item_per_workstream_that_names_a_requirement(tmp_path: Path) -> None:
    two = plan(
        workstreams=[{"name": "Delivery", "objective": "Deliver it."}, {"name": "Governance"}],
        wbs=[*plan()["wbs"], node("2", name="Governance"), node("2.1", name="Reporting")],
    )
    outcome, _ = run([two, detail(package("1.1"), package("1.2"), package("2.1"))])
    view = approach_view(outcome.manifest, SRC, outcome.failure)
    assert [(i.id, i.requirement_ids, i.evidence_class) for i in view.items] == [
        ("APP-001", ["REQ-0001", "REQ-0003"], "ASSUMPTION")
    ]
    assert view.items[0].text == "Delivery: Deliver it." and view.items[0].basis == "Deliver it."
    assert view.items[0].source_ids == ["SRC-0015", "SRC-0017"]
    assert view.unmapped == ["REQ-0002"] and view.questions == [] and view.failure is None
    assert any("workstream 2 names no requirement" in n for n in outcome.manifest.notes)
    data = write_approach(tmp_path, view)
    assert json.loads((tmp_path / "approach.json").read_text(encoding="utf-8")) == data
    assert list(data) == ["items", "unmapped", "questions", "failure"]


def test_the_task_carries_the_option_the_needs_the_claims_and_the_brief() -> None:
    brief = OpportunityBrief(
        scope_in=[BriefItem(id="BI-001", text="Electronic signature.", src_ids=["SRC-0015"])],
        never=[BriefItem(id="BI-002", text="Never store forms abroad.", src_ids=["SRC-0016"])],
    )
    task = plan_task(option(), PLAN, CLAIMS, ASSESSMENTS, brief)
    assert task.option.option_id == "OPT-1" and len(task.option.approach) == 3
    assert [n.need_id for n in task.needs] == ["RG-001", "RG-002", "RG-003"]
    assert [(c.claim_id, c.disposition) for c in task.claims] == [
        ("CL-001", "SUPPORTED"),
        ("CL-002", "UNVERIFIED"),
        ("CL-003", "PARTIALLY_SUPPORTED"),
    ]
    assert [i.id for i in task.scope_in] == ["BI-001"] and [i.id for i in task.never] == ["BI-002"]


@pytest.mark.replay
def test_the_approach_node_writes_approach_json_as_v0_2_did(tmp_path: Path) -> None:
    result, _ = replay("demo", tmp_path)
    assert result.status in ("COMPLETED", "DEGRADED"), result.reason
    raw = (result.run_dir / "approach.json").read_text(encoding="utf-8")
    data = json.loads(raw)
    assert list(data) == ["items", "unmapped", "questions", "failure"]
    assert raw == json.dumps(data, indent=1, ensure_ascii=False) + "\n"
