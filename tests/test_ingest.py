"""Ingest on the development RFP, plus the splitting and heading rules on their own."""

import json
from pathlib import Path

import pytest

from bidwright.ingest import (
    IngestResult,
    display_text,
    doc_id_for,
    ingest_pdf,
    is_heading,
    split_sentences,
)
from bidwright.schemas import Passage

DEV_RFP = Path(__file__).resolve().parents[1] / "inputs" / "dev" / "dev_rfp.pdf"


@pytest.fixture(scope="module")
def result() -> IngestResult:
    return ingest_pdf(DEV_RFP)


def _by_text(result: IngestResult, start: str) -> Passage:
    matches = [p for p in result.passages if display_text(p.text).startswith(start)]
    assert len(matches) == 1, (start, [p.text for p in matches])
    return matches[0]


def test_offsets_slice_back_to_the_passage_text(result: IngestResult) -> None:
    for passage in result.passages:
        assert result.frozen_text[passage.start : passage.end] == passage.text
    ids = [p.id for p in result.passages]
    assert ids == [f"SRC-{n:04d}" for n in range(1, len(ids) + 1)]


def test_list_items_inherit_their_lead_in(result: IngestResult) -> None:
    lead_in = _by_text(result, "The Supplier shall:")
    items = [p for p in result.passages if p.kind == "list_item"]
    assert [display_text(p.text)[:3] for p in items] == ["(a)", "(b)"]
    assert all(p.lead_in_id == lead_in.id for p in items)
    after = _by_text(result, "The Supplier should provide templates")
    assert after.kind == "sentence" and after.lead_in_id is None


def test_every_table_row_points_to_its_header(result: IngestResult) -> None:
    headers = [p for p in result.passages if p.kind == "table_header"]
    rows = [p for p in result.passages if p.kind == "table_row"]
    assert [h.text for h in headers] == ["Criterion | Weight"]
    assert len(rows) == 4 and all(row.header_id == headers[0].id for row in rows)
    assert rows[0].text == "Technical approach | 40%"


def test_repeated_page_headers_and_footers_are_removed(result: IngestResult) -> None:
    assert "RFP KV-2026-014" not in result.frozen_text.replace("Reference KV-2026-014", "")
    assert "Page 1" not in result.frozen_text
    assert len(result.removed_lines) == 8  # a header and a footer on each of 4 pages


def test_headings_build_the_section_path(result: IngestResult) -> None:
    audit = _by_text(result, "The Supplier shall keep an audit record")
    assert audit.section_path == "4 Requirements > 4.1 Signing"
    assert (
        _by_text(result, "Bidders may propose").section_path == "4 Requirements > 4.3 Integration"
    )
    assert _by_text(result, "The contract runs").section_path == "8 Contract"
    title = "Request for Proposal: Electronic Signature Service"
    assert _by_text(result, "Reference KV-2026-014").section_path == title


def test_sentences_split_without_breaking_numbers_in_parentheses(result: IngestResult) -> None:
    retention = _by_text(result, "The Supplier shall store signed documents")
    assert (
        display_text(retention.text)
        == "The Supplier shall store signed documents for ten (10) years."
    )
    migration = _by_text(result, "The Supplier should migrate")
    assert migration.id != retention.id
    wrapped = _by_text(result, "The Supplier shall keep an audit record")
    assert "\n" in wrapped.text and display_text(wrapped.text).endswith("the document version.")


def test_ingest_writes_the_run_files_and_is_deterministic(tmp_path: Path) -> None:
    first = ingest_pdf(DEV_RFP, tmp_path)
    second = ingest_pdf(DEV_RFP)
    assert first == second
    frozen = (tmp_path / "frozen.txt").read_text(encoding="utf-8")
    assert frozen == first.frozen_text
    lines = (tmp_path / "passages.jsonl").read_text(encoding="utf-8").splitlines()
    assert [Passage.model_validate(json.loads(line)) for line in lines] == list(first.passages)


def test_doc_id_is_the_slugged_stem_and_a_hash_prefix() -> None:
    doc_id = doc_id_for(DEV_RFP)
    assert doc_id.startswith("dev-rfp-") and len(doc_id) == len("dev-rfp-") + 8


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            "Use a template, e.g. Form A. Then sign it.",
            ["Use a template, e.g. Form A.", "Then sign it."],
        ),
        (
            "Retain records for seven (7) years. Delete them after.",
            ["Retain records for seven (7) years.", "Delete them after."],
        ),
        (
            "See section 4.2 for details. It applies.",
            ["See section 4.2 for details.", "It applies."],
        ),
        ("Is it signed? Yes. Done!", ["Is it signed?", "Yes.", "Done!"]),
        (
            "Pay within 30 days. 5 days of grace apply.",
            ["Pay within 30 days. 5 days of grace apply."],
        ),
    ],
)
def test_split_sentences(text: str, expected: list[str]) -> None:
    assert [text[a:b] for a, b in split_sentences(text)] == expected


