"""`coverage`: the gap rule, the stop reasons, and whole runs whose gaps are fixed in a later
round, never shrink, or never appear; and the extraction switches of Iteration 3, step 16
(`coverage`, `triage` and `extract_context`), on whole runs."""

import json
from dataclasses import replace
from pathlib import Path

import pytest

from bidwright.coverage import degraded_reason, gap_ids, next_step
from bidwright.graph.build import execute
from bidwright.llm.replay import CassetteStore
from bidwright.llm.types import Request, Response
from bidwright.preflight import Refused
from bidwright.schemas import CandidateRow, CoverageReport, RunManifest, TriageRecord
from tests.node_fakes import _DATA, DEV_RFP, RuleBackend, fake_backends


def _row(src: str, *dispositions: str) -> CandidateRow:
    return CandidateRow.model_validate(
        {
            "src_id": src,
            "doc_id": "d",
            "dispositions": list(dispositions),
            "reasons": [""] * len(dispositions),
            "round": 0,
        }
    )


def test_a_gap_is_unaccounted_or_rejected_with_no_accepted_item() -> None:
    rows = [
        _row("SRC-0001", "UNACCOUNTED"),
        _row("SRC-0002", "REJECTED"),
        _row("SRC-0003", "BINDING", "REJECTED"),
        _row("SRC-0004", "NO_OBLIGATION"),
        _row("SRC-0005", "BACKGROUND"),
    ]
    assert gap_ids(rows) == ["SRC-0001", "SRC-0002"]


def test_the_stop_reasons_follow_the_rule() -> None:
    closed = next_step([_row("SRC-0001", "BINDING")], [], 0, 2)
    assert closed.report is not None and closed.report.stop_reason == "closed"
    assert closed.report.rounds == [], "no gaps means no extra round"
    gaps = [_row("SRC-0001", "UNACCOUNTED"), _row("SRC-0002", "REJECTED")]
    start = next_step(gaps, [], 0, 2)
    assert start.report is None and start.gaps == ["SRC-0001", "SRC-0002"]
    shrunk = next_step([gaps[0], _row("SRC-0002", "OPTIONAL")], start.rounds, 1, 2)
    assert shrunk.report is None and shrunk.gaps == ["SRC-0001"]
    assert shrunk.rounds[0].resolved == ["SRC-0002"]
    capped = next_step([gaps[0]], shrunk.rounds, 2, 2)
    assert capped.report is not None and capped.report.stop_reason == "max_rounds"
    assert [r.round for r in capped.report.rounds] == [1, 2]
    stuck = next_step(gaps, start.rounds, 1, 2)
    assert stuck.report is not None and stuck.report.stop_reason == "no_shrink"
    assert (stuck.report.unaccounted, stuck.report.rejected_only) == (1, 1)
    assert degraded_reason(stuck.report) == "coverage: 2 passages without a disposition"
    never = next_step(gaps, [], 0, 0)
    assert never.report is not None and never.report.stop_reason == "max_rounds"


class GapBackend(RuleBackend):
    """Answers like `RuleBackend`, but never accounts for `omit` in the batches named."""

    def __init__(self, omit: set[str], batches: set[str] | None = None) -> None:
        super().__init__()
        self.omit, self.batches = omit, batches

    def call(self, request: Request) -> Response:
        response = super().call(request)
        if request.schema_name != "ExtractResult":
            return response
        user = next(m.content for m in request.messages if m.role == "user")
        found = _DATA.search(user)
        batch = json.loads(found.group(2))["batch_id"] if found else ""
        if self.batches is not None and batch not in self.batches:
            return response
        body = json.loads(response.text)
        body["items"] = [i for i in body["items"] if not set(i["src_ids"]) & self.omit]
        body["no_obligation_src_ids"] = [
            s for s in body["no_obligation_src_ids"] if s not in self.omit
        ]
        return replace(response, text=json.dumps(body))


def _run(tmp_path: Path, model: RuleBackend, name: str) -> Path:
    result = execute(
        docling_mode="replay",
        source=DEV_RFP,
        profile="free",
        outputs=tmp_path,
        mode="record",
        cassettes=CassetteStore(tmp_path / f"cassettes-{name}"),
        backends=fake_backends(model),
        run_id=name,
        batch_size=20,  # the scenarios are written for two first-pass packs, B01 and B02
        second_pass=False,  # and count the coverage calls alone
    )
    return result.run_dir


