"""Ingest one PDF into frozen text and registered passages, by the Iteration 0a rules.

pdfplumber reads each word with its font, size and position. Then:
- Lines that repeat in the same position on at least half the pages, within the top or
  bottom margin, are page headers or footers. They are removed before splitting, and logged.
- A heading starts a section: a numbered line such as "4.2 Records" set in bold or above the
  body size, or any line set at least 1.2 times the body size. Requiring the larger or bold
  font for numbered lines stops a wrapped body line such as "20 pages by ..." from becoming a
  heading. `section_path` joins the numbered headings, as in "4 Requirements > 4.1 Signing".
- Body lines group into paragraphs by line spacing. A paragraph splits into sentences on
  ".", "?" or "!" followed by a space and a capital letter, except after an abbreviation.
- After a passage that ends with ":", paragraphs that start with a list marker are list
  items, and their `lead_in_id` is that passage.
- Each table row is a `table_row` passage whose `header_id` is the table's first row.

The frozen text keeps the PDF's line breaks, and every passage is a half-open slice of it.
`display_text` gives the form a model sees, with line breaks as spaces and the same offsets.
"""

import hashlib
import logging
import math
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pdfplumber

from bidwright.schemas import Passage, PassageKind

log = logging.getLogger(__name__)

HEADING_NUMBER = re.compile(r"^(\d+(?:\.\d+)*)\s+\S")
LIST_MARKER = re.compile(
    r"^(?:[•▪◦*–-]\s+"  # bullets and dashes
    r"|\((?:[a-z]{1,2}|[ivxlc]{1,5}|\d{1,2})\)\s+"  # (a) (iv) (3)
    r"|(?:[a-z]|[ivxlc]{1,5}|\d{1,2})[.)]\s+)",  # a) iv. 3.
    re.IGNORECASE,
)
SENTENCE_END = re.compile(r"[.?!][\"')\]]?\s+(?=[A-Z])")
ABBREVIATIONS = frozenset(
    "e.g i.e etc no nos vs approx cf fig figs sec art para mr mrs ms dr st ltd inc co".split()
)
MARGIN_SHARE = 0.12  # headers and footers live in the top or bottom 12% of the page
PARAGRAPH_PITCH = 1.55  # a line more than this many font sizes below the last starts a paragraph


@dataclass
class _Line:
    page: int
    top: float
    bottom: float
    x0: float
    size: float
    bold: bool
    text: str


@dataclass
class _Block:
    kind: str  # "heading", "paragraph" or "table"
    lines: list[str]
    size: float = 0.0
    rows: list[list[str]] = field(default_factory=list)


@dataclass(frozen=True)
class IngestResult:
    doc_id: str
    frozen_text: str
    passages: tuple[Passage, ...]
    removed_lines: tuple[str, ...]


def doc_id_for(path: Path, data_class: str = "synthetic") -> str:
    """A corpus file's id is its stem, lowercased, non-alphanumerics as hyphens, plus 8 hex
    digits of its hash. A client document's id is `doc-` and those 8 digits, so its name never
    reaches a run id, a span or a folder name (D-05)."""
    digest = hashlib.sha256(path.read_bytes()).hexdigest()[:8]
    if data_class == "client":
        return f"doc-{digest}"
    stem = re.sub(r"[^a-z0-9]+", "-", path.stem.lower()).strip("-")
    return f"{stem}-{digest}"


def display_text(text: str) -> str:
    """Line breaks as spaces. Same length, so offsets carry over unchanged."""
    return text.replace("\n", " ")


def split_sentences(text: str) -> list[tuple[int, int]]:
    """Half-open spans of the sentences in `text`, trimmed of surrounding whitespace."""
    flat = display_text(text)
    cuts = [0]
    for match in SENTENCE_END.finditer(flat):
        word = re.search(r"([A-Za-z.]+)[.?!][\"')\]]?$", flat[: match.start() + 1])
        if word and word.group(1).lower().rstrip(".") in ABBREVIATIONS:
            continue
        cuts.append(match.end())
    cuts.append(len(flat))
    spans = []
    for start, end in zip(cuts, cuts[1:], strict=False):
        while start < end and flat[start].isspace():
            start += 1
        while end > start and flat[end - 1].isspace():
            end -= 1
        if end > start:
            spans.append((start, end))
    return spans


def is_heading(text: str, size: float, bold: bool, body_size: float) -> bool:
    if size >= 1.2 * body_size:
        return True
    numbered = HEADING_NUMBER.match(text) is not None
    return numbered and len(text) <= 120 and (bold or size >= 1.1 * body_size)


def ingest_pdf(path: Path, run_dir: Path | None = None) -> IngestResult:
    """Read `path`, and write `frozen.txt` and `passages.jsonl` to `run_dir` when given."""
    doc_id = doc_id_for(path)
    with pdfplumber.open(path) as pdf:
        pages = [_page_content(page) for page in pdf.pages]
        heights = [float(page.height) for page in pdf.pages]
    lines_by_page = [lines for lines, _ in pages]
    removed = _remove_running_lines(lines_by_page, heights)
    body_size = _body_size([line for lines in lines_by_page for line in lines])
    blocks = _blocks(lines_by_page, [tables for _, tables in pages], body_size)
    frozen, passages = _register(blocks, doc_id)
    result = IngestResult(doc_id, frozen, tuple(passages), tuple(removed))
    if run_dir is not None:
        write_ingest(result, run_dir)
    return result


