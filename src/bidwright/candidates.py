"""`candidates`: cue annotations and the defined-term registry, in code (Iteration 1, step 8;
ADR-017).

Every passage is matched against the cue kinds of `config/cues.yaml`, and a table row whose
header reads like a requirements table also gets `TABLE_ROW`. Cues are hints for `extract`
and the rule behind the B0 baseline: they never filter a passage out, since every passage
goes to `extract` (ADR-017). `cues.jsonl` holds one row per passage, including passages with
no cue.

The registry lists the terms the RFP defines: a passage defines a term when it reads
`"X" means`, `"X" shall mean` or `(the "X")`, with straight or curly quotes, or when its
section heading names definitions, interpretation or a glossary and it opens with a term of
at most six words followed by "means" or a colon. A definition is the passage text, cut at
the last space before 300 characters. `terms.json` holds the registry.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from bidwright.config import CUE_KINDS, CuesConfig, compile_patterns
from bidwright.ingest import display_text
from bidwright.schemas import (
    CUE_MATCHES_MAX,
    DEFINITION_MAX_CHARS,
    CueHit,
    CueKind,
    DefinedTerm,
    Passage,
)

QUOTED = r"[\"“”]([^\"“”]{1,80})[\"“”]"
DEFINES = re.compile(QUOTED + r"\s+(?:means|shall\s+mean)\b", re.IGNORECASE)
PARENTHETICAL = re.compile(r"\(the\s+" + QUOTED + r"\)", re.IGNORECASE)
DEFINITION_SECTION = re.compile(r"definition|interpretation|glossary", re.IGNORECASE)
OPENS_WITH_TERM = re.compile(r"^\s*([^\s:]+(?:\s+[^\s:]+){0,5}?)\s*(?:\bmeans\b|:)")


@dataclass(frozen=True)
class CompiledCues:
    kinds: dict[str, list[re.Pattern[str]]]
    table_row_headers: list[str]  # lowercase fragments a requirements table's header holds

    @classmethod
    def load(cls, config: CuesConfig) -> "CompiledCues":
        kinds = {
            kind: compile_patterns(config.kinds.get(kind, []), f"config/cues.yaml: cue kind {kind}")
            for kind in CUE_KINDS
        }
        return cls(kinds, [fragment.lower() for fragment in config.table_row_headers])


def cut(text: str, limit: int) -> str:
    """The text, cut at the last whitespace before `limit` characters when it is longer."""
    if len(text) <= limit:
        return text
    head = text[:limit]
    space = max(head.rfind(" "), head.rfind("\n"))
    return head[:space].rstrip() if space > 0 else head


def matches_by_kind(text: str, cues: CompiledCues) -> dict[str, list[str]]:
    """For each cue kind that fires, the strings its patterns matched, in pattern order."""
    found: dict[str, list[str]] = {}
    for kind, patterns in cues.kinds.items():
        for pattern in patterns:
            match = pattern.search(text)
            if match:
                found.setdefault(kind, []).append(match.group(0))
    return found


def _table_row(passage: Passage, by_id: dict[str, Passage], cues: CompiledCues) -> bool:
    if passage.kind != "table_row" or passage.header_id is None:
        return False
    header = by_id.get(passage.header_id)
    text = header.text.lower() if header is not None else ""
    return any(fragment in text for fragment in cues.table_row_headers)


def cue_hits(passages: Sequence[Passage], cues: CompiledCues) -> list[CueHit]:
    """One row per passage, in passage order."""
    by_id = {p.id: p for p in passages}
    hits = []
    for passage in passages:
        found = matches_by_kind(display_text(passage.text), cues)
        kinds: list[CueKind] = [k for k in CUE_KINDS if k in found]  # type: ignore[misc]
        if _table_row(passage, by_id, cues):
            kinds.append("TABLE_ROW")
        matches = [m for kind in kinds for m in found.get(kind, [])][:CUE_MATCHES_MAX]
        hits.append(CueHit(src_id=passage.id, kinds=kinds, matches=matches))
    return hits


def defined_terms(passages: Sequence[Passage]) -> list[DefinedTerm]:
    """The registry, first definition of a term first."""
    terms: dict[str, DefinedTerm] = {}
    for passage in passages:
        text = display_text(passage.text)
        found = [m.group(1) for m in DEFINES.finditer(text)]
        found += [m.group(1) for m in PARENTHETICAL.finditer(text)]
        if not found and DEFINITION_SECTION.search(passage.section_path):
            opening = OPENS_WITH_TERM.match(text)
            if opening:
                found.append(opening.group(1).strip('"“” '))
        for term in found:
            term = " ".join(term.split())
            if term and term.lower() not in terms:
                terms[term.lower()] = DefinedTerm(
                    term=term,
                    definition=cut(text, DEFINITION_MAX_CHARS),
                    src_id=passage.id,
                )
    return list(terms.values())


def write_candidates(run_dir: Path, hits: Sequence[CueHit], terms: Sequence[DefinedTerm]) -> None:
    """`cues.jsonl` and `terms.json`; `candidates` is their only writer."""
    run_dir.mkdir(parents=True, exist_ok=True)
    body = "".join(hit.model_dump_json() + "\n" for hit in hits)
    (run_dir / "cues.jsonl").write_text(body, encoding="utf-8", newline="\n")
    listing = "[" + ",\n ".join(term.model_dump_json() for term in terms) + "]\n"
    (run_dir / "terms.json").write_text(listing, encoding="utf-8", newline="\n")
