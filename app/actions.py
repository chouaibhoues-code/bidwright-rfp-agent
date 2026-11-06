"""The CLI commands the pages run (ADR-053). A page writes no file: it builds an argument list
and runs `bidwright` or `bidwright-eval` as a subprocess, never through a shell, with every
value from a fixed list or a checked id. Long commands (a run, a resume, the demo) run as a
`Job` the session keeps, which the Run page's monitor polls; short ones run and return their
output.
"""

import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from bidwright.preflight import HOME

PROFILES = ("free", "paid", "local")
RESEARCH = ("pack", "off", "live")
SOLUTIONS = ("manifest", "assess", "decide", "fixed", "oneshot")
RISK_MODES = ("agent", "fixed", "oneshot")
UNTIL = ("render", "solution_gate", "capability_map", "brief", "consolidate", "coverage", "verify")
INPUT_SUFFIXES = (".pdf", ".docx", ".xlsx")


def bidwright(*args: str) -> list[str]:
    """The `bidwright` command, through this interpreter, so the venv's package runs."""
    return [sys.executable, "-m", "bidwright.cli", *args]


def bidwright_eval(*args: str) -> list[str]:
    return [sys.executable, "-m", "evals.cli", *args]


def inputs(root: Path | None = None) -> list[str]:
    """The RFP files and package folders under `inputs/`, as paths relative to the repository:
    a folder holding more than one document is a package, and its files are not listed."""
    base = root or HOME / "inputs"
    if not base.is_dir():
        return []
    found: list[str] = []
    for folder in sorted(p for p in base.rglob("*") if p.is_dir()):
        files = [p for p in folder.iterdir() if p.suffix.lower() in INPUT_SUFFIXES]
        if len(files) > 1:
            found.append(folder.relative_to(HOME).as_posix())
        elif len(files) == 1:
            found.append(files[0].relative_to(HOME).as_posix())
    return found


def new_run_id(source: str, profile: str, now: datetime | None = None) -> str:
    """A run id for a run the UI starts: its time, the input's name and the profile."""
    stamp = (now or datetime.now(UTC)).strftime("%Y%m%dT%H%M%SZ")
    stem = Path(source).stem.lower()
    slug = "".join(c if c.isalnum() else "-" for c in stem).strip("-") or "input"
    return f"{stamp}-{slug}-{profile}-ui"


@dataclass
class LaunchRequest:
    source: str
    profile: str = "free"
    research: str = "pack"
    solution: str = "manifest"
    risk_mode: str = "agent"
    reflect: bool = False
    until: str = "render"
    auto_select: bool = False
    run_id: str = ""

    def command(self) -> list[str]:
        """The `bidwright run` argument list; refused values raise ValueError."""
        checks = (
            ("profile", self.profile, PROFILES),
            ("research", self.research, RESEARCH),
            ("solution", self.solution, SOLUTIONS),
            ("risk mode", self.risk_mode, RISK_MODES),
            ("until", self.until, UNTIL),
        )
        for name, value, allowed in checks:
            if value not in allowed:
                raise ValueError(f"{name} takes one of {', '.join(allowed)}, not {value!r}")
        if self.source not in inputs():
            raise ValueError(f"{self.source!r} is not an RFP file or package under inputs/")
        cmd = bidwright(
            "run",
            self.source,
            "--profile",
            self.profile,
            "--research",
            self.research,
            "--solution",
            self.solution,
            "--risk-mode",
            self.risk_mode,
            "--until",
            self.until,
            "--reflect" if self.reflect else "--no-reflect",
        )
        if self.auto_select:
            cmd.append("--auto-select")
        if self.run_id:
            cmd += ["--run-id", self.run_id]
        return cmd


@dataclass
class Job:
    """A long command the session started: its process, and its output once it ends."""

    label: str
    command: list[str]
    run_id: str | None
    process: subprocess.Popen[str]
    started: float = field(default_factory=time.time)
    output: str | None = None

    def poll(self) -> int | None:
        code = self.process.poll()
        if code is not None and self.output is None:
            out, _ = self.process.communicate()
            self.output = out or ""
        return code

    @property
    def elapsed(self) -> float:
        return time.time() - self.started


def start(label: str, command: list[str], run_id: str | None = None) -> Job:
    """Start a long command in its own process group, so it outlives a page rerun."""
    flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) if os.name == "nt" else 0
    process = subprocess.Popen(  # noqa: S603 - an argument list, never a shell
        command,
        cwd=HOME,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        text=True,
        creationflags=flags,
        start_new_session=os.name != "nt",
    )
    return Job(label, command, run_id, process)


def run(command: list[str], stdin_text: str | None = None) -> subprocess.CompletedProcess[str]:
    """Run a short command and return its exit code and output."""
    return subprocess.run(  # noqa: S603 - an argument list, never a shell
        command,
        cwd=HOME,
        input=stdin_text,
        text=True,
        capture_output=True,
        check=False,
    )


def stop(run_dir: Path) -> list[str]:
    return bidwright("stop", str(run_dir))


def resume(run_dir: Path, raise_budget: int | None = None, paid: bool = False) -> list[str]:
    cmd = bidwright("resume", str(run_dir))
    if raise_budget:
        cmd += ["--raise-budget", str(int(raise_budget))]
    if paid:
        cmd += ["--profile", "paid"]
    return cmd


def demo() -> list[str]:
    return bidwright("demo")


def review(run_dir: Path, role: str) -> list[str]:
    """`bidwright review` with its verdicts on standard input, as YAML."""
    return bidwright("review", str(run_dir), "--role", role, "--from", "-")


def phoenix_sync(run_dir: Path) -> list[str]:
    return bidwright("phoenix", "sync", str(run_dir))


def eval_to_phoenix(run_dir: Path) -> list[str]:
    return bidwright_eval("phoenix", str(run_dir))


__all__ = [
    "Job",
    "LaunchRequest",
    "bidwright",
    "demo",
    "eval_to_phoenix",
    "inputs",
    "new_run_id",
    "phoenix_sync",
    "resume",
    "review",
    "run",
    "start",
    "stop",
]
