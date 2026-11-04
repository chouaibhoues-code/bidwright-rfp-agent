"""Ingest: parsed documents become frozen text and registered passages.

A parser (`bidwright.parsers`) turns each file into blocks: headings, paragraphs, list items
and tables. `register_blocks` then applies the passage rules of Iteration 0a to one document:
- A heading starts a section. A numbered heading, such as "4.2 Records", takes its depth from
  its number; an unnumbered one takes the level its parser gives it. `section_path` joins the
  open headings, as in "4 Requirements > 4.1 Signing".
- A paragraph splits into sentences on ".", "?" or "!" followed by a space and a capital
  letter, except after an abbreviation.
- After a passage that ends with ":", the list items that follow, and paragraphs that start
  with a list marker, are list items whose `lead_in_id` is that passage.
- A table gives one `table_header` passage, its header rows stacked column by column with
  " / " and the columns joined with " | ", then one `table_row` passage per body row whose
  `header_id` is the header. A cell's text stays whole.

`ingest_package` registers the documents of a package in the control register's order: each
document's text follows the previous one after two line breaks, and passage ids run across
the package. The frozen text keeps line breaks, and every passage is a half-open slice of it.
`display_text` gives the form a model sees, with line breaks as spaces and the same offsets.
"""

import hashlib
import json
import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from bidwright.schemas import ControlRegister, Passage, PassageKind

if TYPE_CHECKING:
    from bidwright.parsers import ParsedBlock, ParsedDocument

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
DOCUMENT_GAP = "\n\n"


@dataclass(frozen=True)
class IngestResult:
    doc_id: str  # the main document's id
    frozen_text: str
    passages: tuple[Passage, ...]
    removed_lines: tuple[str, ...]
    register: ControlRegister | None = None
    degraded: tuple[str, ...] = ()  # reasons the run continues DEGRADED, such as partial parses


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
    """One PDF through the pdfplumber parser with no guard: the `v0.0` path. Writes
    `frozen.txt` and `passages.jsonl` to `run_dir` when given."""
    from bidwright.parsers.pdfplumber_parser import PdfplumberParser

    doc_id = doc_id_for(path)
    parsed = PdfplumberParser().parse(path, doc_id)
    frozen, passages = register_blocks(parsed.blocks, doc_id, 0, 1)
    result = IngestResult(doc_id, frozen, tuple(passages), tuple(parsed.removed_lines))
    if run_dir is not None:
        write_ingest(result, run_dir)
    return result


def ingest_package(
    register: ControlRegister,
    documents: Sequence["ParsedDocument"],
    run_dir: Path | None,
    suspect: Sequence[re.Pattern[str]] = (),
) -> IngestResult:
    """Register every parsed document in register order, fill each entry's title and pages,
    and write `frozen.txt`, `passages.jsonl`, `control_register.json` and `parse/`."""
    parsed = {document.doc_id: document for document in documents}
    parts: list[str] = []
    passages: list[Passage] = []
    entries = []
    removed: list[str] = []
    degraded: list[str] = []
    offset = 0
    for entry in register.documents:
        document = parsed.get(entry.doc_id)
        if document is None:
            entries.append(entry)
            continue
        if parts:
            parts.append(DOCUMENT_GAP)
            offset += len(DOCUMENT_GAP)
        text, registered = register_blocks(document.blocks, entry.doc_id, offset, len(passages) + 1)
        parts.append(text)
        offset += len(text)
        passages += registered
        removed += document.removed_lines
        if document.status == "partial_success":
            degraded.append(f"docling: partial_success on {entry.file}")
        heading = next((b.text for b in document.blocks if b.kind == "heading" and b.text), None)
        entries.append(
            entry.model_copy(
                update={"title": heading or Path(entry.file).stem, "pages": document.pages}
            )
        )
    passages = [_flag_suspect(p, suspect) for p in passages]
    main = next((e for e in register.documents if e.role == "main"), register.documents[0])
    result = IngestResult(
        doc_id=main.doc_id,
        frozen_text="".join(parts),
        passages=tuple(passages),
        removed_lines=tuple(removed),
        register=register.model_copy(update={"documents": entries}),
        degraded=tuple(degraded),
    )
    if run_dir is not None:
        write_ingest(result, run_dir)
        for document in documents:
            if document.raw is not None:
                _write_raw(run_dir / "parse" / f"{document.doc_id}.json", document.raw)
    return result


