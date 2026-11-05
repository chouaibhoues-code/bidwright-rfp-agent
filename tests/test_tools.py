"""search_rfp over the development RFP's passages, and date_calc on the 20 S-09 cases."""

from pathlib import Path
from typing import Any

import pytest
import yaml

from bidwright.harness.gateway import ToolGateway
from bidwright.ingest import ingest_pdf
from bidwright.retrieval import PassageIndex, match_expression
from bidwright.schemas import Passage, ToolRequest
from bidwright.tools import (
    NO_HOLIDAYS,
    DateArgs,
    ReadSectionArgs,
    SearchArgs,
    SlaArgs,
    date_calc,
    date_tool,
    requirement_ids,
    search_tool,
    section_tool,
    sla_calc,
    sla_tool,
)

ROOT = Path(__file__).resolve().parents[1]
CASES: list[dict[str, Any]] = yaml.safe_load(
    (ROOT / "tests" / "data" / "s09_cases.yaml").read_text(encoding="utf-8")
)


@pytest.fixture(scope="module")
def index(tmp_path_factory: pytest.TempPathFactory) -> PassageIndex:
    result = ingest_pdf(ROOT / "inputs" / "dev" / "dev_rfp.pdf")
    return PassageIndex.build(result.passages, tmp_path_factory.mktemp("run") / "search.sqlite")


def test_s09_has_twenty_cases() -> None:
    assert len(CASES) == 20


@pytest.mark.parametrize("case", CASES, ids=[str(i + 1) for i in range(len(CASES))])
def test_s09_date_calc(case: dict[str, Any]) -> None:
    result = date_calc(DateArgs.model_validate(case["args"]))
    if case.get("status") == "FAILED":
        assert result.status == "FAILED" and result.reason
        return
    assert result.status == "OK", result.reason
    assert result.data["result"] == case["result"]
    if case["args"].get("unit") == "business_days":
        assert NO_HOLIDAYS in result.data["explanation"]


def test_search_finds_the_go_live_and_migration_passages(index: PassageIndex) -> None:
    result = search_tool(index).run(SearchArgs(query="go-live migration deadline", k=5))
    assert result.status == "OK"
    texts = [hit["text"] for hit in result.data]
    assert any("must be live for students" in text for text in texts)
    assert any("should migrate the signed records" in text for text in texts)
    scores = [hit["score"] for hit in result.data]
    assert scores == sorted(scores, reverse=True)


def test_a_requirement_id_returns_the_passages_it_quotes(index: PassageIndex) -> None:
    tool = search_tool(index, {"REQ-0011": ["SRC-0015"], "REQ-0025": ["SRC-0032"]})
    only_ids = tool.run(SearchArgs(query="REQ-0011 REQ-0025", k=5))
    assert [hit["src_id"] for hit in only_ids.data] == ["SRC-0015", "SRC-0032"]
    mixed = tool.run(SearchArgs(query="REQ-0025 migration", k=3))
    ids = [hit["src_id"] for hit in mixed.data]
    assert ids[0] == "SRC-0032" and "SRC-0026" in ids and len(ids) <= 3
    unknown = search_tool(index).run(SearchArgs(query="REQ-0011", k=3))
    assert unknown.status == "EMPTY"


def test_ids_joined_by_function_words_return_only_their_passages(index: PassageIndex) -> None:
    tool = search_tool(index, {"REQ-0011": ["SRC-0015"], "REQ-0025": ["SRC-0032"]})
    result = tool.run(SearchArgs(query="REQ-0011 and REQ-0025 for the", k=5))
    assert [hit["src_id"] for hit in result.data] == ["SRC-0015", "SRC-0032"]


@pytest.mark.parametrize("written", ["req-0011", "REQ-11", "Req 11", "REQ0011"])
def test_requirement_ids_are_read_in_the_forms_models_write(
    index: PassageIndex, written: str
) -> None:
    assert requirement_ids(f"risk in {written}") == ["REQ-0011"]
    result = search_tool(index, {"REQ-0011": ["SRC-0015"]}).run(SearchArgs(query=written, k=3))
    assert [hit["src_id"] for hit in result.data] == ["SRC-0015"]


