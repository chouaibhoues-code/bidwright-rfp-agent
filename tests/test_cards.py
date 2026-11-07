"""Tests for S-12 method cards and evaluation cases (Iteration 3, step 18)."""

import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from bidwright import schemas
from evals.cards import CHECKS, load_cases

ROOT = Path(__file__).resolve().parent.parent

# All agents across Iteration 1-3 (Master-Plan §10.3.2, docs/designs/iteration-3.md §6.3)
ALL_ITERATION_AGENTS = {
    "triage",
    "brief",
    "discover",
    "extract",
    "approach",
    "risk",
    "decide",
    "assess",
    "options",
    "blueprint",
    "blueprint_detail",
    "techcheck",
    "risk_oneshot",
    "draft",
    "consolidate",
}


def test_cards_load_and_validate():
    cards_path = ROOT / "knowledge_base" / "methods" / "cards.yaml"
    assert cards_path.is_file(), "cards.yaml must exist"

    with cards_path.open(encoding="utf-8") as f:
        cards = yaml.safe_load(f)

    assert len(cards) == 18, f"Expected 18 method cards, found {len(cards)}"

    seen_ids = set()
    valid_families = {"REQ", "CFG", "BA", "DEL", "BEN", "RISK", "GOV"}

    for card in cards:
        cid = card["id"]
        assert cid not in seen_ids, f"Duplicate card id: {cid}"
        seen_ids.add(cid)

        assert card["family"] in valid_families, f"Invalid family {card['family']} in {cid}"
        assert card["status"] == "PROPOSED", f"Initial status must be PROPOSED in {cid}"
        assert len(card["text"]) <= 300, f"Card {cid} text exceeds 300 chars: {len(card['text'])}"

        for consumer in card["consumers"]:
            assert consumer in ALL_ITERATION_AGENTS, (
                f"Consumer {consumer} in card {cid} not in ALL_ITERATION_AGENTS"
            )


def test_s12_cases_load_and_validate():
    cases_path = ROOT / "evals" / "s12" / "cases.yaml"
    assert cases_path.is_file(), "cases.yaml must exist"

    max_cost, cases = load_cases(cases_path)
    assert max_cost <= 1.0, f"max_cost_usd must be <= 1.0, got {max_cost}"
    # 20 cases, one for each card a node consumes; CFG-002's is listed as not testable (step 19).
    assert len(cases) == 19, f"Expected 19 cases, got {len(cases)}"

    with (ROOT / "knowledge_base" / "methods" / "cards.yaml").open(encoding="utf-8") as f:
        cards = yaml.safe_load(f)
    card_ids = {c["id"] for c in cards}

    seen_case_ids = set()
    for case in cases:
        assert case.id not in seen_case_ids, f"Duplicate case id: {case.id}"
        seen_case_ids.add(case.id)

        assert case.card in card_ids, f"Unknown card {case.card} in case {case.id}"
        assert case.node in ALL_ITERATION_AGENTS, f"Unknown node {case.node} in case {case.id}"
        assert case.check in CHECKS, f"Unknown check function {case.check} in case {case.id}"

        fixture_path = ROOT / case.fixture
        assert fixture_path.is_file(), f"Fixture file {case.fixture} does not exist"

        with fixture_path.open(encoding="utf-8") as f:
            fixture_data = json.load(f)
        assert isinstance(fixture_data, dict), f"Fixture {case.fixture} must be a JSON object"


def test_s12_fixtures_validate_against_task_schemas():
    cases_path = ROOT / "evals" / "s12" / "cases.yaml"
    _, cases = load_cases(cases_path)

    node_to_schema = {
        "extract": schemas.ExtractBatch,
        "consolidate": schemas.ClusterTask,
        "decide": schemas.DecideTask,
        "assess": schemas.AssessmentTask,
        "options": schemas.OptionsTask,
        "blueprint": schemas.BlueprintPlanTask,
        "risk": schemas.RiskInput,
    }

    for case in cases:
        fixture_path = ROOT / case.fixture
        with fixture_path.open(encoding="utf-8") as f:
            fixture_data = json.load(f)

        schema_cls = node_to_schema[case.node]
        validated = schema_cls.model_validate(fixture_data)
        assert validated is not None


