"""The graph's state. It holds plain JSON-safe data only, so checkpoints need no custom types."""

import operator
from typing import Annotated, Any, TypedDict


class RunState(TypedDict):
    """Keys fill in as the run advances; each node reads only what earlier nodes wrote."""

    guard: dict[str, Any]  # the `GuardReport`
    register: dict[str, Any]  # the `ControlRegister`
    ingest_degraded: list[str]  # scanned files left unparsed, Docling partial successes
    doc_id: str
    title: str
    passages: list[dict[str, Any]]
    cues: list[dict[str, Any]]  # `CueHit` rows, one per passage
    terms: list[dict[str, Any]]  # the defined-term registry
    zones: list[dict[str, Any]]  # `ZoneRecord`s from triage
    profile: dict[str, Any]  # the `RfpProfile` from triage
    hazards: list[dict[str, Any]]  # `SubmissionHazard`s, their requirement ids filled by verify
    triage_fallback: str | None  # "triage: zone fallback" when a call failed twice
    packs: list[dict[str, Any]]  # every extraction `ContextPack`, dumped, across rounds
    round: int  # the coverage round being extracted, 0 for the first pass
    outcomes: Annotated[list[dict[str, Any]], operator.add]
    requirements: list[dict[str, Any]]
    rejected: list[dict[str, Any]]
    candidates: list[dict[str, Any]]  # the candidate ledger, one `CandidateRow` per passage
    # The `CoverageReport` once the loop stops; until then its rounds so far and the call ids
    # of the packs the next round extracts, under "pending".
    coverage: dict[str, Any]
    lint: list[dict[str, Any]]  # `LintFinding`s
    flags: list[dict[str, Any]]  # `ContractFlag`s
    lint_skipped: list[str]  # "lint: <check> skipped on <requirement id>"
    groups: Annotated[list[dict[str, Any]], operator.add]  # one settled draft per cluster
    group_records: list[dict[str, Any]]  # the `RequirementGroup`s, numbered
    discrepancies: list[dict[str, Any]]
    questions: list[dict[str, Any]]  # `ClarificationQuestion`s
    consolidate_fallback: str | None
    approach: dict[str, Any]
    risk: dict[str, Any]
    sections: list[dict[str, Any]]


class BatchState(TypedDict):
    """What one `extract` worker receives through `Send`: one context pack."""

    call_id: str
    round: int  # the coverage round, 0 for the first pass
    pack: dict[str, Any]


class ClusterState(TypedDict):
    """What one `consolidate` worker receives through `Send`: one cluster and its task."""

    cluster: dict[str, Any]
    task: dict[str, Any]
    requirements: list[dict[str, Any]]
    lint: list[dict[str, Any]]
