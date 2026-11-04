"""`candidates`: cue kinds match what they name and nothing else, the term registry finds
definitions, and B0 turns cues into an outcome with no LLM call."""

import json
from pathlib import Path

import pytest

from bidwright.baselines import BASELINES, b0_outcome
from bidwright.candidates import CompiledCues, cue_hits, defined_terms, write_candidates
from bidwright.config import load_config
from bidwright.graph.build import execute
from bidwright.preflight import Refused
from bidwright.schemas import Passage
from tests.node_fakes import DEV_RFP

CUES = CompiledCues.load(load_config().cues)


def _passages(*texts: str, section: str = "4 Requirements") -> list[Passage]:
    out, start = [], 0
    for number, text in enumerate(texts, start=1):
        out.append(
            Passage(
                id=f"SRC-{number:04d}",
                doc_id="fixture",
                section_path=section,
                kind="sentence",
                text=text,
                start=start,
                end=start + len(text),
            )
        )
        start += len(text) + 2
    return out


@pytest.mark.parametrize(
    ("kind", "fires", "quiet"),
    [
        (
            "MODAL",
            "The Supplier shall keep records of every change.",
            "The shallow end of the pool.",
        ),
        (
            "MODAL",
            "The Supplier is required to report each month.",
            "Reports are produced monthly.",
        ),
        ("PROHIBITION", "The Supplier must not disclose any data.", "The Supplier must notify us."),
        (
            "CONDITION",
            "Payment follows, provided that the work is accepted.",
            "The provisions apply.",
        ),
        (
            "RIGHT",
            "The Council reserves the right to audit the service.",
            "That is the right answer.",
        ),
        ("DEADLINE", "Tenders arrive no later than 2027-01-15.", "Tenders arrive later this year."),
        (
            "DEADLINE",
            "Respond within 10 working days of a request.",
            "Respond quickly to a request.",
        ),
        (
            "REJECTION",
            "Late tenders will be rejected without review.",
            "Ideas were rejected in 2025.",
        ),
        ("REFERENCE", "Delivery is in accordance with Annex B.", "The annexed map shows the site."),
        ("AMOUNT", "Turnover of at least £4,000,000 is needed.", "About 4,000 residents attend."),
        ("DATE", "The contract starts on 2027-04-01.", "The contract starts in spring."),
        ("DATE", "Bids close at 12:00 GMT on the day.", "Bids close at noon on the day."),
    ],
)
def test_each_cue_kind_matches_what_it_names(kind: str, fires: str, quiet: str) -> None:
    hit, miss = cue_hits(_passages(fires, quiet), CUES)
    assert kind in hit.kinds and hit.matches
    assert kind not in miss.kinds


def _table(header: str, row: str) -> list[Passage]:
    head = Passage(
        id="SRC-0001",
        doc_id="d",
        section_path="Annex",
        kind="table_header",
        text=header,
        start=0,
        end=len(header),
    )
    body = Passage(
        id="SRC-0002",
        doc_id="d",
        section_path="Annex",
        kind="table_row",
        text=row,
        start=len(header) + 1,
        end=len(header) + 1 + len(row),
        header_id="SRC-0001",
    )
    return [head, body]


def test_a_row_under_a_requirements_header_is_a_table_row_cue() -> None:
    requirement = cue_hits(
        _table("Ref | Requirement | Priority", "B-01 | Export cases | High"), CUES
    )
    assert requirement[1].kinds == ["TABLE_ROW"]
    timetable = cue_hits(_table("Stage | Date", "Contract award | 2027-03-15"), CUES)
    assert "TABLE_ROW" not in timetable[1].kinds and timetable[1].kinds == ["DATE"]


