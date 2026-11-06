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
    # Iteration 2: the brief, as {"record": the `OpportunityBrief`, "degraded": the shortfall};
    # the research, as {"second_job": whether `discover_ask` started one, "degraded": the
    # shortfall `discover_load` records}; the live node's research failure, which routes to
    # `discover_load`; and the domain brief, as {"brief": the `DomainBrief`, "origin": where
    # it came from, "citations": each cited excerpt's source title and tier}, or None.
    brief: dict[str, Any]
    research: dict[str, Any]
    research_failed: str | None
    domain_brief: dict[str, Any] | None
    approach: dict[str, Any]
    risk: dict[str, Any]
    sections: list[dict[str, Any]]
    # Iteration 3 (step 12): the solution path, in graph order. `decide_outcomes` and
    # `assessed` collect the `Send` workers' results; the rest are the joins' settled records.
    needs: dict[str, Any]  # the `NeedPlan`
    decide_outcomes: Annotated[list[dict[str, Any]], operator.add]
    decisions: list[dict[str, Any]]
    claims: list[dict[str, Any]]
    decide_questions: list[dict[str, Any]]
    decide_degraded: str | None
    assessed: Annotated[list[dict[str, Any]], operator.add]
    assessments: list[dict[str, Any]]
    assess_degraded: str | None
    capability_map: dict[str, Any]
    options: dict[str, Any]
    options_degraded: str | None
    manifest: dict[str, Any]
    blueprint_plan: dict[str, Any] | None
    blueprint_failed: str | None
    tech_validations: list[dict[str, Any]]
    techcheck: dict[str, Any]  # {"revision_due": bool}
    gate: dict[str, Any]  # {"next", "option_id", "changed"}
    bid_signal: dict[str, Any]


class BatchState(TypedDict):
    """What one `extract` worker receives through `Send`: one context pack."""

    call_id: str
    round: int  # the coverage round, 0 for the first pass
    pack: dict[str, Any]


class NeedState(TypedDict):
    """What one `decide` worker receives through `Send`: one need (Iteration 3)."""

    need: dict[str, Any]
    passages: list[str]
    records: list[str]


class ClaimState(TypedDict):
    """What one `assess` worker receives through `Send`: one claim and its need."""

    claim: dict[str, Any]
    need: dict[str, Any]


class ClusterState(TypedDict):
    """What one `consolidate` worker receives through `Send`: one cluster and its task."""

    cluster: dict[str, Any]
    task: dict[str, Any]
    requirements: list[dict[str, Any]]
    lint: list[dict[str, Any]]


# Seed runs (Iteration 3, step 16; section 4.11). `SEED_KEYS[point]` lists the state keys the
# nodes before the seed point write, which `seed_load` restores; `SEED_FILES[point]` the files
# they write, which it copies (patterns under the run folder); `SEED_PROMPTS[point]` the prompts
# they use, besides the run's extract prompt, whose hashes the seed must share with the run's.
# A test replays a development run and checks that the lists hold every key and file.
_RESEARCH_KEYS = (
    "guard",
    "register",
    "ingest_degraded",
    "doc_id",
    "title",
    "passages",
    "cues",
    "terms",
    "zones",
    "profile",
    "hazards",
    "triage_fallback",
    "packs",
    "round",
    "outcomes",
    "requirements",
    "rejected",
    "candidates",
    "coverage",
    "lint",
    "flags",
    "lint_skipped",
    "groups",
    "group_records",
    "discrepancies",
    "questions",
    "consolidate_fallback",
    "brief",
)
_RISK_KEYS = (
    "research",
    "research_failed",
    "domain_brief",
    "needs",
    "decide_outcomes",
    "decisions",
    "claims",
    "decide_questions",
    "decide_degraded",
    "assessed",
    "assessments",
    "assess_degraded",
    "capability_map",
    "options",
    "options_degraded",
    "manifest",
    "blueprint_plan",
    "blueprint_failed",
    "tech_validations",
    "techcheck",
    "approach",
)
_RESEARCH_FILES = (
    "frozen.txt",
    "passages.jsonl",
    "search.sqlite",
    "parse/*",
    "guard_report.json",
    "quarantine.jsonl",
    "control_register.json",
    "cues.jsonl",
    "terms.json",
    "triage.json",
    "hazards.json",
    "candidates.jsonl",
    "requirements.jsonl",
    "rejected.jsonl",
    "coverage.json",
    "lint_findings.jsonl",
    "contract_flags.jsonl",
    "requirement_groups.jsonl",
    "discrepancies.jsonl",
    "questions.jsonl",
    "brief.json",
    "context/triage-*",
    "context/extract-*",
    "context/consolidate-*",
    "context/brief-*",
)
_RISK_FILES = (
    "research.json",
    "domain_brief.json",
    "kb.sqlite",
    "decisions.jsonl",
    "claims.jsonl",
    "assessments.jsonl",
    "capability_map.json",
    "options.json",
    "manifest.json",
    "approach.json",
    "tech_docs.jsonl",
    "tech_validations.jsonl",
    "context/discover-*",
    "context/decide-*",
    "context/assess-*",
    "context/options-*",
    "context/blueprint-*",
    "context/techcheck-*",
    "context/approach-*",
)
SEED_KEYS: dict[str, tuple[str, ...]] = {
    "research": _RESEARCH_KEYS,
    "risk": _RESEARCH_KEYS + _RISK_KEYS,
}
SEED_FILES: dict[str, tuple[str, ...]] = {
    "research": _RESEARCH_FILES,
    "risk": _RESEARCH_FILES + _RISK_FILES,
}
SEED_PROMPTS: dict[str, tuple[str, ...]] = {
    "research": ("triage", "consolidate", "brief"),
    "risk": (
        "triage",
        "consolidate",
        "brief",
        "discover",
        "decide",
        "assess",
        "options",
        "blueprint",
        "blueprint_detail",
        "techcheck",
        "approach",
    ),
}
# The seed points' next nodes, and the last node a seeded run may stop at the earliest.
SEED_UNTIL: dict[str, tuple[str, ...]] = {
    "research": ("capability_map", "solution_gate", "render"),
    "risk": ("solution_gate", "render"),
}
