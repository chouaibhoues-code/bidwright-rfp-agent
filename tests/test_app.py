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
    load_compliance_matrix,
    load_run_data,
)
from bidwright.obs.ledger import read_ledger, totals_of
from bidwright.preflight import HOME

APP_DIR = HOME / "app"
MAIN_PAGE = APP_DIR / "main.py"
RUN_PAGE = APP_DIR / "views" / "run.py"
REVIEW_PAGE = APP_DIR / "views" / "review.py"
OPS_PAGE = APP_DIR / "views" / "ops.py"
DEV_SAMPLE = HOME / "samples" / "dev"
DUMMY_SHA = "sha256:" + "a" * 64


@pytest.fixture(autouse=True)
def no_phoenix(monkeypatch: pytest.MonkeyPatch) -> None:
    """The pages ask Phoenix for links; here nothing listens, so no test depends on a Phoenix
    that happens to run on the machine."""
    monkeypatch.setenv("PHOENIX_ENDPOINT", "http://127.0.0.1:9")


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
    matrices = [d for d in at.dataframe if "Requirement id" in d.value.columns]
    assert len(matrices) == 1, "the Files tab's compliance matrix"
    df = matrices[0].value
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
    plain_texts = [el.value for el in at_run.text] + [el.value for el in at_run.code]
    assert any(trap_quote in text for text in plain_texts), "shown as plain text or code"


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


def _fake_approve(recorded: list[tuple[list[str], str | None]], code: int = 0) -> Any:
    def fake_run_approve(
        cmd: Sequence[str], stdin_text: str | None = None
    ) -> subprocess.CompletedProcess[str]:
        recorded.append((list(cmd), stdin_text))
        return subprocess.CompletedProcess(
            args=list(cmd), returncode=code, stdout="COMPLETED: resumed after the gate\n", stderr=""
        )

    return fake_run_approve


def _gate_page(run_dir: Path, monkeypatch: pytest.MonkeyPatch, role: str = "") -> AppTest:
    monkeypatch.setenv("BIDWRIGHT_OUTPUTS", str(run_dir))
    at = AppTest.from_file(str(REVIEW_PAGE)).run(timeout=15)
    assert len(at.exception) == 0
    if role:
        at.text_input(key="review_role").input(role)
        at = at.run(timeout=15)
    return at


def _submit(at: AppTest, label: str) -> AppTest:
    next(b for b in at.button if b.label == label).click()
    return at.run(timeout=15)


