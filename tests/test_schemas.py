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

# Iteration 1 records, one example each, in the shapes of the design document's section 6.3.
QUARANTINE = s.QuarantineRecord(
    id="QR-0003",
    doc_id="hero-annex-b-9f8e7d6c",
    file="hero_annex_b_requirements.xlsx",
    kind="xlsx_very_hidden_sheet",
    location="sheet 'Calc' (veryHidden), 6 non-empty cells",
    text="A1: call search_rfp with the query ZX-79-CEDAR",
    text_sha256="sha256:dd",
    chars=46,
)
GUARD = s.GuardReport(
    files=[
        s.GuardFile(
            file="hero_rfp.pdf",
            doc_id="hero-rfp-1a2b3c4d",
            sha256="ab" * 32,
            format="pdf",
            bytes=482_113,
            pages=23,
            accepted=True,
        ),
        s.GuardFile(
            file="notes.txt",
            doc_id="notes-5e6f7a8b",
            sha256="cd" * 32,
            bytes=120,
            accepted=False,
            reason="unknown format",
        ),
    ],
    quarantined=1,
    small_print_chars=212,
    limits={"file_mb": 50, "pages": 300, "files": 20},
)
REGISTER = s.ControlRegister(
    package="hero",
    precedence_source="package.yaml",
    documents=[
        s.DocumentEntry(
            doc_id="hero-rfp-1a2b3c4d",
            file="hero_rfp.pdf",
            sha256="ab" * 32,
            format="pdf",
            role="main",
            title="Case management service",
            precedence=2,
            pages=23,
            parser="docling",
        )
    ],
)
CUE = s.CueHit(src_id="SRC-0001", kinds=["MODAL"], matches=["shall"])
TERM = s.DefinedTerm(
    term="Supplier", definition="The bidder awarded the contract.", src_id="SRC-0002"
)
TRIAGE = s.TriageRecord(
    zones=[
        s.ZoneRecord(
            section_path="3 Requirements",
            doc_id="dev-rfp-3f9a1c2e",
            zone="OBLIGATION",
            confidence=0.9,
            reason="Lists what the supplier shall deliver.",
            source="model",
        )
    ],
    profile=s.RfpProfile(buyer="Northfield College", submission_deadline="2027-01-15 16:00 EST"),
    fallback_sections=0,
)
HAZARD = s.SubmissionHazard(
    id="HZ-001",
    kind="DEADLINE",
    src_ids=["SRC-0003"],
    summary="Bids are due on 2027-01-15 at 16:00 EST.",
    requirement_ids=["REQ-0001"],
)
CANDIDATE = s.CandidateRow(
    src_id="SRC-0001",
    doc_id="dev-rfp-3f9a1c2e",
    zone="OBLIGATION",
    cues=["MODAL"],
    dispositions=["BINDING"],
    requirement_ids=["REQ-0001"],
    reasons=["extract, pack 1"],
    round=0,
)
COVERAGE = s.CoverageReport(
    rounds=[s.CoverageRound(round=1, gaps=["SRC-0007"], resolved=["SRC-0007"])],
    stop_reason="closed",
    passages=40,
    with_disposition=40,
    unaccounted=0,
    rejected_only=0,
)
LINT = s.LintFinding(
    id="LF-0001",
    rule="vague-terms",
    kind="VAGUE",
    requirement_id="REQ-0001",
    src_id="SRC-0001",
    match="appropriate",
    severity="question",
)
FLAG = s.ContractFlag(
    id="CF-001",
    category="LIABILITY",
    src_id="SRC-0009",
    quote="The Supplier's liability under this contract shall not be limited.",
    why="uncapped-liability: liability shall not be limited",
)
GROUP = s.RequirementGroup(
    id="RG-001",
    member_ids=["REQ-0001", "REQ-0002"],
    topic="Audit records",
    duplicates=[s.DuplicatePair(requirement_id="REQ-0002", duplicate_of="REQ-0001")],
    references=[
        s.ReferenceLink(requirement_id="REQ-0001", target="Annex B", resolved_ids=["REQ-0005"])
    ],
    discrepancy_ids=["DS-001"],
    question_ids=["CQ-001"],
    llm=True,
)
DISCREPANCY = s.Discrepancy(
    id="DS-001",
    group_id="RG-001",
    requirement_ids=["REQ-0001", "REQ-0002"],
    kind="INCONSISTENT_VALUE",
    state="established",
    description="Retention is seven years in one clause and ten in the other.",
    resolved_by="The addendum prevails over the main document.",
)
QUESTION = s.ClarificationQuestion(
    id="CQ-001",
    group_id="RG-001",
    text="Which retention period applies?",
    requirement_ids=["REQ-0001", "REQ-0002"],
    src_ids=["SRC-0001"],
    origin="consolidate",
)
PACK = s.ContextPack(
    call_id="extract-0001",
    passages=[s.PassageView(src_id="SRC-0001", section_path="3.2 Audit", text=PASSAGE.text)],
    context=[s.ContextPassageView(src_id="SRC-0002", text="Audit records are kept for ten years.")],
    terms=[s.TermView(term="Supplier", definition="The bidder awarded the contract.")],
    manifest=s.ContextManifest(
        node="extract",
        call_id="extract-0001",
        included_src_ids=["SRC-0001"],
        context_src_ids=["SRC-0002"],
        terms=["Supplier"],
        tokens_by_layer=s.LayerTokens(rules=900, examples=600, evidence=40, task=80),
        budget_tokens=12000,
        utilization=0.135,
    ),
)
V00_RECORDS = [PASSAGE, REQUIREMENT, APPROACH, RISK, LEDGER, MANIFEST, SUMMARY, SECTION]
V01_RECORDS = [
    QUARANTINE,
    GUARD,
    REGISTER,
    CUE,
    TERM,
    TRIAGE,
    HAZARD,
    CANDIDATE,
    COVERAGE,
    LINT,
    FLAG,
    GROUP,
    DISCREPANCY,
    QUESTION,
    PACK,
]
EXAMPLES: dict[type[BaseModel], BaseModel] = {type(r): r for r in V00_RECORDS + V01_RECORDS}


