"""The matcher's worked examples, on the development RFP."""

import pytest

from bidwright.ingest import IngestResult
from bidwright.schemas import Passage
from evals.matcher import gold_clauses, match
from tests.eval_fakes import gold, record
from tests.node_fakes import dev_ingest

pytestmark = pytest.mark.gold


@pytest.fixture(scope="module")
def run() -> IngestResult:
    return dev_ingest()


def _p(run: IngestResult, src_id: str) -> Passage:
    return next(p for p in run.passages if p.id == src_id)


def test_a_quote_inside_its_only_passage_is_a_strict_and_relaxed_hit(run: IngestResult) -> None:
    item = record(
        1, "The Supplier shall keep an audit record of every signature event", [_p(run, "SRC-0018")]
    )
    result = match([item], gold_clauses(gold(), run.frozen_text), {p.id: p for p in run.passages})
    assert result.captured == {"GR-0002": ["REQ-0001"]}
    assert "GR-0002" in result.strict and not result.merged


def test_citing_a_second_clause_is_flagged_merged(run: IngestResult) -> None:
    cited = [_p(run, "SRC-0023"), _p(run, "SRC-0024")]
    item = record(1, "The Supplier shall store signed documents for ten (10) years.", cited)
    result = match([item], gold_clauses(gold(), run.frozen_text), {p.id: p for p in run.passages})
    assert result.captured == {"GR-0006": ["REQ-0001"]} and result.merged == {"REQ-0001"}


def test_a_list_item_is_its_own_clause(run: IngestResult) -> None:
    item = record(
        1,
        "send a reminder to each signer who has not signed within 72 hours",
        [_p(run, "SRC-0021")],
    )
    result = match([item], gold_clauses(gold(), run.frozen_text), {p.id: p for p in run.passages})
    assert result.captured == {"GR-0004": ["REQ-0001"]}


def test_a_table_header_captures_nothing_and_background_is_a_false_positive(
    run: IngestResult,
) -> None:
    header = record(1, "Criterion | Weight", [_p(run, "SRC-0032")])
    background = record(
        2, "Previous suppliers have generally held ISO 27001 certification.", [_p(run, "SRC-0011")]
    )
    result = match(
        [header, background], gold_clauses(gold(), run.frozen_text), {p.id: p for p in run.passages}
    )
    assert result.captured == {}
    assert result.unmatched == ["REQ-0001"] and result.false_positive == {"REQ-0002"}


def test_a_second_record_on_a_clause_is_a_duplicate(run: IngestResult) -> None:
    passage = [_p(run, "SRC-0018")]
    first = record(1, "The Supplier shall keep an audit record of every signature event", passage)
    second = record(
        2, "keep an audit record of every signature event, including the signer's identity", passage
    )
    result = match(
        [first, second], gold_clauses(gold(), run.frozen_text), {p.id: p for p in run.passages}
    )
    assert result.captured["GR-0002"] == ["REQ-0001", "REQ-0002"] and result.duplicate == {
        "REQ-0002"
    }


def test_optional_records_count_and_other_dispositions_do_not(run: IngestResult) -> None:
    passage = [_p(run, "SRC-0026")]
    optional = record(
        1, "Bidders may propose an on-premises deployment option.", passage, "OPTIONAL"
    )
    background = record(
        2, "Bidders may propose an on-premises deployment option.", passage, "BACKGROUND"
    )
    result = match(
        [optional, background],
        gold_clauses(gold(), run.frozen_text),
        {p.id: p for p in run.passages},
    )
    assert result.captured == {"GR-0009": ["REQ-0001"]}
