"""The compliance matrix (ADR-021, Iteration 1, step 15): `compliance_matrix.xlsx` with three
sheets, and `compliance_matrix.csv`, the first sheet's twin.

Sheet "Compliance matrix" has one row per `BINDING` or `OPTIONAL` requirement with a verified
quote: hazards first, then the other binding requirements, then the optional ones, each in
reading order. Its columns are fixed; those that later iterations fill stay blank, and the
compliance status is always `UNVERIFIED`, which only a person changes. Sheet "Other records"
lists the `BACKGROUND`, `NOT_BINDING` and `OUT_OF_SCOPE` records, so a reviewer can promote
one; sheet "About" gives the run, its status line, the time of writing, each column's meaning
and the note on formula-safe cells.

A value that starts with `=`, `+`, `-`, `@`, a tab or a carriage return could run as a formula
in a spreadsheet, so the XLSX stores it as a string cell, never a formula, and the CSV writes
it with a leading single quote. The CSV is UTF-8 with a byte-order mark, for spreadsheet tools.
"""

import csv
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

if TYPE_CHECKING:
    from bidwright.render import RunRecords

FORMULA_LEAD = ("=", "+", "-", "@", "\t", "\r")
VERIFIED = ("VERBATIM_VERIFIED", "NORMALIZED_MATCH")
OTHER = ("BACKGROUND", "NOT_BINDING", "OUT_OF_SCOPE")
COLUMNS: tuple[tuple[str, str], ...] = (
    ("Requirement id", "The requirement's id in requirements.jsonl"),
    ("Hazard", "yes when missing it could get the bid rejected"),
    ("Mandatory", "yes for a BINDING requirement"),
    ("Disposition", "BINDING or OPTIONAL"),
    ("Modality", "The verb that sets the obligation: shall, must, will, should, may or none"),
    ("Statement", "Who must do what, in one sentence"),
    ("Quote", "The RFP's own words, checked against the source"),
    ("Quote status", "VERBATIM_VERIFIED or NORMALIZED_MATCH"),
    ("Document", "The file that holds the quote"),
    ("Section", "The section path of the quoted passage"),
    ("Page", "The page of the quoted passage, blank for a spreadsheet"),
    ("Zone", "The section's zone from triage"),
    ("Passages", "The passage ids the requirement cites"),
    ("Group", "The requirement group from consolidate"),
    ("Lint findings", "Requirement-quality findings on the quote"),
    ("Clarification questions", "Questions that concern the requirement"),
    ("Contract flags", "Contract terms flagged on the same passages, for legal review"),
    ("Response section", "Filled from Iteration 4"),
    ("Owner role", "Filled from Iteration 3"),
    ("Delivery mode", "Filled from Iteration 3"),
    ("Compliance status", "Always UNVERIFIED until a person reviews it"),
    ("Evidence", "Filled from Iteration 3"),
    ("Verification method", "Filled from Iteration 3"),
    ("Reviewer note", "For the reviewer"),
)
OTHER_COLUMNS = (
    "Requirement id",
    "Disposition",
    "Statement",
    "Quote",
    "Document",
    "Section",
    "Page",
    "Passages",
)
WRAPPED = ("Statement", "Quote")
NOTE = (
    "A value that starts with =, +, -, @, a tab or a carriage return is stored as text, never as"
    " a formula; the CSV twin writes it with a leading single quote."
)

Cell = str | int


def _joined(ids: Sequence[str]) -> str:
    return "; ".join(ids)


def _yes(flag: bool) -> str:
    return "yes" if flag else "no"


def _locate(records: "RunRecords", src_id: str) -> tuple[str, str, Cell]:
    """The document file, section path and page of a passage, as far as the run knows them."""
    passage = records.passages.get(src_id)
    if passage is None:
        return "", "", ""
    files = {e.doc_id: e.file for e in records.register.documents} if records.register else {}
    page: Cell = passage.page if passage.page is not None else ""
    return files.get(passage.doc_id, passage.doc_id), passage.section_path, page


