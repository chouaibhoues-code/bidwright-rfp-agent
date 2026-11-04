"""The coverage matcher: was each gold obligation captured, and by which records?

1. Each gold clause of the four clause kinds (`requirement`, `background`, `not_binding`,
   `out_of_scope`) maps to a span of the run's frozen text, searched after whitespace
   normalization inside the passages of its own document: those whose `doc_id` starts with
   the clause's `doc_id`. A list item's span can extend back over its lead-in. A clause that
   is not found gets `span=None`; the funnel then charges it to `guard` or `parse`. Trap,
   personal-data and seed lines are not clauses.
2. Predictions are records with disposition BINDING or OPTIONAL and a verified quote.
3. Relaxed capture: the record's verified quote lies inside the clause span (or inside the
   clause plus its lead-in, for a list item) and reaches the clause itself, so a quote of the
   lead-in alone, or of an earlier item of the same list, captures nothing. Strict capture
   also needs the record's cited passages to cover the whole clause.
4. A record whose cited passages reach a second requirement clause is flagged `merged`.
   Extra records on an already captured clause are flagged `duplicate`.
5. A prediction whose hits are all distractor clauses (`background`, `not_binding`,
   `out_of_scope`) is a false positive, so a distractor never inflates precision. A
   prediction that captures no gold clause goes to adjudication, so precision is a range.
6. A gold clause in a hidden layer is expected in `quarantine.jsonl`, found there by its
   text, and scored on its own line, never as a miss.
"""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from bidwright.schemas import Passage, Requirement
from bidwright.verify import normalize

PREDICTIONS = ("BINDING", "OPTIONAL")
VERIFIED = ("VERBATIM_VERIFIED", "NORMALIZED_MATCH")
CLAUSE_KINDS = ("requirement", "background", "not_binding", "out_of_scope")
DISTRACTORS = ("background", "not_binding", "out_of_scope")
VISIBLE_LAYERS = ("visible", "small_print")

Span = tuple[int, int]


@dataclass(frozen=True)
class GoldClause:
    gold_id: str
    kind: str
    text: str
    mandatory: bool
    hazard: bool
    span: Span | None  # None when the clause is not in the frozen text
    context: Span | None  # the span plus the lead-in, for a list item
    doc_id: str = ""
    disposition: str | None = None
    modality: str | None = None
    zone: str | None = None
    implicit: str | None = None
    layer: str = "visible"
    small_print: bool = False

    @property
    def hidden(self) -> bool:
        """In a hidden layer, so `guard` should have quarantined it before parsing."""
        return self.layer not in VISIBLE_LAYERS


@dataclass
class Match:
    captured: dict[str, list[str]] = field(default_factory=dict)  # gold id -> record ids
    strict: set[str] = field(default_factory=set)
    merged: set[str] = field(default_factory=set)  # record ids
    duplicate: set[str] = field(default_factory=set)
    false_positive: set[str] = field(default_factory=set)  # predictions on distractors only
    unmatched: list[str] = field(default_factory=list)  # predictions on no gold clause
    # Every verified record whose quote lies inside the clause, whatever its disposition,
    # for disposition accuracy: gold id -> record ids, in record order.
    covering: dict[str, list[str]] = field(default_factory=dict)


def locate(text: str, frozen: str, start: int = 0, end: int | None = None) -> Span | None:
    """The frozen-text span of `text` inside `frozen[start:end]`, matching whitespace
    loosely."""
    stop = len(frozen) if end is None else end
    wanted, _ = normalize(text)
    haystack, origin = normalize(frozen[start:stop])
    found = haystack.find(wanted)
    if found < 0 or not wanted:
        return None
    return start + origin[found], start + origin[found + len(wanted) - 1] + 1


def document_range(doc_id: str, passages: Iterable[Passage]) -> Span | None:
    """The frozen-text range of the passages of a gold document: those whose `doc_id` starts
    with the gold `doc_id`, as the run's doc ids add a hash suffix."""
    spans = [(p.start, p.end) for p in passages if p.doc_id.startswith(doc_id)]
    if not spans:
        return None
    return min(s for s, _ in spans), max(e for _, e in spans)


