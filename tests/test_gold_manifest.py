"""Gold and hypotheses are frozen together: every file matches MANIFEST.sha256, and a change
to either refuses the score until the change is versioned."""

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from evals.cli import hash_gold
from evals.score import GOLD_DIR, HYPOTHESES_ENTRY, GoldChanged, gold_for, recorded_hashes

pytestmark = pytest.mark.gold


def test_every_gold_file_and_the_hypotheses_match_their_recorded_hash() -> None:
    recorded = recorded_hashes()
    files = sorted(GOLD_DIR.glob("*/gold.jsonl"))
    assert {"dev/gold.jsonl", "dev-docx/gold.jsonl", "hero/gold.jsonl"} <= {
        path.relative_to(GOLD_DIR).as_posix() for path in files
    }
    for path in [*files, GOLD_DIR / HYPOTHESES_ENTRY]:
        name = (
            HYPOTHESES_ENTRY
            if path.name == "hypotheses.yaml"
            else path.relative_to(GOLD_DIR).as_posix()
        )
        assert recorded.get(name) == hashlib.sha256(path.read_bytes()).hexdigest(), name


def _frozen_copy(tmp_path: Path) -> Path:
    """A copy of the gold and the hypotheses, laid out as in the repository, then frozen."""
    gold = tmp_path / "evals" / "gold"
    shutil.copytree(GOLD_DIR, gold)
    shutil.copy(GOLD_DIR / HYPOTHESES_ENTRY, gold / HYPOTHESES_ENTRY)
    hash_gold(gold)
    return gold


def test_a_frozen_copy_scores_and_names_its_corpus(tmp_path: Path) -> None:
    gold = _frozen_copy(tmp_path)
    corpus, lines = gold_for("dev-rfp-db9eeb00", gold)
    assert corpus == "dev" and all(line["gold_version"] == 3 for line in lines)


def test_the_hero_and_the_development_pdf_are_at_gold_version_3() -> None:
    """Gold v3 (Iteration 2) adds the factor seeds, and the hero's domain seeds."""
    for corpus in ("hero", "dev"):
        lines = (GOLD_DIR / corpus / "gold.jsonl").read_text(encoding="utf-8").splitlines()
        assert {json.loads(line)["gold_version"] for line in lines} == {3}, corpus


def test_a_changed_gold_file_is_refused(tmp_path: Path) -> None:
    gold = _frozen_copy(tmp_path)
    path = gold / "dev" / "gold.jsonl"
    path.write_text(path.read_text(encoding="utf-8").replace("ten (10)", "eleven (11)"))
    with pytest.raises(GoldChanged, match="dev/gold.jsonl"):
        gold_for("dev-rfp-db9eeb00", gold)


def test_changed_hypotheses_are_refused(tmp_path: Path) -> None:
    gold = _frozen_copy(tmp_path)
    path = gold / HYPOTHESES_ENTRY
    path.write_text(path.read_text(encoding="utf-8").replace("max_drop: 0.03", "max_drop: 0.05"))
    with pytest.raises(GoldChanged, match="hypotheses"):
        gold_for("dev-rfp-db9eeb00", gold)
