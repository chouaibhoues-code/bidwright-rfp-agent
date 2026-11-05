"""The run supervisor (ADR-031): the run lock, the refusals of a resume, the budget across
parts, and the record of every status in the manifest and `events.jsonl`."""

import json
import math
from pathlib import Path
from typing import Any

import pytest
from langgraph.runtime import RunControl

from bidwright import cli
from bidwright.config import Config, RunLimits, load_config
from bidwright.graph.build import RunResult, execute
from bidwright.harness import supervisor
from bidwright.harness.budget import RunBudget
from bidwright.harness.recovery import read_dead_letters
from bidwright.harness.supervisor import RunBusy, RunLock, environment
from bidwright.llm.simulator import ProviderSimulator
from bidwright.llm.types import Backend, Request, Response
from bidwright.obs.events import read_events
from bidwright.obs.ledger import read_ledger
from bidwright.preflight import Refused
from bidwright.purge import RunInUse, purge_run
from bidwright.schemas import BudgetSnapshot, RunManifest
from tests.node_fakes import DEV_RFP, RuleBackend


def _drained() -> RunControl:
    """A control drained before the run starts: the run stops after its first step."""
    control = RunControl()
    control.request_drain("stop requested")
    return control


def _run(tmp_path: Path, model: Backend | None = None, **kwargs: Any) -> RunResult:
    arguments: dict[str, Any] = {
        "docling_mode": "replay",
        "source": DEV_RFP,
        "profile": "free",
        "outputs": tmp_path / "out",
        "backends": {"gemini": model or RuleBackend()},
        "run_id": "run",
        **kwargs,
    }
    return execute(**arguments)


def _manifest(run_dir: Path) -> RunManifest:
    return RunManifest.model_validate_json((run_dir / "run_manifest.json").read_text("utf-8"))


def _edit(run_dir: Path, **changes: Any) -> None:
    data = json.loads((run_dir / "run_manifest.json").read_text(encoding="utf-8"))
    for key, value in changes.items():
        if key == "run_args":
            data["run_args"] = {**data["run_args"], **value}
        else:
            data[key] = value
    (run_dir / "run_manifest.json").write_text(json.dumps(data), encoding="utf-8")


# --- the lock ---------------------------------------------------------------------------------


def test_two_handles_on_the_run_lock_exclude_each_other(tmp_path: Path) -> None:
    first, second = RunLock(tmp_path / "run.lock"), RunLock(tmp_path / "run.lock")
    assert first.acquire(0)
    assert not second.acquire(0.2), "held, even within one process"
    first.release()
    assert second.acquire(0)
    second.release()


def test_a_running_run_cannot_be_resumed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    stopped = _run(tmp_path, control=_drained())
    assert stopped.status == "STOPPED"
    before = (stopped.run_dir / "run_manifest.json").read_text(encoding="utf-8")
    monkeypatch.setattr(supervisor, "LOCK_WAIT_S", 0.3)
    holder = RunLock(stopped.run_dir / "control" / "run.lock")
    assert holder.acquire(0)
    try:
        with pytest.raises(RunBusy, match="still running; stop it first"):
            _run(tmp_path, resume=True)
    finally:
        holder.release()
    assert (stopped.run_dir / "run_manifest.json").read_text(encoding="utf-8") == before


def test_purge_refuses_a_locked_run_and_one_from_another_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_dir = _run(tmp_path, control=_drained()).run_dir
    monkeypatch.setattr(supervisor, "LOCK_WAIT_S", 0.3)
    holder = RunLock(run_dir / "control" / "run.lock")
    assert holder.acquire(0)
    try:
        with pytest.raises(RunInUse, match="still running"):
            purge_run(run_dir, tmp_path / "cache")
    finally:
        holder.release()
    _edit(run_dir, run_args={"environment": "container-elsewhere"})
    with pytest.raises(RunInUse, match="started in container-elsewhere"):
        purge_run(run_dir, tmp_path / "cache")
    assert run_dir.is_dir()


# --- refusals ---------------------------------------------------------------------------------


def test_a_finished_run_is_not_resumed(tmp_path: Path) -> None:
    done = _run(tmp_path)
    assert done.status == "COMPLETED"
    with pytest.raises(Refused, match="ended COMPLETED; a finished run is not resumed"):
        _run(tmp_path, resume=True)
    assert _manifest(done.run_dir).status == "COMPLETED"


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"run_args": {}}, "predates v0.2"),
        ({"run_args": {"mode": "replay"}}, "replay mode is not resumed"),
        ({"run_args": {"environment": "container-elsewhere"}}, "started in container-elsewhere"),
        ({"prompt_hashes": {"risk": "sha256:" + "0" * 64}}, "the prompts risk"),
        ({"input_hashes": {"dev_rfp.pdf": "sha256:" + "0" * 64}}, "input files dev_rfp.pdf"),
    ],
)
def test_a_resume_is_refused_and_leaves_the_run_as_it_was(
    tmp_path: Path, changes: dict[str, Any], message: str
) -> None:
    run_dir = _run(tmp_path, control=_drained()).run_dir
    if changes.get("run_args") == {}:
        data = json.loads((run_dir / "run_manifest.json").read_text(encoding="utf-8"))
        data["run_args"] = {}
        (run_dir / "run_manifest.json").write_text(json.dumps(data), encoding="utf-8")
    elif "prompt_hashes" in changes:
        stored = _manifest(run_dir).prompt_hashes
        _edit(run_dir, prompt_hashes={**stored, **changes["prompt_hashes"]})
    else:
        _edit(run_dir, **changes)
    before = (run_dir / "run_manifest.json").read_text(encoding="utf-8")
    events = (run_dir / "events.jsonl").read_text(encoding="utf-8")
    with pytest.raises(Refused, match=message):
        _run(tmp_path, resume=True)
    assert (run_dir / "run_manifest.json").read_text(encoding="utf-8") == before
    assert (run_dir / "events.jsonl").read_text(encoding="utf-8") == events


