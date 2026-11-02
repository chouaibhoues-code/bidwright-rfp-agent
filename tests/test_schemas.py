"""Schema tests: JSON round trips, id patterns, and the rules the contract enforces."""

from datetime import UTC, datetime

import pytest
from pydantic import BaseModel, ValidationError

from bidwright import schemas as s

PASSAGE = s.Passage(
    id="SRC-0001",
    doc_id="dev-rfp-3f9a1c2e",
    section_path="3 Requirements > 3.2 Audit",
    kind="sentence",
    text="The Supplier shall keep an audit record of every signature event.",
    start=120,
    end=186,
)
REQUIREMENT = s.Requirement(
    id="REQ-0001",
    doc_id="dev-rfp-3f9a1c2e",
    statement="Keep an audit record of every signature event.",
    modality="shall",
    mandatory=True,
    hazard=False,
    disposition="BINDING",
    src_ids=["SRC-0001"],
    quote="The Supplier shall keep an audit record of every signature event.",
    quote_status="VERBATIM_VERIFIED",
    quote_span=(120, 186),
)
APPROACH = s.ApproachItem(
    id="APP-001",
    text="Write an append-only audit event for every signature step.",
    requirement_ids=["REQ-0001"],
    basis="Directly answers REQ-0001.",
    evidence_class="ASSUMPTION",
    source_ids=["SRC-0001"],
)
RISK = s.Risk(
    id="RSK-001",
    condition="Audit storage is sized for current volumes only",
    event="Signature volume grows faster than storage",
    effect="Audit records are lost, breaching REQ-0001",
    owner_role="Solution architect",
    trigger="Storage use passes 70%",
    responses=["Size storage for peak volume", "Alert at 70% use"],
    residual_exposure="Low once alerting is in place",
    evidence_src_ids=["SRC-0001"],
)
LEDGER = s.LedgerEntry(
    run_id="20261103T101200Z-dev-rfp-3f9a1c2e-free",
    node="extract",
    agent="extract",
    provider="gemini",
    model="gemini-3.5-flash-lite",
    prompt_hash="sha256:aa",
    input_hash="sha256:bb",
    repeat=0,
    tokens_in=9120,
    tokens_out=410,
    latency_ms=2300,
    cost_usd=0.0,
    shadow_cost_usd=0.0038,
    replayed=False,
)
MANIFEST = s.RunManifest(
    run_id="20261103T101200Z-dev-rfp-3f9a1c2e-free",
    commit="2a96b8d",
    profile="free",
    models={"extract": "gemini-3.5-flash-lite", "reason": "gemini-3.8-flash"},
    started=datetime(2026, 11, 3, 10, 12, tzinfo=UTC),
    status="COMPLETED",
)
SUMMARY = s.SolutionSummary(
    run_id=MANIFEST.run_id,
    requirements=["REQ-0001"],
    approach=["APP-001"],
    risks=["RSK-001"],
    open_questions=[s.OpenQuestion(text="Which signature formats count?", src_ids=["SRC-0001"])],
    counts={"rejected_quotes": 0},
)
SECTION = s.ProposalSection(
    id="approach",
    title="Our approach",
    text="Every signature step writes an append-only audit event [APP-001].",
    cited_ids=["APP-001"],
    input_hash="sha256:cc",
    status="CURRENT",
)


@pytest.mark.parametrize(
    "record", [PASSAGE, REQUIREMENT, APPROACH, RISK, LEDGER, MANIFEST, SUMMARY, SECTION]
)
def test_json_round_trip(record: BaseModel) -> None:
    assert type(record).model_validate_json(record.model_dump_json()) == record


@pytest.mark.parametrize(
    ("model", "field", "bad"),
    [
        (s.Passage, "id", "SRC-1"),
        (s.Requirement, "id", "REQ-001"),
        (s.ApproachItem, "id", "APP-0001"),
        (s.Risk, "id", "RISK-001"),
    ],
)
def test_ids_must_match_their_pattern(model: type[BaseModel], field: str, bad: str) -> None:
    examples = {s.Passage: PASSAGE, s.Requirement: REQUIREMENT, s.ApproachItem: APPROACH}
    base = examples.get(model, RISK).model_dump()
    with pytest.raises(ValidationError):
        model.model_validate({**base, field: bad})


def test_mandatory_is_true_exactly_for_binding() -> None:
    with pytest.raises(ValidationError):
        s.Requirement.model_validate(
            {**REQUIREMENT.model_dump(), "disposition": "OPTIONAL", "mandatory": True}
        )
    optional = s.Requirement.model_validate(
        {**REQUIREMENT.model_dump(), "disposition": "OPTIONAL", "mandatory": False}
    )
    assert optional.mandatory is False


def test_passage_span_must_be_ordered() -> None:
    with pytest.raises(ValidationError):
        s.Passage.model_validate({**PASSAGE.model_dump(), "end": PASSAGE.start})


def test_stored_records_reject_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        s.Risk.model_validate({**RISK.model_dump(), "probability": 0.4})


def test_extract_item_limits() -> None:
    good = {
        "src_ids": ["SRC-0001"],
        "quote": "x" * s.QUOTE_MAX_CHARS,
        "statement": "s",
        "modality": "shall",
        "disposition": "BINDING",
        "hazard": False,
    }
    s.ExtractItem.model_validate(good)
    with pytest.raises(ValidationError):
        s.ExtractItem.model_validate({**good, "quote": "x" * (s.QUOTE_MAX_CHARS + 1)})
    with pytest.raises(ValidationError):
        s.ExtractItem.model_validate({**good, "src_ids": ["SRC-0001"] * 4})


def test_model_facing_responses_ignore_extra_keys() -> None:
    parsed = s.DraftResult.model_validate({"title": "t", "text": "x", "reasoning": "ignored"})
    assert not hasattr(parsed, "reasoning")


def test_extract_item_schema_puts_the_quote_before_the_labels() -> None:
    order = list(s.ExtractItem.model_json_schema()["properties"])
    assert order[:2] == ["src_ids", "quote"]
    assert order.index("quote") < order.index("disposition")
