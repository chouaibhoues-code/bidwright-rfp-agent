"""The Docling parser: a DoclingDocument walked into blocks (Iteration 1, step 7; C7-08).

The `body` tree is read in order, depth first. Page headers and footers, pictures and the
cells a table repeats as children are left out. `title` and `section_header` items become
headings: a numbered heading keeps its depth from its number, and an unnumbered one takes
Docling's level, shifted so that the first numbered heading's level equals its number's depth
(Docling counts a document title as a level). Text, captions and footnotes become paragraphs,
list items keep their group, a worksheet becomes a heading with its sheet's table, and a table
gives its rows, a spanning cell repeated in each column it spans, with the leading rows whose
cells are all column headers as its header rows.

On a PDF page the guard found hidden lines on, a hidden line's text is removed from any item
whose box overlaps the line and that holds the text verbatim, and an item lying wholly inside
hidden boxes is dropped. An item is small print when at least half of its box lies inside the
guard's small-print boxes. Docling gives PDF boxes in a bottom-left origin, as pdfminer does,
and they are turned to pdfplumber's top-left origin with the page height.
"""

import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from bidwright.guard import FileGuard
from bidwright.ingest import HEADING_NUMBER
from bidwright.parsers import Box, ParsedBlock, ParsedDocument, overlap_share
from bidwright.parsers.docling_client import DoclingClient

SKIP_LABELS = frozenset({"page_header", "page_footer", "picture", "chart", "document_index"})
SKIP_GROUPS = frozenset({"page header", "page footer"})
HEADING_LABELS = frozenset({"title", "section_header"})
HIDDEN_SLACK = 2.0  # points around a hidden line that still count as inside it
WHOLLY_INSIDE = 0.95
SMALL_PRINT_SHARE = 0.5


def _without(text: str, hidden: str) -> str:
    """The text with the first whole-word occurrence of a hidden run removed, whatever the
    spacing between its words."""
    words = hidden.split()
    if not words:
        return text
    found = re.search(r"(?<!\w)" + r"\s+".join(map(re.escape, words)) + r"(?!\w)", text)
    if found is None:
        return text
    return " ".join(f"{text[: found.start()]} {text[found.end() :]}".split())


class DoclingParser:
    def __init__(self, client: DoclingClient) -> None:
        self.client = client

    def parse(self, path: Path, doc_id: str, guard: FileGuard | None = None) -> ParsedDocument:
        response = self.client.convert(path)
        document: dict[str, Any] = response["document"]["json_content"]
        walker = _Walker(document, guard)
        blocks = list(walker.walk(document["body"]))
        is_pdf = (document.get("origin") or {}).get("mimetype") == "application/pdf"
        status = "partial_success" if response.get("status") == "partial_success" else "success"
        return ParsedDocument(
            doc_id=doc_id,
            blocks=blocks,
            pages=len(document.get("pages") or {}) if is_pdf else None,
            status=status,
            errors=[str(e) for e in response.get("errors") or []],
            raw=document,
        )


