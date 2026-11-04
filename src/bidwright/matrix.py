"""The matrix runner (CH-67): each rung's repeats, in order, through `execute`.

    bidwright matrix run <file> [--resume]

A matrix file (`config/matrices/*.yaml`) names an RFP, a profile (`free` or `paid`), the
number of repeats, the last node each run executes (`until`), a cost cap and its rungs, each
with flags for `execute`: `batch_size`, `extract_prompt`, `second_pass` and `baseline`; any
other flag is refused. Every run gets its repeat index, which is in every cassette and cache
key, and the response cache is on, so a run started again answers the calls it already made
from the cache. Runs go to `outputs/matrices/<matrix>/<matrix>-<rung>-r<repeat>/`.

- `--resume` skips a run whose manifest ended `COMPLETED` or `DEGRADED`; any other run folder
  is cleared and the run starts again. Without it, a matrix whose folder already holds runs
  is refused, so two matrices never mix.
- A run that ends `QUOTA_PAUSED` stops the matrix, and the command that resumes it is printed.
- Before each run, the `cost_usd` of the finished runs is summed. The matrix stops when the
  sum has reached `max_cost_usd`, or when the most a finished run has cost would take it past
  the cap, so no run starts that is expected to pass it.
- `matrix_manifest.json` lists every run, its status and the cost so far.

This module never imports `evals`: scoring is `bidwright-eval report <matrix>`.
"""

import json
import shutil
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

from bidwright.preflight import HOME
from bidwright.schemas import RunManifest

FLAGS = ("batch_size", "extract_prompt", "second_pass", "baseline")
FINISHED = ("COMPLETED", "DEGRADED")
MANIFEST = "matrix_manifest.json"


