"""Whole runs with no network and no keys: a development run recorded in the test, then
replayed, and the live recordings of `bidwright record` replayed from their cassettes: the
development PDF with its traps (the demo), in its recorded research mode `pack` and in `off`,
the development DOCX, and the hero package through `consolidate`."""

import json
import socket
from pathlib import Path
from typing import Any

import pytest

from bidwright.graph.build import execute
from bidwright.llm.replay import CassetteStore
from bidwright.llm.types import Request, Response
from bidwright.schemas import (
    ControlRegister,
    LedgerEntry,
    OpportunityBrief,
    Requirement,
    ResearchRecord,
    RunManifest,
)
from tests.node_fakes import DEV_RFP, USAGE, RuleBackend
from tests.recordings import replay

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
    "brief.json",
    "research.json",
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
        docling_mode="replay",
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
        docling_mode="replay",
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
        for node in ("approach", "brief", "consolidate", "draft", "extract", "risk", "triage")
    }
    research = ResearchRecord.model_validate_json(
        (replay.run_dir / "research.json").read_text(encoding="utf-8")
    )
    assert (research.mode, research.pack_id, research.notes) == (
        "pack",
        None,
        ["no pack for this domain"],
    ), "the development PDF's domain has no research pack yet"
    assert manifest.research is not None and manifest.research.mode == "pack"
    brief = OpportunityBrief.model_validate_json(
        (replay.run_dir / "brief.json").read_text(encoding="utf-8")
    )
    assert [(f.name, f.weight, f.status) for f in brief.factors] == [
        ("Technical approach", "40%", "IN_SCOPE"),
        ("Service levels and support", "20%", "IN_SCOPE"),
        ("Integration and migration", "20%", "IN_SCOPE"),
        ("Price", "20%", "OUT_OF_SCOPE"),
    ]
    summary = (replay.run_dir / "solution_summary.md").read_text(encoding="utf-8")
    assert "**Evaluation factors**, as the RFP states them" in summary
    assert "- Price: 20% (SRC-0038), out of scope for the bid team" in summary
    assert "Appendix: domain research" not in summary, "no pack, so no appendix"
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
        docling_mode="replay",
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
        docling_mode="replay",
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