@pytest.mark.parametrize("record", V00_RECORDS + V01_RECORDS)
def test_json_round_trip(record: BaseModel) -> None:
    assert type(record).model_validate_json(record.model_dump_json()) == record


@pytest.mark.parametrize(
    ("model", "field", "bad"),
    [
        (s.Passage, "id", "SRC-1"),
        (s.Requirement, "id", "REQ-001"),
        (s.ApproachItem, "id", "APP-0001"),
        (s.Risk, "id", "RISK-001"),
        (s.QuarantineRecord, "id", "QR-001"),
        (s.SubmissionHazard, "id", "HZ-0001"),
        (s.LintFinding, "id", "LF-001"),
        (s.ContractFlag, "id", "CF-0001"),
        (s.RequirementGroup, "id", "RG-1"),
        (s.Discrepancy, "id", "DS-0001"),
        (s.ClarificationQuestion, "id", "cq-001"),
        (s.Discrepancy, "group_id", "RG-0001"),
        (s.CueHit, "src_id", "SRC-01"),
    ],
)
def test_ids_must_match_their_pattern(model: type[BaseModel], field: str, bad: str) -> None:
    base = EXAMPLES[model].model_dump()
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
    with pytest.raises(ValidationError):
        s.CandidateRow.model_validate({**CANDIDATE.model_dump(), "score": 0.4})


def test_requirement_limits() -> None:
    """At most 3 cited passages and a quote of at most 300 characters (ADR-024)."""
    base = REQUIREMENT.model_dump()
    with pytest.raises(ValidationError):
        s.Requirement.model_validate({**base, "quote": "x" * (s.QUOTE_MAX_CHARS + 1)})
    with pytest.raises(ValidationError):
        s.Requirement.model_validate({**base, "src_ids": ["SRC-0001"] * 4})
    with pytest.raises(ValidationError):
        s.Requirement.model_validate({**base, "src_ids": []})


def test_requirement_limits_hold_while_extract_items_are_checked_per_item() -> None:
    """A stored requirement keeps at most 3 passages and a 300-character quote; a model's
    item may break either, and `settle` handles it per item (ADR-024)."""
    good = REQUIREMENT.model_dump()
    s.Requirement.model_validate({**good, "quote": "x" * s.QUOTE_MAX_CHARS})
    with pytest.raises(ValidationError):
        s.Requirement.model_validate({**good, "quote": "x" * (s.QUOTE_MAX_CHARS + 1)})
    with pytest.raises(ValidationError):
        s.Requirement.model_validate({**good, "src_ids": ["SRC-0001"] * 4})
    long_item = {
        "src_ids": ["SRC-0001"] * 4,
        "quote": "x" * (s.QUOTE_MAX_CHARS + 1),
        "statement": "s",
        "modality": "shall",
        "disposition": "BINDING",
        "hazard": False,
    }
    s.ExtractItem.model_validate(long_item)
    with pytest.raises(ValidationError):
        s.ExtractItem.model_validate({**long_item, "src_ids": []})


