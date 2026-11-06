"""Seed runs (Iteration 3, step 16; ADR-048, design section 4.11): a finished run frozen so
that the SO and RK ladders start their rungs from the same requirements and solution.

`bidwright seed <run> --name NAME` copies the run's folder, its checkpoint included, to
`outputs/seeds/<name>/` and writes `seed.sha256`, the hash of every file it holds. It refuses
a run that has not ended, or that ended `BUDGET_EXCEEDED`, `POLICY_BLOCKED` or
`UNRECOVERABLE_FAULT`, and a name already taken.

`execute(seed_run=<folder>, seed_from="research" | "risk")` checks the seed before its run
folder exists (`check_seed`): every file against `seed.sha256`, and every prompt the seed's
nodes before the seed point used against the current prompt's hash. Its first node,
`seed_load`, returns the state keys `graph/state.py`'s `SEED_KEYS[seed_from]` lists from the
seed's last checkpoint (`seed_values`) and copies the files `SEED_FILES[seed_from]` names,
unchanged (`copy_seed_files`); it is the only writer of those copies in a seeded run.
"""

import hashlib
import shutil
import sqlite3
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from bidwright.graph.state import SEED_FILES, SEED_KEYS, SEED_PROMPTS
from bidwright.harness.supervisor import read_manifest
from bidwright.preflight import Refused
from bidwright.schemas import RunManifest, SeedRecord

SEED_HASHES = "seed.sha256"
SEEDS = "seeds"
SEEDABLE = ("COMPLETED", "DEGRADED")
# Copied with the run but never hashed: the run lock and the stop control.
SKIPPED = ("control",)
# The extraction settings a seed fixes, which a seeded run never changes (section 4.11).
EXTRACTION = (
    "batch_size",
    "second_pass",
    "extract_prompt",
    "extract_context",
    "triage",
    "coverage",
)


def _files(folder: Path) -> list[Path]:
    return sorted(
        p
        for p in folder.rglob("*")
        if p.is_file() and p.name != SEED_HASHES and p.relative_to(folder).parts[0] not in SKIPPED
    )


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_hashes(folder: Path) -> Path:
    """`seed.sha256`: one `<sha256>  <path>` line per file, paths relative and in name order."""
    lines = [f"{_digest(p)}  {p.relative_to(folder).as_posix()}" for p in _files(folder)]
    path = folder / SEED_HASHES
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    return path


def freeze(run_dir: Path, name: str, outputs: Path) -> Path:
    """Copy a finished run to `outputs/seeds/<name>/` and hash it."""
    manifest = read_manifest(run_dir)
    if manifest.status not in SEEDABLE:
        raise Refused(
            f"{run_dir.name} is {manifest.status}; a seed is a run that ended"
            f" {' or '.join(SEEDABLE)}"
        )
    target = outputs / SEEDS / name
    if target.exists():
        raise Refused(f"{target} already holds a seed; choose another name")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(run_dir, target, ignore=shutil.ignore_patterns(*SKIPPED))
    write_hashes(target)
    return target


@dataclass(frozen=True)
class Seed:
    folder: Path
    seed_from: str
    manifest: RunManifest
    record: SeedRecord


def check_seed(folder: Path, seed_from: str, prompts: Mapping[str, Any]) -> Seed:
    """Refuse a seed whose files changed, or whose nodes before the seed point used another
    version of a prompt than the run would; return it with the record its manifest keeps."""
    if seed_from not in SEED_KEYS:
        raise Refused(f"seed_from takes one of {', '.join(SEED_KEYS)}, not {seed_from!r}")
    hashes = folder / SEED_HASHES
    if not hashes.is_file():
        raise Refused(f"{folder} holds no {SEED_HASHES}; freeze the run with bidwright seed")
    recorded: dict[str, str] = {}
    for line in hashes.read_text(encoding="utf-8").splitlines():
        digest, _, name = line.partition("  ")
        if name:
            recorded[name] = digest
    present = {p.relative_to(folder).as_posix(): p for p in _files(folder)}
    for name in sorted(set(recorded) | set(present)):
        if name not in present:
            raise Refused(f"the seed's {name} is missing; freeze the run again")
        if recorded.get(name) != _digest(present[name]):
            raise Refused(f"the seed's {name} changed after it was frozen; freeze the run again")
    manifest = read_manifest(folder)
    for prompt_id in SEED_PROMPTS[seed_from] + (str(manifest.run_args.get("extract_prompt")),):
        then = manifest.prompt_hashes.get(prompt_id)
        if then is None or prompt_id not in prompts:
            continue
        now = prompts[prompt_id].hash
        if now != then:
            raise Refused(
                f"the seed ran {prompt_id} at {then[:19]}, and the current prompt is"
                f" {now[:19]}; make the seed again with the current prompts"
            )
    record = SeedRecord(
        folder=str(folder),
        sha256=f"sha256:{_digest(hashes)}",
        commit=manifest.commit,
        seed_from=seed_from,  # type: ignore[arg-type]
        extraction={k: manifest.run_args.get(k) for k in EXTRACTION},
    )
    return Seed(folder, seed_from, manifest, record)


def checkpoint_values(folder: Path, thread_id: str) -> dict[str, Any]:
    """Every state channel of the last checkpoint in `folder`, empty when it holds none. The
    checkpoint file is read from a copy, so the folder's bytes never change."""
    from langgraph.checkpoint.sqlite import SqliteSaver

    with tempfile.TemporaryDirectory() as scratch:
        copy = Path(scratch) / "checkpoints.sqlite"
        for suffix in ("", "-wal", "-shm"):  # SQLite's write-ahead log, when it kept one
            source = folder / f"checkpoints.sqlite{suffix}"
            if source.exists():
                shutil.copyfile(source, Path(scratch) / source.name)
        if not copy.exists():
            return {}
        connection = sqlite3.connect(copy, check_same_thread=False)
        try:
            found = SqliteSaver(connection).get_tuple({"configurable": {"thread_id": thread_id}})
        finally:
            connection.close()
    return dict(found.checkpoint["channel_values"]) if found is not None else {}


def seed_values(seed: Seed) -> dict[str, Any]:
    """The state keys `SEED_KEYS[seed_from]` lists, from the seed's last checkpoint."""
    values = checkpoint_values(seed.folder, seed.manifest.run_id)
    if not values:
        raise Refused(f"the seed {seed.folder.name} holds no checkpoint")
    missing = [k for k in ("passages", "requirements", "brief") if k not in values]
    if missing:
        raise Refused(f"the seed's checkpoint lacks {', '.join(missing)}: it never reached brief")
    return {k: values[k] for k in SEED_KEYS[seed.seed_from] if k in values}


def copy_seed_files(seed: Seed, run_dir: Path) -> list[str]:
    """The files `SEED_FILES[seed_from]` names, copied byte for byte into the run folder."""
    copied = []
    for pattern in SEED_FILES[seed.seed_from]:
        for source in sorted(seed.folder.glob(pattern)):
            if not source.is_file():
                continue
            relative = source.relative_to(seed.folder)
            target = run_dir / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            copied.append(relative.as_posix())
    return copied


__all__ = [
    "SEEDS",
    "SEED_HASHES",
    "Seed",
    "check_seed",
    "checkpoint_values",
    "copy_seed_files",
    "freeze",
    "seed_values",
    "write_hashes",
]
