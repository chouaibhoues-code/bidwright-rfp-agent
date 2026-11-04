"""D-05's privacy invariant: planted personal data stays in the documents and their fixtures.

After a recorded and a replayed development run, no planted value appears in either run's
spans, ledger or manifest, or in the logging output captured at DEBUG while they ran; at that
level pdfminer would log every text token of the PDF, which is why `bidwright` caps its logger.
The model is the scripted one of `test_text_view.py`, whose answers quote the passage that
holds the values, so a span or ledger field that copied a request or an answer would be
caught. No tracked file
holds a planted value either, outside the folders that hold documents and their fixtures. The
values come from the `personal_data` lines of the development gold and are never written
here."""

import logging
import shutil
import subprocess
from pathlib import Path

import pytest

from bidwright.graph.build import execute
from bidwright.llm.client import Mode
from bidwright.llm.replay import CassetteStore
from bidwright.llm.types import Backend
from tests.node_fakes import DEV_RFP
from tests.privacy_fakes import ScriptedModel, planted_values

pytestmark = pytest.mark.gold

HOME = Path(__file__).resolve().parents[1]
ALLOWED = (
    "inputs/",
    "evals/corpus/",
    "evals/gold/",
    "tests/cassettes/",
    "samples/",
    "docs/designs/iteration-1.md",
)
RUN_FILES = ("spans.jsonl", "ledger.jsonl", "run_manifest.json")


def test_no_planted_value_reaches_spans_the_ledger_the_manifest_or_the_logs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.delenv("PHOENIX_ENDPOINT", raising=False)  # spans go to spans.jsonl
    caplog.set_level(logging.DEBUG)
    planted = planted_values()
    store = CassetteStore(tmp_path / "cassettes")
    model: Backend = ScriptedModel(planted)
    plan: list[tuple[Mode, dict[str, Backend] | None]] = [
        ("record", {"gemini": model}),
        ("replay", None),
    ]
    runs = []
    for mode, backends in plan:
        result = execute(
            docling_mode="replay",
            source=DEV_RFP,
            profile="free",
            outputs=tmp_path / "out",
            mode=mode,
            cassettes=store,
            backends=backends,
            run_id=f"privacy-{mode}",
        )
        assert result.status == "COMPLETED", result.reason
        runs.append(result.run_dir)
    requirements = (runs[1] / "requirements.jsonl").read_text(encoding="utf-8")
    assert any(value in requirements for value in planted), "the answers quoted the values"
    for run_dir in runs:
        for name in RUN_FILES:
            text = (run_dir / name).read_text(encoding="utf-8")
            assert not any(value in text for value in planted), f"{run_dir.name}/{name}"
    assert not any(value in caplog.text for value in planted), "the logging output"


def test_no_tracked_file_holds_a_planted_value_outside_the_fixtures() -> None:
    git = shutil.which("git")
    if git is None:
        pytest.skip("git is not installed")
    listed = subprocess.run([git, "ls-files", "-z"], cwd=HOME, capture_output=True, check=False)
    if listed.returncode != 0:
        pytest.skip("not a git checkout")
    values = [value.encode("utf-8") for value in planted_values()]
    found = []
    for name in listed.stdout.decode("utf-8").split("\0"):
        if not name or name.startswith(ALLOWED):
            continue
        path = HOME / name
        if path.is_file() and any(value in path.read_bytes() for value in values):
            found.append(name)
    assert found == [], "planted personal data outside the fixture folders"