def test_every_passage_gets_a_row_even_with_no_cue(tmp_path: Path) -> None:
    passages = _passages("The Council serves residents.", "The Supplier shall comply.")
    hits = cue_hits(passages, CUES)
    assert [h.src_id for h in hits] == ["SRC-0001", "SRC-0002"]
    assert hits[0].kinds == [] and hits[0].matches == []
    write_candidates(tmp_path, hits, defined_terms(passages))
    lines = (tmp_path / "cues.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2 and json.loads((tmp_path / "terms.json").read_text()) == []


def test_the_term_registry_finds_definitions() -> None:
    long = '"Service Hours" means ' + "the hours of the service desk " * 20 + "on Working Days."
    passages = _passages(
        '"Council" means Halverton Borough Council.',
        "“Contractor” shall mean the bidder that wins the contract.",
        'Halverton Borough Council (the "Authority") invites tenders.',
        long,
        '"Council" means something else later.',
    )
    terms = {t.term: t for t in defined_terms(passages)}
    assert set(terms) == {"Council", "Contractor", "Authority", "Service Hours"}
    assert terms["Council"].src_id == "SRC-0001", "the first definition wins"
    definition = terms["Service Hours"].definition
    assert len(definition) <= 300 and long.startswith(definition) and not definition.endswith(" ")


def test_a_definitions_section_defines_terms_by_their_opening() -> None:
    inside = _passages(
        "Working Day: a day other than a Saturday or a Sunday.", section="14 Definitions"
    )
    outside = _passages("Price: forty percent of the total.", section="13 Evaluation")
    assert [t.term for t in defined_terms(inside)] == ["Working Day"]
    assert defined_terms(outside) == []


def test_b0_turns_cues_into_one_outcome_with_no_llm_call() -> None:
    long = "The Supplier shall " + "keep every record of every change for the whole term " * 8
    passages = _passages(
        "The Supplier shall keep an audit record of every change.",
        "Bidders may propose an on-premises deployment option.",
        "The Supplier should provide templates for the forms.",
        "The Supplier must not store any card number.",
        "Late tenders will be rejected without review.",
        "Tenders must arrive no later than 2027-01-15.",
        "The Council serves about 140,000 residents.",
        "Shall comply.",
        "The Supplier shall keep records, and bidders may add more.",
        long,
    )
    outcome = b0_outcome(passages, CUES)
    assert outcome.batch_id == "B0" and outcome.rejected == []
    assert outcome.no_obligation == ["SRC-0007", "SRC-0008"]
    items = {item.src_ids[0]: (item, check) for item, check in outcome.accepted}
    expected = {
        "SRC-0001": ("BINDING", "shall", False),
        "SRC-0002": ("OPTIONAL", "may", False),
        "SRC-0003": ("OPTIONAL", "should", False),
        "SRC-0004": ("BINDING", "must", False),
        "SRC-0005": ("BINDING", "will", True),
        "SRC-0006": ("BINDING", "must", True),
        "SRC-0009": ("BINDING", "shall", False),
        "SRC-0010": ("BINDING", "shall", False),
    }
    for src_id, (disposition, modality, hazard) in expected.items():
        item, check = items[src_id]
        assert (item.disposition, item.modality, item.hazard) == (disposition, modality, hazard)
        passage = passages[int(src_id[4:]) - 1]
        assert check.status == "VERBATIM_VERIFIED" and check.src_id == src_id
        assert check.span == (passage.start, passage.start + len(item.quote))
        assert passage.text.startswith(item.quote) and item.statement == item.quote
    assert len(items["SRC-0010"][0].quote) <= 300


def test_b0_counts_a_table_row_under_a_requirements_header() -> None:
    passages = _table(
        "Ref | Requirement | Priority", "B-01 | Export every closed case as PDF/A. | High"
    )
    [(item, _)] = b0_outcome(passages, CUES).accepted
    assert item.disposition == "BINDING" and item.modality == "none"


def test_b0_is_registered_and_waits_for_the_graph(tmp_path: Path) -> None:
    b0 = BASELINES["b0"]
    assert (b0.llm, b0.until, b0.one_batch) == (False, "verify", False)
    with pytest.raises(Refused, match="step 16"):
        execute(source=DEV_RFP, profile="free", outputs=tmp_path, baseline="b0")
    assert not any(tmp_path.iterdir())
