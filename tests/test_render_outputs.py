"""The summary's four parts and their order, and a schema failure that blocks all output."""

import dataclasses
from pathlib import Path

import pytest

from bidwright.render import RenderBlocked, RunRecords, render
from bidwright.schemas import ApproachItem, OpenQuestion, ProposalSection, Risk
from tests.node_fakes import GOOD_RISK, dev_requirements
from tests.render_fakes import MARKER
from tests.render_fakes import records as full_records


def _records(**changes: object) -> RunRecords:
    requirements = dev_requirements()
    base = {
        "run_id": "run-1",
        "title": "Test RFP",
        "requirements": requirements,
        "rejected": [{"batch_id": "B01", "src_ids": ["SRC-0009"], "quote": "x", "reason": "r"}],
        "approach": [
            ApproachItem(
                id="APP-001",
                text="Integrate.",
                requirement_ids=["REQ-0002"],
                basis="Stated.",
                evidence_class="ASSUMPTION",
                source_ids=["SRC-0025"],
            )
        ],
        "unmapped": ["REQ-0003"],
        "risks": [Risk(id="RSK-001", **GOOD_RISK)],
        "questions": [OpenQuestion(text="Which API version?", src_ids=["SRC-0025"])],
        "sections": [
            ProposalSection(
                id="understanding",
                title="Our understanding",
                text="Text [REQ-0001].",
                cited_ids=["REQ-0001"],
                input_hash="sha256:x",
                status="CURRENT",
            )
        ],
    }
    return RunRecords(**(base | changes))  # type: ignore[arg-type]


def test_the_summary_has_four_parts_with_hazards_first(tmp_path: Path) -> None:
    summary = render(tmp_path, _records())
    text = (tmp_path / "solution_summary.md").read_text(encoding="utf-8")
    order = [
        "UNREVIEWED_DRAFT",
        "## 1. Requirements",
        "### Submission hazards",
        "REQ-0001",
        "### Mandatory requirements",
        "REQ-0002",
        "### Optional requirements",
        "REQ-0004",
        "## 2. Approach",
        "APP-001",
        "## 3. Risks",
        "RSK-001",
        "## 4. Open questions",
    ]
    positions = [text.index(marker) for marker in order]
    assert positions == sorted(positions)
    assert summary.hazards == ["REQ-0001"]
    assert summary.requirements == ["REQ-0002", "REQ-0003", "REQ-0004"]
    assert summary.counts["rejected"] == 1 and summary.status == "UNREVIEWED_DRAFT"
    assert "UNREVIEWED_DRAFT" in (tmp_path / "proposal.md").read_text(encoding="utf-8")


def test_render_schema_failure_blocks_all_output(tmp_path: Path) -> None:
    broken = Risk.model_construct(id="RISK-1", event="no fields")  # skips validation
    with pytest.raises(RenderBlocked, match="Risk"):
        render(tmp_path, _records(risks=[broken]))
    assert list(tmp_path.iterdir()) == []


# --- Iteration 1, step 15: the new outputs -------------------------------------------------


def test_the_summary_counts_the_review_items_and_never_repeats_hidden_text(
    tmp_path: Path,
) -> None:
    render(tmp_path, full_records())
    summary = (tmp_path / "solution_summary.md").read_text(encoding="utf-8")
    assert MARKER not in summary
    assert (
        "Hidden content quarantined: 2 items; small print: 1 passage; suspect passages: 1;"
        " see `review/quarantine.md`." in summary
    )
    records = full_records()
    render(tmp_path / "one", dataclasses.replace(records, quarantine=records.quarantine[:1]))
    single = (tmp_path / "one" / "solution_summary.md").read_text(encoding="utf-8")
    assert "Hidden content quarantined: 1 item; small print: 1 passage;" in single
    for line in (
        "Requirement groups: 2, in `requirement_groups.jsonl`.",
        "Discrepancies: 0, in `discrepancies.jsonl`.",
        "Clarification questions: 1, in `clarification_questions.md`.",
        "Contract flags for legal review: 1, in `contract_flags.jsonl`.",
    ):
        assert line in summary, line
    assert summary.index("### Submission hazards") < summary.index("Hidden content quarantined")


def test_the_review_file_shows_hidden_text_exactly_in_safe_fences(tmp_path: Path) -> None:
    render(tmp_path, full_records())
    review = (tmp_path / "review" / "quarantine.md").read_text(encoding="utf-8")
    assert MARKER in review and "    ````" in review, "one backtick longer than the text's run"
    assert "(cut at 500 of 600 characters)" in review
    assert "## Small print kept in the text" in review and "- SRC-0029" in review
    assert "## Visible text that reads like an instruction to a model" in review
    assert "- SRC-0018" in review


def test_the_checklist_lists_every_hazard_by_kind(tmp_path: Path) -> None:
    render(tmp_path, full_records())
    checklist = (tmp_path / "submission_checklist.md").read_text(encoding="utf-8")
    assert "Deadline: 2026-12-01 12:00 UTC" in checklist and "Format: One PDF" in checklist
    assert "## FORMAT" in checklist and "## DEADLINE" in checklist
    assert '- [ ] **HZ-001** One PDF only. (REQ-0004) "Proposals must be submitted as one PDF"' in (
        checklist
    )
    assert "- [ ] **HZ-002** Bids close at noon. (no requirement yet)" in checklist


def test_questions_are_grouped_by_topic_with_their_quotes(tmp_path: Path) -> None:
    render(tmp_path, full_records())
    questions = (tmp_path / "clarification_questions.md").read_text(encoding="utf-8")
    assert "## Records (RG-001)" in questions
    assert "- **CQ-001** How long are records kept?" in questions
    assert "Requirements: REQ-0001, REQ-0002. Origin: consolidate." in questions
    assert '> REQ-0001: "The Supplier shall keep an audit record"' in questions


def test_a_v0_shaped_call_still_renders_every_file(tmp_path: Path) -> None:
    render(tmp_path, _records())
    for name in (
        "solution_summary.md",
        "compliance_matrix.xlsx",
        "compliance_matrix.csv",
        "clarification_questions.md",
        "submission_checklist.md",
        "review/quarantine.md",
    ):
        assert (tmp_path / name).exists(), name


@pytest.mark.parametrize(
    "field",
    ["hazards", "groups", "clarifications", "lint_findings", "contract_flags", "quarantine"],
)
def test_a_schema_failure_in_a_new_list_blocks_all_output(tmp_path: Path, field: str) -> None:
    good = getattr(full_records(), field)
    broken = [good[0].model_copy(update={"id": "not an id"})]
    with pytest.raises(RenderBlocked):
        render(tmp_path, full_records(**{field: broken}))
    assert not any(tmp_path.iterdir())
