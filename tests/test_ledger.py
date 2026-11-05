"""The run manifest's totals and the models that answered come from the same entries that
`ledger.jsonl` holds. The file gains each entry as its call finishes, and both readers skip a
last line that a kill cut short."""

import threading
from pathlib import Path

import pytest

from bidwright.graph.build import execute
from bidwright.llm.replay import CassetteStore
from bidwright.llm.simulator import ProviderSimulator
from bidwright.llm.types import Request, Response
from bidwright.obs.ledger import LedgerFile, models_used, read_ledger, totals_of
from bidwright.schemas import LedgerEntry, RunManifest
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


# --- The ledger file (Iteration 2, ADR-031) -------------------------------------------------


def _entry(node: str) -> LedgerEntry:
    return LedgerEntry(
        run_id="run-a",
        node=node,
        agent=node,
        provider="gemini",
        model="gemini-3.5-flash-lite",
        prompt_hash="sha256:p",
        input_hash=f"sha256:{node}",
        repeat=0,
        tokens_in=1000,
        tokens_out=200,
        tokens_cached=0,
        tokens_thinking=0,
        streamed=False,
        latency_ms=10,
        ttft_ms=None,
        load_ms=None,
        prompt_ms=None,
        gen_ms=None,
        cost_usd=0.0,
        shadow_cost_usd=0.0008,
        replayed=False,
        retries=0,
    )


def test_a_last_line_a_kill_cut_short_is_skipped_then_cut(tmp_path: Path) -> None:
    ledger = LedgerFile(tmp_path / "ledger.jsonl")
    ledger.create()
    assert ledger.load() == [] and ledger.repair() == ""
    ledger.append(_entry("triage"))
    ledger.append(_entry("extract"))
    cut = _entry("approach").model_dump_json()[:40]
    with ledger.path.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(cut)
    for read in (ledger.load, lambda: read_ledger(ledger.path)):
        assert [e.node for e in read()] == ["triage", "extract"]
    assert ledger.repair() == cut and ledger.repair() == ""
    ledger.append(_entry("risk"))
    for read in (ledger.load, lambda: read_ledger(ledger.path)):
        assert [e.node for e in read()] == ["triage", "extract", "risk"]


def test_a_cut_inside_a_character_is_still_skipped(tmp_path: Path) -> None:
    """A kill can stop a write inside a multi-byte character, and reading must not fail."""
    path = tmp_path / "ledger.jsonl"
    path.write_bytes(_entry("triage").model_dump_json().encode() + b"\n" + b'{"node": "\xc3')
    assert [e.node for e in read_ledger(path)] == ["triage"]
    assert LedgerFile(path).repair() == '{"node": "�'


class _KilledOnSecondCall:
    """Answers the first call; on the second, reads `ledger.jsonl` as a kill would leave it,
    then raises. The lock keeps a parallel `Send` worker from finishing a call in between."""

    provider = "gemini"
    paid = False

    def __init__(self, ledger: Path) -> None:
        self.inner = RuleBackend()
        self.ledger = ledger
        self.calls = 0
        self.seen: list[LedgerEntry] = []
        self._lock = threading.Lock()

    def call(self, request: Request) -> Response:
        with self._lock:
            self.calls += 1
            if self.calls == 2:
                self.seen = read_ledger(self.ledger)
                raise RuntimeError("the process was killed")
        return self.inner.call(request)


def test_a_run_that_dies_after_its_first_call_has_that_call_on_disk(tmp_path: Path) -> None:
    model = _KilledOnSecondCall(tmp_path / "killed" / "ledger.jsonl")
    with pytest.raises(RuntimeError, match="killed"):
        execute(
            docling_mode="replay",
            source=DEV_RFP,
            profile="free",
            outputs=tmp_path,
            mode="record",
            cassettes=CassetteStore(tmp_path / "cassettes"),
            backends={"gemini": model},
            run_id="killed",
        )
    assert [e.node for e in model.seen] == ["triage"], "written as the call finished"
    ledger = read_ledger(tmp_path / "killed" / "ledger.jsonl")
    manifest = RunManifest.model_validate_json(
        (tmp_path / "killed" / "run_manifest.json").read_text(encoding="utf-8")
    )
    assert manifest.status == "UNRECOVERABLE_FAULT"
    assert manifest.totals == totals_of(ledger, manifest.totals.active_seconds)
