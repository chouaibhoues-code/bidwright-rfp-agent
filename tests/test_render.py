"""The corpus renderer: every gold clause is findable in the PDF, and outputs match the spec."""

import hashlib
import json
import re
from pathlib import Path

import pdfplumber
import pytest

from evals.render.__main__ import INPUTS_DIR, MANIFEST
from evals.render.gold import GOLD_DIR, gold_lines
from evals.render.pdf import render_pdf
from evals.render.spec import load_spec

pytestmark = pytest.mark.gold


def _normalized(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _pdf_text(path: Path) -> str:
    with pdfplumber.open(path) as pdf:
        return _normalized(" ".join(page.extract_text() or "" for page in pdf.pages))


@pytest.fixture(scope="module")
def rendered(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("render") / "dev_rfp.pdf"
    render_pdf(load_spec("dev"), path)
    return path


def test_every_spec_clause_appears_in_the_extracted_text(rendered: Path) -> None:
    text = _pdf_text(rendered)
    spec = load_spec("dev")
    missing = [c.id for c, _, _ in spec.clauses() if _normalized(c.text) not in text]
    assert not missing
    for _, _, lead_in in spec.clauses():
        assert lead_in is None or lead_in in text


def test_rendering_is_reproducible_and_matches_the_committed_file(rendered: Path) -> None:
    spec = load_spec("dev")
    digest = hashlib.sha256(rendered.read_bytes()).hexdigest()
    assert digest == hashlib.sha256((INPUTS_DIR / spec.output).read_bytes()).hexdigest()
    assert f"{digest}  {spec.output}" in MANIFEST.read_text(encoding="utf-8").splitlines()


def test_committed_gold_matches_the_spec() -> None:
    spec = load_spec("dev")
    committed = (GOLD_DIR / spec.corpus / "gold.jsonl").read_text(encoding="utf-8")
    assert [json.loads(line) for line in committed.splitlines()] == gold_lines(spec)


def test_gold_v1_has_the_planned_contents() -> None:
    lines = gold_lines(load_spec("dev"))
    requirements = [line for line in lines if line["kind"] == "requirement"]
    assert len(requirements) == 12
    assert sum(line["mandatory"] for line in requirements) == 8
    assert sum(line["hazard"] for line in requirements) == 1
    assert sum(line["modality"] == "may" for line in requirements) == 1
    assert sum("lead_in" in line for line in requirements) == 2
    assert sum(line["kind"] == "risk_seed" for line in lines) == 3
    assert {line["kind"] for line in lines} == {"requirement", "background", "risk_seed"}


def test_the_pdf_has_four_pages_with_a_repeated_header(rendered: Path) -> None:
    with pdfplumber.open(rendered) as pdf:
        first_lines = [(page.extract_text() or "").splitlines()[0] for page in pdf.pages]
    assert len(first_lines) == 4
    assert len(set(first_lines)) == 1
