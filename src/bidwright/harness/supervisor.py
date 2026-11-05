"""The run supervisor (Iteration 2, ADR-031): the run lock, the run's statuses, stop and resume.

`RunSupervisor` is a context manager around one part of a run: its first start, or a resume.
On entry it takes the run lock, `control/run.lock`, without blocking, retrying for up to five
seconds, since Windows can release a dead process's lock after a short delay; a lock it cannot
take means the run is still running, and it raises `RunBusy`. The operating system releases the
lock when the process ends, however it ends, so a `RUNNING` manifest whose lock is free belongs
to a killed run, which may be resumed. The process id is recorded for information only: on
Windows, `os.kill` ends the process it tests, and ids are reused.

A resume rereads the stored manifest under the lock and refuses a finished run, one waiting at
its solution gate unless `bidwright approve` resumes it (Iteration 3), one that
predates `v0.2` (no `run_args`), one run in the client's `record` or `replay` mode, one started
in another environment, a profile change other than `free` to `paid` after `QUOTA_PAUSED`,
prompts whose hashes changed, since their journal keys would no longer match, and input files
whose hashes changed, since its checkpoints hold the old passages. A refused resume
leaves the run as it was. Otherwise the two manifests are merged: `started` and
`status_history` are kept and `overrides` appended, the budget's counts and raises come back
from `control/budget.json`, and a stop request left from the last part is removed.

The supervisor is the manifest's only writer. `transition` and `finish` record each status in
`status_history` and in `events.jsonl`, and write the manifest and `control/budget.json`
through `fileio.write_atomic`. A watcher thread checks for `control/stop.request` every
`watch_interval_s` seconds, drains the run's `RunControl` when it finds one, and writes the
budget's counts, so a kill loses at most that much active time.
"""

import json
import os
import platform
import sys
import threading
import time
from pathlib import Path
from types import TracebackType
from typing import IO

from langgraph.runtime import RunControl

from bidwright.fileio import repair_lines, write_atomic
from bidwright.harness.budget import RunBudget
from bidwright.obs.events import EventRecorder, utc_now
from bidwright.preflight import Refused
from bidwright.schemas import (
    BudgetSnapshot,
    ResearchRecord,
    ResearchSummary,
    RunManifest,
    RunStatus,
    RunTotals,
    StatusChange,
)

MANIFEST = "run_manifest.json"
EVENTS = "events.jsonl"
CONTROL = "control"
LOCK = "run.lock"
STOP_REQUEST = "stop.request"
BUDGET = "budget.json"
RESEARCH = "research.json"  # graph/discover.py writes it; the manifest summarizes it
LOCK_WAIT_S = 5.0
TERMINAL = frozenset({"COMPLETED", "DEGRADED", "POLICY_BLOCKED", "UNRECOVERABLE_FAULT"})
STOP_REASON = "stopped by request"
DRAIN_REASON = "stop requested"


def environment() -> str:
    """Where a run runs: `container` when `BIDWRIGHT_ENV` says so, as the Dockerfile sets it,
    and `host:<machine name>` otherwise. Locks taken on the host and in a container do not see
    each other on the bind-mounted `outputs/`, so a run is resumed where it started."""
    if os.environ.get("BIDWRIGHT_ENV") == "container":
        return "container"
    return f"host:{platform.node()}"


class RunBusy(Refused):
    """The run's lock is held, so the run is still running."""


class RunLock:
    """An exclusive lock on one file, taken without blocking and held until `release` or until
    the process ends. Two handles conflict even in one process: `fcntl.flock` locks an open
    file, and `msvcrt.locking` a handle's byte range."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._stream: IO[bytes] | None = None

    def acquire(self, wait_s: float = LOCK_WAIT_S, interval_s: float = 0.1) -> bool:
        """Take the lock, retrying for up to `wait_s` seconds; False if it stays held."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + wait_s
        while True:
            stream = self.path.open("a+b")
            try:
                _lock(stream)
            except OSError:
                stream.close()
                if time.monotonic() >= deadline:
                    return False
                time.sleep(interval_s)
                continue
            self._stream = stream
            return True

    def release(self) -> None:
        stream, self._stream = self._stream, None
        if stream is None:
            return
        try:
            _unlock(stream)
        finally:
            stream.close()


if sys.platform == "win32":
    import msvcrt

    def _lock(stream: IO[bytes]) -> None:
        stream.seek(0)
        msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)

    def _unlock(stream: IO[bytes]) -> None:
        stream.seek(0)
        msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)

else:
    import fcntl

    def _lock(stream: IO[bytes]) -> None:
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

    def _unlock(stream: IO[bytes]) -> None:
        fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def lock_held(run_dir: Path, wait_s: float | None = None) -> bool:
    """Whether a live process holds the run's lock, as `bidwright purge` asks. The wait is
    `LOCK_WAIT_S` unless given."""
    lock = RunLock(run_dir / CONTROL / LOCK)
    if not lock.path.exists():
        return False
    if lock.acquire(LOCK_WAIT_S if wait_s is None else wait_s):
        lock.release()
        return False
    return True


