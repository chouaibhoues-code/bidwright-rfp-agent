"""The matrix runner (CH-67): each rung's repeats, in order, through `execute`.

    bidwright matrix run <file> [--resume]

A matrix file (`config/matrices/*.yaml`) names an RFP, a profile (`free` or `paid`), the
number of repeats, the last node each run executes (`until`), a cost cap and its rungs, each
with flags for `execute`: `batch_size`, `extract_prompt`, `second_pass`, `baseline`, from
Iteration 2 `research` (`off` or `pack`), and from Iteration 3 the solution switches
`solution`, `risk_mode` and `reflect`, and from step 16 the extraction switches
`extract_context` (`full` or `bare`), `triage` and `coverage` (true or false), and from step 18
`methods`, the method-card families a run inlines; any other flag is refused. Every run
approves its gate automatically (`gate="auto"`), which never passes a blocked gate. Every run
gets its repeat index, which is in every cassette and cache key, and the response cache is on,
so a run started again answers the calls it already made from the cache. Runs go to
`outputs/matrices/<matrix>/<matrix>-<rung>-r<repeat>/`.

- Before anything starts, a rung that `execute` would refuse is refused: an `extract_prompt`
  a run does not load, such as a retired one, or a baseline asked for the second pass, which a
  baseline never runs (ADR-028), or research mode `live`, since every repeat would start a
  deep research job, minutes long, on the owner's NotebookLM account. Nothing is created, and
  no run is spent first.
- Every run stays on its roles' primary models (`fallback=False`): a second model would change
  what the matrix measures. A spent quota pauses the run instead, and a call that exhausts its
  retries faults it.
- `--resume` skips a run whose manifest ended `COMPLETED` or `DEGRADED` on its primary models;
  any other run folder, including one with a call a fallback model answered, is cleared and
  the run starts again. Without it, a matrix whose folder already holds runs is refused, so
  two matrices never mix.
- A run that ends `QUOTA_PAUSED` stops the matrix, and the command that resumes it is printed.
- The re-run rule (section 4.11): a repeat that ends `BUDGET_EXCEEDED` or `POLICY_BLOCKED`,
  has a call a fallback model answered, or ends `DEGRADED` with a part of its reason (the
  `; `-separated parts) that starts with none of the matrix's `allow_degraded` prefixes, is
  cleared and run again, at most twice. After a third such end it is recorded `invalid`,
  with its reason, and the report leaves it out with a note.
- Before each run, the `cost_usd` of every run so far is summed, whatever its status, with the
  cost of the runs cleared to start again, which `matrix_manifest.json` keeps as `cleared_usd`.
  The matrix stops when the sum has reached `max_cost_usd`, or when the most a run has cost
  would take it past the cap, so no run starts that is expected to pass it.
- `matrix_manifest.json` lists every run, its status and the cost so far.

This module never imports `evals`: scoring is `bidwright-eval report <matrix>`.
"""

import json
import shutil
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

from bidwright.config import load_config
from bidwright.preflight import HOME
from bidwright.schemas import RunManifest

FLAGS = (
    "batch_size",
    "extract_prompt",
    "second_pass",
    "baseline",
    "research",
    "solution",
    "risk_mode",
    "reflect",
    "extract_context",
    "triage",
    "coverage",
    "methods",
)
# The flags that change extraction, which a seeded matrix's rungs never set.
EXTRACTION_FLAGS = (
    "batch_size",
    "extract_prompt",
    "second_pass",
    "baseline",
    "extract_context",
    "triage",
    "coverage",
)
# The flags that take true or false only.
BOOLEAN_FLAGS = ("reflect", "triage", "coverage", "second_pass")
EXTRACT_CONTEXTS = ("full", "bare")
# The ends a repeat is run again for, and how many times a repeat runs at most.
RERUN_STATUSES = ("BUDGET_EXCEEDED", "POLICY_BLOCKED")
MAX_ATTEMPTS = 3
# The research nodes that call a model, each under the `discover` agent's role.
DISCOVER_NODES = ("discover_start", "discover_ask", "discover_extract")
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
        if flags.get("research") is False:  # YAML 1.1 reads a bare `off` as false
            return {**flags, "research": "off"}
        return flags


class MatrixFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(pattern=r"^[A-Za-z0-9_.-]+$")
    rfp: str
    profile: Literal["free", "paid"]
    repeats: int = Field(ge=1)
    until: Literal[
        "verify",
        "coverage",
        "consolidate",
        "brief",
        "capability_map",
        "solution_gate",
        "render",
    ] = "render"
    max_cost_usd: float = Field(ge=0)
    # A seeded matrix (section 4.11): the seed folder, under the repository, and its point.
    seed_run: str | None = None
    seed_from: Literal["research", "risk"] | None = None
    # The reason prefixes a DEGRADED repeat may carry and still count (section 4.11).
    allow_degraded: list[str] = Field(default_factory=list)
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
    attempts: int = 1
    invalid: bool = False  # ended three times in a way the re-run rule runs again
    note: str = ""