def _risk(**changes: object) -> dict[str, object]:
    risk: dict[str, object] = {
        "condition": "The legacy export has no documented format",
        "event": "The migration misses the go-live date",
        "effect": "The service starts late",
        "owner_role": "Delivery lead",
        "trigger": "The export sample fails validation",
        "responses": ["Request a sample export in week 1"],
        "residual_exposure": "Some delay if the sample arrives late",
        "evidence_src_ids": ["SRC-0001"],
    }
    return risk | changes


def _fixture(name: str) -> dict[str, Any]:
    return json.loads((ROOT / "evals" / "s12" / "fixtures" / f"{name}.json").read_text("utf-8"))


def _item(statement: str, *src_ids: str) -> dict[str, Any]:
    return {
        "src_ids": list(src_ids),
        "quote": "",
        "statement": statement,
        "modality": "shall",
        "disposition": "BINDING",
        "hazard": False,
    }


def _fact(text: str, *src_ids: str) -> dict[str, Any]:
    return {
        "text": text,
        "src_ids": list(src_ids),
        "requirement_ids": [],
        "claim_ids": [],
        "domain_item_ids": [],
    }


def _plan(**lists: list[dict[str, Any]]) -> dict[str, Any]:
    empty = (
        "current_state",
        "target_state",
        "workstreams",
        "wbs",
        "assumptions",
        "ground_rules",
        "tech_claims",
    )
    return {name: lists.get(name, []) for name in empty}


def _option(summary: str, assumptions: list[str] | None = None) -> dict[str, Any]:
    return {
        "options": [
            {
                "name": "A",
                "summary": summary,
                "baseline": False,
                "approach": [],
                "assumptions": assumptions or [],
                "scores": [],
            }
        ]
    }


def _claims(*texts: str, reason: str = "From the need.") -> dict[str, Any]:
    claims = [{"kind": "capability", "text": x, "evidence_ids": [], "src_ids": []} for x in texts]
    return {
        "decision": "PROCEED_WITH_GAP",
        "reason": reason,
        "claims": claims,
        "gap": None,
        "question": None,
    }


def _consolidation(duplicates=(), discrepancies=(), questions=()) -> dict[str, Any]:
    return {
        "topic": "t",
        "duplicates": list(duplicates),
        "discrepancies": list(discrepancies),
        "questions": list(questions),
        "references": [],
    }


def _discrepancy(state: str, kind: str, *ids: str) -> dict[str, Any]:
    return {
        "requirement_ids": list(ids),
        "kind": kind,
        "state": state,
        "description": "d",
        "resolved_by": None,
    }


