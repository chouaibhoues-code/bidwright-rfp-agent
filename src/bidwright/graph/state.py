"""The graph's state. It holds plain JSON-safe data only, so checkpoints need no custom types."""

import operator
from typing import Annotated, Any, TypedDict


class RunState(TypedDict):
    """Keys fill in as the run advances; each node reads only what earlier nodes wrote."""

    doc_id: str
    title: str
    passages: list[dict[str, Any]]
    cues: list[dict[str, Any]]  # `CueHit` rows, one per passage
    terms: list[dict[str, Any]]  # the defined-term registry
    zones: list[dict[str, Any]]  # `ZoneRecord`s from triage
    profile: dict[str, Any]  # the `RfpProfile` from triage
    hazards: list[dict[str, Any]]  # `SubmissionHazard`s, their requirement ids filled by verify
    triage_fallback: str | None  # "triage: zone fallback" when a call failed twice
    packs: list[dict[str, Any]]  # every extraction `ContextPack`, dumped
    outcomes: Annotated[list[dict[str, Any]], operator.add]
    requirements: list[dict[str, Any]]
    rejected: list[dict[str, Any]]
    approach: dict[str, Any]
    risk: dict[str, Any]
    sections: list[dict[str, Any]]


class BatchState(TypedDict):
    """What one `extract` worker receives through `Send`: one context pack."""

    call_id: str
    round: int  # the coverage round, 0 for the first pass
    pack: dict[str, Any]