def test_the_gate_shows_on_the_page_what_the_decision_rests_on(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-060: options with scores, reasons, approach and assumptions; the capability map; the
    work packages with evidence; the facts; the risks; all as plain text or table cells."""
    run_dir = tmp_path / "run-waiting"
    _write_iter3_fixture(run_dir, status="WAITING_HUMAN")
    at = _gate_page(run_dir, monkeypatch)
    assert len(at.markdown) == 0
    texts = [el.value for el in at.text]
    assert (
        "Rank 1: OPT-1, Phased OOTB rollout. Total 4 of 4. The manifest below is built on this"
        " option." in texts
    )
    assert "Rank 2: OPT-2, Custom adapter suite. Total 3 of 4." in texts
    assert "Assumes: Adapter spec signed in week 2" in texts
    warnings = [el.value for el in at.warning]
    assert any("Answers RG-002 with no claim behind it" in w for w in warnings)
    assert not any("RG-001" in w for w in warnings), "OPT-1 answers RG-001 with a claim"
    subheaders = [el.value for el in at.subheader]
    for heading in (
        "1. The options",
        "2. What the supplier can prove",
        "3. The solution manifest, for OPT-1",
        "4. Risks",
        "5. The decision",
    ):
        assert heading in subheaders
    assert any("Chosen option: OPT-1" in el.value for el in at.code), "the review file"
    assert at.radio(key="gate_decision").value == "Approve"
    assert "Enter your role at the top of the page" in " ".join(warnings)


def test_the_gate_approves_with_grouped_edits_and_shows_the_recorded_decision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_dir = tmp_path / "run-waiting"
    _write_iter3_fixture(run_dir, status="WAITING_HUMAN")
    recorded: list[tuple[list[str], str | None]] = []
    monkeypatch.setattr("app.data.run_approve", _fake_approve(recorded))
    data = load_run_data(run_dir)
    editable = allowed_edit_fields(data.solution_manifest)

    at = _gate_page(run_dir, monkeypatch, role="Solution Architect")
    at.radio(key="gate_decision").set_value("Approve with edits")
    at = at.run(timeout=15)
    assert len(at.exception) == 0 and len(at.markdown) == 0
    # Every edit widget is one of the gate's own field paths, and every such path has one.
    keys = {
        el.key
        for group in (at.number_input, at.multiselect, at.text_area)
        for el in group
        if el.key and el.key.startswith("edit:")
    }
    assert keys == {f"edit:{path}" for path in editable}
    texts = [el.value for el in at.text]
    assert "1.1.1 SAML Broker Setup" in texts and "1.1.2 Role Mapping Cutover" in texts
    assert any(t.startswith("Evidence CAPABILITY_EVIDENCE; requirements REQ-0001") for t in texts)
    labels = {el.label for el in at.number_input}
    assert labels == {"Low estimate (days)", "High estimate (days)"}
    assert "Assumption 1 (ASSUMPTION)" in {el.label for el in at.text_area}

    at.number_input(key="edit:work_packages[1.1.1].effort.low_days").set_value(7.5)
    at.text_area(key="edit:assumptions[1].text").input("IdP metadata delivered   on day 1\n")
    at = _submit(at, "Approve with these edits")
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
    ]
    parsed = yaml.safe_load(stdin_text or "")
    assert parsed == [
        {"field": "work_packages[1.1.1].effort.low_days", "value": 7.5},
        {"field": "assumptions[1].text", "value": "IdP metadata delivered on day 1"},
    ], "only the changed fields, with text as the gate stores it"
    # The page reran on the recorded decision: the result shows, and the form starts clean.
    assert any("The decision is recorded" in el.value for el in at.success)
    assert at.radio(key="gate_decision").value == "Approve"
    # The gate reads the same edits.
    from bidwright.graph.blueprint import apply_edits
    from bidwright.schemas import GateEdit

    assert data.solution_manifest is not None
    edited, _ = apply_edits(data.solution_manifest, [GateEdit(**e) for e in parsed])
    assert edited.assumptions[0].text == "IdP metadata delivered on day 1"


def test_an_edit_decision_with_no_change_or_no_role_runs_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_dir = tmp_path / "run-waiting"
    _write_iter3_fixture(run_dir, status="WAITING_HUMAN")
    recorded: list[tuple[list[str], str | None]] = []
    monkeypatch.setattr("app.data.run_approve", _fake_approve(recorded))
    at = _gate_page(run_dir, monkeypatch)
    at = _submit(at, "Approve OPT-1")
    assert any("Enter your role at the top of the page first" in el.value for el in at.error)
    at.text_input(key="review_role").input("Solution Architect")
    at.radio(key="gate_decision").set_value("Approve with edits")
    at = at.run(timeout=15)
    at = _submit(at, "Approve with these edits")
    assert any("No field changed" in el.value for el in at.error)
    assert recorded == []


def test_reject_needs_a_reason_and_switching_names_the_other_option(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_dir = tmp_path / "run-waiting"
    _write_iter3_fixture(run_dir, status="WAITING_HUMAN")
    recorded: list[tuple[list[str], str | None]] = []
    monkeypatch.setattr("app.data.run_approve", _fake_approve(recorded))
    at = _gate_page(run_dir, monkeypatch, role="Bid director")
    at.radio(key="gate_decision").set_value("Reject")
    at = at.run(timeout=15)
    at = _submit(at, "Reject the solution")
    assert any("Give the reason for the rejection" in el.value for el in at.error)
    at.text_area(key="gate_reject").input("No partner for the service levels")
    at = _submit(at, "Reject the solution")
    assert recorded[-1] == (
        [
            "bidwright",
            "approve",
            str(run_dir),
            "--role",
            "Bid director",
            "--reject",
            "No partner for the service levels",
        ],
        None,
    )
    at.radio(key="gate_decision").set_value("Switch to another option")
    at = at.run(timeout=15)
    assert at.selectbox(key="gate_option").options == ["OPT-2, Custom adapter suite"]
    at = _submit(at, "Switch option")
    assert recorded[-1][0][-2:] == ["--option", "OPT-2"]
    assert len(at.exception) == 0


def test_a_blocked_gate_asks_for_an_override_and_a_refusal_keeps_the_form(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_dir = tmp_path / "run-blocked"
    _write_iter3_fixture(run_dir, status="WAITING_HUMAN")
    validation = json.loads((run_dir / "tech_validations.jsonl").read_text(encoding="utf-8"))
    validation["verdict"] = "INVALIDATED"
    (run_dir / "tech_validations.jsonl").write_text(json.dumps(validation) + "\n", "utf-8")
    recorded: list[tuple[list[str], str | None]] = []
    monkeypatch.setattr("app.data.run_approve", _fake_approve(recorded, code=2))
    at = _gate_page(run_dir, monkeypatch, role="Bid director")
    assert any("Blocked by technology claims still INVALIDATED: TC-01" in e.value for e in at.error)
    at.text_input(key="gate_override").input("Checked by hand against the vendor's release notes")
    at = _submit(at, "Approve OPT-1")
    assert recorded[-1][0][-2:] == [
        "--override",
        "Checked by hand against the vendor's release notes",
    ]
    # The command failed: the error shows and the form is still there to correct.
    assert any("the run still waits at the gate" in e.value for e in at.error)
    assert any(b.label == "Approve OPT-1" for b in at.button)


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
    assert not [r for r in at.radio if r.key == "gate_decision"], "no gate form"
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


# --- ADR-053: the pages share their state, start runs and record verdicts --------------------


def _two_runs(root: Path) -> tuple[Path, Path]:
    older, newer = root / "20261105T000000Z-a", root / "20261106T000000Z-b"
    for run_dir in (older, newer):
        shutil.copytree(DEV_SAMPLE, run_dir)
    return older, newer


def test_the_run_selection_follows_the_url_and_a_page_keeps_the_values_it_is_given(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Persistence rests on three things, each checked here: the entrypoint draws the run
    selector, which takes the URL's run and the session's value; the entrypoint saves every
    sticky key again before the page runs (Streamlit's documented way to keep a widget's value
    on a page that does not draw it); and a page never resets a value it is given. AppTest
    drops an `st.navigation` entrypoint's widgets after its first run, so a page switch inside
    AppTest cannot show the browser's behavior directly."""
    older, _ = _two_runs(tmp_path)
    monkeypatch.setenv("BIDWRIGHT_OUTPUTS", str(tmp_path))
    at = AppTest.from_file(str(MAIN_PAGE))
    at.query_params["run"] = older.name
    at.run(timeout=20)
    assert len(at.exception) == 0
    assert at.sidebar.selectbox(key="run").value == older.name, "the URL names the run"
    assert at.session_state["run"] == older.name

    source = MAIN_PAGE.read_text(encoding="utf-8")
    assert source.index("keep_sticky()") < source.index("navigation.run()")
    from app.state import STICKY_KEYS

    for page, key, value in (
        (RUN_PAGE, "run_search", "audit"),
        (REVIEW_PAGE, "review_role", "Bid manager"),
        (REVIEW_PAGE, "review_unreviewed_only", True),
    ):
        assert key in STICKY_KEYS
        at = AppTest.from_file(str(page))
        at.session_state[key] = value
        at.run(timeout=20)
        assert len(at.exception) == 0
        assert at.session_state[key] == value, (page.name, key)


def test_the_launcher_starts_bidwright_run_with_the_chosen_settings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.actions as actions

    monkeypatch.setenv("BIDWRIGHT_OUTPUTS", str(tmp_path / "none"))
    started: list[tuple[str, list[str], str | None]] = []

    class FakeProcess:
        def poll(self) -> int | None:
            return None

    def fake_start(label: str, command: list[str], run_id: str | None = None) -> actions.Job:
        started.append((label, command, run_id))
        return actions.Job(label, command, run_id, FakeProcess())  # type: ignore[arg-type]

    monkeypatch.setattr("app.actions.start", fake_start)
    at = AppTest.from_file(str(RUN_PAGE)).run(timeout=15)
    assert len(at.exception) == 0
    at.selectbox(key="launch_input").select("inputs/dev/dev_rfp.pdf")
    at.selectbox(key="launch_solution").select("assess")
    at.checkbox(key="launch_reflect").check()
    next(b for b in at.button if b.label == "Start the run").click()
    at = at.run(timeout=15)
    assert len(at.exception) == 0
    assert len(started) == 1
    _, command, run_id = started[0]
    assert run_id is not None and run_id.endswith("-dev-rfp-free-ui")
    assert command[1:4] == ["-m", "bidwright.cli", "run"]
    assert command[4] == "inputs/dev/dev_rfp.pdf"
    flags = command[5:]
    assert flags[flags.index("--solution") + 1] == "assess"
    assert "--reflect" in flags and "--auto-select" not in flags, "a person decides the gate"
    assert flags[flags.index("--run-id") + 1] == run_id


def test_a_launch_of_a_file_outside_inputs_is_refused() -> None:
    import app.actions as actions

    with pytest.raises(ValueError, match="under inputs/"):
        actions.LaunchRequest(source="../private/secret.pdf").command()
    with pytest.raises(ValueError, match="profile"):
        actions.LaunchRequest(source="inputs/dev/dev_rfp.pdf", profile="root").command()


def test_the_review_page_records_verdicts_through_bidwright_review(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_dir = tmp_path / "run-done"
    _write_iter3_fixture(run_dir, status="COMPLETED")
    monkeypatch.setenv("BIDWRIGHT_OUTPUTS", str(run_dir))
    recorded: list[tuple[list[str], str | None]] = []

    def fake_run(command: list[str], stdin_text: str | None = None) -> Any:
        recorded.append((command, stdin_text))
        return subprocess.CompletedProcess(command, 0, "Recorded 1 verdicts\n", "")

    monkeypatch.setattr("app.actions.run", fake_run)
    at = AppTest.from_file(str(REVIEW_PAGE)).run(timeout=15)
    assert len(at.exception) == 0
    assert any("Reviewed" == m.label for m in at.metric)
    at.text_input(key="review_role").input("Bid manager")
    at.checkbox(key="review_auto_sync").uncheck()
    at.radio(key="verdict:REQ-0001").set_value("accept")
    at.text_input(key="note:REQ-0001").input("Checked against the portal rule.")
    next(b for b in at.button if b.label == "Record these verdicts").click()
    at = at.run(timeout=15)
    assert len(at.exception) == 0
    assert len(recorded) == 1
    command, stdin_text = recorded[0]
    assert command[3:] == ["review", str(run_dir), "--role", "Bid manager", "--from", "-"]
    assert yaml.safe_load(stdin_text or "") == [
        {"item": "REQ-0001", "verdict": "accept", "note": "Checked against the portal rule."}
    ]
    assert len(at.markdown) == 0


def test_the_run_page_shows_the_summary_the_input_pdf_and_a_quote_on_its_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The Summary tab holds solution_summary.md as plain text; the Input tab renders the PDF's
    pages; a requirement shows the page that holds its quote, highlighted."""
    monkeypatch.setenv("BIDWRIGHT_OUTPUTS", str(DEV_SAMPLE))
    at = AppTest.from_file(str(RUN_PAGE)).run(timeout=60)
    assert len(at.exception) == 0 and len(at.markdown) == 0
    summary = (DEV_SAMPLE / "solution_summary.md").read_text(encoding="utf-8")
    assert any(el.value.strip() == summary.strip() for el in at.code)
    assert len(at.get("image")) == 2, "the Input tab's page and the requirement's page"
    texts = [el.value for el in at.text]
    assert "dev_rfp.pdf, page 1 of 4" in texts
    assert any(t.startswith("dev_rfp.pdf, page ") and t.endswith(":") for t in texts)


def test_the_quote_is_found_and_highlighted_on_its_page() -> None:
    from app.document_view import locate, render_page

    pdf = str(HOME / "inputs" / "dev" / "dev_rfp.pdf")
    quote = json.loads((DEV_SAMPLE / "requirements.jsonl").read_text("utf-8").splitlines()[0])[
        "quote"
    ]
    found = locate(pdf, quote)
    assert found is not None
    index, probe = found
    assert render_page(pdf, index, probe) != render_page(pdf, index), "the highlight is drawn"


def test_a_recorded_verdict_starts_the_choice_and_a_change_records_an_update(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from bidwright.review import record

    run_dir = tmp_path / "run-done"
    _write_iter3_fixture(run_dir, status="COMPLETED")
    record(run_dir, [{"item": "REQ-0001", "verdict": "accept", "note": "Fine."}], "Bid manager")
    monkeypatch.setenv("BIDWRIGHT_OUTPUTS", str(run_dir))
    recorded: list[str | None] = []

    def fake_run(command: list[str], stdin_text: str | None = None) -> Any:
        recorded.append(stdin_text)
        return subprocess.CompletedProcess(command, 0, "Recorded\n", "")

    monkeypatch.setattr("app.actions.run", fake_run)
    at = AppTest.from_file(str(REVIEW_PAGE)).run(timeout=15)
    assert at.radio(key="verdict:REQ-0001").value == "accept"
    assert at.text_input(key="note:REQ-0001").value == "Fine."
    at.text_input(key="review_role").input("Bid director")
    at.checkbox(key="review_auto_sync").uncheck()
    record_button = next(b for b in at.button if b.label == "Record these verdicts")
    record_button.click()
    at = at.run(timeout=15)
    assert recorded == [], "nothing changed, so nothing is recorded"
    at.radio(key="verdict:REQ-0001").set_value("reject")
    at.text_input(key="note:REQ-0001").input("The portal rule is the buyer's, not ours.")
    next(b for b in at.button if b.label == "Record these verdicts").click()
    at = at.run(timeout=15)
    assert len(at.exception) == 0
    assert [yaml.safe_load(s or "") for s in recorded] == [
        [
            {
                "item": "REQ-0001",
                "verdict": "reject",
                "note": "The portal rule is the buyer's, not ours.",
            }
        ]
    ]


def test_the_selector_labels_a_run_and_leaves_matrix_runs_out_unless_asked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    shutil.copytree(DEV_SAMPLE, tmp_path / "20261106T000000Z-dev")
    shutil.copytree(DEV_SAMPLE, tmp_path / "matrices" / "m" / "m-a-r0")
    monkeypatch.setenv("BIDWRIGHT_OUTPUTS", str(tmp_path))
    at = AppTest.from_file(str(MAIN_PAGE)).run(timeout=20)
    selector = at.sidebar.selectbox(key="run")
    assert selector.options == ["20261106T000000Z | dev_rfp.pdf | manifest | COMPLETED"]
    at = AppTest.from_file(str(MAIN_PAGE))
    at.session_state["show_matrix_runs"] = True
    at.run(timeout=20)
    assert len(at.sidebar.selectbox(key="run").options) == 2


# --- ADR-060: the gate's view, the views folder and the launcher's defaults ------------------


def test_the_page_scripts_live_outside_a_pages_folder() -> None:
    """Streamlit serves a `pages/` folder next to the entrypoint until a session calls
    `st.navigation`, so the first deep link after a start would get those pages instead."""
    assert not (APP_DIR / "pages").exists()
    assert {p.name for p in (APP_DIR / "views").glob("*.py")} == {"run.py", "review.py", "ops.py"}


def test_the_launcher_starts_from_the_configuration_a_cli_run_uses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from bidwright.config import load_config

    monkeypatch.setenv("BIDWRIGHT_OUTPUTS", str(tmp_path / "none"))
    at = AppTest.from_file(str(RUN_PAGE)).run(timeout=15)
    assert len(at.exception) == 0
    config = load_config()
    assert at.selectbox(key="launch_risk_mode").value == config.limits.switches.risk_mode
    assert at.selectbox(key="launch_solution").value == config.limits.switches.solution
    assert at.selectbox(key="launch_research").value == config.research.mode
    assert at.checkbox(key="launch_reflect").value == config.limits.switches.reflect


def test_changed_edits_sends_only_changes_with_text_as_the_gate_stores_it() -> None:
    from app.data import changed_edits

    editable = {
        "work_packages[1.1].effort.high_days": ("float", 20.0),
        "work_packages[1.2].predecessors": ("predecessors", ["1.1"]),
        "work_packages[1.1].scope": ("str", "Configure audit records."),
        "assumptions[1].text": ("str", "A partner can cover service levels."),
    }
    values = {
        "work_packages[1.1].effort.high_days": 20,
        "work_packages[1.2].predecessors": [],
        "work_packages[1.1].scope": "Configure audit records.\n",
        "assumptions[1].text": "A named partner  covers\nservice levels.",
    }
    assert changed_edits(editable, values) == [
        {"field": "work_packages[1.2].predecessors", "value": []},
        {"field": "assumptions[1].text", "value": "A named partner covers service levels."},
    ]


def test_the_edit_groups_hold_exactly_the_gates_fields_and_skip_an_absent_effort(
    tmp_path: Path,
) -> None:
    from app.data import edit_groups

    run_dir = tmp_path / "run-waiting"
    _write_iter3_fixture(run_dir, status="WAITING_HUMAN")
    manifest = load_run_data(run_dir).solution_manifest
    assert manifest is not None
    manifest.work_packages[1].effort = None
    groups = edit_groups(manifest)
    assert [g.title for g in groups] == [
        "1.1.1 SAML Broker Setup",
        "1.1.2 Role Mapping Cutover",
        "Assumptions",
        "Ground rules",
    ]
    paths = [f.path for g in groups for f in g.fields]
    assert sorted(paths) == sorted(allowed_edit_fields(manifest))
    assert "work_packages[1.1.2].effort.low_days" not in paths


def test_the_option_approach_says_when_a_need_rests_on_no_claim(tmp_path: Path) -> None:
    from app.data import NO_CLAIM, option_approach_rows, unsupported_needs

    run_dir = tmp_path / "run-waiting"
    _write_iter3_fixture(run_dir, status="WAITING_HUMAN")
    data = load_run_data(run_dir)
    assert data.options is not None
    first, second = data.options.options
    assert option_approach_rows(first, data.capability_map, {})[0]["support"] == (
        "CL-001 not assessed"
    )
    row = option_approach_rows(second, data.capability_map, {})[0]
    assert row["support"] == NO_CLAIM and row["map status"] == "GAP"
    assert unsupported_needs(second) == ["RG-002"] and unsupported_needs(first) == []


def test_run_approve_runs_the_cli_through_this_interpreter_from_the_repository(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sys

    import app.data as app_data

    seen: dict[str, Any] = {}

    def fake_run(args: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        seen["args"], seen["kwargs"] = args, kwargs
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(app_data.subprocess, "run", fake_run)
    app_data.run_approve(["bidwright", "approve", "run-x", "--role", "Bid director"], "x: 1\n")
    assert seen["args"] == [
        sys.executable,
        "-m",
        "bidwright.cli",
        "approve",
        "run-x",
        "--role",
        "Bid director",
    ]
    assert seen["kwargs"]["cwd"] == HOME and seen["kwargs"]["input"] == "x: 1\n"


def test_a_long_job_has_its_output_read_while_it_runs() -> None:
    """A pipe nobody reads fills up and blocks the command; the job's reader drains it."""
    import io

    import app.actions as actions

    text = "".join(f"line {n}\n" for n in range(20000))

    class Finished:
        def __init__(self) -> None:
            self.stdout = io.StringIO(text)

        def poll(self) -> int | None:
            return 0

    job = actions.Job("run", ["bidwright"], None, Finished())  # type: ignore[arg-type]
    assert job.poll() == 0
    assert job.output == text