def read_manifest(run_dir: Path) -> RunManifest:
    path = run_dir / MANIFEST
    if not path.is_file():
        raise Refused(f"{run_dir} holds no {MANIFEST}, so there is no run to resume")
    return RunManifest.model_validate_json(path.read_text(encoding="utf-8"))


def refusal(
    stored: RunManifest, new: RunManifest, where: str, *, approving: bool = False
) -> str | None:
    """Why `new`, a resume, may not continue `stored`, or None. A run waiting at its solution
    gate continues only with `bidwright approve` (`approving`), and `approve` only such a run
    (Iteration 3, ADR-046)."""
    if stored.status in TERMINAL:
        return f"the run ended {stored.status}; a finished run is not resumed"
    if stored.status == "WAITING_HUMAN" and not approving:
        return (
            "the run waits at its solution gate (review/solution_gate.md); continue it with"
            f" bidwright approve {stored.run_id} --role ROLE"
        )
    if approving and stored.status != "WAITING_HUMAN":
        return (
            f"the run is {stored.status} and waits at no gate; bidwright approve has nothing to"
            " decide"
        )
    if not stored.run_args:
        return "this run predates v0.2; start it again"
    mode = stored.run_args.get("mode")
    if mode != "live":
        return f"a run in {mode} mode is not resumed; {mode} it again"
    started_in = stored.run_args.get("environment")
    if started_in != where:
        return f"the run started in {started_in}, and this is {where}; resume it there"
    if new.profile != stored.profile and not (
        (stored.profile, new.profile) == ("free", "paid") and stored.status == "QUOTA_PAUSED"
    ):
        return (
            f"--profile {new.profile} resumes only a run of free that is QUOTA_PAUSED; this one"
            f" is {stored.status} on {stored.profile}"
        )
    names = sorted(set(stored.prompt_hashes) | set(new.prompt_hashes))
    changed = [n for n in names if stored.prompt_hashes.get(n) != new.prompt_hashes.get(n)]
    if changed:
        return (
            f"the prompts {', '.join(changed)} changed since the run started, so the journal's"
            " answers no longer match their calls; start the run again"
        )
    if stored.input_hashes and new.input_hashes != stored.input_hashes:
        files = sorted(set(stored.input_hashes) | set(new.input_hashes))
        moved = [f for f in files if stored.input_hashes.get(f) != new.input_hashes.get(f)]
        return (
            f"the input files {', '.join(moved)} changed since the run started, so its"
            " checkpoints hold passages of another version; start a new run"
        )
    return None


def _merged(
    stored: RunManifest, new: RunManifest, part: int, raise_percent: int | None
) -> RunManifest:
    overrides = list(stored.overrides)
    overrides += [o for o in new.overrides if o not in overrides]
    if new.profile != stored.profile:
        overrides.append(f"profile {stored.profile} -> {new.profile} at part {part}")
    if raise_percent:
        overrides.append(f"raise-budget {raise_percent}% at part {part}")
    return new.model_copy(
        update={
            "started": stored.started,
            "status_history": list(stored.status_history),
            "overrides": overrides,
        }
    )


def research_summary(run_dir: Path) -> ResearchSummary | None:
    """The manifest's research block, from the run's `research.json`, or None without one."""
    path = run_dir / RESEARCH
    if not path.exists():
        return None
    try:
        record = ResearchRecord.model_validate_json(path.read_text(encoding="utf-8"))
    except ValueError:
        return None
    return ResearchSummary(
        mode=record.mode,
        pack_id=record.pack_id,
        pack_sha256=record.pack_sha256,
        jobs=len(record.jobs),
        questions=len(record.answers),
        notes=record.notes,
    )


