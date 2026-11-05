"""Lexical search over one run's passages: SQLite FTS5, ranked by BM25.

The index is `search.sqlite` in the run folder. A query is reduced to its content words, each
word is quoted, and the words are joined with OR, so no FTS5 operator written by a model or
hidden in a document reaches the engine. Function words such as "and" or "the" are dropped:
under OR they match nearly every passage, so a query like "REQ-0003 and REQ-0004" would pad
its results with unrelated passages. The `unicode61 remove_diacritics 2` tokenizer folds case and
accents, and the `porter` stemmer wrapped around it lets "migration" find "migrate", a miss
the development RFP showed without it. BM25 returns lower values for better matches, so
results sort ascending, and the score reported back is its negation, where higher is better.

The index holds the text a model may see, so `search_rfp` results come from it (D-05):
`build` takes the run's `TextView`, and with none it indexes the frozen text as every view of
`v0.0` showed it, line breaks as spaces.
"""

import re
import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from bidwright.ingest import display_text
from bidwright.schemas import Passage

if TYPE_CHECKING:
    from bidwright.harness.view import TextView

MAX_K = 8
MAX_QUERY_WORDS = 32
BY_ID = 100.0  # the score of a passage fetched by id rather than ranked by BM25
_WORD = re.compile(r"\w+")
# Function words only. Modal verbs, "not" and "no" stay: they carry meaning in an RFP.
STOPWORDS = frozenset(
    """a an the and or but nor if then than so as of to in on at by for from with into onto
    over under per via about upon within without between through during before after against
    is are was were be been being am do does did has have had it its this that these those
    they them their we us our you your he she his her which who whom whose what when where
    how there here also any all each every some such""".split()
)
# The tokenizer, shared with the knowledge-base index (`kb.py`, Iteration 3).
TOKENIZER = "porter unicode61 remove_diacritics 2"
_SCHEMA = (
    "CREATE VIRTUAL TABLE passages USING fts5("
    f"src_id UNINDEXED, section_path, text, tokenize = '{TOKENIZER}')"
)
# Column weights for bm25(): src_id is unindexed, a section-path hit counts half a text hit.
_RANK = "bm25(passages, 0.0, 0.5, 1.0)"


@dataclass(frozen=True)
class Hit:
    src_id: str
    section_path: str
    text: str
    score: float


def match_expression(query: str) -> str:
    """Every content word of the query as a quoted FTS5 string, joined with OR."""
    words = [w for w in _WORD.findall(query) if w.lower() not in STOPWORDS][:MAX_QUERY_WORDS]
    return " OR ".join('"' + word.replace('"', '""') + '"' for word in words)


class PassageIndex:
    def __init__(self, path: Path) -> None:
        self.path = path

    @classmethod
    def build(
        cls, passages: Iterable[Passage], path: Path, *, view: "TextView | None" = None
    ) -> "PassageIndex":
        """A fresh index of the passages, as `view` shows them; `None` means the frozen text."""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.unlink(missing_ok=True)
        rows = [
            (p.id, p.section_path, view.text(p) if view is not None else display_text(p.text))
            for p in passages
        ]
        with sqlite3.connect(path) as db:
            db.execute(_SCHEMA)
            db.executemany(
                "INSERT INTO passages (src_id, section_path, text) VALUES (?, ?, ?)", rows
            )
        return cls(path)

    def get(self, src_ids: Iterable[str]) -> list[Hit]:
        """Passages by id, in the order asked, with the score `BY_ID`."""
        wanted = list(dict.fromkeys(src_ids))
        if not wanted:
            return []
        db = sqlite3.connect(self.path)
        try:
            marks = ",".join("?" for _ in wanted)
            rows = db.execute(
                f"SELECT src_id, section_path, text FROM passages WHERE src_id IN ({marks})",  # noqa: S608
                wanted,
            ).fetchall()
        finally:
            db.close()
        found = {src_id: Hit(src_id, section, text, BY_ID) for src_id, section, text in rows}
        return [found[s] for s in wanted if s in found]

    def search(self, query: str, k: int = 5) -> list[Hit]:
        expression = match_expression(query)
        if not expression:
            return []
        db = sqlite3.connect(self.path)
        try:
            rows = db.execute(
                f"SELECT src_id, section_path, text, {_RANK} FROM passages"  # noqa: S608
                f" WHERE passages MATCH ? ORDER BY {_RANK}, src_id LIMIT ?",
                (expression, max(1, min(k, MAX_K))),
            ).fetchall()
        finally:
            db.close()
        return [Hit(src_id, section, text, round(-rank, 4)) for src_id, section, text, rank in rows]
