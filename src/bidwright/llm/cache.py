"""The response cache (Iteration 1, step 9): a cassette store under `outputs/.cache/`.

With caching on, `LLMClient._obtain` reads the cache before a live attempt and writes to it
after one, under the cassette key, so an identical call on the same model, settings, input and
repeat index is answered from disk. A hit is reported with `replayed: true` and costs nothing
in the ledger, and it skips the limiter. Each entry's meta names the run that wrote it, so
`bidwright purge` can delete a run's entries with its folder. The cache lives under
`HOME / "outputs"` whatever `--outputs` says, as the quota counts do. It applies to `live` runs;
`record` and `replay` ignore it. `config/limits.yaml` turns it on for matrix runs and off for
single runs, which `--cache` turns on.
"""

from pathlib import Path

from bidwright.llm.replay import CassetteStore
from bidwright.preflight import HOME

CACHE_DIR = HOME / "outputs" / ".cache"


def response_cache(root: Path | None = None) -> CassetteStore:
    """The cache store, at `root` or under `HOME / "outputs"`."""
    return CassetteStore(root if root is not None else CACHE_DIR)


__all__ = ["CACHE_DIR", "response_cache"]
