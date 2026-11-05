"""`solution_gate` (Iteration 3, step 10; ADR-035, ADR-046), on a LangGraph test graph with
stub `blueprint`, `techcheck`, `risk` and `draft` nodes and an in-memory checkpointer, resumed
with `Command(resume=...)`."""

import operator
from collections.abc import Callable
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Annotated, Any, TypedDict

import pytest
import yaml
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command

from bidwright.graph.blueprint import EditRefused, apply_edits, write_manifest
from bidwright.graph.gate import (
    APPROVAL_FILE,
    REVIEW_FILE,
    GateInputs,
    read_approval,
    reviewed_hashes,
    solution_gate,
)
from bidwright.graph.options import write_options
from bidwright.graph.signal import SignalInputs
from bidwright.guard import PolicyBlocked
from bidwright.schemas import (
    CapabilityMap,
    CapabilityRow,
    EffortEstimate,
    GateApproval,
    GateEdit,
    SolutionManifest,
    SolutionOption,
    SolutionOptions,
    TechValidation,
    WorkPackage,
)

RUN_ID = "run-gate"
NOW = datetime(2026, 11, 5, 15, 0, tzinfo=UTC)


def _manifest() -> SolutionManifest:
    effort = EffortEstimate(low_days=5, high_days=10, basis="analogy", basis_text="Similar work.")
    return SolutionManifest(
        option_id="OPT-1",
        work_packages=[
            WorkPackage(code="1.1", name="Configure", requirement_ids=["REQ-0001"], effort=effort),
            WorkPackage(code="1.2", name="Train", effort=effort.model_copy()),
        ],
    )


OPTIONS = SolutionOptions(
    options=[
        SolutionOption(id="OPT-1", name="Configured", total=3.0, rank=1, baseline=True),
        SolutionOption(id="OPT-2", name="Built", total=2.0, rank=2),
    ]
)
CMAP = CapabilityMap(
    rows=[CapabilityRow(need_id="RG-001", origin="RFP", text="Signature", status="COVERED")]
)
CLEAN = [TechValidation(claim_id="TC-01", library="pdfplumber", verdict="VALIDATED")]
WRONG = [TechValidation(claim_id="TC-01", library="pdfplumber", verdict="INVALIDATED")]


class State(TypedDict, total=False):
    visits: Annotated[list[str], operator.add]
    next: str
    changed: list[str]


class Run:
    """A run folder with the manifest and options, and the test graph over it."""

    def __init__(self, folder: Path, mode: str = "wait", validations: list | None = None) -> None:
        self.dir = folder
        folder.mkdir(parents=True, exist_ok=True)
        self.validations = list(validations or CLEAN)
        write_manifest(folder, _manifest())
        write_options(folder, OPTIONS)
        graph = StateGraph(State)
        for name in ("blueprint", "techcheck", "risk", "draft"):
            graph.add_node(name, self._stub(name))
        graph.add_node("gate", self._gate(mode))
        graph.add_edge(START, "blueprint")
        graph.add_edge("blueprint", "techcheck")
        graph.add_edge("techcheck", "risk")
        graph.add_edge("risk", "gate")
        graph.add_conditional_edges(
            "gate", lambda s: s["next"], ["draft", "blueprint", "techcheck"]
        )
        graph.add_edge("draft", END)
        self.graph = graph.compile(checkpointer=InMemorySaver())
        self.config: Any = {"configurable": {"thread_id": RUN_ID}}

    def _stub(self, name: str) -> Callable[..., State]:
        def node(state: State) -> State:
            return {"visits": [name]}

        return node

    def _gate(self, mode: str) -> Callable[..., State]:
        def node(state: State) -> State:
            outcome = solution_gate(self.dir, RUN_ID, self.inputs(), mode=mode)  # type: ignore[arg-type]
            return {"visits": ["gate"], "next": outcome.next, "changed": outcome.changed}

        return node

    def inputs(self) -> GateInputs:
        manifest = SolutionManifest.model_validate_json(
            (self.dir / "manifest.json").read_text(encoding="utf-8")
        )
        signal = SignalInputs(
            capability_map=CMAP,
            options=OPTIONS,
            manifest=manifest,
            tech_validations=self.validations,
            hazards=[],
            flags=[],
            binding_needs={"RG-001"},
            need_of={},
            deadline="not_stated",
            started=date(2026, 11, 5),
        )
        return GateInputs(
            options=OPTIONS,
            capability_map=CMAP,
            manifest=manifest,
            tech_validations=self.validations,
            risks=[],
            questions=[],
            signal_inputs=signal,
            research_origin="research pack local-government-case-management, version 1",
        )

    def start(self) -> dict[str, Any]:
        return self.graph.invoke({"visits": []}, self.config)

    def resume(self, approval: GateApproval) -> dict[str, Any]:
        return self.graph.invoke(Command(resume=approval.model_dump(mode="json")), self.config)

    def approval(self, decision: str = "approve", **fields: Any) -> GateApproval:
        return GateApproval(
            run_id=RUN_ID,
            reviewed=reviewed_hashes(self.dir),
            decision=decision,  # type: ignore[arg-type]
            approver_role="Bid director",
            decided=NOW,
            **fields,
        )


def test_gate_waiting_human_writes_the_review_and_interrupts(tmp_path: Path) -> None:
    run = Run(tmp_path)
    first = run.start()
    assert "__interrupt__" in first and first["__interrupt__"][0].value["review"] == REVIEW_FILE
    review = (tmp_path / REVIEW_FILE).read_text(encoding="utf-8")
    for heading in (
        "## The chosen option",
        "## The ranking",
        "## The capability map",
        "## The work packages",
        "## Technology claims",
        "## The bid signal",
        "## How to decide",
    ):
        assert heading in review
    assert "bidwright approve run-gate --role ROLE" in review
    assert (tmp_path / "bid_signal.json").is_file() and (tmp_path / "bid_memo.md").is_file()
    assert not (tmp_path / APPROVAL_FILE).exists()


