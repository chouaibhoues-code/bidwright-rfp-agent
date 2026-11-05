"""Streamlit UI tests (`WP-3.6`, `CH-94`): `AppTest` over `samples/dev` and Iteration 3 fixtures."""

import ast
import json
import shutil
import subprocess
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest
import yaml
from streamlit.testing.v1 import AppTest

from app.data import (
    allowed_edit_fields,
    build_approve_command,
    load_compliance_matrix,
    load_run_data,
)
from bidwright.obs.ledger import read_ledger, totals_of
from bidwright.preflight import HOME

APP_DIR = HOME / "app"
MAIN_PAGE = APP_DIR / "main.py"
RUN_PAGE = APP_DIR / "pages" / "run.py"
REVIEW_PAGE = APP_DIR / "pages" / "review.py"
OPS_PAGE = APP_DIR / "pages" / "ops.py"
DEV_SAMPLE = HOME / "samples" / "dev"
DUMMY_SHA = "sha256:" + "a" * 64


def _write_iter3_fixture(run_dir: Path, *, status: str = "WAITING_HUMAN") -> None:
    """Populate `run_dir` with Iteration 3 capability map, options, manifest, tech validations,
    and gate review / approval artifacts."""
    shutil.copytree(DEV_SAMPLE, run_dir)
    manifest_path = run_dir / "run_manifest.json"
    manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest_data["status"] = status
    manifest_path.write_text(json.dumps(manifest_data, indent=1) + "\n", encoding="utf-8")

    (run_dir / "capability_map.json").write_text(
        json.dumps(
            {
                "rows": [
                    {
                        "need_id": "RG-001",
                        "origin": "RFP",
                        "text": "Identity federation and SSO",
                        "decision": "RETRIEVE_EVIDENCE",
                        "status": "COVERED",
                        "claim_ids": ["CL-001"],
                        "reason": "All claims supported",
                    },
                    {
                        "need_id": "RG-002",
                        "origin": "RFP",
                        "text": "Legacy mainframes integration",
                        "decision": "PROCEED_WITH_GAP",
                        "status": "GAP",
                        "claim_ids": [],
                        "reason": "No supported claim",
                    },
                ],
                "counts": {"COVERED": 1, "PARTIAL": 0, "PARTNER": 0, "GAP": 1},
            },
            indent=1,
        )
        + "\n",
        encoding="utf-8",
    )

    (run_dir / "options.json").write_text(
        json.dumps(
            {
                "options": [
                    {
                        "id": "OPT-1",
                        "name": "Phased OOTB rollout",
                        "summary": "Baseline phased rollout with minimal custom code",
                        "baseline": True,
                        "approach": [
                            {
                                "need_id": "RG-001",
                                "delivery_mode": "OOTB",
                                "claim_ids": ["CL-001"],
                            }
                        ],
                        "assumptions": ["Client provides IdP metadata"],
                        "scores": [
                            {
                                "factor_id": "EF-01",
                                "score": 4,
                                "reason": "Strong fit",
                            }
                        ],
                        "needs_proof": [],
                        "failed_gates": [],
                        "total": 4.0,
                        "rank": 1,
                    },
                    {
                        "id": "OPT-2",
                        "name": "Custom adapter suite",
                        "summary": "Full custom adapter build",
                        "baseline": False,
                        "approach": [
                            {
                                "need_id": "RG-002",
                                "delivery_mode": "CUSTOM",
                                "claim_ids": [],
                            }
                        ],
                        "assumptions": ["Adapter spec signed in week 2"],
                        "scores": [
                            {
                                "factor_id": "EF-01",
                                "score": 3,
                                "reason": "Higher delivery risk",
                            }
                        ],
                        "needs_proof": [],
                        "failed_gates": [],
                        "total": 3.0,
                        "rank": 2,
                    },
                ],
                "weighting": "stated",
                "hypothetical": True,
                "notes": [],
            },
            indent=1,
        )
        + "\n",
        encoding="utf-8",
    )

    (run_dir / "manifest.json").write_text(
        json.dumps(
            {
                "option_id": "OPT-1",
                "revision": 0,
                "current_state": [
                    {
                        "text": "Manual identity provisioning",
                        "evidence_class": "RFP_SOURCE",
                        "source_ids": ["SRC-0001"],
                        "needs_proof": False,
                    }
                ],
                "target_state": [
                    {
                        "text": "Automated SAML/OIDC federation",
                        "evidence_class": "CAPABILITY_EVIDENCE",
                        "source_ids": ["CL-001"],
                        "needs_proof": False,
                    }
                ],
                "workstreams": [
                    {
                        "code": "1",
                        "name": "Identity Platform",
                        "objective": "Stand up federated SSO",
                    }
                ],
                "wbs": [
                    {
                        "code": "1",
                        "name": "Identity Platform",
                        "deliverable": "Platform release",
                    },
                    {
                        "code": "1.1",
                        "name": "Federation Core",
                        "deliverable": "SSO configuration pack",
                    },
                ],
                "work_packages": [
                    {
                        "code": "1.1.1",
                        "name": "SAML Broker Setup",
                        "deliverable": "Configured broker",
                        "requirement_ids": ["REQ-0001"],
                        "need_ids": ["RG-001"],
                        "claim_ids": ["CL-001"],
                        "scope": "Configure SAML 2.0 broker",
                        "exclusions": "Legacy hardware tokens",
                        "acceptance": "IdP login passes smoke test",
                        "effort": {
                            "low_days": 5.0,
                            "high_days": 10.0,
                            "basis": "analogy",
                            "basis_text": "Prior delivery",
                            "role_ids": ["ROLE-001"],
                            "uncertainty": "IdP readiness",
                            "maturity": "CLASS_5",
                            "provisional": True,
                        },
                        "verification": [
                            {
                                "requirement_id": "REQ-0001",
                                "method": "TEST",
                            }
                        ],
                        "predecessors": [],
                        "evidence_class": "CAPABILITY_EVIDENCE",
                        "needs_proof": False,
                        "untraced": False,
                    },
                    {
                        "code": "1.1.2",
                        "name": "Role Mapping Cutover",
                        "deliverable": "RBAC matrix",
                        "requirement_ids": ["REQ-0002"],
                        "need_ids": ["RG-001"],
                        "claim_ids": ["CL-001"],
                        "scope": "Map directory groups to roles",
                        "exclusions": "Custom HR schema",
                        "acceptance": "Audit sign-off on role matrix",
                        "effort": {
                            "low_days": 3.0,
                            "high_days": 6.0,
                            "basis": "expert_judgment",
                            "basis_text": "Architect estimate",
                            "role_ids": ["ROLE-001"],
                            "uncertainty": "Directory hygiene",
                            "maturity": "CLASS_5",
                            "provisional": True,
                        },
                        "verification": [
                            {
                                "requirement_id": "REQ-0002",
                                "method": "INSPECTION",
                            }
                        ],
                        "predecessors": ["1.1.1"],
                        "evidence_class": "CAPABILITY_EVIDENCE",
                        "needs_proof": False,
                        "untraced": False,
                    },
                ],
                "assumptions": [
                    {
                        "text": "Sandbox IdP available in week 1",
                        "evidence_class": "ASSUMPTION",
                        "source_ids": [],
                        "needs_proof": False,
                    }
                ],
                "ground_rules": [
                    {
                        "text": "All changes go through staging first",
                        "evidence_class": "ASSUMPTION",
                        "source_ids": [],
                        "needs_proof": False,
                    }
                ],
                "tech_claims": [
                    {
                        "id": "TC-01",
                        "text": "FastAPI supports OAuth2Bearer",
                        "library": "fastapi",
                        "version": "0.115",
                        "wbs_code": "1.1.1",
                        "kind": "LIBRARY",
                    }
                ],
                "benefits": [],
                "win_themes": [],
                "pdca": [],
                "gaps": [],
                "checks": [
                    {"name": "tree", "passed": True, "detail": "All parents present"},
                    {"name": "100_percent", "passed": True, "detail": "All binding covered"},
                ],
                "failed": False,
                "notes": [],
            },
            indent=1,
        )
        + "\n",
        encoding="utf-8",
    )

    (run_dir / "tech_validations.jsonl").write_text(
        json.dumps(
            {
                "claim_id": "TC-01",
                "library": "fastapi",
                "version": "0.115",
                "verdict": "VALIDATED",
                "quote": "OAuth2PasswordBearer security utility",
                "source": "libraries-v1",
                "reason": "Confirmed in FastAPI security docs",
                "revision": 0,
            }
        )
        + "\n",
        encoding="utf-8",
    )

    review_dir = run_dir / "review"
    review_dir.mkdir(exist_ok=True)
    (review_dir / "solution_gate.md").write_text(
        "# Solution Gate\nChosen option: OPT-1 (Phased OOTB rollout)\n",
        encoding="utf-8",
    )
    if status != "WAITING_HUMAN":
        (review_dir / "solution_gate.approval.yaml").write_text(
            yaml.safe_dump(
                {
                    "gate": "solution_gate",
                    "run_id": manifest_data["run_id"],
                    "reviewed": {"manifest": DUMMY_SHA, "options": DUMMY_SHA},
                    "decision": "approve",
                    "option_id": "OPT-1",
                    "approver_role": "Bid Director",
                    "decided": "2026-11-05T15:00:00Z",
                    "edits": [],
                    "override_reason": None,
                    "reject_reason": None,
                    "auto_selected": False,
                    "edited_sha256": None,
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )


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


def test_run_page_shows_capability_map_rows_by_status_and_work_packages_under_parent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_dir = tmp_path / "run-iter3"
    _write_iter3_fixture(run_dir, status="COMPLETED")
    monkeypatch.setenv("BIDWRIGHT_OUTPUTS", str(run_dir))

    at = AppTest.from_file(str(RUN_PAGE)).run(timeout=15)
    assert len(at.exception) == 0
    assert len(at.markdown) == 0
    texts = [el.value for el in at.text]
    assert any("RG-001 [COVERED]" in t and "Identity federation and SSO" in t for t in texts)
    assert any("RG-002 [GAP]" in t and "Legacy mainframes integration" in t for t in texts)
    assert any(
        "Parent 1.1 (Federation Core) -> 1.1.1 SAML Broker Setup [CAPABILITY_EVIDENCE]" in t
        for t in texts
    )
    assert any(
        "Parent 1.1 (Federation Core) -> 1.1.2 Role Mapping Cutover [CAPABILITY_EVIDENCE]" in t
        for t in texts
    )
    assert any("TC-01 (fastapi 0.115): VALIDATED" in t for t in texts)


def test_review_form_builds_exact_approve_command_and_stdin_and_blocks_outside_fields(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_dir = tmp_path / "run-waiting"
    _write_iter3_fixture(run_dir, status="WAITING_HUMAN")
    monkeypatch.setenv("BIDWRIGHT_OUTPUTS", str(run_dir))

    recorded: list[tuple[list[str], str | None]] = []

    def fake_run_approve(
        cmd: Sequence[str],
        stdin_text: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        recorded.append((list(cmd), stdin_text))
        return subprocess.CompletedProcess(
            args=list(cmd),
            returncode=0,
            stdout="COMPLETED: resumed after gate edit\n",
            stderr="",
        )

    monkeypatch.setattr("app.data.run_approve", fake_run_approve)

    data = load_run_data(run_dir)
    editable = allowed_edit_fields(data.solution_manifest)
    at = AppTest.from_file(str(REVIEW_PAGE)).run(timeout=15)
    assert len(at.exception) == 0
    assert len(at.markdown) == 0
    assert any("Chosen option: OPT-1" in el.value for el in at.code)

    # Every edit widget key in the form is restricted strictly to section 4.8's allowed field paths.
    edit_widget_keys = {
        el.key
        for group in (at.number_input, at.multiselect, at.text_input)
        for el in group
        if el.key and el.key.startswith("edit:")
    }
    assert edit_widget_keys == {f"edit:{path}" for path in editable}

    # An edit outside section 4.8's field paths cannot be entered or built.
    with pytest.raises(ValueError, match="not allowed by section 4.8"):
        build_approve_command(
            run_dir,
            role="Solution Architect",
            edits=[{"field": "workstreams[0].name", "value": "Forbidden"}],
            manifest=data.solution_manifest,
        )

    # Fill the form with an approver role, two section-4.8 edits, and an override reason.
    at.text_input(key="gate_role").set_value("Solution Architect")
    at.number_input(key="edit:work_packages[1.1.1].effort.low_days").set_value(7.5)
    at.text_input(key="edit:assumptions[0].text").set_value("IdP metadata delivered on day 1")
    at.text_input(key="gate_override").set_value("Waived by Bid Director")
    at.button[0].click()
    at = at.run(timeout=15)

    assert len(at.exception) == 0
    assert len(recorded) == 1
    cmd, stdin_text = recorded[0]
    assert cmd == [
        "bidwright",
        "approve",
        str(run_dir),
        "--role",
        "Solution Architect",
        "--edit",
        "-",
        "--override",
        "Waived by Bid Director",
    ]
    assert stdin_text is not None
    parsed_stdin: list[dict[str, Any]] = yaml.safe_load(stdin_text)
    assert parsed_stdin == [
        {"field": "work_packages[1.1.1].effort.low_days", "value": 7.5},
        {"field": "assumptions[0].text", "value": "IdP metadata delivered on day 1"},
    ]


def test_review_page_for_run_not_waiting_shows_approval_file_and_no_form(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_dir = tmp_path / "run-approved"
    _write_iter3_fixture(run_dir, status="COMPLETED")
    monkeypatch.setenv("BIDWRIGHT_OUTPUTS", str(run_dir))

    at = AppTest.from_file(str(REVIEW_PAGE)).run(timeout=15)
    assert len(at.exception) == 0
    assert len(at.markdown) == 0
    assert len(at.button) == 0
    texts = [el.value for el in at.text]
    assert any("Decision: approve | Role: Bid Director | Option: OPT-1" in t for t in texts)
    assert any("approver_role: Bid Director" in el.value for el in at.code)


def test_ops_page_shows_keep_or_drop_ladder_verdict_and_interval_and_matrix_totals(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    outputs_root = tmp_path / "outputs"
    run_a = outputs_root / "matrices" / "ex-ladder" / "run-ex0"
    run_b = outputs_root / "matrices" / "ex-ladder" / "run-ex1"
    shutil.copytree(DEV_SAMPLE, run_a)
    shutil.copytree(DEV_SAMPLE, run_b)

    results_root = tmp_path / "results"
    ladder_dir = results_root / "ex-ladder"
    ladder_dir.mkdir(parents=True)
    (ladder_dir / "report.json").write_text(
        json.dumps(
            {
                "matrix": "ex-ladder",
                "gold": "hero v4",
                "runs": 2,
                "finished": 2,
                "fell_back": [],
                "rungs": {
                    "EX0": {
                        "missed_mandatory_count": {"median": 4.0, "min": 3.0, "max": 5.0, "n": 1},
                        "cost_usd": {"median": 0.10, "min": 0.10, "max": 0.10, "n": 1},
                    },
                    "EX1": {
                        "missed_mandatory_count": {"median": 2.0, "min": 2.0, "max": 2.0, "n": 1},
                        "cost_usd": {"median": 0.18, "min": 0.18, "max": 0.18, "n": 1},
                    },
                },
                "decisions": [
                    {
                        "rung": "EX1",
                        "control": "EX0",
                        "metric": "missed_mandatory_count",
                        "kind": "keep_or_drop",
                        "verdict": "keep",
                        "interval": [0.5, 2.5],
                        "cost_per_avoided_miss": 0.04,
                        "detail": "d=2.0 [0.5, 2.5]",
                    }
                ],
            },
            indent=1,
        )
        + "\n",
        encoding="utf-8",
    )

    monkeypatch.setenv("BIDWRIGHT_OUTPUTS", str(outputs_root))
    monkeypatch.setenv("BIDWRIGHT_RESULTS", str(results_root))

    at = AppTest.from_file(str(OPS_PAGE)).run(timeout=15)
    assert len(at.exception) == 0
    assert len(at.markdown) == 0

    texts = [el.value for el in at.text]
    assert any(
        "ex-ladder EX1 (vs EX0): verdict=keep, interval=[0.5, 2.5]" in t
        and "cost_per_avoided_miss=$0.04" in t
        for t in texts
    )

    single_entries = read_ledger(DEV_SAMPLE / "ledger.jsonl")
    expected_matrix_totals = totals_of(single_entries * 2, active_seconds=0.0)
    matrix_df = at.table[-1].value
    matrix_row = matrix_df.iloc[0].to_dict()
    assert matrix_row["matrix"] == "ex-ladder"
    assert int(matrix_row["requests"]) == expected_matrix_totals.requests
    assert int(matrix_row["tokens_in"]) == expected_matrix_totals.tokens_in
    assert int(matrix_row["tokens_out"]) == expected_matrix_totals.tokens_out
    assert pytest.approx(float(matrix_row["cost_usd"]), rel=1e-6) == expected_matrix_totals.cost_usd


def test_app_modules_write_no_files_directly() -> None:
    forbidden_attrs = {"write_text", "write_bytes", "mkdir", "unlink", "rmdir"}
    for path in sorted(APP_DIR.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name) and node.func.id == "open":
                    raise AssertionError(f"{path} must not call open()")
                if isinstance(node.func, ast.Attribute) and node.func.attr in forbidden_attrs:
                    raise AssertionError(f"{path} must not call .{node.func.attr}()")
