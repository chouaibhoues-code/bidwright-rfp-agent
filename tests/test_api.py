"""FastAPI wrapper tests (`WP-3.6`, `ADR-051`): `TestClient` over `samples/dev` and fixtures."""

import ast
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
POST_HEADERS = {"X-Bidwright": "1"}
client = TestClient(app, base_url="http://127.0.0.1:8001")


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
    for bad_id in ("nonexistent", "..", "../private", "dev/../../private"):
        res = client.get(f"/runs/{bad_id}")
        assert res.status_code == 404
        assert res.json()["status_line"] == STATUS_LINE, "an error carries it too"


def test_post_without_x_bidwright_header_and_foreign_host_are_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BIDWRIGHT_OUTPUTS", str(DEV_SAMPLE))
    no_header = client.post("/runs/dev/stop")
    assert no_header.status_code == 403
    assert no_header.json()["status_line"] == STATUS_LINE

    wrong_header = client.post("/runs/dev/stop", headers={"X-Bidwright": "0"})
    assert wrong_header.status_code == 403

    foreign_get = client.get("/health", headers={"Host": "evil.example:8001"})
    assert foreign_get.status_code == 400
    assert foreign_get.json()["status_line"] == STATUS_LINE

    foreign_post = client.post(
        "/runs/demo",
        headers={"Host": "evil.example:8001", "X-Bidwright": "1"},
    )
    assert foreign_post.status_code == 400

    localhost_ok = client.get("/health", headers={"Host": "localhost:8001"})
    assert localhost_ok.status_code == 200


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
    ok = client.post("/runs/run-active/stop", headers=POST_HEADERS)
    assert ok.status_code == 200
    assert ok.json()["status"] == "STOP_REQUESTED"
    assert (running_dir / "control" / "stop.request").is_file()

    monkeypatch.setenv("BIDWRIGHT_OUTPUTS", str(DEV_SAMPLE))
    refused = client.post("/runs/dev/stop", headers=POST_HEADERS)
    assert refused.status_code == 409


def test_spans_replay_endpoint_refuses_unlisted_host_with_400(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BIDWRIGHT_OUTPUTS", str(DEV_SAMPLE))
    res = client.post(
        "/runs/dev/spans/replay",
        json={"endpoint": "https://collector.example.com:6006"},
        headers=POST_HEADERS,
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
    res = client.post("/runs/demo", headers=POST_HEADERS)
    assert res.status_code == 200
    body = res.json()
    assert body["run_id"] == "20261105T150000Z-demo"
    assert body["status"] == "COMPLETED"
    assert body["status_line"] == STATUS_LINE


def test_ops_ladders_and_matrices_endpoints_include_status_line(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    outputs_root = tmp_path / "outputs"
    matrix_run = outputs_root / "matrices" / "ex-ladder" / "run-ex0"
    shutil.copytree(DEV_SAMPLE, matrix_run)

    results_root = tmp_path / "results"
    ladder_dir = results_root / "ex-ladder"
    ladder_dir.mkdir(parents=True)
    (ladder_dir / "report.json").write_text(
        json.dumps(
            {
                "matrix": "ex-ladder",
                "gold": "hero v4",
                "rungs": {"EX0": {"missed_mandatory_count": {"median": 4.0}}},
                "decisions": [
                    {
                        "rung": "EX1",
                        "control": "EX0",
                        "metric": "missed_mandatory_count",
                        "kind": "keep_or_drop",
                        "verdict": "keep",
                        "interval": [0.5, 2.5],
                        "cost_per_avoided_miss": 0.04,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("BIDWRIGHT_OUTPUTS", str(outputs_root))
    monkeypatch.setenv("BIDWRIGHT_RESULTS", str(results_root))

    ladders = client.get("/ops/ladders")
    assert ladders.status_code == 200
    assert ladders.json()["status_line"] == STATUS_LINE
    assert len(ladders.json()["ladders"]) == 1

    matrices = client.get("/ops/matrices")
    assert matrices.status_code == 200
    assert matrices.json()["status_line"] == STATUS_LINE
    assert matrices.json()["matrices"][0]["group"] == "ex-ladder"


def test_api_module_writes_no_file_directly() -> None:
    api_path = HOME / "app" / "api.py"
    tree = ast.parse(api_path.read_text(encoding="utf-8"))
    forbidden_attrs = {"write_text", "write_bytes", "mkdir", "unlink", "rmdir"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id == "open":
                raise AssertionError("app/api.py must not call open()")
            if isinstance(node.func, ast.Attribute) and node.func.attr in forbidden_attrs:
                raise AssertionError(f"app/api.py must not call .{node.func.attr}()")