# Per check: its fixture, an answer that commits the card's violation, and a clean answer.
CHECK_CASES = {
    "check_extract_req001": (
        "extract_req001",
        {
            "items": [
                _item(
                    "The Contractor shall provide monthly performance reports within 10 "
                    "working days of month end.",
                    "SRC-011",
                )
            ]
        },
        {
            "items": [
                _item(
                    "The Contractor shall provide performance reports on the service to "
                    "the Authority's satisfaction.",
                    "SRC-011",
                )
            ]
        },
    ),
    "check_extract_req002": (
        "extract_req002",
        {
            "items": [
                _item(
                    "All data shall be retained for seven (7) years, since section 9.2 "
                    "supersedes section 4.1.",
                    "SRC-021",
                    "SRC-022",
                )
            ]
        },
        {
            "items": [
                _item("All project data shall be retained for five years.", "SRC-021"),
                _item("Financial records shall be retained for seven years.", "SRC-022"),
            ]
        },
    ),
    "check_extract_req003": (
        "extract_req003",
        {
            "items": [
                _item("Audits shall take place annually and twice a year.", "SRC-031", "SRC-032")
            ]
        },
        {
            "items": [
                _item(
                    "Compliance audits shall take place annually, except during declared "
                    "emergency operations.",
                    "SRC-031",
                ),
                _item("Security audits shall take place twice a year.", "SRC-032"),
            ]
        },
    ),
    "check_consolidate_req002": (
        "consolidate_req002",
        _consolidation(
            discrepancies=[_discrepancy("established", "INCONSISTENT_VALUE", "REQ-101", "REQ-102")]
        ),
        _consolidation(
            discrepancies=[_discrepancy("conditional", "INCONSISTENT_VALUE", "REQ-101", "REQ-102")]
        ),
    ),
    "check_consolidate_req003": (
        "consolidate_req003",
        _consolidation(duplicates=[{"requirement_id": "REQ-104", "duplicate_of": "REQ-103"}]),
        _consolidation(),
    ),
    "check_consolidate_cfg001": (
        "consolidate_cfg001",
        _consolidation(duplicates=[{"requirement_id": "REQ-105", "duplicate_of": "REQ-107"}]),
        _consolidation(
            discrepancies=[_discrepancy("established", "SUPERSEDED", "REQ-105", "REQ-107")]
        ),
    ),
    "check_decide_ba001": (
        "decide_ba001",
        _claims("The supplier integrates with the Council's Esri ArcGIS 10.8 server."),
        _claims(
            "The integration method depends on the Council's GIS, which is unstated; ask "
            "for its interface."
        ),
    ),
    "check_decide_ba003": (
        "decide_ba003",
        _claims("Our REST API provides integration with SAP S/4HANA for invoice posting."),
        _claims(
            "Integration with SAP S/4HANA is unverified: the generic REST API requires "
            "version-specific test evidence."
        ),
    ),
    "check_assess_ba003": (
        "assess_ba003",
        {
            "reason": "The REST API exchanges JSON.",
            "disposition": "PARTIALLY_SUPPORTED",
            "supporting_ids": ["CAP-001"],
            "missing": "",
        },
        {
            "reason": "A generic API does not show the named integration.",
            "disposition": "UNVERIFIED",
            "supporting_ids": [],
            "missing": "SAP test evidence",
        },
    ),
    "check_options_ba002": (
        "options_ba002",
        _option("The recommended option: configure the platform and build the portal."),
        _option(
            "Configure the platform and build the portal; the weighted ranking is "
            "hypothetical until a bid policy is approved."
        ),
    ),
    "check_options_gov001": (
        "options_gov001",
        _option("A hosted service that ensures full compliance with data protection law."),
        _option(
            "A hosted service; compliance with data protection law is subject to the "
            "Council's legal review."
        ),
    ),
    "check_blueprint_ba001": (
        "blueprint_ba001",
        _plan(current_state=[_fact("The Council runs Civica APP 4.2 on an Oracle database.")]),
        _plan(
            current_state=[
                _fact(
                    "The current case-management system is not stated; its data model is unknown."
                )
            ]
        ),
    ),
    "check_blueprint_del001": (
        "blueprint_del001",
        _plan(
            assumptions=[
                _fact(
                    "The work fits the fixed budget of £450,000 and will be delivered by June 2027."
                )
            ]
        ),
        _plan(
            assumptions=[
                _fact(
                    "Price and schedule are provisional until the work packages "
                    "and their dependencies are confirmed."
                )
            ]
        ),
    ),
    "check_blueprint_del002": (
        "blueprint_del002",
        _plan(
            wbs=[
                {
                    "code": "1.1",
                    "name": "Licence configuration",
                    "deliverable": "40 licence types configured in 60 person-days",
                    "requirement_ids": [],
                    "need_ids": [],
                    "claim_ids": [],
                }
            ]
        ),
        _plan(
            wbs=[
                {
                    "code": "1.1",
                    "name": "Licence configuration",
                    "deliverable": "40 licence "
                    "types configured, estimated at 50 to 70 person-days based on 1.5 days a "
                    "type",
                    "requirement_ids": [],
                    "need_ids": [],
                    "claim_ids": [],
                }
            ]
        ),
    ),
    "check_blueprint_del003": (
        "blueprint_del003",
        _plan(ground_rules=[_fact("Migration takes 6 weeks and go-live is in month 4.")]),
        _plan(
            ground_rules=[
                _fact(
                    "Go-live follows the migration's acceptance checkpoint; "
                    "migration takes 6 weeks after the data extract arrives."
                )
            ]
        ),
    ),
    "check_blueprint_ben001": (
        "blueprint_ben001",
        _plan(target_state=[_fact("Online applications reduce processing costs by 30%.")]),
        _plan(
            target_state=[
                _fact(
                    "Online applications are expected to reduce processing "
                    "time, measured against the current baseline."
                )
            ]
        ),
    ),
    "check_risk_risk001": (
        "risk_risk001",
        {"risks": [_risk(trigger="")], "open_questions": []},
        {"risks": [_risk()], "open_questions": []},
    ),
    "check_risk_risk002": (
        "risk_risk002",
        {
            "risks": [_risk(residual_exposure="High.", effect="A 70% probability of a slip")],
            "open_questions": [],
        },
        {"risks": [_risk()], "open_questions": []},
    ),
    "check_risk_risk003": (
        "risk_risk003",
        {"risks": [_risk(owner_role="System")], "open_questions": []},
        {"risks": [_risk()], "open_questions": []},
    ),
}


