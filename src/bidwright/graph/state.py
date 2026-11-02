"""The graph's state. It holds plain JSON-safe data only, so checkpoints need no custom types."""

import operator
from typing import Annotated, Any, TypedDict


class RunState(TypedDict):
    """Keys fill in as the run advances; each node reads only what earlier nodes wrote."""

    doc_id: str
    title: str
    passages: list[dict[str, Any]]
    batches: list[dict[str, Any]]
    outcomes: Annotated[list[dict[str, Any]], operator.add]
    requirements: list[dict[str, Any]]
    rejected: list[dict[str, Any]]
    approach: dict[str, Any]
    risk: dict[str, Any]
    sections: list[dict[str, Any]]


class BatchState(TypedDict):
    """What one `extract` worker receives through `Send`."""

    batch_id: str
    ids: list[str]
