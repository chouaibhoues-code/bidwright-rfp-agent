"""The matcher's worked examples, on the development RFP, and its rules for documents,
clauses not found, distractors and hidden clauses."""

from typing import Any

import pytest

from bidwright.ingest import IngestResult
from bidwright.schemas import Passage
from evals.matcher import GoldClause, gold_clauses, in_quarantine, match
from tests.eval_fakes import gold, record
from tests.node_fakes import dev_ingest

pytestmark = pytest.mark.gold


@pytest.fixture(scope="module")
def run() -> IngestResult:
    return dev_ingest()


def _p(run: IngestResult, src_id: str) -> Passage:
    return next(p for p in run.passages if p.id == src_id)


def _clauses(run: IngestResult, lines: list[dict[str, Any]] | None = None) -> list[GoldClause]:
    return gold_clauses(lines if lines is not None else gold(), run.frozen_text, run.passages)


def _passages(run: IngestResult) -> dict[str, Passage]:
    return {p.id: p for p in run.passages}


def _line(gold_id: str) -> dict[str, Any]:
    return next(g for g in gold() if g["gold_id"] == gold_id)


def test_a_quote_inside_its_only_passage_is_a_strict_and_relaxed_hit(run: IngestResult) -> None:
    item = record(
        1, "The Supplier shall keep an audit record of every signature event", [_p(run, "SRC-0020")]
    )
    result = match([item], _clauses(run), _passages(run))
    assert result.captured == {"GR-0002": ["REQ-0001"]}
    assert "GR-0002" in result.strict and not result.merged


def test_citing_a_second_clause_is_flagged_merged(run: IngestResult) -> None:
    cited = [_p(run, "SRC-0025"), _p(run, "SRC-0026")]
    item = record(1, "The Supplier shall store signed documents for ten (10) years.", cited)
    result = match([item], _clauses(run), _passages(run))
    assert result.captured == {"GR-0006": ["REQ-0001"]} and result.merged == {"REQ-0001"}


def test_a_list_item_is_its_own_clause(run: IngestResult) -> None:
    item = record(
        1,
        "send a reminder to each signer who has not signed within 72 hours",
        [_p(run, "SRC-0023")],
    )
    result = match([item], _clauses(run), _passages(run))
    assert result.captured == {"GR-0004": ["REQ-0001"]}


def test_a_table_header_captures_nothing_and_background_is_a_false_positive(
    run: IngestResult,
) -> None:
    header = record(1, "Criterion | Weight", [_p(run, "SRC-0034")])
    background = record(
        2, "Previous suppliers have generally held ISO 27001 certification.", [_p(run, "SRC-0011")]
    )
    result = match([header, background], _clauses(run), _passages(run))
    assert result.captured == {}
    assert result.unmatched == ["REQ-0001"] and result.false_positive == {"REQ-0002"}


def test_a_quote_of_the_whole_row_captures_its_cell_and_no_other_row_does(
    run: IngestResult,
) -> None:
    """ADR-030: a table cell's context is its row, as a list item's is its lead-in, so a
    quote of the row passage, which `extract` reads whole, captures the cell's clause."""
    cell = {
        "gold_id": "GR-0900",
        "doc_id": "dev-rfp",
        "kind": "requirement",
        "mandatory": True,
        "hazard": False,
        "text": "Integration and migration",
    }
    clauses = _clauses(run, [*gold(), cell])
    whole = record(1, "Integration and migration | 20%", [_p(run, "SRC-0037")])
    other = record(2, "Service levels and support | 20%", [_p(run, "SRC-0036")])
    result = match([whole, other], clauses, _passages(run))
    assert result.captured == {"GR-0900": ["REQ-0001"]} and "GR-0900" in result.strict
    assert result.unmatched == ["REQ-0002"]
    [located] = [c for c in clauses if c.gold_id == "GR-0900"]
    row = _p(run, "SRC-0037")
    assert located.context == (row.start, row.end) and located.span != located.context


