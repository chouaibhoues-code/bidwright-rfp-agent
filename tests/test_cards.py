"""Tests for S-12 method cards and evaluation cases (Iteration 3, step 18)."""

import json
from pathlib import Path

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

    clean_risk = {
        "risks": [{"statement": "Delay in API access causes milestone slip", "owner": "Lead"}]
    }
    violating_risk_risk002 = {"risks": [{"statement": "Risk score: 85 and probability: 0.95"}]}
    assert CHECKS["check_risk_risk002"](clean_risk) == 0
    assert CHECKS["check_risk_risk002"](violating_risk_risk002) >= 1