@dataclass
class MatrixOutcome:
    name: str
    status: str  # COMPLETED, QUOTA_PAUSED or COST_CAP
    runs: list[MatrixRun] = field(default_factory=list)
    spent_usd: float = 0.0
    cleared_usd: float = 0.0  # the spend of runs whose folders were cleared to start again
    resume: str = ""


def fell_back(manifest: RunManifest, roles: Mapping[str, str] | None = None) -> bool:
    """Whether a fallback model answered any call: a node answered by a model other than its
    role's primary. `roles` maps each node to its model role, from `config/agents.yaml` by
    default; a node with no known role is checked against every role's primary."""
    if roles is None:
        agents = load_config().agents.agents
        roles = {name: agent.model_role for name, agent in agents.items()}
        roles |= {node: agents["discover"].model_role for node in DISCOVER_NODES}
    every = set(manifest.models.values())
    for node, used in manifest.models_used.items():
        role = roles.get(node)
        primary = {manifest.models[role]} if role in manifest.models else every
        if any(model not in primary for model in used):
            return True
    return False


def _manifest(run_dir: Path) -> RunManifest | None:
    path = run_dir / "run_manifest.json"
    if not path.exists():
        return None
    try:
        return RunManifest.model_validate_json(path.read_text(encoding="utf-8"))
    except ValueError:
        return None


def _spent(root: Path, cleared: float) -> tuple[float, float]:
    """The summed and the largest `cost_usd` over every run of the matrix, failed runs
    included, with the spend of the runs already cleared."""
    costs = [
        m.totals.cost_usd
        for m in (_manifest(p) for p in sorted(root.iterdir()) if p.is_dir())
        if m is not None
    ]
    return round(sum(costs) + cleared, 6), max(costs, default=0.0)


def _cleared(root: Path) -> float:
    path = root / MANIFEST
    if not path.exists():
        return 0.0
    try:
        return float(json.loads(path.read_text(encoding="utf-8")).get("cleared_usd", 0.0))
    except (ValueError, TypeError):
        return 0.0


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
        "cleared_usd": outcome.cleared_usd,
        "runs": [asdict(run) for run in outcome.runs],
    }
    (root / MANIFEST).write_text(json.dumps(data, indent=1) + "\n", encoding="utf-8", newline="\n")


class MatrixRefused(ValueError):
    """The matrix cannot start as asked."""


def check_rungs(matrix: MatrixFile) -> None:
    """Refuse, before anything starts, a rung that `execute` would refuse at its first run."""
    from bidwright.graph.build import extract_prompt_ids, run_prompts
    from bidwright.graph.solution import RISK_MODES, SOLUTIONS

    known = extract_prompt_ids(run_prompts(load_config()))
    if (matrix.seed_run is None) != (matrix.seed_from is None):
        raise MatrixRefused("a seeded matrix names both seed_run and seed_from")
    for rung in matrix.rungs:
        if matrix.seed_run is not None:
            fixed = sorted(set(rung.flags) & set(EXTRACTION_FLAGS))
            if fixed:
                raise MatrixRefused(
                    f"rung {rung.name} sets {', '.join(fixed)} on a seeded matrix; a seeded"
                    " rung keeps its seed's extraction"
                )
        name = rung.flags.get("extract_prompt")
        if name is not None and name not in known:
            raise MatrixRefused(
                f"rung {rung.name} names the extract prompt {name!r}, which a run does not"
                f" load; a run loads {', '.join(known)}"
            )
        if rung.flags.get("baseline") is not None and rung.flags.get("second_pass"):
            raise MatrixRefused(
                f"rung {rung.name} sets a baseline and the second pass; a baseline runs"
                " without the second pass (ADR-028)"
            )
        research = rung.flags.get("research")
        if research == "live":
            raise MatrixRefused(
                f"rung {rung.name} sets research mode live; each repeat would start a deep"
                " research job, minutes long, on the owner's NotebookLM account: use off or pack"
            )
        if research is not None and research not in ("off", "pack"):
            raise MatrixRefused(f"rung {rung.name} sets research {research!r}; use off or pack")
        for flag, known_values in (("solution", SOLUTIONS), ("risk_mode", RISK_MODES)):
            value = rung.flags.get(flag)
            if value is not None and value not in known_values:
                raise MatrixRefused(
                    f"rung {rung.name} sets {flag} {value!r}; use one of {', '.join(known_values)}"
                )
        for flag in BOOLEAN_FLAGS:
            if flag in rung.flags and not isinstance(rung.flags[flag], bool):
                raise MatrixRefused(
                    f"rung {rung.name} sets {flag} to a value that is not true or false"
                )
        if "methods" in rung.flags:
            from bidwright.kb import normalize_families

            chosen = rung.flags["methods"]
            if not isinstance(chosen, list):
                raise MatrixRefused(f"rung {rung.name} sets methods to a value that is not a list")
            try:
                normalize_families(chosen)
            except ValueError as exc:
                raise MatrixRefused(f"rung {rung.name}: {exc}") from exc
        context = rung.flags.get("extract_context")
        if context is not None and context not in EXTRACT_CONTEXTS:
            raise MatrixRefused(
                f"rung {rung.name} sets extract_context {context!r}; use full or bare"
            )


