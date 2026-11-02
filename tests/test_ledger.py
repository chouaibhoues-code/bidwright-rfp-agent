"""The run manifest's totals are computed from the same entries `ledger.jsonl` holds."""

from pathlib import Path

from bidwright.graph.build import execute
from bidwright.llm.replay import CassetteStore
from bidwright.obs.ledger import read_ledger, totals_of
from bidwright.schemas import RunManifest
from tests.node_fakes import DEV_RFP, RuleBackend


def test_ledger_totals_match_the_manifest(tmp_path: Path) -> None:
    model = RuleBackend()
    result = execute(
        source=DEV_RFP,
        profile="free",
        outputs=tmp_path,
        mode="record",
        cassettes=CassetteStore(tmp_path / "cassettes"),
        backends={"gemini": model},
        run_id="ledger",
    )
    assert result.status == "COMPLETED", result.reason
    ledger = read_ledger(result.run_dir / "ledger.jsonl")
    manifest = RunManifest.model_validate_json(
        (result.run_dir / "run_manifest.json").read_text(encoding="utf-8")
    )
    assert manifest.totals == totals_of(ledger, manifest.totals.active_seconds)
    assert manifest.totals.requests == len(ledger) == len(model.requests)
    assert manifest.totals.cost_usd == 0.0 and manifest.totals.shadow_cost_usd > 0
    assert {entry.node for entry in ledger} == {"extract", "approach", "risk", "draft"}