class Rung(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(pattern=r"^[A-Za-z0-9_.-]+$")
    flags: dict[str, Any] = Field(default_factory=dict)

    @field_validator("flags")
    @classmethod
    def _known_flags(cls, flags: dict[str, Any]) -> dict[str, Any]:
        unknown = sorted(set(flags) - set(FLAGS))
        if unknown:
            raise ValueError(f"unknown flags {unknown}; a rung may set {', '.join(FLAGS)}")
        return flags


class MatrixFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(pattern=r"^[A-Za-z0-9_.-]+$")
    rfp: str
    profile: Literal["free", "paid"]
    repeats: int = Field(ge=1)
    until: Literal["verify", "coverage", "consolidate", "render"] = "render"
    max_cost_usd: float = Field(ge=0)
    rungs: list[Rung] = Field(min_length=1)


def load_matrix(path: Path) -> MatrixFile:
    with path.open(encoding="utf-8") as handle:
        return MatrixFile.model_validate(yaml.safe_load(handle))


def matrix_dir(name: str, outputs: Path | None = None) -> Path:
    return (outputs or HOME / "outputs") / "matrices" / name


@dataclass
class MatrixRun:
    run_id: str
    rung: str
    repeat: int
    status: str
    cost_usd: float
    skipped: bool = False


@dataclass
class MatrixOutcome:
    name: str
    status: str  # COMPLETED, QUOTA_PAUSED or COST_CAP
    runs: list[MatrixRun] = field(default_factory=list)
    spent_usd: float = 0.0
    resume: str = ""


def _manifest(run_dir: Path) -> RunManifest | None:
    path = run_dir / "run_manifest.json"
    if not path.exists():
        return None
    try:
        return RunManifest.model_validate_json(path.read_text(encoding="utf-8"))
    except ValueError:
        return None


def _spent(root: Path) -> tuple[float, float]:
    """The summed and the largest `cost_usd` over the matrix's finished runs."""
    costs = [
        m.totals.cost_usd
        for m in (_manifest(p) for p in sorted(root.iterdir()) if p.is_dir())
        if m is not None and m.status in FINISHED
    ]
    return round(sum(costs), 6), max(costs, default=0.0)


def _write(root: Path, outcome: MatrixOutcome, matrix: MatrixFile, source: Path) -> None:
    data = {
        "matrix": matrix.name,
        "file": source.as_posix(),
        "rfp": matrix.rfp,
        "profile": matrix.profile,
        "repeats": matrix.repeats,
        "until": matrix.until,
        "max_cost_usd": matrix.max_cost_usd,
        "status": outcome.status,
        "spent_usd": outcome.spent_usd,
        "runs": [asdict(run) for run in outcome.runs],
    }
    (root / MANIFEST).write_text(json.dumps(data, indent=1) + "\n", encoding="utf-8", newline="\n")


class MatrixRefused(ValueError):
    """The matrix cannot start as asked."""


def run_matrix(
    path: Path,
    *,
    resume: bool = False,
    execute: Callable[..., Any] | None = None,
    backends: dict[str, Any] | None = None,
    outputs: Path | None = None,
    say: Callable[[str], None] = print,
) -> MatrixOutcome:
    """Run every rung's repeats in order. `execute` is the run entry, `graph.build.execute`
    unless a test passes a stand-in."""
    if execute is None:
        from bidwright.graph.build import execute as run_entry

        execute = run_entry
    matrix = load_matrix(path)
    root = matrix_dir(matrix.name, outputs)
    command = f"bidwright matrix run {path.as_posix()} --resume"
    if not resume and root.is_dir() and any(p.is_dir() for p in root.iterdir()):
        raise MatrixRefused(
            f"{root} already holds runs of {matrix.name}; continue them with: {command}"
        )
    root.mkdir(parents=True, exist_ok=True)
    outcome = MatrixOutcome(matrix.name, "COMPLETED", resume=command)
    for rung in matrix.rungs:
        for repeat in range(matrix.repeats):
            run_id = f"{matrix.name}-{rung.name}-r{repeat}"
            run_dir = root / run_id
            done = _manifest(run_dir)
            if resume and done is not None and done.status in FINISHED:
                outcome.runs.append(
                    MatrixRun(run_id, rung.name, repeat, done.status, done.totals.cost_usd, True)
                )
                continue
            spent, largest = _spent(root)
            outcome.spent_usd = spent
            if spent >= matrix.max_cost_usd or spent + largest > matrix.max_cost_usd:
                outcome.status = "COST_CAP"
                say(
                    f"Stopped before {run_id}: ${spent:g} spent of the ${matrix.max_cost_usd:g}"
                    f" cap. To go on, raise max_cost_usd, then run: {command}"
                )
                _write(root, outcome, matrix, path)
                return outcome
            if run_dir.exists():
                shutil.rmtree(run_dir)  # an unfinished run starts again; the cache keeps its calls
            say(f"{run_id}: running")
            result = execute(
                source=HOME / matrix.rfp,
                profile=matrix.profile,
                outputs=root,
                run_id=run_id,
                until=matrix.until,
                repeat=repeat,
                cache=True,
                backends=backends,
                **rung.flags,
            )
            finished = _manifest(run_dir)
            cost = finished.totals.cost_usd if finished else 0.0
            outcome.runs.append(MatrixRun(run_id, rung.name, repeat, result.status, cost))
            outcome.spent_usd = _spent(root)[0]
            _write(root, outcome, matrix, path)
            say(f"{run_id}: {result.status}" + (f" ({result.reason})" if result.reason else ""))
            if result.status == "QUOTA_PAUSED":
                outcome.status = "QUOTA_PAUSED"
                say(f"The daily quota is spent. After it resets, run: {command}")
                _write(root, outcome, matrix, path)
                return outcome
    _write(root, outcome, matrix, path)
    return outcome


__all__ = [
    "FLAGS",
    "MatrixFile",
    "MatrixOutcome",
    "MatrixRefused",
    "MatrixRun",
    "Rung",
    "load_matrix",
    "matrix_dir",
    "run_matrix",
]