def write_ingest(result: IngestResult, run_dir: Path) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "frozen.txt").write_text(result.frozen_text, encoding="utf-8", newline="\n")
    body = "".join(passage.model_dump_json() + "\n" for passage in result.passages)
    (run_dir / "passages.jsonl").write_text(body, encoding="utf-8", newline="\n")


# --- Reading pages ---------------------------------------------------------------------


def _page_content(page: Any) -> tuple[list[_Line], list[tuple[float, list[list[str]]]]]:
    tables = page.find_tables()
    boxes = [table.bbox for table in tables]
    words = [
        word
        for word in page.extract_words(extra_attrs=["size", "fontname"])
        if not any(_inside(word, box) for box in boxes)
    ]
    rows_by_table = [
        (float(table.bbox[1]), [[_cell(cell) for cell in row] for row in table.extract()])
        for table in tables
    ]
    return _lines(words, page.page_number), rows_by_table


def _inside(word: dict[str, Any], box: tuple[float, float, float, float]) -> bool:
    x = (word["x0"] + word["x1"]) / 2
    y = (word["top"] + word["bottom"]) / 2
    return box[0] <= x <= box[2] and box[1] <= y <= box[3]


def _cell(value: str | None) -> str:
    return " ".join((value or "").split())


def _lines(words: list[dict[str, Any]], page: int) -> list[_Line]:
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
        out.append(
            _Line(
                page=page,
                top=min(w["top"] for w in group),
                bottom=max(w["bottom"] for w in group),
                x0=group[0]["x0"],
                size=sizes.most_common(1)[0][0],
                bold=all("Bold" in w["fontname"] for w in group),
                text=" ".join(w["text"] for w in group),
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


def _blocks(
    pages: list[list[_Line]],
    tables: list[list[tuple[float, list[list[str]]]]],
    body_size: float,
) -> list[_Block]:
    blocks: list[_Block] = []
    previous: _Line | None = None
    for lines, page_tables in zip(pages, tables, strict=True):
        pending = sorted(page_tables, key=lambda item: item[0])
        for line in lines:
            while pending and pending[0][0] < line.top:
                blocks.append(_Block("table", [], rows=pending.pop(0)[1]))
                previous = None
            previous = _place(blocks, line, previous, body_size)
        for _, rows in pending:
            blocks.append(_Block("table", [], rows=rows))
            previous = None
    return blocks


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
            last.lines.append(line.text)
        else:
            blocks.append(_Block("heading", [line.text], size=line.size))
        return line
    if _continues(blocks, line, previous):
        blocks[-1].lines.append(line.text)
    else:
        blocks.append(_Block("paragraph", [line.text], size=line.size))
    return line


def _continues(blocks: list[_Block], line: _Line, previous: _Line | None) -> bool:
    if not blocks or blocks[-1].kind != "paragraph" or previous is None:
        return False
    if LIST_MARKER.match(line.text) and blocks[-1].lines[-1].rstrip().endswith((":", ";", ".")):
        return False
    if line.page != previous.page:
        return not previous.text.rstrip().endswith((".", ":", ";", "?", "!"))
    return line.top - previous.top <= PARAGRAPH_PITCH * line.size


# --- Registering passages in the frozen text --------------------------------------------


def _register(blocks: list[_Block], doc_id: str) -> tuple[str, list[Passage]]:
    parts: list[str] = []
    passages: list[Passage] = []
    offset = 0
    path: list[tuple[int, str]] = []
    lead_in_id: str | None = None

    def add(text: str) -> int:
        nonlocal offset
        if parts:
            parts.append("\n\n")
            offset += 2
        start = offset
        parts.append(text)
        offset += len(text)
        return start

    def register(kind: PassageKind, start: int, end: int, text: str, **links: str | None) -> str:
        passage_id = f"SRC-{len(passages) + 1:04d}"
        section = " > ".join(title for _, title in path)
        passages.append(
            Passage(
                id=passage_id,
                doc_id=doc_id,
                section_path=section,
                kind=kind,
                text=text,
                start=start,
                end=end,
                lead_in_id=links.get("lead_in_id"),
                header_id=links.get("header_id"),
            )
        )
        return passage_id

    for block in blocks:
        if block.kind == "heading":
            title = " ".join(block.lines)
            add(title)
            number = HEADING_NUMBER.match(title)
            depth = number.group(1).count(".") + 1 if number else 0
            path = [(d, t) for d, t in path if 0 < d < depth] if depth else []
            path.append((depth, title))
            lead_in_id = None
            continue
        if block.kind == "table":
            rows = [" | ".join(cell for cell in row) for row in block.rows if any(row)]
            if not rows:
                continue
            start = add("\n".join(rows))
            header_id = None
            for row in rows:
                if header_id is None:
                    header_id = register("table_header", start, start + len(row), row)
                else:
                    register("table_row", start, start + len(row), row, header_id=header_id)
                start += len(row) + 1
            lead_in_id = None
            continue
        text = "\n".join(block.lines)
        start = add(text)
        if lead_in_id is not None and LIST_MARKER.match(text):
            register("list_item", start, start + len(text), text, lead_in_id=lead_in_id)
            continue
        lead_in_id = None
        last_id = None
        for begin, end in split_sentences(text):
            last_id = register("sentence", start + begin, start + end, text[begin:end])
        if last_id is not None and text.rstrip().endswith(":"):
            lead_in_id = last_id
    return "".join(parts), passages
