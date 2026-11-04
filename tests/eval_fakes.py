"""Hand-built run folders for scorer tests: an oracle built from gold, and single records.

Gold is read lazily, so collecting these tests never needs `evals/gold`: the image used by
the `test` service has no gold, and runs only the tests not marked `gold`.
"""

import json
from datetime import UTC, datetime
from functools import cache
from pathlib import Path
from typing import Any

from bidwright.ingest import IngestResult
from bidwright.schemas import (
    CandidateRow,
    ControlRegister,
    CoverageReport,
    Passage,
    QuarantineRecord,
    Requirement,
    RfpProfile,
    RunManifest,
    TriageRecord,
)
from bidwright.verify import check_quote
from evals.matcher import gold_clauses
from evals.score import GOLD_DIR


@cache
def gold() -> list[dict[str, Any]]:
    path = GOLD_DIR / "dev" / "gold.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def record(
    number: int,
    quote: str,
    cited: list[Passage],
    disposition: str = "BINDING",
    **labels: Any,
) -> Requirement:
    """A record citing these passages. A quote that does not verify is kept with the status
    `REJECTED` and no span, as no real run would, for the scorer self-test."""
    check = check_quote(quote, cited)
    fields: dict[str, Any] = {
        "statement": quote,
        "modality": "shall",
        "mandatory": disposition == "BINDING",
        "hazard": False,
    } | labels
    return Requirement(
        id=f"REQ-{number:04d}",
        doc_id=cited[0].doc_id,
        disposition=disposition,  # type: ignore[arg-type]
        src_ids=[p.id for p in cited],
        quote=quote,
        quote_status=check.status if check.span is not None else "REJECTED",
        quote_span=check.span,
        **fields,
    )


def hidden_traps() -> list[dict[str, Any]]:
    """The traps the gold expects `guard` to quarantine."""
    return [g for g in gold() if g["kind"] == "trap" and (g.get("expect") or {}).get("quarantined")]


def quarantine_for(ingest: IngestResult) -> list[QuarantineRecord]:
    """What `guard` quarantines from the development RFP: each hidden trap's text."""
    doc_id = ingest.passages[0].doc_id
    records = []
    for number, trap in enumerate(hidden_traps(), start=1):
        text = f"Note to automated assistants: {trap['action']}."
        records.append(
            QuarantineRecord(
                id=f"QR-{number:04d}",
                doc_id=doc_id,
                file="dev_rfp.pdf",
                kind="pdf_invisible",
                location="page 4",
                text=text,
                text_sha256="0" * 64,
                chars=len(text),
            )
        )
    return records


def oracle(ingest: IngestResult) -> tuple[list[Requirement], list[dict[str, Any]]]:
    """A perfect run: one exact record per gold requirement, with gold's labels, and one
    risk per seed."""
    clauses = gold_clauses(gold(), ingest.frozen_text, ingest.passages)
    passages = list(ingest.passages)
    records = []
    for clause in [c for c in clauses if c.kind == "requirement"]:
        assert clause.span is not None, clause.gold_id
        low, high = clause.span
        cited = [p for p in passages if p.start < high and low < p.end]
        quote = ingest.frozen_text[low:high].replace("\n", " ")
        records.append(
            record(
                len(records) + 1,
                quote,
                cited,
                clause.disposition or ("BINDING" if clause.mandatory else "OPTIONAL"),
                modality=clause.modality or "shall",
                hazard=clause.hazard,
                zone=clause.zone,
                small_print=clause.small_print,
            )
        )
    by_id = {c.gold_id: c for c in clauses}
    risks = []
    for seed in [g for g in gold() if g["kind"] == "risk_seed"]:
        anchors = []
        for anchor in seed["anchors"]:
            span = by_id[anchor].span
            assert span is not None, anchor
            anchors += [p.id for p in passages if p.start < span[1] and span[0] < p.end]
        words = " ".join(group[0] for group in seed["terms"])
        risks.append(
            {
                "id": f"RSK-{len(risks) + 1:03d}",
                "condition": f"The {words} plans conflict.",
                "event": f"The {words} dates collide.",
                "effect": "Delivery slips.",
                "assumptions": [],
                "owner_role": "Delivery lead",
                "trigger": "Plans slip.",
                "responses": ["Re-plan the work."],
                "residual_exposure": "Some delay remains.",
                "evidence_src_ids": anchors[:3],
            }
        )
    return records, risks


