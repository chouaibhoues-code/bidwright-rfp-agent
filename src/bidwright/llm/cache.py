"""The response cache (Iteration 1, step 9) and each run's journal (Iteration 2, ADR-031).

The cache is a cassette store under `outputs/.cache/`. With caching on, `LLMClient` reads the
cache before a live attempt and, once an answer has parsed, writes it under the cassette key,
so an identical call on the same model, settings, input and repeat index is answered from disk.
An answer that does not parse is never kept. A hit is reported with `replayed: true` and costs
nothing in the ledger, and it skips the limiter. Each entry's meta names the run that wrote
it, so `bidwright purge` can delete a run's entries with its folder. The cache lives under
`HOME / "outputs"` whatever `--outputs` says, as the quota counts do. It applies to `live` runs;
`record` and `replay` ignore it. `config/limits.yaml` turns it on for matrix runs and off for
single runs, which `--cache` turns on.

The journal is a cassette store in the run's own folder, `journal/`. In `live` mode the client
saves every answer that parses to it, whatever `--cache` says, so a resumed run is answered
from it and never pays twice for a call; it belongs to its run alone, so a single run never
feeds a later matrix, and `bidwright purge` deletes it with the run folder.
"""

from pathlib import Path

from bidwright.llm.replay import CassetteStore
from bidwright.preflight import HOME

CACHE_DIR = HOME / "outputs" / ".cache"


def response_cache(root: Path | None = None) -> CassetteStore:
    """The cache store, at `root` or under `HOME / "outputs"`."""
    return CassetteStore(root if root is not None else CACHE_DIR)


def run_journal(run_dir: Path) -> CassetteStore:
    """The run's journal, at `run_dir / "journal"`."""
    return CassetteStore(run_dir / "journal")


__all__ = ["CACHE_DIR", "response_cache", "run_journal"]
