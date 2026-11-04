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


@pytest.fixture
def client_root(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """For whole runs on a client document: `tmp_path` as the client root, outside the
    repository, and pdfplumber for its PDF, since Docling cassettes exist for corpus files only."""
    from bidwright.graph import build
    from bidwright.parsers.pdfplumber_parser import PdfplumberParser

    monkeypatch.setenv("BIDWRIGHT_CLIENT_ROOT", str(tmp_path))
    monkeypatch.setattr(build, "DoclingParser", lambda client: PdfplumberParser())
    return tmp_path
