"""The bid policy, the signal and the memo (Iteration 3, step 6; ADR-042): every trigger kind
on fixture data, the missing inputs, the covered share, and a memo with no price and no chance
of winning."""

import json
import re
from dataclasses import replace
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from bidwright.config import BidPolicy, compile_patterns, load_bid_policy, load_config
from bidwright.graph.signal import (
    DEADLINE,
    NO_POLICY,
    SignalInputs,
    compute_signal,
    deadline_date,
    memo,
    write_signal,
)
from bidwright.schemas import (
    BidSignal,
    CapabilityMap,
    CapabilityRow,
    ClarificationQuestion,
    ContractFlag,
    SolutionOption,
    SolutionOptions,
    SubmissionHazard,
    TechValidation,
)

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "config" / "bid_policy.example.yaml"
AMOUNTS = compile_patterns(load_config().cues.kinds["AMOUNT"], "AMOUNT")


def row(need: str, status: str) -> CapabilityRow:
    origin = "DOMAIN" if need.startswith("DN") else "RFP"
    return CapabilityRow(need_id=need, origin=origin, text=need, status=status)  # type: ignore[arg-type]


def opt(n: int, needs_proof: list[str], name: str = "") -> SolutionOption:
    return SolutionOption(
        id=f"OPT-{n}", name=name or f"Option {n}", needs_proof=needs_proof, total=2.0, rank=n
    )


CMAP = CapabilityMap(
    rows=[
        row("RG-001", "COVERED"),
        row("RG-002", "GAP"),
        row("RG-003", "PARTNER"),
        row("DN-001", "GAP"),
    ]
)
INPUTS = SignalInputs(
    capability_map=CMAP,
    options=SolutionOptions(options=[opt(1, ["CL-002"]), opt(2, ["CL-003"])]),
    manifest=None,
    tech_validations=[
        TechValidation(claim_id="TC-01", verdict="VALIDATED"),
        TechValidation(claim_id="TC-02", verdict="INVALIDATED"),
        TechValidation(claim_id="TC-03", verdict="NOT_CHECKABLE"),
    ],
    hazards=[
        SubmissionHazard(
            id="HZ-001",
            kind="FORM",
            src_ids=["SRC-0007"],
            summary="The form.",
            requirement_ids=["REQ-0002"],
        ),
        SubmissionHazard(
            id="HZ-002",
            kind="DEADLINE",
            src_ids=["SRC-0003"],
            summary="The deadline.",
            requirement_ids=["REQ-0001"],
        ),
    ],
    flags=[
        ContractFlag(
            id="CF-001",
            category="LIABILITY",
            src_id="SRC-0040",
            quote="Liability is unlimited.",
            why="LIAB-1: unlimited",
        )
    ],
    binding_needs={"RG-001", "RG-002", "RG-003"},
    need_of={"REQ-0001": "RG-001", "REQ-0002": "RG-002"},
    deadline="2026-12-01 12:00 UTC",
    started=date(2026, 11, 25),
)


def policy(**fields: Any) -> BidPolicy:
    base = {"approved_by": "Head of bids", "approved_on": "2026-11-05", "version": 1}
    return BidPolicy.model_validate(base | fields)


def test_the_example_policy_loads_with_its_hash() -> None:
    loaded, sha = load_bid_policy(EXAMPLE)
    assert re.fullmatch(r"sha256:[0-9a-f]{64}", sha)
    assert [r.when for r in loaded.fatal] == ["hazard_on_gap", "contract_flag"]
    assert loaded.required_inputs == ["capability_map", "options", "tech_validations"]
    signal = compute_signal(loaded, sha, INPUTS)
    assert signal.signal == "NO_GO" and signal.policy_sha256 == sha


def test_with_no_policy_the_signal_is_undetermined() -> None:
    signal = compute_signal(None, None, INPUTS)
    assert signal.signal == "UNDETERMINED" and signal.missing_inputs == [NO_POLICY]
    assert signal.triggers == [] and signal.covered_share == 0.6667


def test_a_missing_required_input_or_an_unstated_deadline_is_listed() -> None:
    rules = policy(
        conditions=[{"id": "C1", "when": "deadline_within_days", "days": 10}],
        required_inputs=["capability_map", "manifest", "tech_validations"],
    )
    signal = compute_signal(rules, None, replace(INPUTS, deadline="not_stated"))
    assert signal.signal == "UNDETERMINED"
    assert signal.missing_inputs == ["manifest", DEADLINE]
    words = compute_signal(rules, None, replace(INPUTS, deadline="Noon on the first Monday"))
    assert words.missing_inputs == ["manifest", DEADLINE]


