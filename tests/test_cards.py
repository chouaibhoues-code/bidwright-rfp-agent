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
    assert len(cases) == 20, f"Expected 20 cases, got {len(cases)}"

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


def test_checks_detect_violations_and_pass_clean():
    clean_extract = {"items": [{"statement": "Reporting shall be verified by audit."}]}
    violating_extract_req001 = {"items": [{"statement": "Auto-accepted without inspection."}]}
    assert CHECKS["check_extract_req001"](clean_extract) == 0
    assert CHECKS["check_extract_req001"](violating_extract_req001) >= 1

    clean_decide = {
        "decision": "RETRIEVE_EVIDENCE",
        "claims": [{"text": "Valid claim"}],
        "reason": "Reasonable",
    }
    violating_decide_ba003 = {
        "decision": "RETRIEVE_EVIDENCE",
        "claims": [{"text": "Generic REST API proves certified SAP integration"}],
        "reason": "OK",
    }
    assert CHECKS["check_decide_ba003"](clean_decide) == 0
    assert CHECKS["check_decide_ba003"](violating_decide_ba003) >= 1

    # The risk checks read the fields of `RiskRegister` itself (step 18): a merged check read a
    # `statement` field, which no risk answer has, and so counted nothing on a real answer.
    clean_risk = schemas.RiskRegister.model_validate({"risks": [_risk()]}).model_dump()
    rated = _risk(residual_exposure="High.", effect="A 70% probability of a slip")
    violating_risk_risk002 = schemas.RiskRegister.model_validate({"risks": [rated]}).model_dump()
    assert CHECKS["check_risk_risk002"](clean_risk) == 0
    assert CHECKS["check_risk_risk002"](violating_risk_risk002) == 1


# --- step 18: the card slot, the switch, the checks on real answers and the runner ----------


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
    assert CHECKS["check_risk_risk001"](register(_risk())) == 0
    assert CHECKS["check_risk_risk001"](register(_risk(trigger=""))) == 1
    assert CHECKS["check_risk_risk002"](register(already)) == 1
    assert CHECKS["check_risk_risk003"](register(_risk())) == 0
    assert CHECKS["check_risk_risk003"](register(_risk(owner_role="System"))) == 1
    assert CHECKS["check_risk_risk003"](register(_risk(responses=["Auto-approve the risk"]))) == 1
    pair = {"requirement_id": "REQ-103", "duplicate_of": "REQ-104"}
    merged = schemas.ConsolidationResult.model_validate(
        {"topic": "Audits", "duplicates": [pair]}
    ).model_dump()
    kept = schemas.ConsolidationResult.model_validate({"topic": "Audits"}).model_dump()
    assert CHECKS["check_consolidate_req003"](merged) == 1
    assert CHECKS["check_consolidate_req003"](kept) == 0


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