@pytest.mark.parametrize(
    ("text", "size", "bold", "expected"),
    [
        ("4.1 Signing", 12, True, True),
        ("1 Introduction", 13, True, True),
        ("Request for Proposal", 20, True, True),
        ("20 pages by 2026-12-01 12:00 UTC.", 10, False, False),
        ("4.2 Records", 10, True, True),
        ("A plain body line", 10, False, False),
    ],
)
def test_is_heading(text: str, size: float, bold: bool, expected: bool) -> None:
    assert is_heading(text, size, bold, body_size=10) is expected


def test_a_client_document_id_holds_no_part_of_its_file_name(tmp_path: Path) -> None:
    """D-05: a client document is named by its hash alone."""
    path = tmp_path / "Northwind confidential tender.pdf"
    path.write_bytes(DEV_RFP.read_bytes())
    client = doc_id_for(path, "client")
    assert client.startswith("doc-") and len(client) == len("doc-") + 8
    assert "northwind" not in client and "tender" not in client
    assert client.removeprefix("doc-") == doc_id_for(path).rsplit("-", 1)[1]


def _converted(status: str) -> dict[str, object]:
    body = {"texts": [], "tables": [], "groups": [], "pages": {}, "body": {"children": []}}
    return {
        "status": status,
        "errors": [] if status == "success" else ["page 2 could not be read"],
        "document": {"json_content": {**body, "schema_name": "DoclingDocument", "version": "1"}},
    }


def test_ingest_retry_retries_a_failing_docling_call_then_faults(tmp_path: Path) -> None:
    import httpx

    from bidwright.parsers.docling_client import DoclingClient, DoclingFailed

    seen: list[str] = []

    def answer(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        if len(seen) == 1:
            raise httpx.ConnectError("refused", request=request)
        return httpx.Response(503, text="busy")

    pauses: list[float] = []
    client = DoclingClient(
        "live",
        "http://docling.test",
        {"to_formats": ["json"], "do_ocr": False},
        retries=3,
        transport=httpx.MockTransport(answer),
        sleep=pauses.append,
    )
    with pytest.raises(DoclingFailed, match="after 3 retries"):
        client.convert(DEV_RFP)
    assert seen == ["/v1/convert/file"] * 4 and len(pauses) == 3


def test_ingest_unparseable_a_partial_conversion_continues_degraded(tmp_path: Path) -> None:
    import httpx

    from bidwright.ingest import ingest_package
    from bidwright.parsers.docling_client import DoclingClient
    from bidwright.parsers.docling_parser import DoclingParser
    from bidwright.schemas import ControlRegister, DocumentEntry

    client = DoclingClient(
        "live",
        "http://docling.test",
        {"to_formats": ["json"]},
        transport=httpx.MockTransport(
            lambda r: httpx.Response(200, json=_converted("partial_success"))
        ),
    )
    parsed = DoclingParser(client).parse(DEV_RFP, "dev-rfp-test")
    assert parsed.status == "partial_success" and parsed.errors
    entry = DocumentEntry(
        doc_id="dev-rfp-test",
        file="dev_rfp.pdf",
        sha256="0" * 64,
        format="pdf",
        role="main",
        title="dev_rfp",
        precedence=1,
        parser="docling",
    )
    register = ControlRegister(package="dev", documents=[entry], precedence_source="rules")
    result = ingest_package(register, [parsed], tmp_path)
    assert result.degraded == ("docling: partial_success on dev_rfp.pdf",)


def test_a_failure_status_is_a_fault_and_replay_never_connects(tmp_path: Path) -> None:
    import httpx

    from bidwright.parsers.docling_client import (
        DoclingCassetteMissing,
        DoclingClient,
        DoclingFailed,
    )

    failing = DoclingClient(
        "live",
        "http://docling.test",
        {},
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json=_converted("failure"))),
    )
    with pytest.raises(DoclingFailed):
        failing.convert(DEV_RFP)

    def never(request: httpx.Request) -> httpx.Response:
        raise AssertionError("replay opened a connection")

    replay = DoclingClient(
        "replay", "http://docling.test", {}, store=tmp_path, transport=httpx.MockTransport(never)
    )
    with pytest.raises(DoclingCassetteMissing):
        replay.convert(DEV_RFP)
