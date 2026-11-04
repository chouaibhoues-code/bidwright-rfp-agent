"""The extract, verify, approach and draft nodes on scripted model replies."""

import json

from bidwright.graph.nodes import (
    MALFORMED_TWICE,
    BatchOutcome,
    approach,
    assign_requirements,
    batches,
    candidate_rows,
    draft,
    extract_batch,
    link_hazards,
    section_records,
)
from bidwright.schemas import SubmissionHazard
from tests.node_fakes import (
    ScriptBackend,
    context,
    dev_ingest,
    dev_requirements,
    pack_of,
    text,
)

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
    outcome = extract_batch(context(backend), pack_of(SECTION_4))
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
    outcome = extract_batch(context(backend), pack_of(SECTION_4))
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
    outcome = extract_batch(context(backend), pack_of(SECTION_4))
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
    outcome = extract_batch(context(backend), pack_of(SECTION_4))
    reasons = sorted((r["src_ids"][0], r["reason"]) for r in outcome.rejected)
    assert reasons == [("SRC-0025", "withdrawn"), ("SRC-0028", "unaccounted")]


def test_fi02_malformed_output_gets_one_format_repair() -> None:
    backend = ScriptBackend(
        ['{"items": [', text({"items": GOOD_ITEMS, "no_obligation_src_ids": ["SRC-0021"]})]
    )
    outcome = extract_batch(context(backend), pack_of(SECTION_4))
    assert "did not match the response schema" in backend.requests[1].messages[-1].content
    assert len(outcome.accepted) == 8


def test_fi02_malformed_twice_rejects_the_whole_batch() -> None:
    backend = ScriptBackend(['{"items": [', "not json either"])
    outcome = extract_batch(context(backend), pack_of(SECTION_4))
    assert outcome.accepted == []
    assert outcome.rejected[0]["reason"] == "malformed output after repair"
    assert outcome.rejected[0]["src_ids"] == [p.id for p in SECTION_4]


def test_an_id_from_another_batch_is_dropped_from_the_item() -> None:
    """SRC-0032 is a real passage, but not one this batch showed the model."""
    stray = dict(GOOD_ITEMS[0], src_ids=["SRC-0020", "SRC-0032"])
    backend = ScriptBackend([text({"items": [stray], "no_obligation_src_ids": []})])
    outcome = extract_batch(context(backend), pack_of(SECTION_4[:1]))
    [(item, check)] = outcome.accepted
    assert item.src_ids == ["SRC-0020"] and check.status == "VERBATIM_VERIFIED"


def test_requirements_are_numbered_in_reading_order() -> None:
    backend = ScriptBackend(
        [text({"items": GOOD_ITEMS[::-1], "no_obligation_src_ids": ["SRC-0021"]})]
    )
    outcome = extract_batch(context(backend), pack_of(SECTION_4))
    requirements, rejected = assign_requirements([outcome], dev_ingest().passages)
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


# --- Iteration 1, step 11: per-item checks, the ledger, hazards and the second pass ---------

REST = [i for i in GOOD_ITEMS if i["src_ids"] not in (["SRC-0020"], ["SRC-0025"], ["SRC-0027"])]
LONG = "word " * 61  # 305 characters


def test_the_three_repair_kinds_go_in_one_message() -> None:
    first = [
        item("SRC-0020", "The Supplier shall keep an audit trail of every signature"),
        {**GOOD_ITEMS[4], "statement": "The Supplier stores signed documents for 12 years."},
        item("SRC-0027", LONG),
        *REST,
    ]
    repaired = [GOOD_ITEMS[0], GOOD_ITEMS[4], GOOD_ITEMS[6]]
    backend = ScriptBackend(
        [
            text({"items": first, "no_obligation_src_ids": ["SRC-0021"]}),
            text({"items": repaired, "no_obligation_src_ids": []}),
        ]
    )
    outcome = extract_batch(context(backend), pack_of(SECTION_4))
    message = backend.requests[1].messages[-1].content
    assert "were not found in their cited passages" in message
    assert "hold a number or date that is not in the cited passage" in message
    assert "longer than 300 characters" in message
    assert '"The Supplier stores signed documents for 12 years."' in message
    assert outcome.rejected == [] and len(outcome.accepted) == 8
    fixed = {item.src_ids[0] for item, check in outcome.accepted if check.repaired}
    assert fixed == {"SRC-0020", "SRC-0025", "SRC-0027"}
    requirements, _ = assign_requirements([outcome], dev_ingest().passages)
    assert {r.src_ids[0] for r in requirements if r.repaired} == fixed


def test_a_long_quote_fails_only_its_item_and_is_rejected_if_still_long() -> None:
    first = {"items": [item("SRC-0027", LONG), *GOOD_ITEMS[:6], GOOD_ITEMS[7]]}
    backend = ScriptBackend(
        [
            text({**first, "no_obligation_src_ids": ["SRC-0021"]}),
            text({"items": [item("SRC-0027", LONG + "more")], "no_obligation_src_ids": []}),
        ]
    )
    outcome = extract_batch(context(backend), pack_of(SECTION_4))
    assert len(outcome.accepted) == 7, "the other items stand"
    [rejected] = outcome.rejected
    assert rejected["src_ids"] == ["SRC-0027"]
    assert rejected["reason"] == "quote over 300 characters"


