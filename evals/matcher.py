"""The coverage matcher: was each gold obligation captured, and by which records?

1. Each gold clause maps to a span of the run's frozen text by search after whitespace
   normalization. A list item's span can extend back over its lead-in.
2. Predictions are records with disposition BINDING or OPTIONAL and a verified quote.
3. Relaxed capture: the record's verified quote lies inside the clause span (or inside the
   clause plus its lead-in, for a list item). Strict capture also needs the record's cited
   passages to cover the whole clause.
4. A record whose cited passages reach a second gold clause is flagged `merged`. Extra
   records on an already captured clause are flagged `duplicate`.
5. A prediction that captures no gold clause goes to adjudication, so precision is a range.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from bidwright.schemas import Passage, Requirement
from bidwright.verify import normalize

PREDICTIONS = ("BINDING", "OPTIONAL")
VERIFIED = ("VERBATIM_VERIFIED", "NORMALIZED_MATCH")


@dataclass(frozen=True)
class GoldClause:
    gold_id: str
    kind: str
    text: str
    mandatory: bool
    hazard: bool
    span: tuple[int, int]
    context: tuple[int, int]  # the span plus the lead-in, for a list item


@dataclass
class Match:
    captured: dict[str, list[str]] = field(default_factory=dict)  # gold id -> record ids
    strict: set[str] = field(default_factory=set)
    merged: set[str] = field(default_factory=set)  # record ids
    duplicate: set[str] = field(default_factory=set)
    false_positive: set[str] = field(default_factory=set)  # predictions on background
    unmatched: list[str] = field(default_factory=list)  # predictions on no gold clause


def locate(text: str, frozen: str, start: int = 0) -> tuple[int, int] | None:
    """The frozen-text span of `text`, matching whitespace loosely."""
    wanted, _ = normalize(text)
    haystack, origin = normalize(frozen[start:])
    found = haystack.find(wanted)
    if found < 0 or not wanted:
        return None
    return start + origin[found], start + origin[found + len(wanted) - 1] + 1


def gold_clauses(lines: Sequence[dict[str, Any]], frozen: str) -> list[GoldClause]:
    clauses = []
    for line in lines:
        if line["kind"] not in ("requirement", "background"):
            continue
        span = locate(line["text"], frozen)
        if span is None:
            raise ValueError(f"{line['gold_id']} is not in the frozen text")
        context = span
        if line.get("lead_in"):
            before = frozen.rfind(line["lead_in"].rstrip(), 0, span[0])
            context = (before if before >= 0 else span[0], span[1])
        clauses.append(
            GoldClause(
                gold_id=line["gold_id"],
                kind=line["kind"],
                text=line["text"],
                mandatory=bool(line.get("mandatory")),
                hazard=bool(line.get("hazard")),
                span=span,
                context=context,
            )
        )
    return clauses


def _inside(inner: tuple[int, int], outer: tuple[int, int]) -> bool:
    return outer[0] <= inner[0] and inner[1] <= outer[1]


def _overlaps(a: tuple[int, int], b: tuple[int, int]) -> bool:
    return a[0] < b[1] and b[0] < a[1]


def match(
    records: Sequence[Requirement], clauses: Sequence[GoldClause], passages: dict[str, Passage]
) -> Match:
    result = Match()
    predictions = [
        r
        for r in records
        if r.disposition in PREDICTIONS and r.quote_status in VERIFIED and r.quote_span
    ]
    for record in predictions:
        quote = record.quote_span
        assert quote is not None  # noqa: S101 - filtered above
        cited = [(passages[s].start, passages[s].end) for s in record.src_ids if s in passages]
        hits = [c for c in clauses if _inside(quote, c.context)]
        if not hits:
            result.unmatched.append(record.id)
            continue
        if all(c.kind == "background" for c in hits):
            result.false_positive.add(record.id)
            continue
        for clause in hits:
            if clause.kind != "requirement":
                continue
            owners = result.captured.setdefault(clause.gold_id, [])
            if owners:
                result.duplicate.add(record.id)
            owners.append(record.id)
            covered = sum(max(0, min(e, clause.span[1]) - max(s, clause.span[0])) for s, e in cited)
            if covered >= clause.span[1] - clause.span[0]:
                result.strict.add(clause.gold_id)
            others = [c for c in clauses if c is not clause and c.kind == "requirement"]
            if any(_overlaps(span, other.span) for span in cited for other in others):
                result.merged.add(record.id)
    return result