def rerun_reason(
    status: str, manifest: RunManifest | None, allow_degraded: list[str]
) -> str | None:
    """Why the re-run rule runs a repeat again, or None when it counts as it is."""
    if status in RERUN_STATUSES:
        return status
    if status not in FINISHED or manifest is None:
        return None
    if fell_back(manifest):
        return "a fallback model answered a call"
    if status == "DEGRADED":
        parts = [p.strip() for p in (manifest.status_reason or "").split("; ") if p.strip()]
        other = [p for p in parts if not any(p.startswith(a) for a in allow_degraded)]
        if other:
            return "DEGRADED: " + "; ".join(other)
    return None


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
    check_rungs(matrix)
    root = matrix_dir(matrix.name, outputs)
    command = f"bidwright matrix run {path.as_posix()} --resume"
    if not resume and root.is_dir() and any(p.is_dir() for p in root.iterdir()):
        raise MatrixRefused(
            f"{root} already holds runs of {matrix.name}; continue them with: {command}"
        )
    root.mkdir(parents=True, exist_ok=True)
    seeded: dict[str, Any] = (
        {"seed_run": HOME / matrix.seed_run, "seed_from": matrix.seed_from}
        if matrix.seed_run is not None
        else {}
    )
    outcome = MatrixOutcome(
        matrix.name, "COMPLETED", cleared_usd=_cleared(root) if resume else 0.0, resume=command
    )
    for rung in matrix.rungs:
        for repeat in range(matrix.repeats):
            run_id = f"{matrix.name}-{rung.name}-r{repeat}"
            run_dir = root / run_id
            done = _manifest(run_dir)
            if (
                resume
                and done is not None
                and done.status in FINISHED
                and rerun_reason(done.status, done, matrix.allow_degraded) is None
            ):
                outcome.runs.append(
                    MatrixRun(run_id, rung.name, repeat, done.status, done.totals.cost_usd, True)
                )
                continue
            run: MatrixRun | None = None
            for attempt in range(1, MAX_ATTEMPTS + 1):
                spent, largest = _spent(root, outcome.cleared_usd)
                outcome.spent_usd = spent
                if spent >= matrix.max_cost_usd or spent + largest > matrix.max_cost_usd:
                    outcome.status = "COST_CAP"
                    say(
                        f"Stopped before {run_id}: ${spent:g} spent of the"
                        f" ${matrix.max_cost_usd:g} cap. To go on, raise max_cost_usd, then"
                        f" run: {command}"
                    )
                    _write(root, outcome, matrix, path)
                    return outcome
                if run_dir.exists():
                    # A run starts again; the cache keeps its calls, and its spend stays on
                    # the matrix's account.
                    done = _manifest(run_dir)
                    if done is not None:
                        outcome.cleared_usd = round(outcome.cleared_usd + done.totals.cost_usd, 6)
                    shutil.rmtree(run_dir)
                    _write(root, outcome, matrix, path)
                say(f"{run_id}: running" + (f", attempt {attempt}" if attempt > 1 else ""))
                result = execute(
                    source=HOME / matrix.rfp,
                    profile=matrix.profile,
                    outputs=root,
                    run_id=run_id,
                    until=matrix.until,
                    repeat=repeat,
                    cache=True,
                    backends=backends,
                    fallback=False,
                    gate="auto",
                    **seeded,
                    **rung.flags,
                )
                finished = _manifest(run_dir)
                cost = finished.totals.cost_usd if finished else 0.0
                reason = rerun_reason(result.status, finished, matrix.allow_degraded)
                run = MatrixRun(run_id, rung.name, repeat, result.status, cost, attempts=attempt)
                say(f"{run_id}: {result.status}" + (f" ({result.reason})" if result.reason else ""))
                if reason is None or result.status == "QUOTA_PAUSED":
                    break
                if attempt == MAX_ATTEMPTS:
                    run.invalid, run.note = True, f"invalid after {attempt} runs: {reason}"
                    say(f"{run_id}: {run.note}")
                else:
                    say(f"{run_id}: run again, since {reason}")
            if run is None:  # MAX_ATTEMPTS is at least 1, so the loop ran
                raise RuntimeError(f"{run_id} did not run")
            outcome.runs.append(run)
            outcome.spent_usd = _spent(root, outcome.cleared_usd)[0]
            _write(root, outcome, matrix, path)
            if run.status == "QUOTA_PAUSED":
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
    "check_rungs",
    "fell_back",
    "load_matrix",
    "matrix_dir",
    "rerun_reason",
    "run_matrix",
]