def test_a_resume_without_run_args_is_refused_at_the_command_line(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    run_dir = _run(tmp_path, control=_drained()).run_dir
    data = json.loads((run_dir / "run_manifest.json").read_text(encoding="utf-8"))
    data["run_args"] = {}
    (run_dir / "run_manifest.json").write_text(json.dumps(data), encoding="utf-8")
    assert cli.main(["resume", str(run_dir)]) == 2
    assert "this run predates v0.2; start it again" in capsys.readouterr().err


def test_a_raise_applies_to_a_resume_only(tmp_path: Path) -> None:
    with pytest.raises(Refused, match="applies to a resume"):
        _run(tmp_path, raise_budget=50)


# --- statuses ---------------------------------------------------------------------------------


def test_every_transition_is_in_the_history_and_the_events(tmp_path: Path) -> None:
    run_dir = _run(tmp_path, control=_drained()).run_dir
    assert not (run_dir / "control" / "stop.request").exists()
    (run_dir / "control" / "stop.request").write_text("left from the last part\n", "utf-8")
    resumed = _run(tmp_path, resume=True)
    assert resumed.status == "COMPLETED", resumed.reason
    assert not (run_dir / "control" / "stop.request").exists(), "removed when the run resumes"
    manifest = _manifest(run_dir)
    history = [(change.status, change.reason) for change in manifest.status_history]
    assert history == [
        ("RUNNING", "started"),
        ("STOPPED", "stopped by request"),
        ("RUNNING", "resumed, part 1"),
        ("COMPLETED", None),
    ]
    rows = [(e.part, e.detail) for e in read_events(run_dir / "events.jsonl") if e.kind == "status"]
    assert rows == [
        (0, "RUNNING: started"),
        (0, "STOPPED: stopped by request"),
        (1, "RUNNING: resumed, part 1"),
        (1, "COMPLETED"),
    ]
    assert manifest.pid is not None and manifest.ended is not None
    assert manifest.run_args["environment"] == environment()
    assert manifest.run_args["source"] == "inputs/dev/dev_rfp.pdf"


def test_a_run_killed_before_its_first_checkpoint_starts_again(tmp_path: Path) -> None:
    """Killed with its manifest written and no checkpoint, the run starts from the beginning
    under its own id, and its journal answers every call it had made."""
    done = _run(tmp_path)
    (done.run_dir / "checkpoints.sqlite").unlink()
    _edit(done.run_dir, status="RUNNING")
    model = RuleBackend()
    again = _run(tmp_path, model, resume=True)
    assert again.status == "COMPLETED" and again.run_id == "run"
    assert model.requests == [], "the journal answered every call"


# --- the budget across parts --------------------------------------------------------------------


def test_a_snapshot_restores_counts_and_raises() -> None:
    limits = RunLimits(requests=10, tokens=1000, active_minutes=3)
    budget = RunBudget(limits)
    budget.raise_by(50)
    budget.raise_by(25)
    assert budget.limits == RunLimits(requests=18, tokens=1750, active_minutes=6)
    budget.requests, budget.tokens = 4, 300
    snapshot = budget.snapshot()
    assert snapshot == BudgetSnapshot(attempts=4, tokens=300, active_seconds=0, raise_percent=75)
    restored = RunBudget(limits)
    restored.restore(snapshot)
    assert restored.limits == budget.limits and restored.requests == 4
    with pytest.raises(ValueError, match="positive"):
        restored.raise_by(0)


class _DrainOnFirstCall(RuleBackend):
    """Asks the run to stop on its first call; the step in progress still finishes."""

    def __init__(self, control: RunControl) -> None:
        super().__init__()
        self.control = control

    def call(self, request: Request) -> Response:
        self.control.request_drain("stop requested")
        return super().call(request)


def _tight(config: Config, requests: int) -> Config:
    runs = {
        tier: {
            profile: (
                limits.model_copy(update={"requests": requests})
                if (tier, profile) == ("dev", "free")
                else limits
            )
            for profile, limits in by_profile.items()
        }
        for tier, by_profile in config.limits.runs.items()
    }
    return config.model_copy(update={"limits": config.limits.model_copy(update={"runs": runs})})


def test_a_raise_lets_a_run_over_budget_finish_and_holds_across_resumes(tmp_path: Path) -> None:
    """A limit of two thirds of the run's calls stops it; one raise of 50% covers the rest,
    and still holds on the resume after the next one."""
    counted = RuleBackend()
    assert _run(tmp_path / "count", counted).status == "COMPLETED"
    limit = math.ceil(len(counted.requests) * 2 / 3)
    config = _tight(load_config(), limit)
    over = _run(tmp_path, config=config)
    assert over.status == "BUDGET_EXCEEDED", over.reason
    control = RunControl()
    first = _run(
        tmp_path,
        _DrainOnFirstCall(control),
        config=config,
        resume=True,
        raise_budget=50,
        control=control,
    )
    assert first.status == "STOPPED", first.reason
    second = _run(tmp_path, config=config, resume=True)
    assert second.status == "COMPLETED", "the raise of the first resume still holds"
    manifest = _manifest(second.run_dir)
    assert [o for o in manifest.overrides if o.startswith("raise-budget")] == [
        "raise-budget 50% at part 1"
    ]
    stored = json.loads((second.run_dir / "control" / "budget.json").read_text("utf-8"))
    assert stored["raise_percent"] == 50 and stored["attempts"] <= limit + math.ceil(limit / 2)


def test_a_paused_free_run_resumes_on_paid_and_records_the_switch(tmp_path: Path) -> None:
    spent = ProviderSimulator(RuleBackend(), [{"call": 1, "fault": "quota_exhausted"}])
    paused = _run(tmp_path, spent, fallback=False)
    assert paused.status == "QUOTA_PAUSED", paused.reason
    assert paused.reason is not None and "bidwright resume" in paused.reason
    resumed = _run(tmp_path, profile="paid", resume=True, fallback=False)
    assert resumed.status == "COMPLETED", resumed.reason
    manifest = _manifest(resumed.run_dir)
    assert manifest.profile == "paid" and manifest.run_args["profile"] == "paid"
    assert "profile free -> paid at part 1" in manifest.overrides


def test_paid_resumes_only_a_free_run_that_paused_on_its_quota(tmp_path: Path) -> None:
    _run(tmp_path, control=_drained())
    with pytest.raises(Refused, match="QUOTA_PAUSED; this one is STOPPED on free"):
        _run(tmp_path, profile="paid", resume=True)


def test_cut_lines_are_removed_from_every_line_file_on_resume(tmp_path: Path) -> None:
    """A kill can cut the last line of any of the four line files; a resume cuts each before
    it appends, so no new line lands on a cut one, and records each cut."""
    run_dir = _run(tmp_path, control=_drained()).run_dir
    for name in ("ledger.jsonl", "events.jsonl", "tool_calls.jsonl", "dead_letter.jsonl"):
        with (run_dir / name).open("a", encoding="utf-8") as stream:
            stream.write('{"run_id": "run", "node": "tri')
    resumed = _run(tmp_path, resume=True)
    assert resumed.status == "COMPLETED", resumed.reason
    recovery = [e for e in read_events(run_dir / "events.jsonl") if e.kind == "recovery"]
    assert [(e.part, e.detail.split(":")[0]) for e in recovery] == [
        (1, "events_cut"),
        (1, "ledger_cut"),
        (1, "tool_calls_cut"),
        (1, "dead_letter_cut"),
    ]
    manifest = _manifest(run_dir)
    assert manifest.totals.requests == len(read_ledger(run_dir / "ledger.jsonl")) > 0
    assert read_dead_letters(run_dir / "dead_letter.jsonl") == []
    for line in (run_dir / "tool_calls.jsonl").read_text(encoding="utf-8").splitlines():
        json.loads(line)


class _Interrupted(RuleBackend):
    """Ctrl+C during the first call."""

    def call(self, request: Request) -> Response:
        raise KeyboardInterrupt


def test_ctrl_c_stops_the_run_and_a_resume_completes_it(tmp_path: Path) -> None:
    with pytest.raises(KeyboardInterrupt):
        _run(tmp_path, _Interrupted())
    manifest = _manifest(tmp_path / "out" / "run")
    assert (manifest.status, manifest.status_reason) == ("STOPPED", "interrupted by the operator")
    resumed = _run(tmp_path, resume=True)
    assert resumed.status == "COMPLETED", resumed.reason


def test_a_run_waiting_at_its_gate_resumes_only_through_approve(tmp_path: Path) -> None:
    """Iteration 3, step 10: WAITING_HUMAN leaves by bidwright approve, and approve continues
    only a run that waits."""
    run_dir = _run(tmp_path, control=_drained()).run_dir
    _edit(run_dir, status="WAITING_HUMAN")
    with pytest.raises(Refused, match="continue it with bidwright approve run --role ROLE"):
        _run(tmp_path, resume=True)
    stored, new = _manifest(run_dir), _manifest(run_dir)
    assert supervisor.refusal(stored, new, environment(), approving=True) is None
    _edit(run_dir, status="STOPPED")
    stopped = _manifest(run_dir)
    assert "waits at no gate" in (
        supervisor.refusal(stopped, stopped, environment(), approving=True) or ""
    )
