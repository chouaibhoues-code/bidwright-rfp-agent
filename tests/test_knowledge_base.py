"""The supplier knowledge base: it loads, its ids are unique, its references resolve, and it
says nothing about the capabilities the corpus plants as gaps."""

import shutil
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from bidwright.kb import KB_DIR, load_kb
from evals.render.spec import CORPUS_DIR, GapSeed, load_spec


def test_every_file_loads_with_unique_ids() -> None:
    kb = load_kb()
    assert kb.capabilities and kb.case_studies and kb.certifications and kb.roles
    ids = [record.id for record in kb.records()]
    assert len(ids) == len(set(ids))
    assert any("partner" in c.tags for c in kb.capabilities)


def _copy(tmp_path: Path) -> Path:
    root = tmp_path / "kb"
    shutil.copytree(KB_DIR, root)
    return root


def _edit(root: Path, name: str, key: str, index: int, field: str, value: object) -> None:
    path = root / name
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data[key][index][field] = value
    path.write_text(yaml.safe_dump(data), encoding="utf-8")


@pytest.mark.parametrize(
    ("name", "key", "field", "value", "message"),
    [
        ("capabilities.yaml", "capabilities", "id", "CAP-002", "duplicate"),
        ("capabilities.yaml", "capabilities", "evidence", ["CS-999"], "unknown evidence"),
        (
            "case_studies.yaml",
            "case_studies",
            "capability_ids",
            ["CAP-999"],
            "unknown capabilities",
        ),
        ("roles.yaml", "roles", "capability_ids", ["CAP-999"], "unknown capabilities"),
    ],
)
def test_a_broken_base_is_refused(
    tmp_path: Path, name: str, key: str, field: str, value: object, message: str
) -> None:
    root = _copy(tmp_path)
    _edit(root, name, key, 0, field, value)
    with pytest.raises(ValidationError, match=message):
        load_kb(root)


@pytest.mark.gold
def test_no_gap_seed_term_occurs_in_the_knowledge_base() -> None:
    """Each RFP asks for capabilities the base lacks; the base never mentions them."""
    texts = [text.lower() for text in load_kb().texts()]
    seeds = [
        seed
        for path in sorted(CORPUS_DIR.glob("*/spec.yaml"))
        for seed in load_spec(path.parent.name).seeds
        if isinstance(seed, GapSeed)
    ]
    assert len(seeds) >= 4
    for seed in seeds:
        for term in seed.absent_terms:
            assert not any(term.lower() in text for text in texts), (seed.id, term)