def matrix_rows(records: "RunRecords") -> list[list[Cell]]:
    """The first sheet's rows: hazards, then binding, then optional, each in reading order."""
    listed = [
        r
        for r in records.requirements
        if r.disposition in ("BINDING", "OPTIONAL") and r.quote_status in VERIFIED
    ]
    ordered = [r for r in listed if r.hazard]
    ordered += [r for r in listed if not r.hazard and r.disposition == "BINDING"]
    ordered += [r for r in listed if not r.hazard and r.disposition == "OPTIONAL"]
    groups = {m: g.id for g in records.groups for m in g.member_ids}
    rows = []
    for r in ordered:
        document, section, page = _locate(records, r.src_ids[0])
        lint = [f.id for f in records.lint_findings if f.requirement_id == r.id]
        questions = [q.id for q in records.clarifications if r.id in q.requirement_ids]
        flags = [f.id for f in records.contract_flags if f.src_id in r.src_ids]
        rows.append(
            [
                r.id,
                _yes(r.hazard),
                _yes(r.mandatory),
                r.disposition,
                r.modality,
                r.statement,
                r.quote,
                r.quote_status,
                document,
                section,
                page,
                r.zone or "",
                _joined(r.src_ids),
                groups.get(r.id, ""),
                _joined(lint),
                _joined(questions),
                _joined(flags),
                "",
                "",
                "",
                "UNVERIFIED",
                "",
                "",
                "",
            ]
        )
    return rows


def other_rows(records: "RunRecords") -> list[list[Cell]]:
    rows = []
    for r in records.requirements:
        if r.disposition not in OTHER:
            continue
        document, section, page = _locate(records, r.src_ids[0])
        rows.append(
            [r.id, r.disposition, r.statement, r.quote, document, section, page, _joined(r.src_ids)]
        )
    return rows


def _put(sheet: Worksheet, row: int, column: int, value: Cell) -> None:
    cell = sheet.cell(row=row, column=column, value=value)
    if isinstance(value, str) and value.startswith(FORMULA_LEAD):
        cell.data_type = "s"  # text, never a formula


def _sheet(
    sheet: Worksheet, header: Sequence[str], rows: Sequence[Sequence[Cell]], wrapped: Sequence[str]
) -> None:
    for column, name in enumerate(header, start=1):
        _put(sheet, 1, column, name)
        sheet.cell(row=1, column=column).font = Font(bold=True)
    for index, row in enumerate(rows, start=2):
        for column, value in enumerate(row, start=1):
            _put(sheet, index, column, value)
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = sheet.dimensions
    for column, name in enumerate(header, start=1):
        letter = get_column_letter(column)
        sheet.column_dimensions[letter].width = 60 if name in wrapped else 18
        if name in wrapped:
            for index in range(2, len(rows) + 2):
                sheet.cell(row=index, column=column).alignment = Alignment(wrap_text=True)


def write_matrix(run_dir: Path, records: "RunRecords", status_line: str) -> None:
    """`compliance_matrix.xlsx` and `compliance_matrix.csv`."""
    rows = matrix_rows(records)
    header = [name for name, _ in COLUMNS]
    book = Workbook()
    matrix = book.worksheets[0]
    matrix.title = "Compliance matrix"
    _sheet(matrix, header, rows, WRAPPED)
    _sheet(book.create_sheet("Other records"), OTHER_COLUMNS, other_rows(records), WRAPPED)
    about = book.create_sheet("About")
    written = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    lines: list[list[Cell]] = [
        ["Run", records.run_id],
        ["Status", status_line],
        ["Written", written],
        ["", ""],
        ["Column", "Meaning"],
        *[[name, meaning] for name, meaning in COLUMNS],
        ["", ""],
        ["Formula-safe cells", NOTE],
    ]
    for index, (name, meaning) in enumerate(lines, start=1):
        _put(about, index, 1, name)
        _put(about, index, 2, meaning)
    about.column_dimensions["A"].width = 24
    about.column_dimensions["B"].width = 100
    run_dir.mkdir(parents=True, exist_ok=True)
    book.save(run_dir / "compliance_matrix.xlsx")
    with (run_dir / "compliance_matrix.csv").open("w", encoding="utf-8-sig", newline="") as out:
        writer = csv.writer(out, lineterminator="\n")
        writer.writerow(header)
        for row in rows:
            writer.writerow([_csv_safe(value) for value in row])


def _csv_safe(value: Cell) -> Cell:
    return f"'{value}" if isinstance(value, str) and value.startswith(FORMULA_LEAD) else value


__all__ = ["COLUMNS", "FORMULA_LEAD", "matrix_rows", "other_rows", "write_matrix"]
