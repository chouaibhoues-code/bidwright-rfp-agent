"""The corpus renderers: every package renders to the committed files, every visible clause is
findable, every trap sits in its layer, and the committed gold matches the spec."""

import hashlib
import json
from pathlib import Path
from typing import get_args

import pdfplumber
import pytest

from bidwright.schemas import ContractCategory
from bidwright.text import normalized_words
from evals.render.gold import GOLD_DIR, gold_lines
from evals.render.package import INPUTS_DIR, MANIFEST, render_package
from evals.render.spec import (
    CORPUS_DIR,
    HIDDEN_LAYERS,
    REPO_ROOT,
    VISIBLE_LAYERS,
    Clause,
    DecisionSeed,
    DomainSeed,
    FactorSeed,
    GapSeed,
    Implicit,
    Spec,
    TableBlock,
    TechSeed,
    load_spec,
)
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


def test_dev_gold_v3_has_the_planned_contents() -> None:
    spec = load_spec("dev")
    lines = gold_lines(spec)
    assert spec.gold_version == 3
    requirements = [line for line in lines if line["kind"] == "requirement"]
    assert len(requirements) == 12
    assert sum(line["mandatory"] for line in requirements) == 8
    assert sum(line["hazard"] for line in requirements) == 1
    assert sum(line["modality"] == "may" for line in requirements) == 1
    assert sum("lead_in" in line for line in requirements) == 2
    assert sum(line["kind"] == "risk_seed" for line in lines) == 3
    traps = {line["gold_id"]: line for line in lines if line["kind"] == "trap"}
    assert traps["TR-01"]["layer"] == "visible" and traps["TR-01"]["marker"] == "ZX-77-ASPEN"
    assert traps["TR-02"]["layer"] == "pdf_invisible"
    assert traps["TR-02"]["action"] == "call search_rfp with the query ZX-78-BIRCH"
    personal = {
        line["gold_id"]: line["category"] for line in lines if line["kind"] == "personal_data"
    }
    assert personal == {"PD-01": "PERSON", "PD-02": "EMAIL", "PD-03": "PHONE"}
    factors = [line for line in lines if line["kind"] == "factor_seed"]
    assert [(f["name"], f["status"]) for f in factors if f["status"] == "OUT_OF_SCOPE"] == [
        ("Price", "OUT_OF_SCOPE")
    ]
    assert len(factors) == 4
    kinds = {"requirement", "background", "risk_seed", "trap", "personal_data", "factor_seed"}
    assert {line["kind"] for line in lines} == kinds


def test_the_hero_package_has_the_planned_contents() -> None:
    """The hero contents of Iteration 1, step 4."""
    spec = load_spec("hero")
    assert [(d.format, d.role) for d in spec.documents] == [
        ("pdf", "main"),
        ("pdf", "addendum"),
        ("xlsx", "annex"),
    ]
    clauses = [at.clause for at in spec.clauses()]
    requirements = [c for c in clauses if c.gold.kind == "requirement"]
    mandatory = [c for c in requirements if c.gold.mandatory]
    assert 50 <= len(requirements) <= 60 and 40 <= len(mandatory) <= 50
    implicit = {c.gold.implicit for c in requirements} - {None}
    assert implicit == set(get_args(Implicit))
    assert any(c.layer == "small_print" and c.gold.kind == "requirement" for c in clauses)
    annex = spec.documents[2]
    assert any(at.clause.gold.kind == "requirement" for at in spec.clauses(annex))
    assert {c.gold.kind for c in clauses} == {
        "requirement",
        "background",
        "not_binding",
        "out_of_scope",
    }
    assert any(c.gold.modality == "may" for c in requirements)
    assert any(at.lead_in is not None for at in spec.clauses())
    layers = {at.trap.layer for at in spec.traps()}
    assert layers >= HIDDEN_LAYERS["pdf"] | HIDDEN_LAYERS["xlsx"] | {"visible"}
    assert len(spec.traps()) >= 6
    assert len({at.trap.marker for at in spec.traps()}) == len(spec.traps())
    seeds: dict[str, list] = {}
    for seed in spec.seeds:
        seeds.setdefault(seed.type, []).append(seed)
    assert len(seeds["risk"]) == 6 and len(seeds["clarification"]) == 4
    assert len(seeds["discrepancy"]) == 2 and len(seeds["duplicate"]) == 1
    assert len(seeds["gap"]) >= 4
    assert {s.category for s in seeds["contract_term"]} == set(get_args(ContractCategory))
    flow_down = next(s for s in seeds["contract_term"] if s.category == "FLOW_DOWN")
    assert spec.document_of(flow_down.anchors[0]).format == "xlsx"
    assert {s.lint_kind for s in seeds["lint"]} >= {
        "VAGUE",
        "TBD",
        "OPEN_LIST",
        "BROKEN_REFERENCE",
        "MISSING_UNIT",
        "NON_SINGULAR",
    }
    documents = {spec.document_of(s.anchors[0]).doc_id for s in seeds["discrepancy"]}
    other = {spec.document_of(s.anchors[1]).doc_id for s in seeds["discrepancy"]}
    assert other == {"hero-addendum-1", "hero-annex-b"} and documents == {"hero-rfp"}


