"""Test-wide isolation. The limiter's daily counts and the response cache live under
`HOME / "outputs"` on a real machine, whatever a run's `--outputs` says, so every test gets
its own empty folders for them: a test run never spends, or reads, the developer's counts."""

from pathlib import Path

import pytest

import bidwright.llm.cache
import bidwright.llm.limits


@pytest.fixture(autouse=True)
def _isolated_quota_and_cache(
    monkeypatch: pytest.MonkeyPatch, tmp_path_factory: pytest.TempPathFactory
) -> tuple[Path, Path]:
    root = tmp_path_factory.mktemp("home-outputs")
    quota, cache = root / ".quota", root / ".cache"
    monkeypatch.setattr(bidwright.llm.limits, "QUOTA_DIR", quota)
    monkeypatch.setattr(bidwright.llm.cache, "CACHE_DIR", cache)
    return quota, cache