def _flag_suspect(passage: Passage, patterns: Sequence[re.Pattern[str]]) -> Passage:
    text = display_text(passage.text)
    if any(pattern.search(text) for pattern in patterns):
        return passage.model_copy(update={"suspect": True})
    return passage


def _write_raw(path: Path, raw: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(raw, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")


def write_ingest(result: IngestResult, run_dir: Path) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "frozen.txt").write_text(result.frozen_text, encoding="utf-8", newline="\n")
    body = "".join(passage.model_dump_json() + "\n" for passage in result.passages)
    (run_dir / "passages.jsonl").write_text(body, encoding="utf-8", newline="\n")
    if result.register is not None:
        (run_dir / "control_register.json").write_text(
            result.register.model_dump_json(indent=1) + "\n", encoding="utf-8", newline="\n"
        )


# --- Registering passages in the frozen text --------------------------------------------


def table_header(header_rows: Sequence[Sequence[str]], columns: int) -> str:
    """Header rows stacked column by column, top to bottom with " / ", columns with " | "."""
    stacked = []
    for column in range(columns):
        cells = [row[column] for row in header_rows if column < len(row) and row[column]]
        unique = [cell for i, cell in enumerate(cells) if cell not in cells[:i]]
        stacked.append(" / ".join(unique))
    return " | ".join(stacked)


def register_blocks(
    blocks: Sequence["ParsedBlock"], doc_id: str, offset: int, start: int
) -> tuple[str, list[Passage]]:
    """One document's text and passages. `offset` is where the text starts in the package's
    frozen text, and `start` is the number of the document's first passage."""
    parts: list[str] = []
    passages: list[Passage] = []
    local = 0
    path: list[tuple[int, str]] = []
    lead_in_id: str | None = None

    def add(text: str) -> int:
        nonlocal local
        if parts:
            parts.append("\n\n")
            local += 2
        begin = local
        parts.append(text)
        local += len(text)
        return offset + begin

    def register(
        kind: PassageKind,
        begin: int,
        end: int,
        text: str,
        block: "ParsedBlock",
        **links: str | None,
    ) -> str:
        passage_id = f"SRC-{start + len(passages):04d}"
        passages.append(
            Passage(
                id=passage_id,
                doc_id=doc_id,
                section_path=" > ".join(title for _, title in path),
                kind=kind,
                text=text,
                start=begin,
                end=end,
                lead_in_id=links.get("lead_in_id"),
                header_id=links.get("header_id"),
                page=block.page,
                small_print=block.small_print,
            )
        )
        return passage_id

    for block in blocks:
        if block.kind == "heading":
            title = block.text
            if not title:
                continue
            add(title)
            number = HEADING_NUMBER.match(title)
            depth = number.group(1).count(".") + 1 if number else block.level
            path = [(d, t) for d, t in path if 0 < d < depth] if depth else []
            path.append((depth, title))
            lead_in_id = None
            continue
        if block.kind == "table":
            columns = max((len(row) for row in [*block.header_rows, *block.rows]), default=0)
            header = table_header(block.header_rows, columns) if block.header_rows else None
            rows = [" | ".join(row) for row in block.rows if any(row)]
            lines = ([header] if header else []) + rows
            if not lines:
                continue
            begin = add("\n".join(lines))
            header_id = None
            if header:
                header_id = register("table_header", begin, begin + len(header), header, block)
                begin += len(header) + 1
            for row in rows:
                if header_id is None:
                    header_id = register("table_header", begin, begin + len(row), row, block)
                else:
                    register("table_row", begin, begin + len(row), row, block, header_id=header_id)
                begin += len(row) + 1
            lead_in_id = None
            continue
        text = block.text
        if not text.strip():
            continue
        begin = add(text)
        if lead_in_id is not None and (block.kind == "list_item" or LIST_MARKER.match(text)):
            register("list_item", begin, begin + len(text), text, block, lead_in_id=lead_in_id)
            continue
        if block.kind == "list_item":
            register("list_item", begin, begin + len(text), text, block)
            continue
        lead_in_id = None
        last_id = None
        for first, last in split_sentences(text):
            last_id = register("sentence", begin + first, begin + last, text[first:last], block)
        if last_id is not None and text.rstrip().endswith(":"):
            lead_in_id = last_id
    return "".join(parts), passages