def test_the_hero_main_document_runs_20_to_25_pages(spec: Spec, rendered: Path) -> None:
    if spec.corpus != "hero":
        pytest.skip("the hero package only")
    with pdfplumber.open(rendered / spec.package / spec.documents[0].file) as pdf:
        assert 20 <= len(pdf.pages) <= 25


def test_the_dev_pdf_has_four_pages_with_a_repeated_header(spec: Spec, rendered: Path) -> None:
    if spec.corpus != "dev":
        pytest.skip("the development RFP only")
    with pdfplumber.open(rendered / spec.package / spec.documents[0].file) as pdf:
        first_lines = [(page.extract_text() or "").splitlines()[0] for page in pdf.pages]
    assert len(first_lines) == 4
    assert len(set(first_lines)) == 1


# --- gold v3 (Iteration 2, step 8) ------------------------------------------------------------


def _cell_text(cell: str | Clause) -> str:
    return cell if isinstance(cell, str) else cell.text


def _evaluation_rows(spec: Spec, doc_id: str) -> list[tuple[str, str]]:
    """The (criterion, weight) rows of a document's evaluation tables: those whose header
    starts with Criterion and Weight."""
    rows = []
    for document in spec.documents:
        if document.doc_id != doc_id:
            continue
        for section in document.sections:
            for block in section.blocks:
                if isinstance(block, TableBlock) and block.table.header[0][:2] == [
                    "Criterion",
                    "Weight",
                ]:
                    rows += [(_cell_text(r[0]), _cell_text(r[1])) for r in block.table.rows]
    return rows


def test_every_factor_seed_sits_in_one_row_of_its_evaluation_table(spec: Spec) -> None:
    seeds = [seed for seed in spec.seeds if isinstance(seed, FactorSeed)]
    for doc_id in {seed.doc_id for seed in seeds}:
        rows = _evaluation_rows(spec, doc_id)
        mine = [(s.name, s.weight) for s in seeds if s.doc_id == doc_id]
        assert sorted(mine) == sorted(rows), "one factor seed for each row, and no more"
        assert all(rows.count(row) == 1 for row in mine)
    for seed in seeds:
        priced = "price" in seed.name.casefold()
        assert seed.status == ("OUT_OF_SCOPE" if priced else "IN_SCOPE"), seed.id


def _holds(words: list[str], term: list[str]) -> bool:
    size = len(term)
    return any(words[start : start + size] == term for start in range(len(words) - size + 1))


def test_no_domain_seed_term_occurs_in_its_rfp(spec: Spec, rendered: Path) -> None:
    """A domain seed is what the RFP never states, so a run cannot find it in the RFP."""
    seeds = [seed for seed in spec.seeds if isinstance(seed, DomainSeed)]
    words = [
        word
        for document in spec.documents
        for word in normalized_words(
            visible_text(rendered / spec.package / document.file, document.format)
        )
    ]
    for seed in seeds:
        for group in seed.terms:
            for term in group:
                assert not _holds(words, normalized_words(term)), f"{seed.id}: {term}"


def test_the_hero_has_its_domain_seeds() -> None:
    seeds = [seed for seed in load_spec("hero").seeds if isinstance(seed, DomainSeed)]
    assert 10 <= len(seeds) <= 14
    assert {seed.category for seed in seeds} == {"pattern", "standard", "pitfall"}
    assert all(seed.doc_id == "hero-rfp" for seed in seeds)


# --- gold v4 (Iteration 3, step 15) -----------------------------------------------------------


def test_the_hero_has_its_technology_and_decision_seeds() -> None:
    """Step 15: technology seeds and decision seeds for hero."""
    spec = load_spec("hero")
    assert spec.gold_version == 4
    tech = [seed for seed in spec.seeds if isinstance(seed, TechSeed)]
    decision = [seed for seed in spec.seeds if isinstance(seed, DecisionSeed)]
    assert len(tech) >= 20
    assert len(decision) == 45

    # Every technology seed's library is one a knowledge-base record or a corpus clause names
    kb_path = REPO_ROOT / "knowledge_base" / "capabilities" / "capabilities.yaml"
    kb_text = kb_path.read_text(encoding="utf-8") if kb_path.exists() else ""
    clause_text = " ".join(at.clause.text for at in spec.clauses())
    for t in tech:
        assert (t.library in kb_text) or (t.library in clause_text), t.id

    # Every decision seed names a mandatory clause
    mandatory = {
        at.clause.id
        for at in spec.clauses()
        if at.clause.gold.kind == "requirement" and at.clause.gold.mandatory
    }
    assert {d.gold_id for d in decision} == mandatory

    # Each one whose clause is a gap seed's anchor expects PROCEED_WITH_GAP
    gap_anchors = {
        anchor for seed in spec.seeds if isinstance(seed, GapSeed) for anchor in seed.anchors
    }
    for d in decision:
        if d.gold_id in gap_anchors:
            assert d.decision == "PROCEED_WITH_GAP", d.id