class _Walker:
    def __init__(self, document: dict[str, Any], guard: FileGuard | None) -> None:
        self.document = document
        self.pdf = (document.get("origin") or {}).get("mimetype") == "application/pdf"
        self.heights = {
            int(number): float(page["size"]["height"])
            for number, page in (document.get("pages") or {}).items()
            if page.get("size")
        }
        self.hidden = guard.hidden_lines if guard is not None and self.pdf else []
        self.small = guard.small_print if guard is not None and self.pdf else []
        self.offset = self._level_offset()

    def resolve(self, ref: str) -> dict[str, Any]:
        _, kind, index = ref.split("/")
        return self.document[kind][int(index)]

    def _level_offset(self) -> int:
        """Docling's level minus the number's depth, for the first numbered heading."""
        for item in self.document.get("texts", []):
            if item.get("label") == "section_header":
                number = HEADING_NUMBER.match(item.get("text", ""))
                if number:
                    return int(item.get("level") or 1) - (number.group(1).count(".") + 1)
        return 0

    def walk(self, node: dict[str, Any]) -> Iterator[ParsedBlock]:
        for child in node.get("children", []):
            ref = child["$ref"]
            item = self.resolve(ref)
            label = item.get("label", "")
            if ref.startswith("#/groups/"):
                if item.get("name") in SKIP_GROUPS:
                    continue
                if label == "sheet":
                    yield ParsedBlock("heading", 1, item.get("name", ""))
                yield from self.walk(item)
                continue
            if label in SKIP_LABELS:
                continue
            if label == "table":
                table = self._table(item)
                if table is not None:
                    yield table
                continue
            block = self._text(item, label)
            if block is not None:
                yield block
            yield from self.walk(item)

    def _place(self, item: dict[str, Any]) -> tuple[int | None, Box | None, list[tuple[int, Box]]]:
        provs = item.get("prov") or []
        boxes: list[tuple[int, Box]] = []
        for prov in provs:
            page = int(prov.get("page_no") or 0)
            bbox = prov.get("bbox")
            if not bbox or page not in self.heights:
                continue
            if bbox.get("coord_origin", "BOTTOMLEFT") == "BOTTOMLEFT":
                height = self.heights[page]
                box = (bbox["l"], height - bbox["t"], bbox["r"], height - bbox["b"])
            else:
                box = (bbox["l"], bbox["t"], bbox["r"], bbox["b"])
            boxes.append(
                (
                    page,
                    (
                        min(box[0], box[2]),
                        min(box[1], box[3]),
                        max(box[0], box[2]),
                        max(box[1], box[3]),
                    ),
                )
            )
        if not self.pdf or not boxes:
            return None, None, boxes
        return boxes[0][0], boxes[0][1], boxes

    def _text(self, item: dict[str, Any], label: str) -> ParsedBlock | None:
        text = item.get("text") or ""
        page, box, boxes = self._place(item)
        for number, item_box in boxes:
            lines = [line for line in self.hidden if line.page == number]
            hidden = [(line.x0, line.top, line.x1, line.bottom) for line in lines]
            grown = [_grow(b, HIDDEN_SLACK) for b in hidden]
            if grown and overlap_share(item_box, grown) >= WHOLLY_INSIDE:
                return None
            for line, line_box in zip(lines, grown, strict=True):
                if overlap_share(item_box, [line_box]) > 0:
                    text = _without(text, line.text)
        if not text.strip():
            return None
        small = (
            box is not None
            and page is not None
            and overlap_share(
                box, [(b.x0, b.top, b.x1, b.bottom) for b in self.small if b.page == page]
            )
            >= SMALL_PRINT_SHARE
        )
        if label in HEADING_LABELS:
            return ParsedBlock("heading", self._level(item, label, text), text, page, box)
        kind = "list_item" if label == "list_item" else "paragraph"
        return ParsedBlock(kind, 0, text, page, box, small_print=small)

    def _level(self, item: dict[str, Any], label: str, text: str) -> int:
        if label == "title" or HEADING_NUMBER.match(text):
            return 0
        return max(int(item.get("level") or 1) - self.offset, 0)

    def _table(self, item: dict[str, Any]) -> ParsedBlock | None:
        data = item.get("data") or {}
        rows_count, columns = int(data.get("num_rows") or 0), int(data.get("num_cols") or 0)
        if not rows_count or not columns:
            return None
        grid = [["" for _ in range(columns)] for _ in range(rows_count)]
        header = [[True for _ in range(columns)] for _ in range(rows_count)]
        present = [[False for _ in range(columns)] for _ in range(rows_count)]
        for cell in data.get("table_cells", []):
            text = " ".join((cell.get("text") or "").split())
            for row in range(
                cell["start_row_offset_idx"], min(cell["end_row_offset_idx"], rows_count)
            ):
                for column in range(
                    cell["start_col_offset_idx"], min(cell["end_col_offset_idx"], columns)
                ):
                    grid[row][column] = text
                    present[row][column] = True
                    header[row][column] = bool(cell.get("column_header"))
        heads = 0
        while (
            heads < rows_count
            and all(header[heads][c] for c in range(columns) if present[heads][c])
            and any(present[heads])
        ):
            heads += 1
        page, box, _ = self._place(item)
        return ParsedBlock(
            "table",
            page=page,
            box=box,
            header_rows=tuple(tuple(row) for row in grid[:heads]),
            rows=tuple(tuple(row) for row in grid[heads:]),
        )


def _grow(box: Box, slack: float) -> Box:
    return (box[0] - slack, box[1] - slack, box[2] + slack, box[3] + slack)
