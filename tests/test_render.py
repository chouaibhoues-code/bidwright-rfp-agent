"""The corpus renderers: every package renders to the committed files, every visible clause is
findable, every trap sits in its layer, and the committed gold matches the spec."""

import hashlib
import json
from pathlib import Path

import pdfplumber
import pytest

from evals.render.gold import GOLD_DIR, gold_lines
from evals.render.package import INPUTS_DIR, MANIFEST, render_package
from evals.render.spec import CORPUS_DIR, VISIBLE_LAYERS, Spec, load_spec
from tests.render_checks import normalized, text_in_layer, visible_text

pytestmark = pytest.mark.gold
CORPORA = sorted(path.parent.name for path in CORPUS_DIR.glob("*/spec.yaml"))


@pytest.fixture(scope="module", params=CORPORA)
def spec(request: pytest.FixtureRequest) -> Spec:
    return load_spec(request.param)


@pytest.fixture(scope="module")
def rendered(spec: Spec, tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp(f"render-{spec.corpus}")
    render_package(spec, root)
    return root


def _files(spec: Spec) -> list[str]:
    files = [f"{spec.package}/{document.file}" for document in spec.documents]
    if len(spec.documents) > 1:
        files.append(f"{spec.package}/package.yaml")
    return files


def test_rendering_is_reproducible(
    spec: Spec, rendered: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    again = tmp_path_factory.mktemp("again")
    render_package(spec, again)
    for file in _files(spec):
        assert (rendered / file).read_bytes() == (again / file).read_bytes(), file


def test_rendered_files_match_the_committed_inputs_and_manifest(spec: Spec, rendered: Path) -> None:
    lines = MANIFEST.read_text(encoding="utf-8").splitlines()
    for file in _files(spec):
        digest = hashlib.sha256((rendered / file).read_bytes()).hexdigest()
        assert digest == hashlib.sha256((INPUTS_DIR / file).read_bytes()).hexdigest(), file
        assert f"{digest}  {file}" in lines


def test_every_visible_clause_appears_in_the_visible_text(spec: Spec, rendered: Path) -> None:
    for document in spec.documents:
        text = visible_text(rendered / spec.package / document.file, document.format)
        for at in spec.clauses(document):
            if at.clause.layer in VISIBLE_LAYERS:
                assert normalized(at.clause.text) in text, at.clause.id
            if at.lead_in is not None:
                assert normalized(at.lead_in) in text, at.clause.id
        for at in spec.personal_data(document):
            assert at.datum.value in text, at.datum.id


def test_every_trap_and_hidden_clause_sits_in_its_layer(spec: Spec, rendered: Path) -> None:
    for at in spec.traps():
        path = rendered / spec.package / at.document.file
        assert at.trap.marker in text_in_layer(path, at.document.format, at.trap.layer), at.trap.id
    for at in spec.clauses():
        if at.clause.layer not in VISIBLE_LAYERS:
            path = rendered / spec.package / at.document.file
            hidden = text_in_layer(path, at.document.format, at.clause.layer)
            assert normalized(at.clause.text) in hidden, at.clause.id


def test_committed_gold_matches_the_spec(spec: Spec) -> None:
    committed = (GOLD_DIR / spec.corpus / "gold.jsonl").read_text(encoding="utf-8")
    lines = [json.loads(line) for line in committed.splitlines()]
    assert lines == gold_lines(spec)
    assert all(line["gold_version"] == spec.gold_version for line in lines)


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


def test_the_dev_pdf_has_four_pages_with_a_repeated_header(spec: Spec, rendered: Path) -> None:
    if spec.corpus != "dev":
        pytest.skip("the development RFP only")
    with pdfplumber.open(rendered / spec.package / spec.documents[0].file) as pdf:
        first_lines = [(page.extract_text() or "").splitlines()[0] for page in pdf.pages]
    assert len(first_lines) == 4
    assert len(set(first_lines)) == 1