class RunSupervisor:
    def __init__(
        self,
        run_dir: Path,
        manifest: RunManifest,
        *,
        control: RunControl,
        budget: RunBudget,
        resume: bool,
        raise_budget: int | None = None,
        watch_interval_s: float = 1.0,
        lock_wait_s: float | None = None,
        approving: bool = False,
    ) -> None:
        self.run_dir = run_dir
        self.manifest = manifest
        self.control = control
        self.budget = budget
        self.resume = resume
        self.raise_budget = raise_budget
        self.approving = approving  # a resume by bidwright approve (Iteration 3)
        self.watch_interval_s = watch_interval_s
        self.lock_wait_s = LOCK_WAIT_S if lock_wait_s is None else lock_wait_s
        self.part = 0
        self.events = EventRecorder(run_dir / EVENTS)
        self._lock = RunLock(run_dir / CONTROL / LOCK)
        self._writing = threading.RLock()
        self._stopped = threading.Event()
        self._watcher: threading.Thread | None = None
        self._finished = False

    @property
    def stop_request(self) -> Path:
        return self.run_dir / CONTROL / STOP_REQUEST

    def __enter__(self) -> "RunSupervisor":
        if not self._lock.acquire(self.lock_wait_s):
            raise RunBusy(f"the run {self.run_dir.name} is still running; stop it first")
        try:
            self._open()
        except BaseException:
            self._lock.release()
            raise
        self._watcher = threading.Thread(
            target=self._watch, name=f"watch-{self.run_dir.name}", daemon=True
        )
        self._watcher.start()
        return self

    def _open(self) -> None:
        reason = "started"
        if self.resume:
            stored = read_manifest(self.run_dir)
            refused = refusal(stored, self.manifest, environment(), approving=self.approving)
            if refused:
                raise Refused(refused)
            self.part = sum(1 for change in stored.status_history if change.status == "RUNNING")
            self.manifest = _merged(stored, self.manifest, self.part, self.raise_budget)
            reason = f"resumed, part {self.part}"
            if stored.commit != self.manifest.commit:
                reason += f"; commit {stored.commit} -> {self.manifest.commit}"
            snapshot = self.run_dir / CONTROL / BUDGET
            if snapshot.is_file():
                text = snapshot.read_text(encoding="utf-8")
                self.budget.restore(BudgetSnapshot.model_validate_json(text))
            if self.raise_budget:
                self.budget.raise_by(self.raise_budget)
            # Before this part's first event, so it never lands on the end of a cut line.
            cut = repair_lines(self.events.path)
        else:
            self.events.create()
            cut = ""
        self.events.part = self.part
        self.stop_request.unlink(missing_ok=True)
        self.manifest = self.manifest.model_copy(update={"pid": os.getpid(), "ended": None})
        self.transition("RUNNING", reason)
        if cut:
            detail = f"events_cut: {len(cut)} characters of an unfinished last line removed"
            self.events.record("recovery", None, detail)

    def transition(self, status: RunStatus, reason: str | None = None) -> None:
        """Record a status: in the manifest's history, in the events log, and on disk."""
        with self._writing:
            change = StatusChange(at=utc_now(), status=status, reason=reason)
            self.manifest = self.manifest.model_copy(
                update={
                    "status": status,
                    "status_reason": reason,
                    "status_history": [*self.manifest.status_history, change],
                }
            )
            self.events.record("status", None, f"{status}: {reason}" if reason else status)
            write_atomic(self.run_dir / MANIFEST, self.manifest.model_dump_json(indent=1) + "\n")
            self._write_budget()

    def finish(
        self,
        status: RunStatus,
        reason: str | None,
        totals: RunTotals,
        models_used: dict[str, list[str]],
        research: ResearchSummary | None = None,
    ) -> None:
        """The part's last status, with the run's totals over every part, and the research
        block from `research.json` when the run has one."""
        if research is None:
            research = research_summary(self.run_dir)
        with self._writing:
            self.manifest = self.manifest.model_copy(
                update={
                    "ended": utc_now(),
                    "totals": totals,
                    "models_used": models_used,
                    "research": research,
                }
            )
            self.transition(status, reason)
            self._finished = True

    def _write_budget(self) -> None:
        with self._writing:
            body = json.dumps(self.budget.snapshot().model_dump()) + "\n"
            write_atomic(self.run_dir / CONTROL / BUDGET, body)

    def _watch(self) -> None:
        while not self._stopped.wait(self.watch_interval_s):
            if self.stop_request.exists() and not self.control.drain_requested:
                self.control.request_drain(DRAIN_REASON)
            try:
                self._write_budget()
            except OSError:
                pass  # the next tick, or the next transition, writes it again

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self._stopped.set()
        if self._watcher is not None:
            self._watcher.join(timeout=10)
        try:
            if (
                not self._finished
                and exc_type is not None
                and issubclass(exc_type, KeyboardInterrupt)
            ):
                self.transition("STOPPED", "interrupted by the operator")
            elif not self._finished:
                # The caller never finished the part: a fault, so no live process's exit ever
                # leaves a manifest that reads RUNNING.
                detail = f"unexpected {exc_type.__name__}: {exc}" if exc_type else None
                self.transition("UNRECOVERABLE_FAULT", detail or "the run ended before it finished")
        finally:
            self._lock.release()


__all__ = [
    "CONTROL",
    "DRAIN_REASON",
    "LOCK_WAIT_S",
    "MANIFEST",
    "STOP_REASON",
    "STOP_REQUEST",
    "TERMINAL",
    "RunBusy",
    "RunLock",
    "RunSupervisor",
    "environment",
    "lock_held",
    "read_manifest",
    "refusal",
    "research_summary",
]
