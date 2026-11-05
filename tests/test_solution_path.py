"""The solution path wired into the run (Iteration 3, step 12): each `solution` value on fakes,
the new `--until` stops, the gate under `wait` and `approve`, the summary's solution block, and
the family rule's `DEGRADED` reason."""

import json
from pathlib import Path
from typing import Any

import pytest

from bidwright.graph.build import RunResult, execute
from bidwright.graph.gate import reviewed_hashes
from bidwright.schemas import GateApproval, RunManifest
from tests.node_fakes import DEV_RFP, RuleBackend, fake_backends


def run(tmp_path: Path, run_id: str = "path", **kwargs: Any) -> RunResult:
    arguments: dict[str, Any] = {
        "docling_mode": "replay",
        "source": DEV_RFP,
        "profile": "free",
        "outputs": tmp_path / "out",
        "backends": fake_backends(RuleBackend()),
        "run_id": run_id,
        "research": "off",
        **kwargs,
    }
    return execute(**arguments)


def summary(result: RunResult) -> str:
    return (result.run_dir / "solution_summary.md").read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("solution", "files"),
    [
        ("oneshot", ["approach.json"]),
        ("fixed", ["claims.jsonl", "decisions.jsonl", "approach.json"]),
        ("decide", ["claims.jsonl", "decisions.jsonl", "approach.json"]),
        ("assess", ["assessments.jsonl", "capability_map.json", "approach.json"]),
        (
            "manifest",
            ["options.json", "manifest.json", "tech_validations.jsonl", "bid_signal.json"],
        ),
    ],
)
def test_each_solution_value_reaches_render(
    tmp_path: Path, solution: str, files: list[str]
) -> None:
    result = run(tmp_path, solution=solution)
    assert result.status in ("COMPLETED", "DEGRADED"), result.reason
    for name in [*files, "solution_summary.md", "proposal.md"]:
        assert (result.run_dir / name).is_file(), name
    stored = RunManifest.model_validate_json((result.run_dir / "run_manifest.json").read_text())
    assert stored.switches["solution"] == solution
    assert stored.run_args["solution"] == solution
    if solution in ("oneshot", "fixed", "decide"):
        assert not (result.run_dir / "options.json").exists()


def test_the_manifest_path_writes_the_solution_block_and_decides_questions(tmp_path: Path) -> None:
    result = run(tmp_path, solution="manifest")
    text = summary(result)
    parts = [text.index(h) for h in ("## 1. Requirements", "## 2. Approach", "## 3. Risks")]
    parts.append(text.index("## 4. Open questions"))
    assert parts == sorted(parts), "the summary keeps its four parts"
    block = text.index("### The chosen solution")
    assert parts[1] < block < parts[2], "the solution block sits after the approach part"
    assert "Option: OPT-1." in text and "Bid signal: UNDETERMINED" in text
    data = json.loads((result.run_dir / "solution_summary.json").read_text(encoding="utf-8"))
    assert data["summary"]["option_id"] == "OPT-1"
    assert data["summary"]["bid_signal"] == "UNDETERMINED"
    approval = (result.run_dir / "review" / "solution_gate.approval.yaml").read_text("utf-8")
    assert "auto_selected: true" in approval


@pytest.mark.parametrize("until", ["capability_map", "solution_gate"])
def test_the_new_until_values_stop_there(tmp_path: Path, until: str) -> None:
    result = run(tmp_path, solution="manifest", until=until)
    assert result.status in ("COMPLETED", "DEGRADED") and f"stopped after {until}" in (
        result.reason or ""
    )
    assert (result.run_dir / "capability_map.json").is_file()
    assert (result.run_dir / "options.json").exists() == (until == "solution_gate")
    assert not (result.run_dir / "solution_summary.md").exists()


def test_gate_waiting_human_then_approve_completes_the_run(tmp_path: Path) -> None:
    waiting = run(tmp_path, solution="manifest", gate="wait")
    assert waiting.status == "WAITING_HUMAN", waiting.reason
    assert "bidwright approve path --role ROLE" in (waiting.reason or "")
    assert (waiting.run_dir / "review" / "solution_gate.md").is_file()
    assert not (waiting.run_dir / "solution_summary.md").exists()
    with pytest.raises(Exception, match="bidwright approve"):
        run(tmp_path, solution="manifest", gate="wait", resume=True)
    approval = GateApproval(
        run_id="path",
        reviewed=reviewed_hashes(waiting.run_dir),
        decision="approve",
        approver_role="Bid director",
        decided="2026-11-05T15:00:00Z",  # type: ignore[arg-type]
    )
    done = run(tmp_path, solution="manifest", gate="wait", resume=True, approval=approval)
    assert done.status in ("COMPLETED", "DEGRADED"), done.reason
    assert (done.run_dir / "solution_summary.md").is_file()
    stored = (done.run_dir / "review" / "solution_gate.approval.yaml").read_text("utf-8")
    assert "Bid director" in stored and "auto_selected: false" in stored


def test_a_gemini_only_free_run_is_degraded_same_family(tmp_path: Path) -> None:
    result = run(tmp_path, solution="assess", backends={"gemini": RuleBackend()})
    assert result.status == "DEGRADED" and "assess: SAME_FAMILY" in (result.reason or "")
    stored = RunManifest.model_validate_json((result.run_dir / "run_manifest.json").read_text())
    assert stored.assess_route == "same"


def test_an_unknown_switch_value_is_refused(tmp_path: Path) -> None:
    with pytest.raises(Exception, match="solution takes one of"):
        run(tmp_path, solution="everything")
