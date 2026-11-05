"""The query audit (Iteration 2, step 11): how close each text a run sent for research came to
the RFP.

`query_overlaps(run_dir)` gives every text in `research.json` that left for research, each job's
query and each question, its longest run of consecutive normalized words shared with one
passage of the run (`text.normalized_words` and `text.shared_run`), and that passage's id. The
gateway's rule G3 refuses 8 or more before anything is sent, so a recorded text should share at
most 7; step 15 reports the figures, never the texts.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from bidwright.ingest import display_text
from bidwright.schemas import Passage, ResearchRecord
from bidwright.text import normalized_words, shared_run

RESEARCH_FILE = "research.json"
PASSAGES_FILE = "passages.jsonl"


@dataclass(frozen=True)
class QueryOverlap:
    kind: Literal["query", "question"]
    label: str  # the job's label, or Q1, Q2 and on in the order the questions were asked
    shared: int  # the longest run of words shared with one passage
    src_id: str | None  # that passage, or None when the text shares no word


def query_overlaps(run_dir: Path) -> list[QueryOverlap]:
    """Each job's query, then each question, with its longest run shared with a passage."""
    record = ResearchRecord.model_validate_json(
        (run_dir / RESEARCH_FILE).read_text(encoding="utf-8")
    )
    passages = [
        Passage.model_validate_json(line)
        for line in (run_dir / PASSAGES_FILE).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    words = [(p.id, normalized_words(display_text(p.text))) for p in passages]
    sent: list[tuple[Literal["query", "question"], str, str]] = [
        ("query", job.label, job.query) for job in record.jobs
    ]
    for number, answer in enumerate(record.answers, start=1):
        sent.append(("question", f"Q{number}", answer.question))
    found = []
    for kind, label, text in sent:
        mine = normalized_words(text)
        best, where = 0, None
        for src_id, theirs in words:
            length = shared_run(mine, theirs)
            if length > best:
                best, where = length, src_id
        found.append(QueryOverlap(kind, label, best, where))
    return found


__all__ = ["QueryOverlap", "query_overlaps"]