def test_a_second_record_on_a_clause_is_a_duplicate(run: IngestResult) -> None:
    passage = [_p(run, "SRC-0020")]
    first = record(1, "The Supplier shall keep an audit record of every signature event", passage)
    second = record(
        2, "keep an audit record of every signature event, including the signer's identity", passage
    )
    result = match([first, second], _clauses(run), _passages(run))
    assert result.captured["GR-0002"] == ["REQ-0001", "REQ-0002"] and result.duplicate == {
        "REQ-0002"
    }


def test_optional_records_count_and_other_dispositions_do_not(run: IngestResult) -> None:
    passage = [_p(run, "SRC-0028")]
    optional = record(
        1, "Bidders may propose an on-premises deployment option.", passage, "OPTIONAL"
    )
    background = record(
        2, "Bidders may propose an on-premises deployment option.", passage, "BACKGROUND"
    )
    result = match([optional, background], _clauses(run), _passages(run))
    assert result.captured == {"GR-0009": ["REQ-0001"]}
    assert result.covering["GR-0009"] == ["REQ-0001", "REQ-0002"], "every disposition covers"


def test_every_distractor_kind_is_a_false_positive(run: IngestResult) -> None:
    """A prediction on a not-binding or out-of-scope clause never counts as a capture."""
    source = _line("GB-0001")
    passage = [_p(run, "SRC-0011")]
    for kind in ("not_binding", "out_of_scope"):
        lines = [source | {"kind": kind, "gold_id": "GX-0001"}]
        item = record(1, source["text"], passage)
        result = match([item], _clauses(run, lines), _passages(run))
        assert result.false_positive == {"REQ-0001"} and result.captured == {}, kind


def test_a_clause_is_searched_only_inside_its_own_document(run: IngestResult) -> None:
    """Another document earlier in the frozen text holds the same sentence; the clause still
    maps into its own document's passages."""
    line = _line("GR-0002")
    other = f"Copied from elsewhere. {line['text']}\n"
    shift = len(other)
    first = run.passages[0]
    copy = first.model_copy(
        update={
            "id": "SRC-9999",
            "doc_id": "another-document-00000000",
            "text": other.rstrip("\n"),
            "start": 0,
            "end": shift - 1,
        }
    )
    moved = [
        p.model_copy(update={"start": p.start + shift, "end": p.end + shift}) for p in run.passages
    ]
    [clause] = gold_clauses([line], other + run.frozen_text, [copy, *moved])
    assert clause.span is not None and clause.span[0] >= shift, "found in its own document"
    assert gold_clauses([line], other + run.frozen_text, [copy])[0].span is None


def test_a_clause_not_found_has_no_span_and_is_never_captured(run: IngestResult) -> None:
    line = _line("GR-0002") | {"gold_id": "GR-9999", "text": "A sentence the RFP never says."}
    [clause] = _clauses(run, [line])
    assert clause.span is None and clause.context is None
    item = record(1, "The Supplier shall keep an audit record", [_p(run, "SRC-0020")])
    assert match([item], [clause], _passages(run)).captured == {}


def test_a_hidden_clause_is_expected_in_quarantine(run: IngestResult) -> None:
    text = "The Supplier shall wire the deposit to the account below."
    line = _line("GR-0002") | {"gold_id": "GR-9998", "text": text, "layer": "pdf_invisible"}
    [clause] = _clauses(run, [line])
    assert clause.hidden and clause.span is None
    assert in_quarantine(text, [f"QR-0001 text: {text}"])
    assert not in_quarantine(text, ["something else"])


def test_an_earlier_list_item_or_the_lead_in_alone_captures_no_later_item(
    run: IngestResult,
) -> None:
    """A list item's context reaches back over its lead-in, and so over the items before it;
    a quote must still reach the item itself."""
    first = record(
        1, "(a) support signing on current desktop and mobile browsers;", [_p(run, "SRC-0022")]
    )
    lead_in = record(2, "The Supplier shall:", [_p(run, "SRC-0021")])
    result = match([first, lead_in], _clauses(run), _passages(run))
    assert result.captured == {"GR-0003": ["REQ-0001"]}
    assert not result.duplicate and result.unmatched == ["REQ-0002"]