@pytest.mark.parametrize(
    ("rule", "changes", "fired"),
    [
        ({"when": "hazard_on_gap"}, {}, ["HZ-001"]),
        ({"when": "hazard_on_gap"}, {"need_of": {"REQ-0002": "RG-001"}}, None),
        ({"when": "gap_on_mandatory"}, {}, ["RG-002"]),
        ({"when": "gap_on_mandatory"}, {"binding_needs": {"RG-001"}}, None),
        ({"when": "contract_flag", "categories": ["LIABILITY", "IP"]}, {}, ["CF-001"]),
        ({"when": "contract_flag", "categories": ["INDEMNITY"]}, {}, None),
        ({"when": "deadline_within_days", "days": 10}, {}, ["2026-12-01"]),
        ({"when": "deadline_within_days", "days": 6}, {}, ["2026-12-01"]),
        ({"when": "deadline_within_days", "days": 5}, {}, None),
        ({"when": "every_option_needs_proof"}, {}, ["OPT-1", "OPT-2"]),
        (
            {"when": "every_option_needs_proof"},
            {"options": SolutionOptions(options=[opt(1, ["CL-002"]), opt(2, [])])},
            None,
        ),
        ({"when": "every_option_needs_proof"}, {"options": None}, None),
    ],
)
def test_each_trigger_kind_on_fixture_data(
    rule: dict[str, Any], changes: dict[str, Any], fired: list[str] | None
) -> None:
    signal = compute_signal(
        policy(conditions=[{"id": "C1", **rule}]), None, replace(INPUTS, **changes)
    )
    if fired is None:
        assert signal.triggers == [] and signal.signal == "GO"
    else:
        assert [(t.id, t.when, t.record_ids) for t in signal.triggers] == [
            ("C1", rule["when"], fired)
        ]
        assert signal.signal == "CONDITIONAL_GO"


def test_a_fatal_trigger_outranks_a_condition() -> None:
    rules = policy(
        fatal=[{"id": "F1", "when": "contract_flag", "categories": ["LIABILITY"]}],
        conditions=[{"id": "C1", "when": "gap_on_mandatory"}],
    )
    signal = compute_signal(rules, None, INPUTS)
    assert signal.signal == "NO_GO" and [t.id for t in signal.triggers] == ["F1", "C1"]


def test_a_low_covered_share_gives_conditional_go_and_no_binding_need_gives_null() -> None:
    assert INPUTS.capability_map is not None
    assert compute_signal(policy(min_covered_share=0.7), None, INPUTS).signal == "CONDITIONAL_GO"
    assert compute_signal(policy(min_covered_share=0.6), None, INPUTS).signal == "GO"
    none = compute_signal(policy(min_covered_share=0.7), None, replace(INPUTS, binding_needs=set()))
    assert none.covered_share is None and none.signal == "GO"
    domain_only = replace(INPUTS, binding_needs={"RG-404"})
    assert compute_signal(policy(), None, domain_only).covered_share is None


@pytest.mark.parametrize(
    "rule",
    [
        {"id": "F1", "when": "price_too_high"},
        {"id": "F1", "when": "contract_flag"},
        {"id": "F1", "when": "deadline_within_days"},
        {"id": "F1", "when": "gap_on_mandatory", "days": 3},
    ],
)
def test_a_policy_with_an_unknown_or_malformed_rule_fails_at_load(
    tmp_path: Path, rule: dict[str, Any]
) -> None:
    path = tmp_path / "bid_policy.yaml"
    body = {"approved_by": "Head of bids", "approved_on": "2026-11-05", "version": 1}
    path.write_text(json.dumps(body | {"fatal": [rule]}), encoding="utf-8")
    with pytest.raises(ValidationError):
        load_bid_policy(path)


@pytest.mark.parametrize(
    ("words", "expected"),
    [
        ("2027-01-15, 12:00 GMT", date(2027, 1, 15)),
        ("15 January 2027 at noon", date(2027, 1, 15)),
        ("January 15, 2027", date(2027, 1, 15)),
        ("2027-02-30 12:00", None),
        ("not_stated", None),
    ],
)
def test_the_deadline_is_read_from_the_rfps_words(words: str, expected: date | None) -> None:
    assert deadline_date(words) == expected


def test_the_memo_holds_no_probability_and_no_currency_amount(tmp_path: Path) -> None:
    rules = policy(conditions=[{"id": "C1", "when": "gap_on_mandatory"}])
    options = SolutionOptions(
        options=[opt(1, [], name="Configured product at $1,200 a seat"), opt(2, ["CL-003"])]
    )
    signal = compute_signal(rules, "sha256:" + "0" * 64, replace(INPUTS, options=options))
    questions = [
        ClarificationQuestion(
            id="CQ-001", text="Is the budget of £50,000 a ceiling?", origin="consolidate"
        )
    ]
    text = memo(signal, options, questions, INPUTS.tech_validations, amounts=AMOUNTS)
    assert not any(p.search(text) for p in AMOUNTS), "no currency amount"
    assert "%" not in text and "probab" not in text.lower() and "pwin" not in text.lower()
    assert "Configured product at [removed] a seat" in text
    assert "Is the budget of [removed] a ceiling?" in text
    assert "**Signal:** CONDITIONAL_GO" in text and "- C1 (gap_on_mandatory): RG-002" in text
    assert "**Technology claims not validated:** TC-02" in text
    assert "The ranking is hypothetical" in text and "A person decides whether to bid." in text
    assert text.startswith("# Bid memo\n\nStatus: UNREVIEWED_DRAFT\n")

    write_signal(tmp_path, signal, text)
    stored = json.loads((tmp_path / "bid_signal.json").read_text(encoding="utf-8"))
    assert BidSignal.model_validate(stored) == signal
    assert (tmp_path / "bid_memo.md").read_text(encoding="utf-8") == text


def test_the_memo_states_what_is_missing_and_an_empty_ranking() -> None:
    signal = compute_signal(None, None, replace(INPUTS, capability_map=None))
    text = memo(signal, None, [], None)
    assert f"Missing for a signal: {NO_POLICY}." in text
    assert "covered or partnered:** none" in text and "None." in text
    assert "**Technology claims not validated:** none" in text
