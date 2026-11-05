"""Streamlit UI tests (`WP-3.6`, `CH-94`): `AppTest` over `samples/dev` and synthetic fixtures."""

import json
import shutil
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from app.data import load_compliance_matrix, load_run_data
from bidwright.obs.ledger import read_ledger, totals_of
from bidwright.preflight import HOME

APP_DIR = HOME / "app"
MAIN_PAGE = APP_DIR / "main.py"
RUN_PAGE = APP_DIR / "pages" / "run.py"
REVIEW_PAGE = APP_DIR / "pages" / "review.py"
OPS_PAGE = APP_DIR / "pages" / "ops.py"
DEV_SAMPLE = HOME / "samples" / "dev"


def test_each_page_loads_over_samples_dev_with_no_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BIDWRIGHT_OUTPUTS", str(DEV_SAMPLE))
    for page in (MAIN_PAGE, RUN_PAGE, REVIEW_PAGE, OPS_PAGE):
        at = AppTest.from_file(str(page)).run(timeout=15)
        assert len(at.exception) == 0, f"{page.name} raised: {at.exception}"
        assert len(at.markdown) == 0, f"{page.name} rendered Markdown elements: {at.markdown}"


def test_run_page_table_holds_the_compliance_matrix_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BIDWRIGHT_OUTPUTS", str(DEV_SAMPLE))
    expected_rows = load_compliance_matrix(DEV_SAMPLE)
    assert len(expected_rows) > 0

    at = AppTest.from_file(str(RUN_PAGE)).run(timeout=15)
    assert len(at.exception) == 0
    assert len(at.dataframe) == 1
    df = at.dataframe[0].value
    assert len(df) == len(expected_rows)
    assert list(df["Requirement id"]) == [row["Requirement id"] for row in expected_rows]
    assert list(df["Quote"]) == [row["Quote"] for row in expected_rows]


def test_ops_page_totals_equal_ledger_sums_and_manifest_totals(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BIDWRIGHT_OUTPUTS", str(DEV_SAMPLE))
    data = load_run_data(DEV_SAMPLE)
    entries = read_ledger(DEV_SAMPLE / "ledger.jsonl")
    expected_totals = totals_of(entries, active_seconds=data.manifest.totals.active_seconds)
    expected_latency = sum(e.latency_ms for e in entries)

    assert data.manifest.totals == expected_totals
    assert data.ledger_totals.requests == expected_totals.requests
    assert data.ledger_totals.tokens_in == expected_totals.tokens_in
    assert data.ledger_totals.tokens_out == expected_totals.tokens_out
    assert data.ledger_totals.tokens_cached == expected_totals.tokens_cached
    assert data.ledger_totals.tokens_thinking == expected_totals.tokens_thinking
    assert data.ledger_totals.cost_usd == expected_totals.cost_usd
    assert data.ledger_totals.shadow_cost_usd == expected_totals.shadow_cost_usd
    assert data.ledger_totals.latency_ms == expected_latency

    for group_rows in (data.by_node, data.by_model):
        assert sum(r.requests for r in group_rows) == expected_totals.requests
        assert sum(r.tokens_in for r in group_rows) == expected_totals.tokens_in
        assert sum(r.tokens_out for r in group_rows) == expected_totals.tokens_out
        assert sum(r.tokens_cached for r in group_rows) == expected_totals.tokens_cached
        assert sum(r.tokens_thinking for r in group_rows) == expected_totals.tokens_thinking
        assert round(sum(r.cost_usd for r in group_rows), 8) == expected_totals.cost_usd
        assert (
            round(sum(r.shadow_cost_usd for r in group_rows), 8) == expected_totals.shadow_cost_usd
        )
        assert sum(r.latency_ms for r in group_rows) == expected_latency

    at = AppTest.from_file(str(OPS_PAGE)).run(timeout=15)
    assert len(at.exception) == 0
    totals_df = at.table[0].value
    row = totals_df.iloc[0].to_dict()
    assert int(row["requests"]) == expected_totals.requests
    assert int(row["tokens_in"]) == expected_totals.tokens_in
    assert int(row["tokens_out"]) == expected_totals.tokens_out
    assert int(row["tokens_cached"]) == expected_totals.tokens_cached
    assert int(row["tokens_thinking"]) == expected_totals.tokens_thinking
    assert pytest.approx(float(row["cost_usd"]), rel=1e-6) == expected_totals.cost_usd
    assert pytest.approx(float(row["shadow_cost_usd"]), rel=1e-6) == expected_totals.shadow_cost_usd
    assert int(row["latency_ms"]) == expected_latency


def test_a_quote_with_a_markdown_image_link_appears_only_as_plain_text(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture_run = tmp_path / "run-trap"
    shutil.copytree(DEV_SAMPLE, fixture_run)
    trap_quote = "Suppliers must submit ![beacon](https://evil.example.com/leak.png) on time."
    summary_path = fixture_run / "solution_summary.json"
    summary_data = json.loads(summary_path.read_text(encoding="utf-8"))
    summary_data["requirements"][0]["quote"] = trap_quote
    summary_path.write_text(json.dumps(summary_data, indent=1) + "\n", encoding="utf-8")

    monkeypatch.setenv("BIDWRIGHT_OUTPUTS", str(fixture_run))
    for page in (RUN_PAGE, REVIEW_PAGE, OPS_PAGE):
        at = AppTest.from_file(str(page)).run(timeout=15)
        assert len(at.exception) == 0
        assert len(at.markdown) == 0
    at_run = AppTest.from_file(str(RUN_PAGE)).run(timeout=15)
    plain_texts = [el.value for el in at_run.text]
    assert any(trap_quote in text for text in plain_texts)


def test_a_run_with_no_scores_shows_none_and_no_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BIDWRIGHT_OUTPUTS", str(DEV_SAMPLE))
    monkeypatch.setenv("BIDWRIGHT_RESULTS", str(tmp_path / "empty-results"))
    at = AppTest.from_file(str(OPS_PAGE)).run(timeout=15)
    assert len(at.exception) == 0
    texts = [el.value for el in at.text]
    assert "No scores recorded for this run." in texts
    assert any("twice in Phoenix" in t for t in texts)


def test_a_run_with_scores_shows_scores_and_scorecard_as_plain_text(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    results_root = tmp_path / "results"
    run_scores_dir = results_root / "runs" / DEV_SAMPLE.name
    run_scores_dir.mkdir(parents=True)
    (run_scores_dir / "scores.json").write_text(
        json.dumps({"missed_mandatory": 0, "precision_low": 0.92}),
        encoding="utf-8",
    )
    (run_scores_dir / "scorecard.md").write_text(
        "# Scorecard: dev\n- Missed mandatory: 0\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("BIDWRIGHT_OUTPUTS", str(DEV_SAMPLE))
    monkeypatch.setenv("BIDWRIGHT_RESULTS", str(results_root))
    at = AppTest.from_file(str(OPS_PAGE)).run(timeout=15)
    assert len(at.exception) == 0
    assert len(at.markdown) == 0
    assert any("# Scorecard: dev" in el.value for el in at.code)
