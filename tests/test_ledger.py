"""The run manifest's totals and the models that answered come from the same entries that
`ledger.jsonl` holds."""

from pathlib import Path

from bidwright.graph.build import execute
from bidwright.llm.replay import CassetteStore
from bidwright.llm.simulator import ProviderSimulator
from bidwright.obs.ledger import models_used, read_ledger, totals_of
from bidwright.schemas import RunManifest
from tests.node_fakes import DEV_RFP, RuleBackend


def test_ledger_totals_match_the_manifest(tmp_path: Path) -> None:
    model = RuleBackend()
    result = execute(
        docling_mode="replay",
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
    nodes = {"triage", "extract", "consolidate", "approach", "risk", "draft"}
    assert {entry.node for entry in ledger} == nodes


def test_the_manifest_lists_the_models_that_answered(tmp_path: Path) -> None:
    """A spent quota on the first call, `triage`'s, moves it to the fallback, so both models
    answered."""
    model = ProviderSimulator(RuleBackend(), [{"call": 1, "fault": "quota_exhausted"}])
    result = execute(
        docling_mode="replay",
        source=DEV_RFP,
        profile="free",
        outputs=tmp_path,
        mode="record",
        cassettes=CassetteStore(tmp_path / "cassettes"),
        backends={"gemini": model},
        run_id="fallback",
    )
    assert result.status == "COMPLETED", result.reason
    ledger = read_ledger(result.run_dir / "ledger.jsonl")
    manifest = RunManifest.model_validate_json(
        (result.run_dir / "run_manifest.json").read_text(encoding="utf-8")
    )
    assert manifest.models == {role: "gemini-3.5-flash-lite" for role in ("extract", "reason")}
    assert manifest.models_used == models_used(ledger)
    assert manifest.models_used["triage"] == ["gemini-3.1-flash-lite"]
    assert manifest.models_used["extract"] == ["gemini-3.5-flash-lite"]
    assert manifest.models_used["approach"] == ["gemini-3.5-flash-lite"]
    assert sum(entry.retries for entry in ledger) == 1  # the refused attempt
