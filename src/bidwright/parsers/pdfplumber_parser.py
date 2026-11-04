"""The `v0.0` reading of a PDF with pdfplumber, as a parser (Iteration 1, step 7).

pdfplumber reads each word with its font, size and position. Then:
- Characters the guard found hidden are dropped first, matched by page, position and text.
- Lines that repeat in the same position on at least half the pages, within the top or bottom
  margin, are page headers or footers, removed and logged.
- A heading is a numbered line set in bold or above the body size, or any line set at least
  1.2 times the body size (`ingest.is_heading`).
- Body lines group into paragraphs by line spacing, and each table becomes one block whose
  first row is its header.
- A paragraph is small print when at least half of its characters lie in the guard's
  small-print boxes.
"""

import math
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pdfplumber

from bidwright.guard import FileGuard
from bidwright.ingest import (
    HEADING_NUMBER,
    LIST_MARKER,
    MARGIN_SHARE,
    PARAGRAPH_PITCH,
    is_heading,
    log,
)
from bidwright.parsers import Box, ParsedBlock, ParsedDocument, inside

HIDDEN_SLACK = 0.5  # points: a hidden character matches a page character this close


@dataclass
class _Line:
    page: int
    top: float
    bottom: float
    x0: float
    x1: float
    size: float
    bold: bool
    text: str
    small: int = 0  # characters inside the guard's small-print boxes
    chars: int = 0


@dataclass
class _Block:
    kind: str  # "heading", "paragraph" or "table"
    lines: list[str]
    size: float = 0.0
    rows: list[list[str]] = field(default_factory=list)
    page: int | None = None
    box: Box | None = None
    small: int = 0
    chars: int = 0


class PdfplumberParser:
    def parse(self, path: Path, doc_id: str, guard: FileGuard | None = None) -> ParsedDocument:
        hidden = guard.hidden if guard is not None else []
        small = guard.small_print if guard is not None else []
        with pdfplumber.open(path) as pdf:
            pages = []
            for page in pdf.pages:
                mine = [c for c in hidden if c.page == page.page_number]
                if mine:
                    page = page.filter(lambda obj, mine=mine: not _is_hidden(obj, mine))
                boxes = [(b.x0, b.top, b.x1, b.bottom) for b in small if b.page == page.page_number]
                pages.append(_page_content(page, boxes))
            heights = [float(page.height) for page in pdf.pages]
            count = len(pdf.pages)
        lines_by_page = [lines for lines, _ in pages]
        removed = _remove_running_lines(lines_by_page, heights)
        body_size = _body_size([line for lines in lines_by_page for line in lines])
        blocks = _blocks(lines_by_page, [tables for _, tables in pages], body_size)
        return ParsedDocument(doc_id, [_parsed(b) for b in blocks], count, removed)


def _is_hidden(obj: dict[str, Any], hidden: list[Any]) -> bool:
    if obj.get("object_type") != "char":
        return False
    return any(
        obj["text"] == h.text
        and abs(obj["x0"] - h.x0) <= HIDDEN_SLACK
        and abs(obj["top"] - h.top) <= HIDDEN_SLACK
        for h in hidden
    )


def _parsed(block: _Block) -> ParsedBlock:
    if block.kind == "table":
        rows = [tuple(row) for row in block.rows if any(row)]
        return ParsedBlock(
            "table",
            page=block.page,
            box=block.box,
            header_rows=tuple(rows[:1]),
            rows=tuple(rows[1:]),
        )
    if block.kind == "heading":
        return ParsedBlock("heading", 0, " ".join(block.lines), block.page, block.box)
    return ParsedBlock(
        "paragraph",
        text="\n".join(block.lines),
        page=block.page,
        box=block.box,
        small_print=block.chars > 0 and block.small * 2 >= block.chars,
    )


# --- Reading pages ---------------------------------------------------------------------


Table = tuple[float, list[list[str]], Box]


def _page_content(page: Any, small: list[Box]) -> tuple[list[_Line], list[Table]]:
    tables = page.find_tables()
    boxes = [table.bbox for table in tables]
    words = [
        word
        for word in page.extract_words(extra_attrs=["size", "fontname"])
        if not any(_inside(word, box) for box in boxes)
    ]
    rows_by_table = [
        (
            float(table.bbox[1]),
            [[_cell(cell) for cell in row] for row in table.extract()],
            _box(table.bbox),
        )
        for table in tables
    ]
    return _lines(words, page.page_number, small), rows_by_table


def _box(bbox: Any) -> Box:
    x0, top, x1, bottom = (float(v) for v in bbox)
    return (x0, top, x1, bottom)


def _inside(word: dict[str, Any], box: tuple[float, float, float, float]) -> bool:
    x = (word["x0"] + word["x1"]) / 2
    y = (word["top"] + word["bottom"]) / 2
    return box[0] <= x <= box[2] and box[1] <= y <= box[3]


def _cell(value: str | None) -> str:
    return " ".join((value or "").split())