@pytest.mark.parametrize("check", sorted(CHECK_CASES))
def test_each_check_fires_on_a_violation_and_stays_at_zero_on_a_clean_answer(check: str) -> None:
    """Step 19: the checks are tested against answers a model could give, each read with the
    case's fixture; the step-18 checks searched for phrases no model writes and counted 0 with
    the cards off and on alike."""
    name, violating, clean = CHECK_CASES[check]
    task = _fixture(name)
    assert CHECKS[check](violating, task) >= 1
    assert CHECKS[check](clean, task) == 0


def test_every_case_has_a_tested_check_and_cfg_002_is_listed_as_not_testable() -> None:
    from evals.cards import not_testable

    path = ROOT / "evals" / "s12" / "cases.yaml"
    _, cases = load_cases(path)
    assert {c.check for c in cases} == set(CHECK_CASES) == set(CHECKS)
    assert [c["card"] for c in not_testable(path)] == ["CFG-002"]


# --- step 18: the card slot, the switch, the checks on real answers and the runner ----------


def test_every_card_consumer_is_an_agent_and_the_cards_load() -> None:
    from bidwright.config import load_config
    from bidwright.kb import load_cards

    agents = set(load_config().agents.agents)
    cards = load_cards()
    assert len(cards) == 18
    assert {c for card in cards for c in card.consumers} <= agents


def test_a_family_off_appends_nothing_and_on_appends_exactly_its_cards() -> None:
    from bidwright.config import load_config
    from bidwright.graph.build import run_prompts
    from bidwright.prompts import load_prompt_ref

    config = load_config()
    plain = {n: load_prompt_ref(a.prompt) for n, a in config.agents.agents.items()}
    off = run_prompts(config, [])
    assert all(off[n].hash == plain[n].hash for n in plain), "no cassette key changes"
    on = run_prompts(config, ["risk"])  # a family is named in any case
    assert on["risk"].cards == ("RISK-001", "RISK-002", "RISK-003")
    assert on["risk"].hash != off["risk"].hash
    block = on["risk"].system.split("<method_cards>")[1]
    assert block.rstrip().endswith("</method_cards>") and block.count("RISK-00") == 3
    assert "REQ-001" not in on["risk"].system
    assert all(on[n].hash == off[n].hash for n in off if n != "risk"), "other prompts unchanged"


