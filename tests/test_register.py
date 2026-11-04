"""The control register: roles and precedence from file names and from `package.yaml`, and the
titles and page counts that ingest fills after parsing."""

from pathlib import Path

import pytest

from bidwright.config import load_config
from bidwright.register import RegisterInput, build_register, role_from_name
from tests.package_fakes import HERO, parse_package


@pytest.mark.parametrize(
    ("name", "role"),
    [
        ("main_tender.pdf", "main"),
        ("Addendum 2.pdf", "addendum"),
        ("amendment-1.docx", "addendum"),
        ("Annex_B_requirements.xlsx", "annex"),
        ("appendices.pdf", "annex"),
        ("Schedule 3 prices.xlsx", "annex"),
        ("form_of_tender.docx", "form"),
        ("declaration.pdf", "form"),
        ("performance_report.pdf", "main"),
    ],
)
def test_roles_come_from_file_names(name: str, role: str) -> None:
    assert role_from_name(name) == role


def _item(folder: Path, name: str) -> RegisterInput:
    path = folder / name
    path.write_bytes(name.encode())
    fmt = {"pdf": "pdf", "docx": "docx", "xlsx": "xlsx"}[name.rsplit(".", 1)[1]]
    return RegisterInput(path, path.stem.lower(), "0" * 64, fmt, sanitized=fmt != "pdf")  # type: ignore[arg-type]


def test_precedence_by_rules(tmp_path: Path) -> None:
    folder = tmp_path / "tender"
    folder.mkdir()
    names = [
        "b_tender.pdf",
        "a_tender.pdf",
        "addendum_1.pdf",
        "addendum_2.pdf",
        "annex_a.xlsx",
        "form.docx",
    ]
    items = [_item(folder, name) for name in names]
    register = build_register(folder, items, load_config().ingest.parsers)
    assert register.precedence_source == "rules"
    entries = {e.file: e for e in register.documents}
    assert entries["a_tender.pdf"].role == "main" and entries["b_tender.pdf"].role == "annex"
    by_precedence = [e.file for e in sorted(register.documents, key=lambda e: e.precedence)]
    assert by_precedence == [
        "addendum_2.pdf",
        "addendum_1.pdf",
        "a_tender.pdf",
        "annex_a.xlsx",
        "b_tender.pdf",
        "form.docx",
    ]
    assert entries["annex_a.xlsx"].parser == "docling" and entries["annex_a.xlsx"].sanitized


def test_precedence_from_package_yaml(tmp_path: Path) -> None:
    _, result = parse_package(HERO, tmp_path)
    assert result.register is not None
    register = result.register
    assert register.package == "hero" and register.precedence_source == "package.yaml"
    entries = [(e.file, e.role, e.precedence) for e in register.documents]
    assert entries == [
        ("hero_rfp.pdf", "main", 2),
        ("hero_addendum_1.pdf", "addendum", 1),
        ("hero_annex_b_requirements.xlsx", "annex", 3),
    ]
    titles = [e.title for e in register.documents]
    assert titles[0].startswith("Request for Proposal") and titles[1].startswith("Addendum 1")
    assert [e.pages for e in register.documents] == [22, 1, None]
    written = (tmp_path / "control_register.json").read_text(encoding="utf-8")
    assert '"precedence_source": "package.yaml"' in written
