"""`consolidate`: every requirement stays in exactly one group whatever the model returns, the
answer is filtered to its cluster, unanswered lint findings get template questions, a failed
call falls back to a code group, and the calls replay from cassettes recorded here."""

import json
from pathlib import Path

import pytest

from bidwright.config import load_config
from bidwright.graph.consolidate import ConsolidateOutcome, consolidate
from bidwright.graph.nodes import RunContext
from bidwright.llm.replay import CassetteStore
from bidwright.prompts import load_prompt
from bidwright.schemas import LintFinding, Requirement
from tests.node_fakes import Reply, ScriptBackend, context, dev_ingest, requirement, text

CONFIG = load_config()
PASSAGES = dev_ingest().passages


def _requirements() -> list[Requirement]:
    return [
        requirement(
            1, "SRC-0020", "The Supplier shall keep an audit record of every signature event"
        ),
        requirement(
            2,
            "SRC-0025",
            "The Supplier shall store signed documents for ten (10) years.",
            zone="OBLIGATION",
        ),
        requirement(
            3,
            "SRC-0027",
            "The service must integrate with the College's student records system",
            zone="CONTRACT",
        ),
        requirement(4, "SRC-0029", "The service shall be available 99.5% of the time"),
        requirement(
            5,
            "SRC-0031",
            "Contract award is planned for 2026-12-15.",
            disposition="BACKGROUND",
            mandatory=False,
        ),
    ]


FINDINGS = [
    LintFinding(
        id="LF-0001",
        rule="vague-terms",
        kind="VAGUE",
        requirement_id="REQ-0001",
        src_id="SRC-0020",
        match="every",
        severity="question",
    ),
    LintFinding(
        id="LF-0002",
        rule="non-singular",
        kind="NON_SINGULAR",
        requirement_id="REQ-0003",
        src_id="SRC-0027",
        match="integrate",
        severity="note",
    ),
    LintFinding(
        id="LF-0003",
        rule="missing-unit",
        kind="MISSING_UNIT",
        requirement_id="REQ-0004",
        src_id="SRC-0029",
        match="99.5%",
        severity="question",
    ),
]
ANSWER = {
    "topic": "Signing, records and integration",
    "duplicates": [
        {"requirement_id": "REQ-0001", "duplicate_of": "REQ-0999"},
        {"requirement_id": "REQ-0002", "duplicate_of": "REQ-0001"},
    ],
    "discrepancies": [
        {
            "requirement_ids": ["REQ-0001", "REQ-0999"],
            "kind": "CONFLICT",
            "state": "established",
            "description": "Invented.",
        },
        {
            "requirement_ids": ["REQ-0002", "REQ-0003"],
            "kind": "INCONSISTENT_VALUE",
            "state": "established",
            "description": "Retention and integration disagree on the record period.",
        },
    ],
    "questions": [
        {
            "text": "Which record period applies to integrated records?",
            "requirement_ids": ["REQ-0002", "REQ-0999"],
            "lint_finding_ids": ["LF-0099"],
            "reason": "Two periods.",
        }
    ],
    "references": [
        {
            "requirement_id": "REQ-0003",
            "target": "Section 4.2",
            "resolved_ids": ["REQ-0002", "REQ-0999"],
        },
        {"requirement_id": "REQ-0999", "target": "Annex Z", "resolved_ids": []},
    ],
}


def _run(ctx: RunContext, run_dir: Path) -> ConsolidateOutcome:
    ctx.prompts["consolidate"] = load_prompt("consolidate")
    return consolidate(ctx, _requirements(), PASSAGES, CONFIG, run_dir, findings=FINDINGS)


def _members(outcome: ConsolidateOutcome) -> list[str]:
    return [m for group in outcome.groups for m in group.member_ids]


def test_consolidate_anchors(tmp_path: Path) -> None:
    """Every binding and optional requirement is in exactly one group, after any answer."""
    for name, reply in (("clean", text(ANSWER)), ("junk", text({**ANSWER, "topic": "x"}))):
        outcome = _run(context(ScriptBackend([reply])), tmp_path / name)
        assert sorted(_members(outcome)) == ["REQ-0001", "REQ-0002", "REQ-0003", "REQ-0004"]
        assert len(_members(outcome)) == len(set(_members(outcome)))


def test_the_answer_is_filtered_to_its_cluster(tmp_path: Path) -> None:
    backend = ScriptBackend([text(ANSWER)])
    outcome = _run(context(backend), tmp_path)
    assert len(backend.requests) == 1, "the singleton needs no call"
    model, single = outcome.groups
    assert (model.id, model.llm, model.member_ids) == (
        "RG-001",
        True,
        ["REQ-0001", "REQ-0002", "REQ-0003"],
    )
    assert [(d.requirement_id, d.duplicate_of) for d in model.duplicates] == [
        ("REQ-0002", "REQ-0001")
    ]
    assert [(r.requirement_id, r.resolved_ids) for r in model.references] == [
        ("REQ-0003", ["REQ-0002"])
    ]
    [discrepancy] = outcome.discrepancies
    assert (discrepancy.id, discrepancy.requirement_ids) == ("DS-001", ["REQ-0002", "REQ-0003"])
    assert discrepancy.state == "conditional", "the two requirements sit in different zones"
    first, template, other = outcome.questions
    assert (first.id, first.requirement_ids, first.lint_finding_ids, first.origin) == (
        "CQ-001",
        ["REQ-0002"],
        [],
        "consolidate",
    )
    assert first.src_ids == ["SRC-0025"]
    assert template.origin == "lint_template" and template.lint_finding_ids == ["LF-0001"]
    assert template.text == 'What measurable level does "every" in REQ-0001 mean?'
    assert (single.id, single.llm, single.topic) == ("RG-002", False, "5 Service levels")
    assert other.group_id == "RG-002" and other.lint_finding_ids == ["LF-0003"]
    assert model.question_ids == ["CQ-001", "CQ-002"] and single.question_ids == ["CQ-003"]
    assert outcome.degraded is None
    for name in ("requirement_groups.jsonl", "discrepancies.jsonl", "questions.jsonl"):
        assert (tmp_path / name).exists(), name
    manifest = json.loads((tmp_path / "context" / "consolidate-RG-001.json").read_text("utf-8"))
    assert manifest["included_src_ids"] == ["SRC-0020", "SRC-0025", "SRC-0027"]


def test_a_failed_call_falls_back_to_a_code_group(tmp_path: Path) -> None:
    outcome = _run(context(ScriptBackend(["{}", "not json"])), tmp_path)
    group = outcome.groups[0]
    assert group.llm is False and group.topic == "4.1 Signing"
    assert outcome.discrepancies == []
    assert [q.origin for q in outcome.questions] == ["lint_template", "lint_template"]
    assert outcome.degraded == "consolidate: 1 clusters fell back to code groups"


def test_the_calls_replay_from_cassettes(tmp_path: Path) -> None:
    store = CassetteStore(tmp_path / "cassettes")
    replies: list[Reply] = [text(ANSWER)]
    recorded = _run(context(ScriptBackend(replies), mode="record", cassettes=store), tmp_path / "a")
    replayed = _run(context(None, mode="replay", cassettes=store), tmp_path / "b")
    assert replayed == recorded


@pytest.mark.parametrize("prompt_id", ["consolidate"])
def test_the_prompt_renders_its_cluster_examples(prompt_id: str) -> None:
    prompt = load_prompt(prompt_id)
    assert prompt.examples.count("A cluster:") == 2 and '"kind": "SUPERSEDED"' in prompt.examples
    assert "RG-001" in prompt.task_text(data_tag="data-x", cluster_id="RG-001")
