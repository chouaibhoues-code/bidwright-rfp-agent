"""The compliance matrix (ADR-021): its sheets, columns and row order, formula-safe cells in
the XLSX and the CSV, and the other-records sheet."""

import csv
import zipfile
from pathlib import Path

import pytest
from openpyxl import load_workbook

from bidwright.render import render
from bidwright.render_xlsx import COLUMNS
from tests.render_fakes import FORMULA_QUOTE, records

HEADER = [name for name, _ in COLUMNS]


def _text(value: object) -> str:
    return "" if value is None else str(value)


@pytest.fixture(scope="module")
def run_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    folder = tmp_path_factory.mktemp("matrix")
    render(folder, records())
    return folder


def test_the_workbook_has_three_sheets_and_the_fixed_columns(run_dir: Path) -> None:
    book = load_workbook(run_dir / "compliance_matrix.xlsx")
    assert book.sheetnames == ["Compliance matrix", "Other records", "About"]
    sheet = book["Compliance matrix"]
    rows = [[_text(cell.value) for cell in row] for row in sheet.iter_rows()]
    assert rows[0] == HEADER
    assert HEADER[:3] == ["Requirement id", "Hazard", "Mandatory"]
    assert HEADER[-4:] == ["Compliance status", "Evidence", "Verification method", "Reviewer note"]
    assert sheet.freeze_panes == "A2" and sheet.auto_filter.ref
    ids = [row[0] for row in rows[1:]]
    assert ids == ["REQ-0004", "REQ-0001", "REQ-0002", "REQ-0003"], "hazards, binding, optional"
    by_id = {row[0]: dict(zip(HEADER, row, strict=True)) for row in rows[1:]}
    first = by_id["REQ-0001"]
    assert first["Document"] == "dev_rfp.pdf" and first["Section"].startswith("4 Requirements")
    assert first["Zone"] == "OBLIGATION" and first["Group"] == "RG-001"
    assert first["Lint findings"] == "LF-0001" and first["Clarification questions"] == "CQ-001"
    assert by_id["REQ-0002"]["Contract flags"] == "CF-001"
    assert {row["Compliance status"] for row in by_id.values()} == {"UNVERIFIED"}
    for blank in ("Response section", "Owner role", "Delivery mode", "Evidence"):
        assert {row[blank] for row in by_id.values()} == {""}, blank
    other = [[_text(c.value) for c in row] for row in book["Other records"].iter_rows()]
    assert [row[0] for row in other[1:]] == ["REQ-0005"]
    about = [[_text(c.value) for c in row] for row in book["About"].iter_rows()]
    assert about[0] == ["Run", "run-1"] and "UNREVIEWED_DRAFT" in about[1][1]
    assert ["Compliance status", "Always UNVERIFIED until a person reviews it"] in about


def test_a_formula_lead_stays_text(run_dir: Path) -> None:
    with zipfile.ZipFile(run_dir / "compliance_matrix.xlsx") as archive:
        sheet = archive.read("xl/worksheets/sheet1.xml").decode("utf-8")
    assert "<f>" not in sheet and "<f " not in sheet, "no formula element"
    assert FORMULA_QUOTE in sheet
    raw = (run_dir / "compliance_matrix.csv").read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf"), "UTF-8 with a byte-order mark"
    with (run_dir / "compliance_matrix.csv").open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.reader(handle))
    assert rows[0] == HEADER
    quoted = next(row for row in rows if row[0] == "REQ-0002")
    assert quoted[HEADER.index("Quote")] == f"'{FORMULA_QUOTE}"
    assert [row[0] for row in rows[1:]] == ["REQ-0004", "REQ-0001", "REQ-0002", "REQ-0003"]
