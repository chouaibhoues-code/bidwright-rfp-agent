"""The Docling parser on the recorded cassettes of the corpus (S-02 becomes this test): every
passage is a slice of the frozen text, tables and lists keep their links, headings build
section paths, and no hidden trap reaches the text."""

import json
from pathlib import Path

import pytest

from bidwright.ingest import IngestResult
from tests.package_fakes import (
    DEV_DOCX,
    DEV_PDF,
    HERO,
    HIDDEN_MARKERS,
    VISIBLE_MARKERS,
    parse_package,
)

pytestmark = pytest.mark.replay
SOURCES = {"dev": DEV_PDF, "dev-docx": DEV_DOCX, "hero": HERO}


@pytest.fixture(scope="module", params=sorted(SOURCES))
def ingested(
    request: pytest.FixtureRequest, tmp_path_factory: pytest.TempPathFactory
) -> tuple[str, Path, IngestResult]:
    run_dir = tmp_path_factory.mktemp(f"ingest-{request.param}")
    _, result = parse_package(SOURCES[request.param], run_dir)
    return request.param, run_dir, result


def test_every_passage_is_a_slice_of_the_frozen_text(
    ingested: tuple[str, Path, IngestResult],
) -> None:
    _, run_dir, result = ingested
    frozen = (run_dir / "frozen.txt").read_text(encoding="utf-8")
    assert frozen == result.frozen_text
    ids = [p.id for p in result.passages]
    assert ids == [f"SRC-{n:04d}" for n in range(1, len(ids) + 1)]
    for passage in result.passages:
        assert frozen[passage.start : passage.end] == passage.text, passage.id


def test_every_table_row_points_to_its_header(ingested: tuple[str, Path, IngestResult]) -> None:
    _, _, result = ingested
    by_id = {p.id: p for p in result.passages}
    rows = [p for p in result.passages if p.kind == "table_row"]
    assert rows
    for row in rows:
        assert row.header_id is not None and by_id[row.header_id].kind == "table_header", row.id


def test_list_items_keep_their_lead_ins(ingested: tuple[str, Path, IngestResult]) -> None:
    _, _, result = ingested
    by_id = {p.id: p for p in result.passages}
    linked = [p for p in result.passages if p.kind == "list_item" and p.lead_in_id]
    assert len(linked) >= 2
    for item in linked:
        assert by_id[item.lead_in_id or ""].text.rstrip().endswith(":"), item.id


def test_no_hidden_trap_reaches_the_frozen_text(ingested: tuple[str, Path, IngestResult]) -> None:
    corpus, _, result = ingested
    for marker in HIDDEN_MARKERS:
        assert marker not in result.frozen_text, (corpus, marker)
    expected = {"dev": "ZX-77-ASPEN", "hero": "ZX-41-QUILL"}.get(corpus)
    if expected is not None:
        assert expected in VISIBLE_MARKERS and expected in result.frozen_text
        assert any(p.suspect for p in result.passages) == (corpus == "hero")


def test_the_raw_document_is_kept_per_document(ingested: tuple[str, Path, IngestResult]) -> None:
    _, run_dir, result = ingested
    assert result.register is not None
    for entry in result.register.documents:
        raw = json.loads((run_dir / "parse" / f"{entry.doc_id}.json").read_text(encoding="utf-8"))
        assert raw["schema_name"] == "DoclingDocument" and raw["version"]


def test_headings_build_section_paths(tmp_path: Path) -> None:
    _, dev = parse_package(DEV_PDF, tmp_path / "dev")
    paths = {p.section_path for p in dev.passages}
    assert "4 Requirements > 4.1 Signing" in paths and "8 Contract" in paths
    _, hero = parse_package(HERO, tmp_path / "hero")
    paths = {p.section_path for p in hero.passages}
    assert "6 Functional requirements > 6.1 Case handling" in paths
    assert "Annex A Optional services" in paths, "an unnumbered annex starts its own section"
    assert "Requirements" in paths, "a worksheet is a section"
    assert not any(path.startswith("15 Contract terms > Annex") for path in paths)


def test_a_stacked_header_gives_one_header_passage(tmp_path: Path) -> None:
    _, hero = parse_package(HERO, tmp_path)
    headers = [
        p for p in hero.passages if p.kind == "table_header" and p.section_path == "13 Evaluation"
    ]
    assert [h.text for h in headers] == ["Criterion | Weight / Percent of the total"]


def test_package_documents_follow_the_register_with_small_print_and_pages(tmp_path: Path) -> None:
    _, hero = parse_package(HERO, tmp_path)
    assert hero.register is not None
    order = [p.doc_id for p in hero.passages]
    documents = [e.doc_id for e in hero.register.documents]
    assert sorted(set(order), key=order.index) == documents
    assert hero.doc_id == documents[0]
    small = [p for p in hero.passages if p.small_print]
    assert [p.text[:40] for p in small] == ["The Contractor shall keep professional i"]
    pdf_pages = {p.page for p in hero.passages if p.doc_id == documents[0]}
    assert None not in pdf_pages and max(pdf_pages) <= 22  # type: ignore[type-var]
    sheet_pages = {p.page for p in hero.passages if p.doc_id == documents[2]}
    assert sheet_pages == {None}
