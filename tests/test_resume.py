"""Resumes (ADR-031) end to end: a run stopped by `bidwright stop`, a run killed inside the
`extract` fan-out, a run killed inside the `consolidate` fan-out with one cluster fallen back to
code, and a run stopped after `draft`. Each resumes to the outputs of a run that was never
interrupted, and no call answered before the interruption reaches the model again."""

import json
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

import pytest
from langgraph.runtime import RunControl

from bidwright import cli
from bidwright.graph import build
from bidwright.graph.build import RunResult, execute
from bidwright.llm.types import Request, Response
from bidwright.obs.ledger import read_ledger
from bidwright.preflight import HOME
from bidwright.schemas import RunManifest
from tests.kill_target import RUN_ID, ScriptedRun, kind, one_worker
from tests.node_fakes import DEV_RFP, RuleBackend, fake_backends

# The outputs a resumed run must share with an uninterrupted one; none names the run.
SAME = ("requirements.jsonl", "rejected.jsonl", "approach.json", "risks.jsonl", "coverage.json")


def _summary(run_dir: Path) -> dict[str, Any]:
    data = json.loads((run_dir / "solution_summary.json").read_text(encoding="utf-8"))
    data["summary"].pop("run_id")
    return data


def _same_outputs(resumed: Path, clean: Path) -> None:
    assert _summary(resumed) == _summary(clean)
    for name in SAME:
        assert (resumed / name).read_text("utf-8") == (clean / name).read_text("utf-8"), name


def _manifest(run_dir: Path) -> RunManifest:
    return RunManifest.model_validate_json((run_dir / "run_manifest.json").read_text("utf-8"))


def _run(outputs: Path, model: Any, run_id: str, **kwargs: Any) -> RunResult:
    return execute(
        docling_mode="replay",
        source=DEV_RFP,
        profile="free",
        outputs=outputs,
        backends=fake_backends(model),
        run_id=run_id,
        config=one_worker(),
        **kwargs,
    )


def _resume(run_dir: Path, model: Any, **kwargs: Any) -> RunResult:
    """A resume as `bidwright resume` makes it: from the manifest's `run_args`."""
    manifest = _manifest(run_dir)
    return execute(
        **cli.resume_arguments(manifest.run_args, run_dir),
        profile=manifest.profile,
        backends=fake_backends(model),
        resume=True,
        config=one_worker(),
        **kwargs,
    )


def _clean(tmp_path: Path, script: str) -> RunResult:
    """The same script, never interrupted. A cluster that falls back to code makes the run
    `DEGRADED`, as it would without any interruption."""
    clean = _run(tmp_path / "clean", ScriptedRun(script, block=False), "clean")
    assert clean.status in ("COMPLETED", "DEGRADED"), clean.reason
    return clean


# --- bidwright stop -----------------------------------------------------------------------------


class _BlocksOnTheFirstPack(RuleBackend):
    """Blocks on B01's first reading until the test lets it go."""

    def __init__(self) -> None:
        super().__init__()
        self.blocked = threading.Event()
        self.release = threading.Event()
        self.kinds: list[str] = []

    def call(self, request: Request) -> Response:
        self.kinds.append(kind(request))
        if kind(request) == "B01":
            self.blocked.set()
            self.release.wait(60)
        return super().call(request)


def test_stop_drains_between_nodes_and_resume_completes(tmp_path: Path) -> None:
    control = RunControl()
    model = _BlocksOnTheFirstPack()
    results: list[RunResult] = []
    worker = threading.Thread(
        target=lambda: results.append(
            _run(tmp_path / "out", model, "stopped", control=control, watch_interval_s=0.05)
        )
    )
    worker.start()
    try:
        assert model.blocked.wait(120), "the run never reached extract"
        assert cli.main(["stop", str(tmp_path / "out" / "stopped")]) == 0
        deadline = time.monotonic() + 10
        while not control.drain_requested and time.monotonic() < deadline:
            time.sleep(0.02)
        assert control.drain_requested, "the watcher read the stop request"
    finally:
        model.release.set()
        worker.join(120)
    [stopped] = results
    assert stopped.status == "STOPPED" and stopped.reason == "stopped by request"
    assert (stopped.run_dir / "checkpoints.sqlite").exists()
    resumed_model = _BlocksOnTheFirstPack()
    resumed_model.release.set()
    resumed = _resume(stopped.run_dir, resumed_model)
    assert resumed.status == "COMPLETED", resumed.reason
    assert not set(model.kinds) & set(resumed_model.kinds), "no answered call is asked again"


# --- killed inside a fan-out ------------------------------------------------------------------


def _killed(tmp_path: Path, script: str, state: Path) -> Path:
    """Run `tests/kill_target.py` in a subprocess and kill it on its blocking call."""
    marker = tmp_path / "blocked.txt"
    process = subprocess.Popen(
        [sys.executable, "-m", "tests.kill_target", str(tmp_path / "out"), str(state), script,
         str(marker)],
        cwd=HOME,
    )  # fmt: skip
    try:
        deadline = time.monotonic() + 300
        while not marker.exists():
            assert process.poll() is None, f"the run ended before it blocked: {process.returncode}"
            assert time.monotonic() < deadline, "the run never blocked"
            time.sleep(0.1)
    finally:
        process.kill()
        process.wait(60)
    run_dir = tmp_path / "out" / RUN_ID
    assert _manifest(run_dir).status == "RUNNING", "a kill writes no status"
    return run_dir