def _lines(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_coverage_rounds(tmp_path: Path) -> None:
    """A gap fixed in round 1 replaces its round-0 entry, and its pack continues the B ids."""
    run = _run(tmp_path, GapBackend({"SRC-0020"}, batches={"B01"}), "fixed")
    report = CoverageReport.model_validate_json((run / "coverage.json").read_text("utf-8"))
    assert report.stop_reason == "closed"
    assert [(r.round, r.gaps, r.resolved) for r in report.rounds] == [
        (1, ["SRC-0020"], ["SRC-0020"])
    ]
    rows = {row["src_id"]: row for row in _lines(run / "candidates.jsonl")}
    assert rows["SRC-0020"]["dispositions"] == ["BINDING"] and rows["SRC-0020"]["round"] == 1
    assert not any(r["reason"] == "unaccounted" for r in _lines(run / "rejected.jsonl"))
    assert (run / "context" / "extract-B03.json").exists(), "the gap pack is B03"
    requirements = _lines(run / "requirements.jsonl")
    assert [r["id"] for r in requirements] == [
        f"REQ-{n:04d}" for n in range(1, len(requirements) + 1)
    ]
    order = [int(r["src_ids"][0][4:]) for r in requirements]
    assert order == sorted(order), "renumbered in reading order"
    manifest = RunManifest.model_validate_json((run / "run_manifest.json").read_text("utf-8"))
    assert manifest.status == "COMPLETED", manifest.status_reason


def test_a_gap_that_never_shrinks_marks_the_run_degraded(tmp_path: Path) -> None:
    run = _run(tmp_path, GapBackend({"SRC-0020"}), "stuck")
    report = CoverageReport.model_validate_json((run / "coverage.json").read_text("utf-8"))
    assert report.stop_reason == "no_shrink" and len(report.rounds) == 1
    manifest = RunManifest.model_validate_json((run / "run_manifest.json").read_text("utf-8"))
    assert manifest.status == "DEGRADED"
    assert manifest.status_reason == "coverage: 1 passages without a disposition"


def test_no_gaps_means_no_extra_call(tmp_path: Path) -> None:
    model = RuleBackend()
    run = _run(tmp_path, model, "clean")
    report = CoverageReport.model_validate_json((run / "coverage.json").read_text("utf-8"))
    assert report.stop_reason == "closed" and report.rounds == []
    extract_calls = [r for r in model.requests if r.schema_name == "ExtractResult"]
    packs = sorted(p.name for p in (run / "context").glob("extract-*.json"))
    assert len(extract_calls) == len(packs) == 2


def _switched(tmp_path: Path, model: RuleBackend, name: str, **switches: object) -> Path:
    result = execute(
        docling_mode="replay",
        source=DEV_RFP,
        profile="free",
        outputs=tmp_path,
        mode="record",
        cassettes=CassetteStore(tmp_path / f"cassettes-{name}"),
        backends=fake_backends(model),
        run_id=name,
        until="coverage",
        batch_size=20,
        second_pass=False,
        **switches,  # type: ignore[arg-type]
    )
    return result.run_dir


def test_coverage_off_runs_no_second_round(tmp_path: Path) -> None:
    """Section 4.11's `coverage: false` sets `max_rounds` to 0, so a gap stays a gap."""
    run = _switched(tmp_path, GapBackend({"SRC-0020"}, batches={"B01"}), "off", coverage=False)
    report = CoverageReport.model_validate_json((run / "coverage.json").read_text("utf-8"))
    assert report.rounds == [] and report.unaccounted == 1
    assert not (run / "context" / "extract-B03.json").exists(), "no gap pack"
    manifest = RunManifest.model_validate_json((run / "run_manifest.json").read_text("utf-8"))
    assert manifest.run_args["coverage"] is False and manifest.switches["coverage"] is False


def test_triage_off_zones_every_section_obligation_with_no_call(tmp_path: Path) -> None:
    model = RuleBackend()
    run = _switched(tmp_path, model, "no-triage", triage=False)
    assert not [r for r in model.requests if r.schema_name == "TriageResult"], "no triage call"
    record = TriageRecord.model_validate_json((run / "triage.json").read_text("utf-8"))
    assert record.zones and all(
        z.zone == "OBLIGATION" and z.source == "forced" for z in record.zones
    )
    assert json.loads((run / "hazards.json").read_text("utf-8")) == []


def test_bare_extraction_sends_ids_and_texts_only(tmp_path: Path) -> None:
    model = RuleBackend()
    run = _switched(tmp_path, model, "bare", extract_context="bare")
    batches = []
    for request in model.requests:
        if request.schema_name != "ExtractResult":
            continue
        user = next(m.content for m in request.messages if m.role == "user")
        found = _DATA.search(user)
        assert found is not None
        batches.append(json.loads(found.group(2)))
    assert batches and all(b["context"] == [] and b["terms"] == [] for b in batches)
    views = [p for b in batches for p in b["passages"]]
    assert all(p["section_path"] == "" and p.get("lead_in") is None for p in views)
    manifest = RunManifest.model_validate_json((run / "run_manifest.json").read_text("utf-8"))
    assert manifest.run_args["extract_context"] == "bare"


def test_an_unknown_extract_context_is_refused(tmp_path: Path) -> None:
    with pytest.raises(Refused, match="extract_context"):
        _switched(tmp_path, RuleBackend(), "skim", extract_context="skim")
