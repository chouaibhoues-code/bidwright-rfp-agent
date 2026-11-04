"""The funnel: the first stage that lost each missed mandatory clause.

- `guard`: the clause is not in `frozen.txt`, and its text is in `quarantine.jsonl`.
- `parse`: the clause is not in `frozen.txt`, and nothing quarantined it.
- `verify`: an item cited one of the clause's passages and was rejected for its quote.
- `extract`: no item captured it; the passage's ledger row in `candidates.jsonl` says why
  (`NO_OBLIGATION`, `BACKGROUND`, `NOT_BINDING`, `OUT_OF_SCOPE` or `UNACCOUNTED`), or an item
  on the passage quoted something else.
- `consolidate` cannot lose a requirement, since every member ends in exactly one group, so
  it always shows 0.

Cue recall, the share of mandatory clauses whose passage carries a cue, is a diagnostic shown
beside the funnel: cues annotate passages and no longer filter them (ADR-017). Every input
except the frozen text and the passages is optional, so a `v0.0` run folder still scores.
"""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from bidwright.schemas import CandidateRow, Passage
from evals.matcher import GoldClause, in_quarantine, overlapping

STAGES = ("guard", "parse", "extract", "verify", "consolidate")
# The rejection reasons that are quote failures (step 11). "unaccounted" and "malformed
# output after repair" are losses in `extract`, not in `verify`.
QUOTE_FAILURES = (
    "not found in the cited passages",
    "not repaired",
    "withdrawn",
    "cites no passage of the batch",
    "a quote needs at least 3 words",
    "quote over 300 characters",
    "number not in source",
)
NOT_EXTRACTED = ("NO_OBLIGATION", "BACKGROUND", "NOT_BINDING", "OUT_OF_SCOPE", "UNACCOUNTED")


@dataclass(frozen=True)
class Loss:
    gold_id: str
    stage: str
    reason: str
    src_ids: tuple[str, ...] = ()


@dataclass
class RunTrail:
    """What the funnel reads from a run folder, beyond the passages."""

    candidates: Mapping[str, CandidateRow] = field(default_factory=dict)  # by src id
    rejected: Sequence[Mapping[str, Any]] = ()
    quarantined: Sequence[str] = ()  # the quarantined texts


def _rejection(src_ids: set[str], rejected: Sequence[Mapping[str, Any]]) -> str | None:
    for entry in rejected:
        cited = {str(s) for s in entry.get("src_ids") or []}
        reason = str(entry.get("reason") or "")
        if reason in QUOTE_FAILURES and src_ids & cited:
            return reason
    return None


def lost_at(clause: GoldClause, passages: Sequence[Passage], trail: RunTrail) -> Loss:
    """The first stage that lost a clause no record captured."""
    if clause.span is None:
        if in_quarantine(clause.text, trail.quarantined):
            return Loss(clause.gold_id, "guard", "its text was quarantined before parsing")
        return Loss(clause.gold_id, "parse", "its text is not in frozen.txt")
    cited = overlapping(clause.span, passages)
    ids = tuple(p.id for p in cited)
    reason = _rejection(set(ids), trail.rejected)
    if reason is not None:
        return Loss(clause.gold_id, "verify", f"an item citing it was rejected: {reason}", ids)
    for src_id in ids:
        row = trail.candidates.get(src_id)
        if row is None:
            continue
        lost = [
            f"{d}: {r}" if r else d
            for d, r in zip(row.dispositions, row.reasons, strict=True)
            if d in NOT_EXTRACTED
        ]
        if lost:
            return Loss(clause.gold_id, "extract", "; ".join(lost), ids)
    return Loss(clause.gold_id, "extract", "no item captured it", ids)


def funnel(
    missed: Iterable[GoldClause], passages: Sequence[Passage], trail: RunTrail
) -> dict[str, list[str]]:
    """Every stage, in order, with the clauses it lost first."""
    stages: dict[str, list[str]] = {stage: [] for stage in STAGES}
    for clause in missed:
        stages[lost_at(clause, passages, trail).stage].append(clause.gold_id)
    return {stage: sorted(ids) for stage, ids in stages.items()}


def cue_recall(
    mandatory: Sequence[GoldClause],
    passages: Sequence[Passage],
    cues: Mapping[str, Sequence[str]],
) -> float | None:
    """The share of located mandatory clauses with a cue on one of their passages, or None
    when the run recorded no cues."""
    located = [c for c in mandatory if c.span is not None]
    if not cues or not located:
        return None
    hits = sum(
        1
        for clause in located
        if clause.span is not None
        and any(cues.get(p.id) for p in overlapping(clause.span, passages))
    )
    return round(hits / len(located), 4)


__all__ = ["Loss", "RunTrail", "STAGES", "cue_recall", "funnel", "lost_at"]