def test_resume_after_a_kill_spends_nothing_twice(
    tmp_path: Path, _isolated_quota_and_cache: tuple[Path, Path]
) -> None:
    clean = _clean(tmp_path, "extract")
    run_dir = _killed(tmp_path, "extract", _isolated_quota_and_cache[0].parent)
    before = read_ledger(run_dir / "ledger.jsonl")
    assert [e.node for e in before] == ["triage", "extract"], "triage and B01's first reading"
    assert len(list((run_dir / "journal").glob("*.json"))) == 2, "both answers journaled"
    first = before[1]
    model = ScriptedRun("extract", block=False)
    resumed = _resume(run_dir, model)
    assert resumed.status == "COMPLETED", resumed.reason
    assert "B01" not in model.kinds, "the backend receives no call under B01's first key"
    assert "B01-repair" in model.kinds, "the call that never finished is asked again"
    again = [
        e for e in read_ledger(run_dir / "ledger.jsonl")[2:] if e.input_hash == first.input_hash
    ]
    assert [(e.replayed, e.cost_usd) for e in again] == [(True, 0.0)]
    assert clean.status == "COMPLETED"
    _same_outputs(run_dir, clean.run_dir)


def test_a_resume_inside_the_consolidate_fan_out_matches_an_uninterrupted_run(
    tmp_path: Path, _isolated_quota_and_cache: tuple[Path, Path]
) -> None:
    """RG-002 fell back to code and RG-003 was killed mid-call; the resume asks RG-003 again,
    and the run's groups match a run that was never interrupted."""
    clean = _clean(tmp_path, "consolidate")
    assert (
        clean.status == "DEGRADED"
        and clean.reason == "consolidate: 1 clusters fell back to code groups"
    )
    run_dir = _killed(tmp_path, "consolidate", _isolated_quota_and_cache[0].parent)
    model = ScriptedRun("consolidate", block=False)
    resumed = _resume(run_dir, model)
    assert (resumed.status, resumed.reason) == (clean.status, clean.reason)
    assert "RG-003" in model.kinds and "B01" not in model.kinds
    _same_outputs(run_dir, clean.run_dir)
    groups = "requirement_groups.jsonl"
    assert (run_dir / groups).read_text("utf-8") == (clean.run_dir / groups).read_text("utf-8")


# --- stopped after draft ------------------------------------------------------------------------


class _StopsDuringDraft(RuleBackend):
    def __init__(self, control: RunControl) -> None:
        super().__init__()
        self.control = control

    def call(self, request: Request) -> Response:
        if request.schema_name == "DraftResult":
            self.control.request_drain("stop requested")
        return super().call(request)


def test_a_resume_at_render_after_a_stop_following_draft(tmp_path: Path) -> None:
    clean = _run(tmp_path / "clean", RuleBackend(), "clean")
    control = RunControl()
    stopped = _run(tmp_path / "out", _StopsDuringDraft(control), "drafted", control=control)
    assert stopped.status == "STOPPED", stopped.reason
    assert not (stopped.run_dir / "solution_summary.json").exists(), "render has not run"
    model = RuleBackend()
    resumed = _resume(stopped.run_dir, model)
    assert resumed.status == "COMPLETED", resumed.reason
    assert model.requests == [], "render makes no call, and every draft was done"
    _same_outputs(stopped.run_dir, clean.run_dir)


# --- a package stopped after guard ----------------------------------------------------------


@pytest.mark.replay
def test_the_hero_package_stopped_after_guard_rebuilds_its_documents(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A stop while `guard` runs: the resume's `ingest` finds the package's documents again
    from the folder, where a run that never stopped had them from `guard`."""
    control = RunControl()
    guard = build.run_guard

    def guard_then_stop(*args: Any, **kwargs: Any) -> Any:
        result = guard(*args, **kwargs)
        control.request_drain("stop requested")
        return result

    monkeypatch.setattr(build, "run_guard", guard_then_stop)
    hero = HOME / "inputs" / "hero"
    stopped = execute(
        docling_mode="replay",
        source=hero,
        profile="free",
        outputs=tmp_path / "out",
        backends=fake_backends(RuleBackend()),
        run_id="hero",
        until="verify",
        control=control,
    )
    assert stopped.status == "STOPPED", stopped.reason
    assert (stopped.run_dir / "guard_report.json").exists()
    assert not (stopped.run_dir / "passages.jsonl").exists(), "stopped before ingest"
    monkeypatch.setattr(build, "run_guard", guard)
    resumed = _resume(stopped.run_dir, RuleBackend())
    assert resumed.status == "COMPLETED", resumed.reason
    register = json.loads((stopped.run_dir / "control_register.json").read_text("utf-8"))
    files = {document["file"] for document in register["documents"]}
    assert len(files) > 1, "every document of the package, not the folder itself"
