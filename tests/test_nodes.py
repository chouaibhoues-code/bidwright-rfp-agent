"""The extract, verify, approach and draft nodes on scripted model replies."""

import json

from bidwright.graph.nodes import (
    MALFORMED_TWICE,
    BatchOutcome,
    approach,
    assign_requirements,
    batches,
    draft,
    extract_batch,
    section_records,
)
from tests.node_fakes import ScriptBackend, context, dev_ingest, dev_requirements, text

# The 4.1 to 4.3 requirement passages of the development RFP: SRC-0020 to SRC-0028.
SECTION_4 = [p for p in dev_ingest().passages if "4 Requirements >" in p.section_path]


def item(src: str, quote: str, disposition: str = "BINDING", modality: str = "shall") -> dict:
    return {
        "src_ids": [src],
        "quote": quote,
        "statement": quote,
        "modality": modality,
        "disposition": disposition,
        "hazard": False,
    }


GOOD_ITEMS = [
    item("SRC-0020", "The Supplier shall keep an audit record of every signature event"),
    item("SRC-0022", "support signing on current desktop and mobile browsers"),
    item("SRC-0023", "send a reminder to each signer who has not signed within 72 hours"),
    item("SRC-0024", "The Supplier should provide templates", "OPTIONAL", "should"),
    item("SRC-0025", "The Supplier shall store signed documents for ten (10) years."),
    item(
        "SRC-0026",
        "should migrate the signed records held in the current tool",
        "OPTIONAL",
        "should",
    ),
    item(
        "SRC-0027",
        "The service must integrate with the College's student records system",
        modality="must",
    ),
    item("SRC-0028", "Bidders may propose an on-premises deployment option.", "OPTIONAL", "may"),
]


def test_section_4_is_one_batch_of_nine_passages() -> None:
    assert [p.id for p in SECTION_4] == [f"SRC-{n:04d}" for n in range(20, 29)]
    assert len(batches(dev_ingest().passages, 20)) == 2


def test_a_clean_batch_needs_no_repair() -> None:
    backend = ScriptBackend([text({"items": GOOD_ITEMS, "no_obligation_src_ids": ["SRC-0021"]})])
    outcome = extract_batch(context(backend), SECTION_4, "B01")
    assert len(backend.requests) == 1
    assert len(outcome.accepted) == 8 and outcome.rejected == []
    statuses = {check.status for _, check in outcome.accepted}
    assert statuses == {"VERBATIM_VERIFIED"}


def test_verify_repair_fixes_a_quote_and_a_missing_id() -> None:
    wrong = item("SRC-0025", "The Supplier shall store signed documents for twelve years.")
    first = [i for i in GOOD_ITEMS if i["src_ids"] != ["SRC-0025"] and i["src_ids"] != ["SRC-0028"]]
    repaired = [GOOD_ITEMS[4], GOOD_ITEMS[7]]
    backend = ScriptBackend(
        [
            text({"items": [*first, wrong], "no_obligation_src_ids": ["SRC-0021"]}),
            text({"items": repaired, "no_obligation_src_ids": []}),
        ]
    )
    outcome = extract_batch(context(backend), SECTION_4, "B01")
    repair = backend.requests[1].messages[-1].content
    assert "were not found in their cited passages" in repair
    assert '["SRC-0025", "The Supplier shall store signed documents for twelve years."]' in repair
    assert 'missing from your answer: ["SRC-0028"]' in repair
    assert len(outcome.accepted) == 8 and outcome.rejected == []


def test_a_quote_still_wrong_after_repair_is_rejected_and_logged() -> None:
    wrong = item("SRC-0025", "The Supplier shall store signed documents for twelve years.")
    first = [i for i in GOOD_ITEMS if i["src_ids"] != ["SRC-0025"]]
    backend = ScriptBackend(
        [
            text({"items": [*first, wrong], "no_obligation_src_ids": ["SRC-0021"]}),
            text({"items": [wrong], "no_obligation_src_ids": []}),
        ]
    )
    outcome = extract_batch(context(backend), SECTION_4, "B01")
    assert len(outcome.accepted) == 7
    assert outcome.rejected == [
        {
            "batch_id": "B01",
            "src_ids": ["SRC-0025"],
            "quote": wrong["quote"],
            "reason": "not found in the cited passages",
        }
    ]


def test_a_withdrawn_quote_and_an_unaccounted_id_are_logged() -> None:
    wrong = item("SRC-0025", "store signed documents for a decade")
    first = [i for i in GOOD_ITEMS if i["src_ids"] not in (["SRC-0025"], ["SRC-0028"])]
    backend = ScriptBackend(
        [
            text({"items": [*first, wrong], "no_obligation_src_ids": ["SRC-0021"]}),
            text({"items": [item("SRC-0025", "")], "no_obligation_src_ids": []}),
        ]
    )
    outcome = extract_batch(context(backend), SECTION_4, "B01")
    reasons = sorted((r["src_ids"][0], r["reason"]) for r in outcome.rejected)
    assert reasons == [("SRC-0025", "withdrawn"), ("SRC-0028", "unaccounted")]