def test_an_approval_is_written_with_the_hashes_reviewed_and_the_run_goes_on(
    tmp_path: Path,
) -> None:
    run = Run(tmp_path)
    run.start()
    done = run.resume(run.approval())
    assert "__interrupt__" not in done and done["visits"][-2:] == ["gate", "draft"]
    stored = read_approval(tmp_path)
    assert stored is not None and stored.reviewed == reviewed_hashes(tmp_path)
    assert yaml.safe_load((tmp_path / APPROVAL_FILE).read_text(encoding="utf-8"))["gate"] == (
        "solution_gate"
    )


def test_a_manifest_changed_after_review_voids_the_approval(tmp_path: Path) -> None:
    run = Run(tmp_path)
    run.start()
    approval = run.approval()
    changed = _manifest().model_copy(update={"notes": ["changed after review"]})
    write_manifest(tmp_path, changed)
    again = run.resume(approval)
    assert "__interrupt__" in again
    assert "changed after it was reviewed" in (again["__interrupt__"][0].value["note"] or "")
    done = run.resume(run.approval())
    assert done["visits"][-1] == "draft"


def test_gate_recheck(tmp_path: Path) -> None:
    """Edits to an effort and a predecessor are applied, techcheck and risk run again, and the
    gate then passes without waiting while the manifest's hash equals edited_sha256."""
    run = Run(tmp_path)
    run.start()
    edits = [
        GateEdit(field="work_packages[1.2].effort.high_days", value=14),
        GateEdit(field="work_packages[1.2].predecessors", value=["1.1"]),
    ]
    done = run.resume(run.approval("edit", edits=edits))
    assert "__interrupt__" not in done
    assert done["visits"] == [
        "blueprint",
        "techcheck",
        "risk",
        "gate",
        "techcheck",
        "risk",
        "gate",
        "draft",
    ]
    assert done["changed"] == []  # the second pass changes nothing
    stored = read_approval(tmp_path)
    assert stored is not None and stored.edited_sha256 == reviewed_hashes(tmp_path).manifest
    edited = SolutionManifest.model_validate_json((tmp_path / "manifest.json").read_text("utf-8"))
    package = edited.work_packages[1]
    assert package.effort is not None and package.effort.high_days == 14
    assert package.predecessors == ["1.1"]
    assert "edited at the gate: work_packages[1.2].predecessors" in edited.notes


def test_an_approval_with_another_option_leads_back_to_blueprint(tmp_path: Path) -> None:
    run = Run(tmp_path)
    run.start()
    again = run.resume(run.approval(option_id="OPT-2"))
    assert "__interrupt__" in again, "the gate waits again for the new option's manifest"
    state = run.graph.get_state(run.config).values
    assert state["visits"] == [
        "blueprint",
        "techcheck",
        "risk",
        "gate",
        "blueprint",
        "techcheck",
        "risk",
    ]


def test_techcheck_blocks_gate(tmp_path: Path) -> None:
    run = Run(tmp_path / "wait", validations=WRONG)
    first = run.start()
    assert first["__interrupt__"][0].value["blocked_by"] == ["TC-01"]
    again = run.resume(run.approval())
    assert "needs --override" in (again["__interrupt__"][0].value["note"] or "")
    done = run.resume(run.approval(override_reason="The library pack predates the fix."))
    assert done["visits"][-1] == "draft"
    stored = read_approval(tmp_path / "wait")
    assert stored is not None and stored.override_reason == "The library pack predates the fix."

    auto = Run(tmp_path / "auto", mode="auto", validations=WRONG)
    with pytest.raises(PolicyBlocked, match="GATE_BLOCKED"):
        auto.start()


def test_automatic_approval_takes_the_top_option_without_waiting(tmp_path: Path) -> None:
    run = Run(tmp_path, mode="auto")
    done = run.start()
    assert "__interrupt__" not in done and done["visits"][-1] == "draft"
    stored = read_approval(tmp_path)
    assert stored is not None and stored.auto_selected and stored.option_id == "OPT-1"


def test_a_reject_ends_the_run_policy_blocked(tmp_path: Path) -> None:
    run = Run(tmp_path)
    run.start()
    with pytest.raises(PolicyBlocked, match="GATE_REJECTED: Out of our scope."):
        run.resume(run.approval("reject", reject_reason="Out of our scope."))
    stored = read_approval(tmp_path)
    assert stored is not None and stored.decision == "reject"


@pytest.mark.parametrize(
    ("field", "value", "problem"),
    [
        ("work_packages[9.9].scope", "x", "no work package 9.9"),
        ("work_packages[1.1].effort.low_days", 20, "low_days would be above high_days"),
        ("work_packages[1.1].effort.low_days", -1, "0 or more"),
        ("work_packages[1.1].predecessors", ["1.1"], "not other work packages"),
        ("assumptions[1].text", "Any.", "no such fact"),
        ("work_packages[1.1].name", "New", "is not a field an edit may change"),
    ],
)
def test_apply_edits_refuses_what_it_cannot_apply(field: str, value: Any, problem: str) -> None:
    with pytest.raises(EditRefused, match=problem):
        apply_edits(_manifest(), [GateEdit(field=field, value=value)])


def test_apply_edits_refuses_a_cycle() -> None:
    manifest = _manifest()
    manifest.work_packages[1].predecessors = ["1.1"]
    with pytest.raises(EditRefused, match="cycle"):
        apply_edits(manifest, [GateEdit(field="work_packages[1.1].predecessors", value=["1.2"])])
