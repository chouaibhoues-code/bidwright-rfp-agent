"""Render a corpus document to XLSX with openpyxl.

Each sheet carries its state (`visible`, `hidden` or `veryHidden`), an optional bold header
row, its rows, and at most one trap, written after the rows. Text takes its layer's
mechanism: a plain cell in a visible or hidden sheet, a 5 pt font for small print, the number
format `;;;` for hidden-format text, and a cell comment for comment text. The workbook
properties and every zip entry carry fixed dates, so two renders give identical bytes.
"""

from pathlib import Path
from typing import cast

import openpyxl
from openpyxl.cell.cell import Cell as XlsxCell
from openpyxl.comments import Comment
from openpyxl.styles import Font
from openpyxl.worksheet.worksheet import Worksheet

from evals.render.office import AUTHOR, FIXED_TIME_NAIVE, fix_modified, freeze_zip
from evals.render.spec import Cell, Clause, Document, Sheet

HIDDEN_FORMAT = ";;;"
SMALL_PRINT_PT = 5


def _write(target: XlsxCell, text: str, layer: str) -> None:
    """Write text into a cell by its layer's mechanism."""
    if layer == "xlsx_comment":
        target.comment = Comment(text, AUTHOR)
        return
    target.value = text
    if layer == "small_print":
        target.font = Font(size=SMALL_PRINT_PT)
    elif layer == "xlsx_hidden_format":
        target.number_format = HIDDEN_FORMAT


def _cell(sheet: Worksheet, row: int, column: int) -> XlsxCell:
    return cast(XlsxCell, sheet.cell(row=row, column=column))


def _sheet(workbook: openpyxl.Workbook, spec: Sheet) -> None:
    sheet = workbook.create_sheet(title=spec.name)
    sheet.sheet_state = spec.state
    row = 0
    if spec.header is not None:
        row += 1
        for column, text in enumerate(spec.header, start=1):
            target = _cell(sheet, row, column)
            target.value = text
            target.font = Font(bold=True)
    for cells in spec.rows:
        row += 1
        for column, cell in enumerate(cells, start=1):
            target = _cell(sheet, row, column)
            if isinstance(cell, str):
                target.value = cell
            elif isinstance(cell, Clause):
                _write(target, cell.text, cell.layer)
            else:
                _plain(target, cell)
    if spec.trap is not None:
        _write(_cell(sheet, row + 1, 1), spec.trap.text, spec.trap.layer)


def _plain(target: XlsxCell, cell: Cell) -> None:
    target.value = cell.text
    if cell.format:
        target.number_format = cell.format
    if cell.comment:
        target.comment = Comment(cell.comment, AUTHOR)


def render_xlsx(document: Document, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    workbook = openpyxl.Workbook()
    workbook.remove(workbook.worksheets[0])
    for sheet in document.sheets:
        _sheet(workbook, sheet)
    properties = workbook.properties
    properties.creator = AUTHOR
    properties.title = document.title
    properties.created = FIXED_TIME_NAIVE
    properties.modified = FIXED_TIME_NAIVE
    workbook.save(str(path))  # stamps the current time as `modified`, fixed below
    freeze_zip(path, {"docProps/core.xml": fix_modified})