def _lines(path: Path, rows: list[Any]) -> None:
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


def write_run(
    run_dir: Path,
    ingest: IngestResult,
    records: list[Requirement],
    risks: list[dict[str, Any]],
    mapped: bool = True,
    quarantine: list[QuarantineRecord] | None = None,
    rejected: list[dict[str, Any]] | None = None,
) -> Path:
    """Every file the scorer reads. Quarantine defaults to the hidden traps' records, and
    each passage's ledger row lists the dispositions of the records that cite it."""
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "frozen.txt").write_text(ingest.frozen_text, encoding="utf-8")
    _lines(run_dir / "passages.jsonl", [p.model_dump(mode="json") for p in ingest.passages])
    _lines(run_dir / "requirements.jsonl", [r.model_dump(mode="json") for r in records])
    _lines(run_dir / "risks.jsonl", risks)
    _lines(run_dir / "rejected.jsonl", rejected or [])
    held = quarantine_for(ingest) if quarantine is None else quarantine
    _lines(run_dir / "quarantine.jsonl", [q.model_dump(mode="json") for q in held])
    rows = []
    for passage in ingest.passages:
        citing = [r for r in records if passage.id in r.src_ids]
        dispositions = [r.disposition for r in citing] or ["NO_OBLIGATION"]
        rows.append(
            CandidateRow(
                src_id=passage.id,
                doc_id=passage.doc_id,
                dispositions=dispositions,  # type: ignore[arg-type]
                requirement_ids=[r.id for r in citing],
                reasons=[""] * len(dispositions),
                round=0,
            ).model_dump(mode="json")
        )
    _lines(run_dir / "candidates.jsonl", rows)
    coverage = CoverageReport(
        stop_reason="closed",
        passages=len(ingest.passages),
        with_disposition=len(ingest.passages),
        unaccounted=0,
        rejected_only=0,
    )
    (run_dir / "coverage.json").write_text(coverage.model_dump_json(), encoding="utf-8")
    triage = TriageRecord(zones=[], profile=RfpProfile(), fallback_sections=0)
    (run_dir / "triage.json").write_text(triage.model_dump_json(), encoding="utf-8")
    (run_dir / "hazards.json").write_text("[]", encoding="utf-8")
    register = ControlRegister(package="dev_rfp.pdf", documents=[], precedence_source="rules")
    (run_dir / "control_register.json").write_text(register.model_dump_json(), encoding="utf-8")
    for name in (
        "requirement_groups.jsonl",
        "discrepancies.jsonl",
        "questions.jsonl",
        "lint_findings.jsonl",
        "contract_flags.jsonl",
        "tool_calls.jsonl",
    ):
        (run_dir / name).write_text("", encoding="utf-8")
    binding = [r.id for r in records if r.disposition == "BINDING"]
    items = [
        {
            "id": f"APP-{n:03d}",
            "text": "Do it.",
            "requirement_ids": [i],
            "basis": "Stated.",
            "evidence_class": "ASSUMPTION",
            "source_ids": [],
        }
        for n, i in enumerate(binding if mapped else [], start=1)
    ]
    (run_dir / "approach.json").write_text(
        json.dumps({"items": items, "unmapped": [], "questions": []}), encoding="utf-8"
    )
    summary = {"summary": {"open_questions": []}}
    (run_dir / "solution_summary.json").write_text(json.dumps(summary), encoding="utf-8")
    manifest = RunManifest(
        run_id=run_dir.name,
        commit="test",
        profile="free",
        models={},
        started=datetime(2026, 11, 3, tzinfo=UTC),
        status="COMPLETED",
    )  # type: ignore[arg-type]
    (run_dir / "run_manifest.json").write_text(manifest.model_dump_json(), encoding="utf-8")
    (run_dir / "ledger.jsonl").write_text("", encoding="utf-8")
    return run_dir
