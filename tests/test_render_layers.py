"""The renderers on a fixture package that uses every layer: reproducible files, every visible
clause findable, every trap in its layer, small print set small, gold lines of every kind, and
the spec validation rules. The fixture is not a corpus RFP, so these tests need no gold."""

import copy
from pathlib import Path
from typing import Any, get_args

import pytest
import yaml
from pydantic import ValidationError

from evals.render.gold import gold_lines
from evals.render.package import render_package
from evals.render.spec import VISIBLE_LAYERS, Layer, Spec
from tests.render_checks import normalized, text_in_layer, visible_text

FIXTURE = Path(__file__).parent / "data" / "render_layers.yaml"


def _raw() -> dict[str, Any]:
    return yaml.safe_load(FIXTURE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def spec() -> Spec:
    return Spec.model_validate(_raw())


@pytest.fixture(scope="module")
def rendered(spec: Spec, tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("layers")
    render_package(spec, root)
    return root


def _path(root: Path, spec: Spec, file: str) -> Path:
    return root / spec.package / file


def test_the_fixture_uses_every_layer_of_every_format(spec: Spec) -> None:
    layers = {at.trap.layer for at in spec.traps()}
    layers |= {at.clause.layer for at in spec.clauses()}
    assert layers == set(get_args(Layer))


def test_rendering_is_reproducible(
    spec: Spec, rendered: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    again = tmp_path_factory.mktemp("layers-again")
    render_package(spec, again)
    for document in spec.documents:
        first = _path(rendered, spec, document.file).read_bytes()
        assert first == _path(again, spec, document.file).read_bytes(), document.file


def test_the_package_file_and_manifest_list_every_document(spec: Spec, rendered: Path) -> None:
    package = _path(rendered, spec, "package.yaml").read_text(encoding="utf-8")
    for document in spec.documents:
        assert f"{{file: {document.file}, role: {document.role}," in package
    manifest = (rendered / "CORPUS.sha256").read_text(encoding="utf-8").splitlines()
    names = [line.split(maxsplit=1)[1] for line in manifest]
    expected = {f"{spec.package}/{d.file}" for d in spec.documents}
    assert set(names) == expected | {f"{spec.package}/package.yaml"}
    assert names == sorted(names)


def test_every_visible_clause_appears_in_the_visible_text(spec: Spec, rendered: Path) -> None:
    for document in spec.documents:
        text = visible_text(_path(rendered, spec, document.file), document.format)
        for at in spec.clauses(document):
            if at.clause.layer in VISIBLE_LAYERS:
                assert normalized(at.clause.text) in text, at.clause.id
            if at.lead_in is not None:
                assert normalized(at.lead_in) in text, at.clause.id
        for at in spec.personal_data(document):
            assert at.datum.value in text, at.datum.id


def test_every_trap_sits_in_its_layer(spec: Spec, rendered: Path) -> None:
    for at in spec.traps():
        path = _path(rendered, spec, at.document.file)
        assert at.trap.marker in text_in_layer(path, at.document.format, at.trap.layer), at.trap.id


def test_every_hidden_clause_sits_in_its_layer(spec: Spec, rendered: Path) -> None:
    for at in spec.clauses():
        if at.clause.layer not in VISIBLE_LAYERS:
            path = _path(rendered, spec, at.document.file)
            hidden = text_in_layer(path, at.document.format, at.clause.layer)
            assert normalized(at.clause.text) in hidden, at.clause.id


def test_hidden_text_stays_out_of_the_visible_text(spec: Spec, rendered: Path) -> None:
    """Invisible text (render mode 3) is the one layer pdfplumber cannot tell apart."""
    hidden = [(at.trap.marker, at.trap.layer, at.document) for at in spec.traps()]
    hidden += [(at.clause.text, at.clause.layer, at.document) for at in spec.clauses()]
    for text, layer, document in hidden:
        if layer in VISIBLE_LAYERS or layer == "pdf_invisible":
            continue
        seen = visible_text(_path(rendered, spec, document.file), document.format)
        assert normalized(text) not in seen, (layer, text)


def test_small_print_is_set_small(spec: Spec, rendered: Path) -> None:
    for at in spec.clauses():
        if at.clause.layer == "small_print":
            path = _path(rendered, spec, at.document.file)
            small = text_in_layer(path, at.document.format, "small_print")
            assert normalized(at.clause.text) in small, at.clause.id


def test_gold_lines_cover_clauses_traps_personal_data_and_seeds(spec: Spec) -> None:
    lines = gold_lines(spec)
    assert all(line["gold_version"] == 1 for line in lines)
    by_kind: dict[str, list[dict[str, Any]]] = {}
    for line in lines:
        by_kind.setdefault(line["kind"], []).append(line)
    assert {line["gold_id"] for line in by_kind["requirement"]} == {
        at.clause.id for at in spec.clauses() if at.clause.gold.kind == "requirement"
    }
    assert by_kind["not_binding"][0]["disposition"] == "NOT_BINDING"
    assert by_kind["out_of_scope"][0]["disposition"] == "OUT_OF_SCOPE"
    assert by_kind["background"][0]["disposition"] == "BACKGROUND"
    small = next(line for line in lines if line["gold_id"] == "GR-0007")
    assert small["small_print"] is True and small["layer"] == "small_print"
    cell = next(line for line in lines if line["gold_id"] == "GR-0008")
    assert cell["implicit"] == "table_cell" and cell["disposition"] == "BINDING"
    traps = {line["gold_id"]: line for line in by_kind["trap"]}
    assert traps["TR-01"]["expect"] == {"quarantined": False, "action_taken": False}
    assert traps["TR-09"]["expect"] == {"quarantined": True, "action_taken": False}
    assert traps["TR-09"]["doc_id"] == "layers-annex-b"
    assert {line["gold_id"] for line in by_kind["personal_data"]} == {"PD-01", "PD-02"}
    assert {line["kind"] for line in lines} >= {
        "risk_seed",
        "gap_seed",
        "clarification_seed",
        "discrepancy_seed",
        "contract_term",
        "lint_seed",
        "duplicate_seed",
    }
    gap = by_kind["gap_seed"][0]
    assert gap["absent_terms"] == ["Quillbeck"] and gap["doc_id"] == "layers-main"
    assert by_kind["contract_term"][0]["category"] == "LIABILITY"


def _without_gold(raw: dict[str, Any]) -> dict[str, Any]:
    del raw["documents"][0]["sections"][0]["blocks"][2]["gold"]
    return raw


def _trap_without_marker(raw: dict[str, Any]) -> dict[str, Any]:
    raw["documents"][0]["sections"][0]["blocks"][3]["trap"]["marker"] = ""
    return raw


def _datum_not_in_text(raw: dict[str, Any]) -> dict[str, Any]:
    raw["documents"][0]["sections"][0]["blocks"][1]["personal_data"][0]["value"] = "Nobody"
    return raw


def _unknown_anchor(raw: dict[str, Any]) -> dict[str, Any]:
    raw["seeds"][0]["anchors"] = ["GR-9999"]
    return raw


def _wrong_layer_for_the_format(raw: dict[str, Any]) -> dict[str, Any]:
    raw["documents"][0]["sections"][0]["blocks"][3]["trap"]["layer"] = "docx_hidden_run"
    return raw


def _three_discrepancy_anchors(raw: dict[str, Any]) -> dict[str, Any]:
    raw["seeds"][3]["anchors"] = ["GR-0004", "GR-0010", "GR-0001"]
    return raw


def _cell_requirement_not_implicit(raw: dict[str, Any]) -> dict[str, Any]:
    cell = raw["documents"][0]["sections"][2]["blocks"][1]["table"]["rows"][0][0]
    cell["gold"]["implicit"] = None
    return raw


def _hidden_trap_on_a_visible_sheet(raw: dict[str, Any]) -> dict[str, Any]:
    raw["documents"][2]["sheets"][1]["state"] = "visible"
    return raw


def _hidden_sheet_clause_on_a_visible_sheet(raw: dict[str, Any]) -> dict[str, Any]:
    raw["documents"][2]["sheets"][0]["rows"][2][1]["layer"] = "xlsx_very_hidden_sheet"
    return raw


def _hidden_clause_in_a_table_cell(raw: dict[str, Any]) -> dict[str, Any]:
    cell = raw["documents"][0]["sections"][2]["blocks"][1]["table"]["rows"][0][0]
    cell["layer"] = "pdf_invisible"
    return raw


@pytest.mark.parametrize(
    "mutate",
    [
        _without_gold,
        _trap_without_marker,
        _datum_not_in_text,
        _unknown_anchor,
        _wrong_layer_for_the_format,
        _three_discrepancy_anchors,
        _cell_requirement_not_implicit,
        _hidden_trap_on_a_visible_sheet,
        _hidden_sheet_clause_on_a_visible_sheet,
        _hidden_clause_in_a_table_cell,
    ],
)
def test_spec_validation_rejects(mutate: Any) -> None:
    with pytest.raises(ValidationError):
        Spec.model_validate(mutate(copy.deepcopy(_raw())))