def test_an_enabled_family_reaches_its_consumers_manifests(tmp_path: Path) -> None:
    from bidwright.graph.build import execute
    from bidwright.llm.replay import CassetteStore
    from bidwright.preflight import Refused
    from bidwright.schemas import ContextManifest, RunManifest
    from tests.node_fakes import DEV_RFP, RuleBackend, fake_backends

    def run(name: str, methods: list[str]) -> Path:
        return execute(
            docling_mode="replay",
            source=DEV_RFP,
            profile="free",
            outputs=tmp_path,
            mode="record",
            cassettes=CassetteStore(tmp_path / f"c-{name}"),
            backends=fake_backends(RuleBackend()),
            run_id=name,
            until="verify",
            methods=methods,
        ).run_dir

    with_req = run("req", ["REQ"])
    extract = [
        ContextManifest.model_validate_json(p.read_text("utf-8"))
        for p in sorted((with_req / "context").glob("extract-*.json"))
    ]
    assert extract and all(m.cards == ["REQ-001", "REQ-002", "REQ-003"] for m in extract)
    triage = ContextManifest.model_validate_json(
        next((with_req / "context").glob("triage-*.json")).read_text("utf-8")
    )
    assert triage.cards == [], "triage consumes no card"
    manifest = RunManifest.model_validate_json((with_req / "run_manifest.json").read_text("utf-8"))
    assert manifest.run_args["methods"] == ["REQ"]
    plain = run("plain", [])
    first = sorted((plain / "context").glob("extract-*.json"))[0]
    assert ContextManifest.model_validate_json(first.read_text("utf-8")).cards == []
    with pytest.raises(Refused, match="unknown card families"):
        run("bad", ["NOPE"])


def test_the_risk_and_consolidate_checks_read_real_answers() -> None:
    def register(*risks: dict[str, object]) -> dict[str, object]:
        return schemas.RiskRegister.model_validate({"risks": list(risks)}).model_dump()

    already = _risk(event="The outage has already occurred")
    task = _fixture("risk_risk001")
    assert CHECKS["check_risk_risk001"](register(_risk()), task) == 0
    assert CHECKS["check_risk_risk001"](register(_risk(trigger="")), task) == 1
    assert CHECKS["check_risk_risk002"](register(already), task) == 1
    assert CHECKS["check_risk_risk003"](register(_risk()), task) == 0
    assert CHECKS["check_risk_risk003"](register(_risk(owner_role="System")), task) == 1
    waived = register(_risk(responses=["Auto-approve the risk"]))
    assert CHECKS["check_risk_risk003"](waived, task) == 1
    pair = {"requirement_id": "REQ-103", "duplicate_of": "REQ-104"}
    merged = schemas.ConsolidationResult.model_validate(
        {"topic": "Audits", "duplicates": [pair]}
    ).model_dump()
    kept = schemas.ConsolidationResult.model_validate({"topic": "Audits"}).model_dump()
    members = _fixture("consolidate_req003")
    assert CHECKS["check_consolidate_req003"](merged, members) == 1
    assert CHECKS["check_consolidate_req003"](kept, members) == 0


class _Paid:
    """A paid stand-in that answers `risk` with a rated risk and `assess` with UNVERIFIED."""

    provider = "gemini"
    paid = True

    def __init__(self) -> None:
        self.requests: list[Any] = []

    def call(self, request: Any) -> Any:
        from bidwright.llm.types import Response, Usage

        self.requests.append(request)
        if request.schema_name == "RiskRegister":
            body: dict[str, object] = {
                "risks": [_risk(residual_exposure="High.")],
                "open_questions": [],
            }
        else:
            body = {"reason": "No record holds it.", "disposition": "UNVERIFIED"}
        return Response(text=json.dumps(body), usage=Usage(tokens_in=4000, tokens_out=1000))


def _cases(tmp_path: Path, max_cost: float) -> Path:
    path = tmp_path / f"cases-{max_cost}.yaml"
    path.write_text(
        f"max_cost_usd: {max_cost}\ncases:\n"
        "  - {id: C1, card: RISK-002, family: RISK, node: risk,"
        " fixture: evals/s12/fixtures/risk_risk002.json, check: check_risk_risk002}\n"
        "  - {id: C2, card: BA-003, family: BA, node: assess,"
        " fixture: evals/s12/fixtures/assess_ba003.json, check: check_assess_ba003}\n",
        encoding="utf-8",
    )
    return path


