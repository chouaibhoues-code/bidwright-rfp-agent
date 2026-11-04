"""Checks the renderer tests share: what a reader sees in a file, and what each layer hides.

The visible text of a PDF comes through pdfplumber with the hidden characters filtered out
(render mode 3 cannot be seen there, so invisible text stays in), read whole, by page half for
two-column pages, and by table cell. The hidden layers are read with the mechanism each one
uses: the content stream through pikepdf, character fill, size and position through
pdfplumber, run properties and parts through python-docx, and sheet state, number formats and
comments through openpyxl.
"""

import re
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import docx
import openpyxl
import pdfplumber
import pikepdf
from docx.shared import Pt

WHITE_TOLERANCE = 0.05
SMALL_PRINT_MAX_PT = 6
TINY_MAX_PT = 2
HIDDEN_FORMAT = ";;;"


def normalized(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def is_white(color: Any) -> bool:
    if color is None:
        return False
    values = list(color) if isinstance(color, list | tuple) else [color]
    try:
        numbers = [float(value) for value in values]
    except (TypeError, ValueError):
        return False
    if not numbers:
        return False
    if len(numbers) == 4:  # CMYK: white is all zeros
        return all(value <= WHITE_TOLERANCE for value in numbers)
    return all(value >= 1 - WHITE_TOLERANCE for value in numbers)


def _char_is_visible(char: dict[str, Any], page_width: float) -> bool:
    return (
        char["size"] >= TINY_MAX_PT
        and not is_white(char.get("non_stroking_color"))
        and 0 <= char["x0"] < page_width
    )


def _pdf_text_where(path: Path, keep: Callable[[dict[str, Any], float], bool]) -> str:
    """The page text of the characters `keep` selects, read whole and by page half."""
    parts: list[str] = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            width = page.width

            def test(obj: dict[str, Any], width: float = width) -> bool:
                return obj.get("object_type") != "char" or keep(obj, width)

            filtered = page.filter(test)
            parts.append(filtered.extract_text() or "")
            half = width / 2
            for box in ((0, 0, half, page.height), (half, 0, width, page.height)):
                parts.append(filtered.crop(box).extract_text() or "")
            for table in filtered.extract_tables():
                parts += [cell or "" for row in table for cell in row]
    return normalized(" ".join(parts))


def pdf_visible_text(path: Path) -> str:
    return _pdf_text_where(path, _char_is_visible)


def pdf_small_print_text(path: Path) -> str:
    return _pdf_text_where(path, lambda char, _: TINY_MAX_PT <= char["size"] < SMALL_PRINT_MAX_PT)


def pdf_white_text(path: Path) -> str:
    return _pdf_text_where(path, lambda char, _: is_white(char.get("non_stroking_color")))


def pdf_tiny_text(path: Path) -> str:
    return _pdf_text_where(path, lambda char, _: char["size"] < TINY_MAX_PT)


def pdf_off_page_text(path: Path) -> str:
    return _pdf_text_where(path, lambda char, width: char["x0"] >= width)


def _operand_text(operands: Any) -> str:
    if not operands:
        return ""
    operand = operands[0]
    if isinstance(operand, pikepdf.Array):
        items = [operand[index] for index in range(len(operand))]
        return "".join(str(item) for item in items if isinstance(item, pikepdf.String))
    return str(operand) if isinstance(operand, pikepdf.String) else ""


def pdf_invisible_text(path: Path) -> str:
    """Text shown while the render mode is 3, read from the content streams with pikepdf."""
    found: list[str] = []
    with pikepdf.open(path) as pdf:
        for page in pdf.pages:
            mode, stack = 0, []
            for operands, operator in pikepdf.parse_content_stream(page, "Tr Tj TJ q Q"):
                name = str(operator)
                if name == "q":
                    stack.append(mode)
                elif name == "Q":
                    mode = stack.pop() if stack else 0
                elif name == "Tr":
                    mode = int(operands[0])
                elif mode == 3:
                    found.append(_operand_text(operands))
    return normalized(" ".join(found))


def docx_visible_text(path: Path) -> str:
    """The runs a reader sees: not hidden, not deleted, and not in a comment."""
    document = docx.Document(str(path))
    paragraphs = list(document.paragraphs)
    for table in document.tables:
        for row in table.rows:
            for cell in row.cells:
                paragraphs += cell.paragraphs
    parts = [
        "".join(run.text for run in paragraph.runs if not run.font.hidden)
        for paragraph in paragraphs
    ]
    return normalized(" ".join(parts))


def docx_small_print_text(path: Path) -> str:
    document = docx.Document(str(path))
    runs = [run for paragraph in document.paragraphs for run in paragraph.runs]
    for table in document.tables:
        for row in table.rows:
            for cell in row.cells:
                runs += [run for paragraph in cell.paragraphs for run in paragraph.runs]
    return normalized(" ".join(run.text for run in runs if run.font.size == Pt(5)))


def _body(path: Path) -> Any:
    return cast(Any, docx.Document(str(path)).element).body


def docx_hidden_run_text(path: Path) -> str:
    body = _body(path)
    return normalized(" ".join(t.text or "" for t in body.xpath(".//w:r[w:rPr/w:vanish]/w:t")))


def docx_deleted_text(path: Path) -> str:
    body = _body(path)
    return normalized(" ".join(t.text or "" for t in body.xpath(".//w:del//w:delText")))


def docx_comment_text(path: Path) -> str:
    document = docx.Document(str(path))
    return normalized(" ".join(comment.text for comment in document.comments))


def _xlsx_cells(path: Path, states: set[str]) -> list[Any]:
    workbook = openpyxl.load_workbook(path)
    return [
        cell
        for sheet in workbook.worksheets
        if sheet.sheet_state in states
        for row in sheet.iter_rows()
        for cell in row
    ]


def xlsx_visible_text(path: Path) -> str:
    cells = _xlsx_cells(path, {"visible"})
    values = [
        str(cell.value)
        for cell in cells
        if cell.value is not None and cell.number_format != HIDDEN_FORMAT
    ]
    return normalized(" ".join(values))


def xlsx_sheet_text(path: Path, state: str) -> str:
    cells = _xlsx_cells(path, {state})
    return normalized(" ".join(str(cell.value) for cell in cells if cell.value is not None))


def xlsx_small_print_text(path: Path) -> str:
    cells = _xlsx_cells(path, {"visible"})
    values = [
        str(c.value)
        for c in cells
        if c.value is not None and c.font is not None and (c.font.sz or 11) < SMALL_PRINT_MAX_PT
    ]
    return normalized(" ".join(values))


def xlsx_hidden_format_text(path: Path) -> str:
    cells = _xlsx_cells(path, {"visible", "hidden", "veryHidden"})
    values = [
        str(c.value) for c in cells if c.value is not None and c.number_format == HIDDEN_FORMAT
    ]
    return normalized(" ".join(values))


def xlsx_comment_text(path: Path) -> str:
    cells = _xlsx_cells(path, {"visible", "hidden", "veryHidden"})
    return normalized(" ".join(cell.comment.text for cell in cells if cell.comment is not None))


def visible_text(path: Path, fmt: str) -> str:
    return {"pdf": pdf_visible_text, "docx": docx_visible_text, "xlsx": xlsx_visible_text}[fmt](
        path
    )


def text_in_layer(path: Path, fmt: str, layer: str) -> str:
    """The text a file holds in one layer, visible or hidden, by that layer's own mechanism."""
    if layer == "visible":
        return visible_text(path, fmt)
    if layer == "small_print":
        small = {
            "pdf": pdf_small_print_text,
            "docx": docx_small_print_text,
            "xlsx": xlsx_small_print_text,
        }
        return small[fmt](path)
    readers: dict[str, Callable[[Path], str]] = {
        "pdf_invisible": pdf_invisible_text,
        "pdf_background_color": pdf_white_text,
        "pdf_tiny_font": pdf_tiny_text,
        "pdf_off_page": pdf_off_page_text,
        "docx_hidden_run": docx_hidden_run_text,
        "docx_deleted_revision": docx_deleted_text,
        "docx_comment": docx_comment_text,
        "xlsx_hidden_sheet": lambda p: xlsx_sheet_text(p, "hidden"),
        "xlsx_very_hidden_sheet": lambda p: xlsx_sheet_text(p, "veryHidden"),
        "xlsx_hidden_format": xlsx_hidden_format_text,
        "xlsx_comment": xlsx_comment_text,
    }
    return readers[layer](path)
