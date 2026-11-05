"""FastAPI wrapper tests (`WP-3.6`): `TestClient` over `samples/dev` and synthetic fixtures."""

import json
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api import app
from bidwright.obs.ledger import read_ledger, totals_of
from bidwright.preflight import HOME
from bidwright.render import STATUS_LINE

DEV_SAMPLE = HOME / "samples" / "dev"
client = TestClient(app)


def test_health_and_runs_include_unreviewed_draft_status_line(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BIDWRIGHT_OUTPUTS", str(DEV_SAMPLE))
    health = client.get("/health")
    assert health.status_code == 200
    assert health.json() == {"status": "ok", "status_line": STATUS_LINE}

    runs = client.get("/runs")
    assert runs.status_code == 200
    body = runs.json()
    assert body["status_line"] == STATUS_LINE
    assert body["runs"] == ["dev"]


def test_run_endpoints_return_manifest_summary_matrix_quarantine_ledger_and_scores(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BIDWRIGHT_OUTPUTS", str(DEV_SAMPLE))
    monkeypatch.setenv("BIDWRIGHT_RESULTS", str(tmp_path / "empty-results"))

    full = client.get("/runs/dev")
    assert full.status_code == 200
    payload = full.json()
    assert payload["status_line"] == STATUS_LINE
    assert payload["run_id"] == "dev"
    assert payload["manifest"]["status"] == "COMPLETED"
    assert len(payload["compliance_rows"]) > 0
    assert payload["quarantine_text"] is not None
    assert payload["has_spans"] is True

    manifest_res = client.get("/runs/dev/manifest")
    assert manifest_res.status_code == 200
    assert manifest_res.json()["manifest"]["status"] == "COMPLETED"

    summary_res = client.get("/runs/dev/summary")
    assert summary_res.status_code == 200
    assert len(summary_res.json()["requirements"]) > 0

    matrix_res = client.get("/runs/dev/matrix")
    assert matrix_res.status_code == 200
    assert len(matrix_res.json()["rows"]) == len(payload["compliance_rows"])

    quarantine_res = client.get("/runs/dev/quarantine")
    assert quarantine_res.status_code == 200
    assert "Hidden content removed before parsing" in quarantine_res.json()["quarantine_text"]

    ledger_res = client.get("/runs/dev/ledger")
    assert ledger_res.status_code == 200
    entries = read_ledger(DEV_SAMPLE / "ledger.jsonl")
    expected_totals = totals_of(entries, active_seconds=0.0)
    totals = ledger_res.json()["totals"]
    assert totals["requests"] == expected_totals.requests
    assert totals["tokens_in"] == expected_totals.tokens_in
    assert totals["tokens_out"] == expected_totals.tokens_out

    scores_res = client.get("/runs/dev/scores")
    assert scores_res.status_code == 200
    assert scores_res.json()["scores"] is None


def test_unknown_or_traversal_run_id_is_rejected_with_404(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BIDWRIGHT_OUTPUTS", str(DEV_SAMPLE))
    for bad_id in ("nonexistent", "..", "../private"):
        res = client.get(f"/runs/{bad_id}")
        assert res.status_code == 404


def test_stop_endpoint_writes_stop_request_for_running_run_and_409_when_completed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    running_dir = tmp_path / "run-active"
    shutil.copytree(DEV_SAMPLE, running_dir)
    manifest_path = running_dir / "run_manifest.json"
    manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest_data["status"] = "RUNNING"
    manifest_path.write_text(json.dumps(manifest_data), encoding="utf-8")

    monkeypatch.setenv("BIDWRIGHT_OUTPUTS", str(tmp_path))
    ok = client.post("/runs/run-active/stop")
    assert ok.status_code == 200
    assert ok.json()["status"] == "STOP_REQUESTED"
    assert (running_dir / "control" / "stop.request").is_file()

    monkeypatch.setenv("BIDWRIGHT_OUTPUTS", str(DEV_SAMPLE))
    refused = client.post("/runs/dev/stop")
    assert refused.status_code == 409


def test_spans_replay_endpoint_refuses_unlisted_host_with_400(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BIDWRIGHT_OUTPUTS", str(DEV_SAMPLE))
    res = client.post(
        "/runs/dev/spans/replay",
        json={"endpoint": "https://collector.example.com:6006"},
    )
    assert res.status_code == 400
    assert "phoenix" in res.json()["detail"]


def test_demo_endpoint_invokes_cli_demo_and_returns_latest_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    demo_run = tmp_path / "20261105T150000Z-demo"
    shutil.copytree(DEV_SAMPLE, demo_run)

    def fake_main(argv: list[str] | None = None) -> int:
        assert argv is not None and argv[0] == "demo"
        return 0

    monkeypatch.setenv("BIDWRIGHT_OUTPUTS", str(tmp_path))
    monkeypatch.setattr("bidwright.cli.main", fake_main)
    res = client.post("/runs/demo")
    assert res.status_code == 200
    body = res.json()
    assert body["run_id"] == "20261105T150000Z-demo"
    assert body["status"] == "COMPLETED"
    assert body["status_line"] == STATUS_LINE
