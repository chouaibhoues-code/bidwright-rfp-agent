"""The generated reference documents match what the code generates (WP-0b.4).

`docs/agents.md`, `docs/reference/cli.md` and `docs/reference/schemas.md` come from
`scripts/gen_docs.py`. After a change to the agents, models, prompts, tools, graph, CLI or
schemas, run `uv run python scripts/gen_docs.py` and commit the result.
"""

import importlib.util
import os
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "gen_docs.py"

pytestmark = pytest.mark.skipif(not SCRIPT.exists(), reason="scripts/ is not in this image")


def test_generated_docs_are_current(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COLUMNS", "37")
    spec = importlib.util.spec_from_file_location("gen_docs", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    stale = module.stale_paths(module.generate())
    assert not stale, f"out of date, run uv run python scripts/gen_docs.py: {stale}"
    assert os.environ["COLUMNS"] == "37", "generation must restore the environment"