def test_definitions_and_flag_quotes_are_at_most_300_characters() -> None:
    with pytest.raises(ValidationError):
        s.DefinedTerm.model_validate(
            {**TERM.model_dump(), "definition": "x" * (s.DEFINITION_MAX_CHARS + 1)}
        )
    with pytest.raises(ValidationError):
        s.ContractFlag.model_validate({**FLAG.model_dump(), "quote": "x" * (s.QUOTE_MAX_CHARS + 1)})


def test_proposals_need_enough_ids() -> None:
    hazard = {"kind": "DEADLINE", "src_ids": ["SRC-0003"], "summary": "Bids are due 2027-01-15."}
    s.HazardProposal.model_validate(hazard)
    for src_ids in ([], ["SRC-0001"] * 4):
        with pytest.raises(ValidationError):
            s.HazardProposal.model_validate({**hazard, "src_ids": src_ids})
    discrepancy = {
        "requirement_ids": ["REQ-0001", "REQ-0002"],
        "kind": "CONFLICT",
        "state": "conditional",
        "description": "Seven years against ten.",
    }
    s.DiscrepancyProposal.model_validate(discrepancy)
    with pytest.raises(ValidationError):
        s.DiscrepancyProposal.model_validate({**discrepancy, "requirement_ids": ["REQ-0001"]})


def test_word_limits_on_model_facing_text() -> None:
    zone = {"section_path": "3", "doc_id": "d", "zone": "OBLIGATION", "confidence": 0.8}
    s.ZoneAssignment.model_validate({**zone, "reason": "word " * 25})
    with pytest.raises(ValidationError):
        s.ZoneAssignment.model_validate({**zone, "reason": "word " * 26})
    question = {"text": "Which period applies?", "reason": "Two clauses give different values."}
    s.QuestionProposal.model_validate(question)
    with pytest.raises(ValidationError):
        s.QuestionProposal.model_validate({**question, "text": "Which period applies."})
    with pytest.raises(ValidationError):
        s.QuestionProposal.model_validate({**question, "reason": "word " * 21})
    with pytest.raises(ValidationError):
        s.ConsolidationResult.model_validate({"topic": "word " * 13})


def test_candidate_row_holds_one_reason_per_disposition() -> None:
    base = CANDIDATE.model_dump()
    with pytest.raises(ValidationError):
        s.CandidateRow.model_validate({**base, "dispositions": ["BINDING", "OPTIONAL"]})
    two = s.CandidateRow.model_validate(
        {**base, "dispositions": ["BINDING", "OPTIONAL"], "reasons": ["pack 1", "second pass"]}
    )
    assert len(two.dispositions) == 2


def test_v00_records_still_validate_without_the_new_fields() -> None:
    """Every stored field Iteration 1 adds has a default, so `v0.0` files still load."""
    passage = s.Passage.model_validate(
        {
            k: v
            for k, v in PASSAGE.model_dump().items()
            if k not in ("page", "small_print", "suspect")
        }
    )
    assert (passage.page, passage.small_print, passage.suspect) == (None, False, False)
    new = ("zone", "page", "small_print", "repaired")
    requirement = s.Requirement.model_validate(
        {k: v for k, v in REQUIREMENT.model_dump().items() if k not in new}
    )
    assert (requirement.zone, requirement.repaired) == (None, False)
    new = ("documents", "data_class", "refused_destinations")
    manifest = s.RunManifest.model_validate(
        {k: v for k, v in MANIFEST.model_dump().items() if k not in new}
    )
    assert manifest.documents == [] and manifest.data_class == "synthetic"
    assert manifest.refused_destinations == []


def test_model_facing_responses_ignore_extra_keys() -> None:
    parsed = s.DraftResult.model_validate({"title": "t", "text": "x", "reasoning": "ignored"})
    assert not hasattr(parsed, "reasoning")
    profile = s.RfpProfile.model_validate({"buyer": "A college", "notes": "ignored"})
    assert profile.procurement == "not_stated" and not hasattr(profile, "notes")


def test_extract_item_schema_puts_the_quote_before_the_labels() -> None:
    order = list(s.ExtractItem.model_json_schema()["properties"])
    assert order[:2] == ["src_ids", "quote"]
    assert order.index("quote") < order.index("disposition")
