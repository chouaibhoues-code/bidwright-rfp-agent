"""Parsers turn one input file into blocks that `ingest` registers as passages (Iteration 1,
step 7). Each parser yields headings, paragraphs, list items and tables in reading order, with
the page and box of each block in pdfplumber's top-left origin where the format has pages.

`PdfplumberParser` is the `v0.0` reading of a PDF; `DoclingParser` sends PDF, DOCX and XLSX
files to the docling-serve service. Both drop the characters the guard found hidden, and both
mark a block as small print from the guard's small-print boxes.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Protocol

from bidwright.guard import FileGuard

BlockKind = Literal["heading", "paragraph", "list_item", "table"]
Box = tuple[float, float, float, float]  # x0, top, x1, bottom


@dataclass(frozen=True)
class ParsedBlock:
    kind: BlockKind
    level: int = 0  # a heading's level, 0 when the heading carries its depth in its number
    text: str = ""
    page: int | None = None  # 1-based; None for a format without pages
    box: Box | None = None
    rows: tuple[tuple[str, ...], ...] = ()  # a table's body rows, one string per column
    header_rows: tuple[tuple[str, ...], ...] = ()  # a table's header rows, top to bottom
    small_print: bool = False


@dataclass
class ParsedDocument:
    doc_id: str
    blocks: list[ParsedBlock]
    pages: int | None = None
    removed_lines: list[str] = field(default_factory=list)  # running headers and footers
    status: Literal["success", "partial_success"] = "success"
    errors: list[str] = field(default_factory=list)
    raw: dict[str, Any] | None = None  # the parser's own document, saved as parse/<doc_id>.json


class Parser(Protocol):
    def parse(self, path: Path, doc_id: str, guard: FileGuard | None = None) -> ParsedDocument: ...


def inside(point: tuple[float, float], box: Box, slack: float = 0.0) -> bool:
    x, y = point
    return box[0] - slack <= x <= box[2] + slack and box[1] - slack <= y <= box[3] + slack


def overlap_share(box: Box, others: list[Box]) -> float:
    """The share of `box`'s area that lies inside the union of `others`, assuming they do not
    overlap one another, as lines on a page do not."""
    area = max(box[2] - box[0], 0.0) * max(box[3] - box[1], 0.0)
    if area == 0:
        return 0.0
    covered = 0.0
    for other in others:
        width = min(box[2], other[2]) - max(box[0], other[0])
        height = min(box[3], other[3]) - max(box[1], other[1])
        if width > 0 and height > 0:
            covered += width * height
    return min(covered / area, 1.0)
