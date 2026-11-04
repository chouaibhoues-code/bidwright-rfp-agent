"""Purge (ADR-026, D-05, C4): a client run has an end.

`purge_run` deletes a run's folder, which holds its checkpoints, and every entry of the
response cache under `HOME / "outputs" / ".cache"` that the run wrote, read from the `run_id`
in each entry's meta. `purge_expired` does the same for every client run under
`HOME / "outputs"` and its `matrices/` folder, whatever `--outputs` said at the time, whose end
time, from its manifest, is more than `retention.client_days` days ago. Synthetic runs and
recent client runs stay. Each purge returns what it deleted, and the CLI prints it. Only a
folder that holds a run manifest is ever deleted.
"""

import json
import shutil
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

from bidwright.llm import cache as response_cache
from bidwright.preflight import HOME
from bidwright.schemas import RunManifest

MANIFEST = "run_manifest.json"


def outputs_root() -> Path:
    return HOME / "outputs"


def _cache_entries(run_id: str, cache_dir: Path) -> list[Path]:
    if not cache_dir.is_dir():
        return []
    found = []
    for entry in sorted(cache_dir.glob("*.json")):
        try:
            meta = json.loads(entry.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(meta, dict) and meta.get("run_id") == run_id:
            found.append(entry)
    return found


class NotARun(ValueError):
    """The folder holds no run manifest, so it is not a run folder and is never deleted."""


def purge_run(run_dir: Path, cache_dir: Path | None = None) -> list[Path]:
    """Delete one run's folder and its cache entries; return what was deleted. A folder with
    no `run_manifest.json` is refused, so a mistyped path never deletes anything else."""
    if not (run_dir / MANIFEST).is_file():
        raise NotARun(f"{run_dir} holds no {MANIFEST}, so it is not a run folder")
    cache_dir = cache_dir if cache_dir is not None else response_cache.CACHE_DIR
    deleted = []
    for entry in _cache_entries(run_dir.name, cache_dir):
        entry.unlink()
        deleted.append(entry)
    if run_dir.is_dir():
        shutil.rmtree(run_dir)
        deleted.append(run_dir)
    return deleted


def _run_folders(root: Path) -> Iterator[Path]:
    """Every folder holding a run manifest, under `root` and its `matrices/` folder."""
    for manifest in sorted(root.glob(f"*/{MANIFEST}")):
        yield manifest.parent
    for manifest in sorted((root / "matrices").glob(f"*/*/{MANIFEST}")):
        yield manifest.parent


def expired_runs(root: Path, client_days: int, now: datetime | None = None) -> list[Path]:
    """The client runs whose recorded end is more than `client_days` days ago."""
    cutoff = (now or datetime.now(UTC)) - timedelta(days=client_days)
    found = []
    for folder in _run_folders(root):
        try:
            manifest = RunManifest.model_validate_json(
                (folder / MANIFEST).read_text(encoding="utf-8")
            )
        except (OSError, ValueError):
            continue
        ended = manifest.ended or manifest.started
        if manifest.data_class == "client" and ended < cutoff:
            found.append(folder)
    return found


def purge_expired(
    client_days: int,
    root: Path | None = None,
    cache_dir: Path | None = None,
    now: datetime | None = None,
) -> list[Path]:
    """Purge every expired client run; return what was deleted."""
    deleted: list[Path] = []
    for folder in expired_runs(root if root is not None else outputs_root(), client_days, now):
        deleted += purge_run(folder, cache_dir)
    return deleted


__all__ = ["NotARun", "expired_runs", "outputs_root", "purge_expired", "purge_run"]