def test_an_item_keeps_its_first_three_passages() -> None:
    four = dict(GOOD_ITEMS[0], src_ids=["SRC-0020", "SRC-0021", "SRC-0022", "SRC-0023"])
    backend = ScriptBackend(
        [
            text({"items": [four], "no_obligation_src_ids": []}),
            text({"items": [], "no_obligation_src_ids": ["SRC-0023"]}),
        ]
    )
    outcome = extract_batch(context(backend), pack_of(SECTION_4[:4]))
    [(kept, check)] = outcome.accepted
    assert kept.src_ids == ["SRC-0020", "SRC-0021", "SRC-0022"]
    assert check.status == "VERBATIM_VERIFIED"
    assert 'missing from your answer: ["SRC-0023"]' in backend.requests[1].messages[-1].content
    assert outcome.no_obligation == ["SRC-0023"], "the cut id is asked for again"


def test_hazards_mark_the_requirements_that_quote_their_passages() -> None:
    requirements = dev_requirements()
    target = next(r for r in requirements if not r.hazard)
    hazard = SubmissionHazard(
        id="HZ-001", kind="DEADLINE", src_ids=[target.src_ids[0]], summary="A deadline."
    )
    marked, [linked] = link_hazards(requirements, [hazard])
    quoting = [r.id for r in requirements if target.src_ids[0] in r.src_ids]
    assert linked.requirement_ids == quoting
    assert next(r for r in marked if r.id == target.id).hazard is True
    others = [r.hazard for r in marked if r.id not in quoting]
    assert others == [r.hazard for r in requirements if r.id not in quoting]


def test_the_candidate_ledger_has_a_row_for_every_passage() -> None:
    passages = dev_ingest().passages
    backend = ScriptBackend(
        [
            text({"items": GOOD_ITEMS[:7], "no_obligation_src_ids": ["SRC-0021"]}),
            text({"items": [], "no_obligation_src_ids": []}),
        ]
    )
    outcome = extract_batch(context(backend), pack_of(SECTION_4))
    requirements, _ = assign_requirements([outcome], passages)
    zones = {(p.doc_id, p.section_path): "OBLIGATION" for p in SECTION_4}
    rows = {row.src_id: row for row in candidate_rows([outcome], passages, requirements, zones)}
    assert list(rows) == [p.id for p in passages]
    assert rows["SRC-0020"].dispositions == ["BINDING"] and rows["SRC-0020"].reasons == [""]
    assert rows["SRC-0020"].requirement_ids == ["REQ-0001"]
    assert rows["SRC-0021"].dispositions == ["NO_OBLIGATION"]
    assert rows["SRC-0028"].dispositions == ["UNACCOUNTED"], "missing after the repair"
    assert rows["SRC-0028"].reasons == ["unaccounted"]
    assert rows["SRC-0001"].dispositions == ["UNACCOUNTED"], "in no pack"
    assert rows["SRC-0020"].zone == "OBLIGATION" and rows["SRC-0001"].zone is None


def test_the_second_pass_reads_the_unbound_obligation_passages_again() -> None:
    no_templates = [i for i in GOOD_ITEMS if i["src_ids"] != ["SRC-0024"]]
    backend = ScriptBackend(
        [
            text({"items": no_templates, "no_obligation_src_ids": ["SRC-0021", "SRC-0024"]}),
            text({"items": [GOOD_ITEMS[3]], "no_obligation_src_ids": []}),
        ]
    )
    pack = pack_of(SECTION_4, zone="OBLIGATION")
    outcome = extract_batch(context(backend), pack, second_pass=True)
    first, again = backend.requests
    asked = again.messages[-1].content
    assert "that the first reading missed" in asked
    assert json.dumps(["SRC-0021", "SRC-0024"]) in asked
    tag = first.messages[1].content.split(">", 1)[0]
    assert again.messages[1].content.startswith(tag), "the same data tag"
    assert again.messages[0].content == first.messages[0].content and len(again.messages) == 2
    added = [(i, c) for i, c in outcome.accepted if c.second_pass]
    assert [i.src_ids for i, _ in added] == [["SRC-0024"]]
    requirements, _ = assign_requirements([outcome], dev_ingest().passages)
    rows = {r.src_id: r for r in candidate_rows([outcome], dev_ingest().passages, requirements)}
    assert rows["SRC-0024"].dispositions == ["NO_OBLIGATION", "OPTIONAL"]
    assert rows["SRC-0024"].reasons == ["", "second pass"]
    assert rows["SRC-0021"].dispositions == ["NO_OBLIGATION"], "no new item keeps its row"


def test_no_second_pass_without_the_flag_or_outside_obligation_zones() -> None:
    reply = text({"items": GOOD_ITEMS, "no_obligation_src_ids": ["SRC-0021"]})
    cases = ((pack_of(SECTION_4, zone="OBLIGATION"), False), (pack_of(SECTION_4), True))
    for pack, flag in cases:
        backend = ScriptBackend([reply])
        extract_batch(context(backend), pack, second_pass=flag)
        assert len(backend.requests) == 1


def test_requirements_take_zone_page_and_small_print_from_their_first_passage() -> None:
    passages = [
        p.model_copy(update={"page": 2, "small_print": p.id == "SRC-0025"})
        for p in dev_ingest().passages
    ]
    backend = ScriptBackend([text({"items": GOOD_ITEMS, "no_obligation_src_ids": ["SRC-0021"]})])
    outcome = extract_batch(context(backend), pack_of(SECTION_4))
    zones = {(p.doc_id, p.section_path): "OBLIGATION" for p in SECTION_4}
    requirements, _ = assign_requirements([outcome], passages, zones)
    assert {r.zone for r in requirements} == {"OBLIGATION"}
    assert {r.page for r in requirements} == {2}
    assert [r.src_ids[0] for r in requirements if r.small_print] == ["SRC-0025"]
    assert {r.doc_id for r in requirements} == {SECTION_4[0].doc_id}