def test_search_caps_k_and_reports_empty(index: PassageIndex) -> None:
    assert len(index.search("supplier service records", k=50)) == 8
    empty = search_tool(index).run(SearchArgs(query="kangaroo", k=3))
    assert empty.status == "EMPTY" and empty.data == []
    assert index.search("the and of for", k=5) == []


def test_fts5_operators_in_queries_are_inert(index: PassageIndex) -> None:
    assert match_expression('audit" OR NEAR(x y) *') == '"audit" OR "NEAR" OR "x" OR "y"'
    assert index.search('records NOT audit "') != []
    assert index.search("*** ---") == []


def test_tool_specs_expose_only_required_fields_as_required() -> None:
    schema = date_tool().spec.parameters
    assert schema["required"] == ["date", "op"]
    assert "title" not in schema and "title" not in schema["properties"]["op"]
    assert search_tool.__name__ == "search_tool"


SLA_CASES: list[dict[str, Any]] = yaml.safe_load(
    (ROOT / "tests" / "data" / "sla_cases.yaml").read_text(encoding="utf-8")
)["cases"]


@pytest.fixture(scope="module")
def dev_passages() -> list[Passage]:
    return list(ingest_pdf(ROOT / "inputs" / "dev" / "dev_rfp.pdf").passages)


def test_sla_has_twelve_cases() -> None:
    assert len(SLA_CASES) == 12


@pytest.mark.parametrize("case", SLA_CASES, ids=lambda c: f"{c['target']}-{c['period']}")
def test_sla_calc(case: dict[str, Any]) -> None:
    result = sla_calc(
        SlaArgs(
            target_percent=case["target"],
            period=case["period"],
            measured_minutes=case.get("measured"),
        )
    )
    if case.get("failed"):
        assert result.status == "FAILED" and "longer than a month" in str(result.reason)
        return
    assert result.status == "OK" and isinstance(result.data, dict)
    assert "counts as" in result.data["explanation"], "the period's length is named"
    if "measured" in case:
        assert result.data["result"] == pytest.approx(case["achieved"])
        assert result.data["met"] is case["met"]
    else:
        assert result.data["result"] == pytest.approx(case["allowed"])


def test_a_percentage_outside_90_to_100_is_denied_by_the_argument_check() -> None:
    gateway = ToolGateway.for_agent("risk", ["sla_calc"], [sla_tool()], 6)
    request = ToolRequest(
        tool="sla_calc", args={"target_percent": 120, "period": "month"}, agent="risk", turn=1
    )
    result = gateway.call(request)
    assert result.status == "DENIED"


def test_read_section_by_passage_and_by_path_returns_the_same_passages(
    dev_passages: list[Passage],
) -> None:
    tool = section_tool(dev_passages)
    anchor = next(p for p in dev_passages if p.section_path.startswith("3"))
    by_passage = tool.run(ReadSectionArgs(src_id=anchor.id))
    by_path = tool.run(ReadSectionArgs(doc_id=anchor.doc_id, section_path=anchor.section_path))
    assert by_passage.status == "OK" and by_passage == by_path
    assert isinstance(by_passage.data, list) and 1 <= len(by_passage.data) <= 8
    assert all(row["section_path"] == anchor.section_path for row in by_passage.data)
    assert tool.run(ReadSectionArgs(src_id="SRC-9999")).status == "EMPTY"


def test_read_section_returns_at_most_eight_passages() -> None:
    passages = [
        Passage(
            id=f"SRC-{n:04d}",
            doc_id="d",
            section_path="4 Big",
            kind="sentence",
            text=f"Line {n}.",
            start=n * 10,
            end=n * 10 + 8,
        )
        for n in range(1, 13)
    ]
    result = section_tool(passages).run(ReadSectionArgs(src_id="SRC-0012"))
    assert isinstance(result.data, list)
    assert [row["src_id"] for row in result.data] == [f"SRC-{n:04d}" for n in range(1, 9)]