def _lines(words: list[dict[str, Any]], page: int, small: list[Box]) -> list[_Line]:
    lines: list[list[dict[str, Any]]] = []
    for word in sorted(words, key=lambda w: (round(w["top"], 1), w["x0"])):
        if lines and abs(lines[-1][0]["top"] - word["top"]) <= 3:
            lines[-1].append(word)
        else:
            lines.append([word])
    out = []
    for group in lines:
        group.sort(key=lambda w: w["x0"])
        sizes = Counter(round(w["size"], 1) for w in group)
        centers = [((w["x0"] + w["x1"]) / 2, (w["top"] + w["bottom"]) / 2) for w in group]
        small_chars = sum(
            len(w["text"])
            for w, center in zip(group, centers, strict=True)
            if any(inside(center, box, 1.0) for box in small)
        )
        out.append(
            _Line(
                page=page,
                top=min(w["top"] for w in group),
                bottom=max(w["bottom"] for w in group),
                x0=group[0]["x0"],
                x1=max(w["x1"] for w in group),
                size=sizes.most_common(1)[0][0],
                bold=all("Bold" in w["fontname"] for w in group),
                text=" ".join(w["text"] for w in group),
                small=small_chars,
                chars=sum(len(w["text"]) for w in group),
            )
        )
    return out


def _running_key(line: _Line) -> tuple[int, str]:
    return round(line.top), re.sub(r"\d+", "#", line.text)


def _remove_running_lines(pages: list[list[_Line]], heights: list[float]) -> list[str]:
    """Drop margin lines that repeat in the same position on at least half the pages."""
    if len(pages) < 2:
        return []
    needed = max(2, math.ceil(len(pages) / 2))
    counts: Counter[tuple[int, str]] = Counter()
    for lines, height in zip(pages, heights, strict=True):
        counts.update({_running_key(ln) for ln in lines if _in_margin(ln, height)})
    running = {key for key, count in counts.items() if count >= needed}
    removed = []
    for index, (lines, height) in enumerate(zip(pages, heights, strict=True)):
        keep = []
        for line in lines:
            if _in_margin(line, height) and _running_key(line) in running:
                removed.append(f"page {index + 1}: {line.text}")
            else:
                keep.append(line)
        lines[:] = keep
    if removed:
        log.info("removed %d running header and footer lines", len(removed))
    return removed


def _in_margin(line: _Line, height: float) -> bool:
    return line.top < MARGIN_SHARE * height or line.bottom > (1 - MARGIN_SHARE) * height


def _body_size(lines: list[_Line]) -> float:
    weights: Counter[float] = Counter()
    for line in lines:
        weights[line.size] += len(line.text)
    return weights.most_common(1)[0][0] if weights else 10.0


# --- Blocks: headings, paragraphs and tables in reading order ---------------------------


def _blocks(pages: list[list[_Line]], tables: list[list[Table]], body_size: float) -> list[_Block]:
    blocks: list[_Block] = []
    previous: _Line | None = None
    for lines, page_tables in zip(pages, tables, strict=True):
        pending = sorted(page_tables, key=lambda item: item[0])
        for line in lines:
            while pending and pending[0][0] < line.top:
                blocks.append(_table(pending.pop(0), line.page))
                previous = None
            previous = _place(blocks, line, previous, body_size)
        page_number = lines[0].page if lines else None
        for table in pending:
            blocks.append(_table(table, page_number))
            previous = None
    return blocks


def _table(table: Table, page: int | None) -> _Block:
    _, rows, box = table
    return _Block("table", [], rows=rows, page=page, box=box)


def _grow(block: _Block, line: _Line) -> None:
    block.lines.append(line.text)
    block.small += line.small
    block.chars += line.chars
    if block.box is not None and block.page == line.page:
        x0, top, x1, bottom = block.box
        block.box = (
            min(x0, line.x0),
            min(top, line.top),
            max(x1, line.x1),
            max(bottom, line.bottom),
        )


def _start(kind: str, line: _Line) -> _Block:
    return _Block(
        kind,
        [line.text],
        size=line.size,
        page=line.page,
        box=(line.x0, line.top, line.x1, line.bottom),
        small=line.small,
        chars=line.chars,
    )


def _place(blocks: list[_Block], line: _Line, previous: _Line | None, body: float) -> _Line:
    if is_heading(line.text, line.size, line.bold, body):
        last = blocks[-1] if blocks else None
        same_heading = (
            last is not None
            and last.kind == "heading"
            and previous is not None
            and last.size == line.size
            and HEADING_NUMBER.match(line.text) is None
        )
        if same_heading and last is not None:
            _grow(last, line)
        else:
            blocks.append(_start("heading", line))
        return line
    if _continues(blocks, line, previous):
        _grow(blocks[-1], line)
    else:
        blocks.append(_start("paragraph", line))
    return line


def _continues(blocks: list[_Block], line: _Line, previous: _Line | None) -> bool:
    if not blocks or blocks[-1].kind != "paragraph" or previous is None:
        return False
    if LIST_MARKER.match(line.text) and blocks[-1].lines[-1].rstrip().endswith((":", ";", ".")):
        return False
    if line.page != previous.page:
        return not previous.text.rstrip().endswith((".", ":", ";", "?", "!"))
    return line.top - previous.top <= PARAGRAPH_PITCH * line.size
