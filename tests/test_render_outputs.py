"""The summary's four parts and their order, and a schema failure that blocks all output."""

from pathlib import Path

import pytest

from bidwright.render import RenderBlocked, RunRecords, render
from bidwright.schemas import ApproachItem, OpenQuestion, ProposalSection, Risk
from tests.node_fakes import GOOD_RISK, dev_requirements


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