def gold_clauses(
    lines: Sequence[dict[str, Any]], frozen: str, passages: Iterable[Passage]
) -> list[GoldClause]:
    passages = list(passages)
    ranges: dict[str, Span | None] = {}
    clauses = []
    for line in lines:
        if line["kind"] not in CLAUSE_KINDS:
            continue
        doc_id = line.get("doc_id", "")
        if doc_id not in ranges:
            ranges[doc_id] = document_range(doc_id, passages)
        bounds = ranges[doc_id]
        span = locate(line["text"], frozen, *bounds) if bounds else None
        context = span
        if span is not None and line.get("lead_in"):
            low = bounds[0] if bounds else 0
            before = frozen.rfind(line["lead_in"].rstrip(), low, span[0])
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
                doc_id=doc_id,
                disposition=line.get("disposition"),
                modality=line.get("modality"),
                zone=line.get("zone"),
                implicit=line.get("implicit"),
                layer=line.get("layer") or "visible",
                small_print=bool(line.get("small_print")),
            )
        )
    return clauses


def in_quarantine(text: str, quarantined: Iterable[str]) -> bool:
    """Whether a gold text or trap marker occurs in a quarantined text, whitespace loosely."""
    wanted, _ = normalize(text)
    return bool(wanted) and any(wanted in normalize(q)[0] for q in quarantined)


def overlapping(span: Span, passages: Iterable[Passage]) -> list[Passage]:
    return [p for p in passages if p.start < span[1] and span[0] < p.end]


def _inside(inner: Span, outer: Span) -> bool:
    return outer[0] <= inner[0] and inner[1] <= outer[1]


def quote_hits(quote: Span, clause: GoldClause) -> bool:
    """The quote lies inside the clause, or inside its lead-in and the clause, and reaches
    the clause itself: a quote of only the lead-in, or of an earlier item of the same list,
    captures nothing."""
    if clause.span is None or clause.context is None:
        return False
    return _inside(quote, clause.context) and _overlaps(quote, clause.span)


def _overlaps(a: Span, b: Span) -> bool:
    return a[0] < b[1] and b[0] < a[1]


def match(
    records: Sequence[Requirement],
    clauses: Sequence[GoldClause],
    passages: Mapping[str, Passage],
) -> Match:
    result = Match()
    located = [c for c in clauses if c.context is not None]
    requirements = [c for c in located if c.kind == "requirement"]
    for record in records:
        quote = record.quote_span
        if record.quote_status not in VERIFIED or quote is None:
            continue
        for clause in located:
            if quote_hits(quote, clause):
                result.covering.setdefault(clause.gold_id, []).append(record.id)
    for record in records:
        quote = record.quote_span
        if record.disposition not in PREDICTIONS or record.quote_status not in VERIFIED:
            continue
        if quote is None:
            continue
        cited = [(passages[s].start, passages[s].end) for s in record.src_ids if s in passages]
        hits = [c for c in located if quote_hits(quote, c)]
        if not hits:
            result.unmatched.append(record.id)
            continue
        if all(c.kind in DISTRACTORS for c in hits):
            result.false_positive.add(record.id)
            continue
        for clause in hits:
            if clause.kind != "requirement" or clause.span is None:
                continue
            owners = result.captured.setdefault(clause.gold_id, [])
            if owners:
                result.duplicate.add(record.id)
            owners.append(record.id)
            low, high = clause.span
            covered = sum(max(0, min(e, high) - max(s, low)) for s, e in cited)
            if covered >= high - low:
                result.strict.add(clause.gold_id)
            others = [c.span for c in requirements if c is not clause and c.span is not None]
            if any(_overlaps(span, other) for span in cited for other in others):
                result.merged.add(record.id)
    return result