def test_bidwright_eval_cards_runs_each_case_off_and_on_and_stops_at_the_cap(
    tmp_path: Path,
) -> None:
    from bidwright.llm.replay import CassetteStore
    from evals.cards import family_results, run_cards, write_report

    backend = _Paid()
    backends = {"gemini": backend, "cerebras": backend, "groq": backend}

    def cards_run(name: str, max_cost: float) -> Any:
        return run_cards(
            repeats=2,
            profile="paid",
            mode="record",
            name=name,
            cases_path=_cases(tmp_path, max_cost),
            backends=backends,
            cassettes=CassetteStore(tmp_path / f"c-{name}"),
            outputs=tmp_path,
        )

    run = cards_run("s12", 10)
    assert run.stopped is None and run.spent_usd > 0
    assert run.violations["C1"] == {"off": [1, 1], "on": [1, 1]}, "a rating each time"
    with_cards = [r for r in backend.requests if "<method_cards>" in r.messages[0].content]
    assert len(with_cards) == 4 and len(backend.requests) == 8
    plan = {"control": "off", "rungs": {"RISK": {"metric": "violations", "kind": "superiority"}}}
    assert family_results(run, plan)["RISK"]["passed"] is False, "the cards changed nothing"
    assert family_results(run, {"rungs": {}})["RISK"]["passed"] is None, "no hypothesis"
    out = write_report(run, tmp_path / "res", plan)
    assert "| RISK | 1 | [1, 1] | [1, 1] | fail |" in (out / "report.md").read_text("utf-8")
    capped = cards_run("s12-capped", 0.000001)
    assert capped.stopped is not None and "cap" in capped.stopped
    assert capped.violations["C1"] == {"off": [1], "on": []}
    assert family_results(capped, plan)["RISK"]["on"] == [], "a capped run still reports"


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("family", "CFG", "is family REQ, not CFG"),
        ("node", "risk", "risk does not consume REQ-002"),
        ("card", "REQ-099", "no method card REQ-099"),
    ],
)
def test_a_case_that_would_not_test_its_card_is_refused(
    tmp_path: Path, field: str, value: str, message: str
) -> None:
    """A case's 'on' state inlines its family's cards on its node, so a case labeled with
    another family, or on a node that does not consume its card, measures nothing."""
    case = {
        "id": "X1",
        "card": "REQ-002",
        "family": "REQ",
        "node": "consolidate",
        "fixture": "evals/s12/fixtures/consolidate_req002.json",
        "check": "check_consolidate_req002",
    }
    path = tmp_path / "cases.yaml"
    path.write_text(yaml.safe_dump({"cases": [case | {field: value}]}), encoding="utf-8")
    with pytest.raises(ValueError, match=message):
        load_cases(path)


def test_every_case_renders_its_nodes_prompt_with_the_tasks_own_ids() -> None:
    """Step 19: `extract`'s task text names `$batch_id` and `consolidate`'s `$cluster_id`, which
    the nodes pass from their task models; `call_node` passes them the same way, so no case
    fails before its call."""
    from bidwright.config import load_config
    from bidwright.graph.build import run_prompts
    from bidwright.graph.single import template_values
    from evals.cards import task_models

    prompts = run_prompts(load_config(), [])
    models = task_models()
    _, cases = load_cases(ROOT / "evals" / "s12" / "cases.yaml")
    for case in cases:
        task = models[case.node].model_validate_json((ROOT / case.fixture).read_text("utf-8"))
        prompt = prompts[case.node]
        rendered = prompt.render(
            task.model_dump_json(), run_id="s12", **template_values(prompt, task)
        )
        if case.node == "extract":
            assert task.batch_id in rendered.messages[-1].content
