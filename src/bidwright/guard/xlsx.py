"""XLSX: hidden and very hidden sheets are quarantined, one record per sheet, and removed;
cells formatted `;;;`, cell comments, data-validation messages and defined names are
quarantined and cleared; external relationships are removed first, at the archive level. The
sanitized workbook is saved with openpyxl."""

import io

import openpyxl
from openpyxl.worksheet.worksheet import Worksheet

from bidwright.guard.ooxml import (
    Finding,
    fix_modified,
    read_parts,
    strip_external_relationships,
    write_parts,
)

HIDDEN_FORMAT = ";;;"
STATE_KIND = {"hidden": "xlsx_hidden_sheet", "veryHidden": "xlsx_very_hidden_sheet"}


def _cells(sheet: Worksheet) -> list[tuple[str, str]]:
    return [
        (cell.coordinate, str(cell.value))
        for row in sheet.iter_rows()
        for cell in row
        if cell.value is not None and str(cell.value).strip()
    ]


def _scan_sheet(sheet: Worksheet) -> list[Finding]:
    findings = []
    title = sheet.title
    for row in sheet.iter_rows():
        for cell in row:
            where = f"sheet '{title}', cell {cell.coordinate}"
            if cell.number_format == HIDDEN_FORMAT and cell.value is not None:
                findings.append(Finding("xlsx_hidden_format", where, str(cell.value)))
                cell.value = None
                cell.number_format = "General"
            if cell.comment is not None:
                findings.append(Finding("xlsx_comment", where, cell.comment.text or ""))
                cell.comment = None
    for validation in sheet.data_validations.dataValidation:
        messages = [
            m
            for m in (
                validation.promptTitle,
                validation.prompt,
                validation.errorTitle,
                validation.error,
            )
            if m
        ]
        if messages:
            where = f"sheet '{title}', cells {validation.sqref}"
            findings.append(Finding("xlsx_validation_message", where, "\n".join(messages)))
        validation.promptTitle = validation.prompt = None
        validation.errorTitle = validation.error = None
    for name, defined in list(sheet.defined_names.items()):
        findings.append(
            Finding("xlsx_defined_name", f"sheet '{title}', name {name}", defined.attr_text or "")
        )
        del sheet.defined_names[name]
    return findings


def scan_xlsx(data: bytes, label: str) -> tuple[list[Finding], bytes]:
    """The hidden content of an XLSX, and the bytes of its sanitized copy."""
    parts = read_parts(data)
    findings, _ = strip_external_relationships(parts, label)
    workbook = openpyxl.load_workbook(io.BytesIO(write_parts(parts)))
    for sheet in list(workbook.worksheets):
        kind = STATE_KIND.get(sheet.sheet_state)
        if kind is None:
            continue
        cells = _cells(sheet)
        where = f"sheet '{sheet.title}' ({sheet.sheet_state}), {len(cells)} non-empty cells"
        findings.append(Finding(kind, where, "\n".join(f"{c}: {v}" for c, v in cells)))
        workbook.remove(sheet)
    for sheet in workbook.worksheets:
        findings += _scan_sheet(sheet)
    for name, defined in list(workbook.defined_names.items()):
        findings.append(Finding("xlsx_defined_name", f"name {name}", defined.attr_text or ""))
        del workbook.defined_names[name]
    if not workbook.worksheets:
        workbook.create_sheet("Sheet1")
    workbook.active = 0
    out = io.BytesIO()
    workbook.save(out)
    saved = read_parts(out.getvalue())
    if "docProps/core.xml" in saved:
        saved["docProps/core.xml"] = fix_modified(saved["docProps/core.xml"])
    return findings, write_parts(saved)
