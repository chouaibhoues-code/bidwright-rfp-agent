"""Baselines: the simple configurations each agentic rung is judged against.

EX0 sends every passage of the RFP in one call to `extract_oneshot.md`, a plain instruction,
and expects the same `ExtractResult`. `verify` still checks its quotes, so the step from EX0
to EX1 measures batching and the prompt contract only. Run it with
`bidwright run <file> --baseline ex0`, and score it with the same scorer as any run.

B0 makes no LLM call (Iteration 1, step 8): the cue rule is the answer. Per passage, fewer
than three words, or no `MODAL`, `PROHIBITION`, `REJECTION` or `TABLE_ROW` cue, means no
obligation. Otherwise the passage is one item: its text, cut at the last space before 300
characters, is both the quote and the statement; the modality is the first of shall, must,
will, should and may that appears, or none; the disposition is OPTIONAL when the only
`MODAL` matches are "may" or "should" and no prohibition, rejection or table-row cue fired,
and BINDING otherwise; and the item is a hazard when a `DEADLINE` or `REJECTION` cue also
fired. Its quotes are verbatim by construction. B0 runs up to `verify` and stops there.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass

from bidwright.candidates import CompiledCues, cue_hits, cut, matches_by_kind
from bidwright.graph.nodes import BatchOutcome
from bidwright.ingest import display_text
from bidwright.schemas import QUOTE_MAX_CHARS, ExtractItem, Passage
from bidwright.verify import QuoteCheck

B0_BATCH = "B0"
OBLIGATION_CUES = frozenset({"MODAL", "PROHIBITION", "REJECTION", "TABLE_ROW"})
HAZARD_CUES = frozenset({"DEADLINE", "REJECTION"})
MODAL_WORDS = re.compile(r"\b(shall|must|will|should|may)\b", re.IGNORECASE)
SOFT_MODALS = frozenset({"may", "should"})
MIN_WORDS = 3


@dataclass(frozen=True)
class Baseline:
    name: str
    extract_prompt: str
    one_batch: bool
    llm: bool = True  # False when the baseline answers without a model
    until: str | None = None  # the last node the run executes, when it stops early


BASELINES = {
    "ex0": Baseline(name="ex0", extract_prompt="extract_oneshot", one_batch=True),
    "b0": Baseline("b0", extract_prompt="extract", one_batch=False, llm=False, until="verify"),
}


def b0_outcome(passages: Sequence[Passage], cues: CompiledCues) -> BatchOutcome:
    """One outcome over every passage, by the cue rule alone."""
    outcome = BatchOutcome(B0_BATCH)
    for passage, hit in zip(passages, cue_hits(passages, cues), strict=True):
        kinds = set(hit.kinds)
        text = passage.text
        if len(text.split()) < MIN_WORDS or not kinds & OBLIGATION_CUES:
            outcome.no_obligation.append(passage.id)
            continue
        modal_matches = [
            m.lower() for m in matches_by_kind(display_text(text), cues).get("MODAL", [])
        ]
        soft = bool(modal_matches) and all(m in SOFT_MODALS for m in modal_matches)
        optional = soft and not kinds & {"PROHIBITION", "REJECTION", "TABLE_ROW"}
        first = MODAL_WORDS.search(text)
        quote = cut(text, QUOTE_MAX_CHARS)
        item = ExtractItem(
            src_ids=[passage.id],
            quote=quote,
            statement=quote,
            modality=first.group(1).lower() if first else "none",  # type: ignore[arg-type]
            disposition="OPTIONAL" if optional else "BINDING",
            hazard=bool(kinds & HAZARD_CUES),
        )
        span = (passage.start, passage.start + len(quote))
        outcome.accepted.append((item, QuoteCheck("VERBATIM_VERIFIED", passage.id, span)))
    return outcome