def test_fi02_malformed_output_gets_one_format_repair() -> None:
    backend = ScriptBackend(
        ['{"items": [', text({"items": GOOD_ITEMS, "no_obligation_src_ids": ["SRC-0021"]})]
    )
    outcome = extract_batch(context(backend), SECTION_4, "B01")
    assert "did not match the response schema" in backend.requests[1].messages[-1].content
    assert len(outcome.accepted) == 8


def test_fi02_malformed_twice_rejects_the_whole_batch() -> None:
    backend = ScriptBackend(['{"items": [', "not json either"])
    outcome = extract_batch(context(backend), SECTION_4, "B01")
    assert outcome.accepted == []
    assert outcome.rejected[0]["reason"] == "malformed output after repair"
    assert outcome.rejected[0]["src_ids"] == [p.id for p in SECTION_4]


def test_an_id_from_another_batch_is_dropped_from_the_item() -> None:
    """SRC-0032 is a real passage, but not one this batch showed the model."""
    stray = dict(GOOD_ITEMS[0], src_ids=["SRC-0020", "SRC-0032"])
    backend = ScriptBackend([text({"items": [stray], "no_obligation_src_ids": []})])
    outcome = extract_batch(context(backend), SECTION_4[:1], "B01")
    [(item, check)] = outcome.accepted
    assert item.src_ids == ["SRC-0020"] and check.status == "VERBATIM_VERIFIED"


def test_requirements_are_numbered_in_reading_order() -> None:
    backend = ScriptBackend(
        [text({"items": GOOD_ITEMS[::-1], "no_obligation_src_ids": ["SRC-0021"]})]
    )
    outcome = extract_batch(context(backend), SECTION_4, "B01")
    requirements, rejected = assign_requirements([outcome], dev_ingest().passages, "dev-rfp")
    assert [r.src_ids[0] for r in requirements] == [i["src_ids"][0] for i in GOOD_ITEMS]
    assert [r.id for r in requirements][:2] == ["REQ-0001", "REQ-0002"]
    assert [r.mandatory for r in requirements] == [
        i["disposition"] == "BINDING" for i in GOOD_ITEMS
    ]
    assert rejected == []
    assert all(r.quote_span is not None for r in requirements)


def test_approach_keeps_known_ids_and_lists_what_is_unmapped() -> None:
    result = {
        "items": [
            {"text": "Bid compliance.", "requirement_ids": ["REQ-0001"], "basis": "Stated."},
            {
                "text": "Integration.",
                "requirement_ids": ["REQ-0002", "REQ-0099"],
                "basis": "Stated.",
            },
            {"text": "Invented.", "requirement_ids": ["REQ-0098"], "basis": "None."},
        ],
        "unmapped_requirement_ids": [],
        "open_questions": [{"text": "Which API version?", "requirement_ids": ["REQ-0002"]}],
    }
    outcome = approach(context(ScriptBackend([text(result)])), dev_requirements())
    assert [(a.id, a.requirement_ids) for a in outcome.items] == [
        ("APP-001", ["REQ-0001"]),
        ("APP-002", ["REQ-0002"]),
    ]
    assert outcome.items[1].source_ids == ["SRC-0027"]
    assert outcome.items[0].evidence_class == "ASSUMPTION"
    assert outcome.unmapped == ["REQ-0003", "REQ-0004"]
    assert outcome.questions[0].src_ids == ["SRC-0027"]


def test_approach_degrades_after_two_schema_failures() -> None:
    """The requirements are verified by now, so the run keeps them and ends DEGRADED."""
    outcome = approach(context(ScriptBackend(["{}", "[]"])), dev_requirements())
    assert outcome.items == [] and outcome.questions == []
    assert outcome.unmapped == ["REQ-0001", "REQ-0002", "REQ-0003", "REQ-0004"]
    assert outcome.failure == MALFORMED_TWICE


def test_draft_keeps_only_ids_from_its_records() -> None:
    records = section_records("understanding", dev_requirements(), [], [], [])
    assert records[0]["id"] == "REQ-0001" and records[0]["hazard"] is True
    reply = {
        "title": "Understanding",
        "text": "Bids go to the portal [REQ-0001].",
        "cited_ids": ["REQ-0001", "REQ-0777"],
    }
    section = draft(context(ScriptBackend([text(reply)])), "understanding", records)
    assert section.status == "CURRENT" and section.cited_ids == ["REQ-0001"]
    failed = draft(context(ScriptBackend(["{}", "{}"])), "approach", [])
    assert failed.status == "FAILED" and failed.text == ""


def test_open_questions_get_draft_ids() -> None:
    from bidwright.schemas import OpenQuestion

    records = section_records(
        "risks_and_assumptions", [], [], [], [OpenQuestion(text="Which API?", src_ids=[])]
    )
    assert records == [{"id": "Q-01", "question": "Which API?"}]
    assert json.dumps(records)  # records stay JSON-safe for the prompt


def test_batch_outcome_defaults_are_independent() -> None:
    first, second = BatchOutcome("a"), BatchOutcome("b")
    first.no_obligation.append("SRC-0001")
    assert second.no_obligation == []
