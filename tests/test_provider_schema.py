"""The schema cleaner drops `title` annotations but never a field that is called `title`."""

from pydantic import BaseModel

from bidwright.llm.schema import provider_schema
from bidwright.schemas import DraftResult, ExtractResult
from bidwright.tools import parameters_schema


def test_a_field_named_title_survives_and_stays_required() -> None:
    schema = provider_schema(DraftResult)
    assert list(schema["properties"]) == ["title", "text", "cited_ids"]
    assert schema["required"] == ["title", "text", "cited_ids"]
    assert "title" not in schema["properties"]["title"]  # its own annotation is dropped


def test_nested_objects_are_closed_and_annotations_dropped() -> None:
    schema = provider_schema(ExtractResult)
    item = schema["properties"]["items"]["items"]
    assert item["additionalProperties"] is False and "$defs" not in schema
    assert all("title" not in field for field in item["properties"].values())


def test_tool_parameters_keep_a_field_named_title() -> None:
    class Args(BaseModel):
        title: str
        limit: int = 5

    schema = parameters_schema(Args)
    assert list(schema["properties"]) == ["title", "limit"] and schema["required"] == ["title"]
