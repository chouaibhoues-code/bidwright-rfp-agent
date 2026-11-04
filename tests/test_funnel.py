"""The funnel charges each missed mandatory clause to the first stage that lost it: one miss
placed at each stage, on the development RFP, read straight from its gold lines."""

import pytest

from bidwright.schemas import CandidateRow
from evals.funnel import RunTrail, cue_recall, funnel, lost_at
from evals.matcher import GoldClause, gold_clauses, overlapping
from tests.eval_fakes import gold
from tests.node_fakes import dev_ingest

pytestmark = pytest.mark.gold


def _mandatory(clauses: list[GoldClause]) -> list[GoldClause]:
    return [c for c in clauses if c.kind == "requirement" and c.mandatory]


def _blanked(frozen: str, clauses: list[GoldClause]) -> str:
    """The frozen text with these clauses overwritten, at the same length."""
    for clause in clauses:
        assert clause.span is not None
        low, high = clause.span
        frozen = frozen[:low] + "#" * (high - low) + frozen[high:]
    return frozen


def test_one_miss_at_each_stage() -> None:
    ingest = dev_ingest()
    passages = list(ingest.passages)
    first = _mandatory(gold_clauses(gold(), ingest.frozen_text, passages))
    guarded, unparsed, unextracted, unverified = first[:4]
    clauses = _mandatory(
        gold_clauses(gold(), _blanked(ingest.frozen_text, [guarded, unparsed]), passages)
    )
    by_id = {c.gold_id: c for c in clauses}
    assert by_id[guarded.gold_id].span is None and by_id[unparsed.gold_id].span is None
    assert unextracted.span is not None and unverified.span is not None
    row_id = overlapping(unextracted.span, passages)[0]
    cited = overlapping(unverified.span, passages)[0]
    trail = RunTrail(
        candidates={
            row_id.id: CandidateRow(
                src_id=row_id.id,
                doc_id=row_id.doc_id,
                dispositions=["NO_OBLIGATION"],
                reasons=[""],
                round=0,
            )
        },
        rejected=[
            {"src_ids": [cited.id], "quote": "x", "reason": "not found in the cited passages"}
        ],
        quarantined=[f"Hidden: {guarded.text}"],
    )
    missed = [by_id[c.gold_id] for c in (guarded, unparsed, unextracted, unverified)]
    assert funnel(missed, passages, trail) == {
        "guard": [guarded.gold_id],
        "parse": [unparsed.gold_id],
        "extract": [unextracted.gold_id],
        "verify": [unverified.gold_id],
        "consolidate": [],
    }
    assert "NO_OBLIGATION" in lost_at(by_id[unextracted.gold_id], passages, trail).reason


def test_an_unaccounted_or_failed_batch_is_an_extract_loss() -> None:
    ingest = dev_ingest()
    passages = list(ingest.passages)
    clause = _mandatory(gold_clauses(gold(), ingest.frozen_text, passages))[0]
    assert clause.span is not None
    src_id = overlapping(clause.span, passages)[0].id
    for reason in ("unaccounted", "malformed output after repair"):
        trail = RunTrail(rejected=[{"src_ids": [src_id], "quote": "", "reason": reason}])
        assert lost_at(clause, passages, trail).stage == "extract", reason


def test_cue_recall_counts_mandatory_clauses_with_a_cue() -> None:
    ingest = dev_ingest()
    passages = list(ingest.passages)
    mandatory = _mandatory(gold_clauses(gold(), ingest.frozen_text, passages))
    span = mandatory[0].span
    assert span is not None
    cues = {p.id: ["MODAL"] for p in overlapping(span, passages)}
    assert cue_recall(mandatory, passages, cues) == round(1 / len(mandatory), 4)
    assert cue_recall(mandatory, passages, {}) is None, "a run with no cue rows"