def test_an_unexpected_error_is_recorded_as_a_fault(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(*_: object, **__: object) -> None:
        raise RuntimeError("a parser bug")

    monkeypatch.setattr("bidwright.graph.build.ingest_package", broken)
    with pytest.raises(RuntimeError):
        execute(
            docling_mode="replay",
            source=DEV_RFP,
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
    assert (manifest.status_reason or "").startswith("unexpected RuntimeError")


def test_a_corrupt_input_is_blocked_by_guard_with_a_manifest(tmp_path: Path) -> None:
    """`guard` runs first, so a file it cannot read ends the run POLICY_BLOCKED."""
    broken = tmp_path / "broken.pdf"
    broken.write_bytes(b"%PDF-1.7 not really a PDF")
    result = execute(
        docling_mode="replay",
        source=broken,
        profile="free",
        outputs=tmp_path,
        mode="replay",
        cassettes=CassetteStore(tmp_path / "empty"),
        run_id="unreadable",
    )
    assert result.status == "POLICY_BLOCKED", result.reason
    manifest = RunManifest.model_validate_json(
        (tmp_path / "unreadable" / "run_manifest.json").read_text(encoding="utf-8")
    )
    assert manifest.status == "POLICY_BLOCKED" and manifest.totals.requests == 0


def test_a_missing_input_is_blocked_with_a_manifest(tmp_path: Path) -> None:
    result = execute(
        docling_mode="replay",
        source=tmp_path / "missing.pdf",
        profile="free",
        outputs=tmp_path,
        mode="replay",
        cassettes=CassetteStore(tmp_path / "empty"),
        run_id="missing",
    )
    assert result.status == "POLICY_BLOCKED"
    manifest = RunManifest.model_validate_json(
        (tmp_path / "missing" / "run_manifest.json").read_text(encoding="utf-8")
    )
    assert manifest.status == "POLICY_BLOCKED"
    assert manifest.input_hashes == {"missing.pdf": "unreadable: FileNotFoundError"}


def test_an_interrupt_is_recorded_as_stopped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def interrupt(*_: object, **__: object) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr("bidwright.graph.build.run_guard", interrupt)
    with pytest.raises(KeyboardInterrupt):
        execute(
            docling_mode="replay",
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
        docling_mode="replay",
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


def test_b0_makes_no_model_call_and_stops_after_verify(tmp_path: Path) -> None:
    result = execute(
        docling_mode="replay",
        source=DEV_RFP,
        profile="free",
        outputs=tmp_path,
        backends={},
        baseline="b0",
        run_id="b0",
    )
    assert result.status == "COMPLETED"
    assert result.reason == "stopped after verify by request"
    assert (result.run_dir / "ledger.jsonl").read_text(encoding="utf-8") == ""
    requirements = (result.run_dir / "requirements.jsonl").read_text(encoding="utf-8")
    assert requirements and not (result.run_dir / "triage.json").exists()
    assert not (result.run_dir / "solution_summary.md").exists()


# --- the live recordings, replayed ---------------------------------------------------------------


@pytest.fixture
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Any attempt to open a connection fails the run, so a replay that reached for a model,
    Docling or a collector would show."""

    def refuse(*_: Any, **__: Any) -> None:
        raise OSError("the network is disabled in this test")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.delenv("PHOENIX_ENDPOINT", raising=False)


def _records(run_dir: Path, name: str) -> list[dict[str, Any]]:
    lines = (run_dir / name).read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line]


def _all_replayed(run_dir: Path) -> None:
    ledger = [LedgerEntry.model_validate(row) for row in _records(run_dir, "ledger.jsonl")]
    assert ledger and all(entry.replayed for entry in ledger)


def _verified(run_dir: Path) -> list[Requirement]:
    requirements = [Requirement.model_validate(r) for r in _records(run_dir, "requirements.jsonl")]
    assert requirements, "the recording extracted requirements"
    assert all(r.quote_status in ("VERBATIM_VERIFIED", "NORMALIZED_MATCH") for r in requirements)
    return requirements


def test_the_development_pdf_with_its_traps_replays_from_the_demo_cassettes(
    tmp_path: Path, no_network: None
) -> None:
    result, recording = replay("demo", tmp_path)
    assert recording["source"] == "inputs/dev/dev_rfp.pdf"
    assert result.status == "COMPLETED", result.reason
    for name in OUTPUTS:
        assert (result.run_dir / name).exists(), name
    _all_replayed(result.run_dir)
    _verified(result.run_dir)
    quarantined = _records(result.run_dir, "quarantine.jsonl")
    assert quarantined, "the hidden trap was removed before parsing"
    hidden = {q["text"] for q in quarantined}
    frozen = (result.run_dir / "frozen.txt").read_text(encoding="utf-8")
    assert not any(text in frozen for text in hidden), "no model saw the hidden text"
    assert (result.run_dir / "review" / "quarantine.md").exists()
    assert recording["research"] == "pack"
    research = ResearchRecord.model_validate_json(
        (result.run_dir / "research.json").read_text(encoding="utf-8")
    )
    assert research.notes == ["no pack for this domain"]


def test_the_demo_replays_in_research_mode_off(tmp_path: Path, no_network: None) -> None:
    result, _ = replay("demo", tmp_path, research="off")
    assert result.status == "COMPLETED", result.reason
    _all_replayed(result.run_dir)
    assert (result.run_dir / "brief.json").exists() and not (
        result.run_dir / "research.json"
    ).exists()
    manifest = RunManifest.model_validate_json(
        (result.run_dir / "run_manifest.json").read_text(encoding="utf-8")
    )
    assert manifest.research is None and manifest.run_args["research"] == "off"


def test_the_development_docx_replays_from_its_cassettes(tmp_path: Path, no_network: None) -> None:
    result, recording = replay("dev-docx", tmp_path)
    assert recording["source"] == "inputs/dev-docx/dev_docx_rfp.docx"
    assert result.status == "COMPLETED", result.reason
    for name in OUTPUTS:
        assert (result.run_dir / name).exists(), name
    _all_replayed(result.run_dir)
    _verified(result.run_dir)
    assert (result.run_dir / "compliance_matrix.xlsx").exists()


def test_the_hero_package_replays_through_consolidate(tmp_path: Path, no_network: None) -> None:
    result, recording = replay("hero", tmp_path)
    assert (recording["source"], recording["until"]) == ("inputs/hero", "consolidate")
    assert result.status in ("COMPLETED", "DEGRADED")
    assert (result.reason or "").endswith("stopped after consolidate by request")
    _all_replayed(result.run_dir)
    register = ControlRegister.model_validate_json(
        (result.run_dir / "control_register.json").read_text(encoding="utf-8")
    )
    files = {entry.file for entry in register.documents}
    assert {"hero_rfp.pdf", "hero_addendum_1.pdf", "hero_annex_b_requirements.xlsx"} <= files
    requirements = _verified(result.run_dir)
    groups = _records(result.run_dir, "requirement_groups.jsonl")
    grouped = [rid for group in groups for rid in group["member_ids"]]
    chosen = [r.id for r in requirements if r.disposition in ("BINDING", "OPTIONAL")]
    assert sorted(grouped) == sorted(chosen), "every requirement ends in exactly one group"
    manifest = RunManifest.model_validate_json(
        (result.run_dir / "run_manifest.json").read_text(encoding="utf-8")
    )
    assert "consolidate" in manifest.models_used and "approach" not in manifest.models_used
    assert not (result.run_dir / "solution_summary.md").exists()
