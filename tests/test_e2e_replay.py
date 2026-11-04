"""A full development run recorded once, then replayed with no network and no keys."""

import json
from pathlib import Path

import pytest

from bidwright.graph.build import execute
from bidwright.llm.replay import CassetteStore
from bidwright.llm.types import Request, Response
from bidwright.schemas import LedgerEntry, RunManifest
from tests.node_fakes import DEV_RFP, USAGE, RuleBackend

pytestmark = pytest.mark.replay

OUTPUTS = (
    "frozen.txt",
    "passages.jsonl",
    "search.sqlite",
    "requirements.jsonl",
    "rejected.jsonl",
    "approach.json",
    "risks.jsonl",
    "tool_calls.jsonl",
    "sections/understanding.md",
    "sections/approach.md",
    "sections/risks_and_assumptions.md",
    "proposal.md",
    "solution_summary.md",
    "solution_summary.json",
    "ledger.jsonl",
    "run_manifest.json",
)


def _summary(run_dir: Path) -> dict:
    data = json.loads((run_dir / "solution_summary.json").read_text(encoding="utf-8"))
    data["summary"].pop("run_id")
    return data


def test_a_development_run_replays_with_no_network(tmp_path: Path) -> None:
    store = CassetteStore(tmp_path / "cassettes")
    model = RuleBackend()
    live = execute(
        source=DEV_RFP,
        profile="free",
        outputs=tmp_path / "out",
        mode="record",
        cassettes=store,
        backends={"gemini": model},
        run_id="recorded",
    )
    assert live.status == "COMPLETED", live.reason
    replay = execute(
        source=DEV_RFP,
        profile="free",
        outputs=tmp_path / "out",
        mode="replay",
        cassettes=store,
        run_id="replayed",
    )
    assert replay.status == "COMPLETED", replay.reason
    for name in OUTPUTS:
        assert (replay.run_dir / name).exists(), name
    assert _summary(replay.run_dir) == _summary(live.run_dir)
    ledger = [
        LedgerEntry.model_validate_json(line)
        for line in (replay.run_dir / "ledger.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert ledger and all(entry.replayed for entry in ledger)
    assert len(ledger) == len(model.requests)
    manifest = RunManifest.model_validate_json(
        (replay.run_dir / "run_manifest.json").read_text(encoding="utf-8")
    )
    assert manifest.status == "COMPLETED" and manifest.totals.requests == len(ledger)
    assert manifest.models_used == {
        node: ["gemini-3.5-flash-lite"]
        for node in ("approach", "draft", "extract", "risk", "triage")
    }
    calls = [
        json.loads(line)
        for line in (replay.run_dir / "tool_calls.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert [(c["tool"], c["turn"], c["status"]) for c in calls] == [("search_rfp", 1, "OK")]
    assert calls[0]["data"] and calls[0]["reason"] is None


class BrokenApproach(RuleBackend):
    """Answers every approach call with output that breaks its schema."""

    def call(self, request: Request) -> Response:
        if request.schema_name == "ApproachResult":
            self.requests.append(request)
            return Response(text="{}", usage=USAGE)
        return super().call(request)


def test_a_broken_approach_degrades_the_run_and_keeps_the_summary(tmp_path: Path) -> None:
    result = execute(
        source=DEV_RFP,
        profile="free",
        outputs=tmp_path,
        mode="record",
        cassettes=CassetteStore(tmp_path / "c"),
        backends={"gemini": BrokenApproach()},
        run_id="broken-approach",
    )
    assert result.status == "DEGRADED"
    assert result.reason == "approach: malformed output twice"
    summary = (result.run_dir / "solution_summary.md").read_text(encoding="utf-8")
    assert "REQ-0001" in summary and "No approach items." in summary
    assert "Not yet mapped to an approach item: REQ-0001" in summary


def test_a_missing_cassette_ends_the_run_as_a_fault(tmp_path: Path) -> None:
    result = execute(
        source=DEV_RFP,
        profile="free",
        outputs=tmp_path,
        mode="replay",
        cassettes=CassetteStore(tmp_path / "empty"),
        run_id="nothing-recorded",
    )
    assert result.status == "UNRECOVERABLE_FAULT"
    assert "CassetteMissing" in (result.reason or "")
    assert (result.run_dir / "run_manifest.json").exists()
    assert not (result.run_dir / "solution_summary.md").exists()


def test_an_unexpected_error_is_recorded_as_a_fault(tmp_path: Path) -> None:
    broken = tmp_path / "broken.pdf"
    broken.write_bytes(b"%PDF-1.7 not really a PDF")
    with pytest.raises(Exception):  # noqa: B017 - any parser error will do
        execute(
            source=broken,
            profile="free",
            outputs=tmp_path,
            mode="replay",
            cassettes=CassetteStore(tmp_path / "empty"),
            run_id="unreadable",
        )
    manifest = RunManifest.model_validate_json(
        (tmp_path / "unreadable" / "run_manifest.json").read_text(encoding="utf-8")
    )
    assert manifest.status == "UNRECOVERABLE_FAULT"
    assert (manifest.status_reason or "").startswith("unexpected ")


def test_a_missing_input_still_leaves_a_manifest(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        execute(
            source=tmp_path / "missing.pdf",
            profile="free",
            outputs=tmp_path,
            mode="replay",
            cassettes=CassetteStore(tmp_path / "empty"),
            run_id="missing",
        )
    manifest = RunManifest.model_validate_json(
        (tmp_path / "missing" / "run_manifest.json").read_text(encoding="utf-8")
    )
    assert manifest.status == "UNRECOVERABLE_FAULT"
    assert manifest.input_hashes == {"missing.pdf": "unreadable: FileNotFoundError"}


def test_an_interrupt_is_recorded_as_stopped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def interrupt(*_: object, **__: object) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr("bidwright.graph.build.ingest_pdf", interrupt)
    with pytest.raises(KeyboardInterrupt):
        execute(
            source=DEV_RFP,
            profile="free",
            outputs=tmp_path,
            mode="replay",
            cassettes=CassetteStore(tmp_path / "empty"),
            run_id="interrupted",
        )
    manifest = RunManifest.model_validate_json(
        (tmp_path / "interrupted" / "run_manifest.json").read_text(encoding="utf-8")
    )
    assert manifest.status == "STOPPED"


def test_ex0_sends_every_passage_in_one_call(tmp_path: Path) -> None:
    model = RuleBackend()
    result = execute(
        source=DEV_RFP,
        profile="free",
        outputs=tmp_path,
        mode="record",
        cassettes=CassetteStore(tmp_path / "c"),
        backends={"gemini": model},
        baseline="ex0",
        run_id="ex0",
    )
    assert result.status == "COMPLETED", result.reason
    extract_calls = [r for r in model.requests if r.schema_name == "ExtractResult"]
    assert len(extract_calls) == 1
    assert "You list the obligations" in extract_calls[0].messages[0].content
