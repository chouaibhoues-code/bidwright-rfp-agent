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
from bidwright.schemas import Passage, Requirement, RunManifest
from bidwright.verify import check_quote
from evals.matcher import gold_clauses
from evals.score import GOLD_DIR


@cache
def gold() -> list[dict[str, Any]]:
    path = GOLD_DIR / "dev" / "gold.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def record(
    number: int, quote: str, cited: list[Passage], disposition: str = "BINDING"
) -> Requirement:
    check = check_quote(quote, cited)
    assert check.span is not None, quote
    return Requirement(
        id=f"REQ-{number:04d}",
        doc_id=cited[0].doc_id,
        statement=quote,
        modality="shall",
        mandatory=disposition == "BINDING",
        hazard=False,
        disposition=disposition,  # type: ignore[arg-type]
        src_ids=[p.id for p in cited],
        quote=quote,
        quote_status=check.status,
        quote_span=check.span,
    )


def oracle(ingest: IngestResult) -> tuple[list[Requirement], list[dict[str, Any]]]:
    """A perfect run: one exact record per gold requirement, and one risk per seed."""
    clauses = gold_clauses(gold(), ingest.frozen_text)
    passages = list(ingest.passages)
    records = []
    for clause in [c for c in clauses if c.kind == "requirement"]:
        cited = [p for p in passages if p.start < clause.span[1] and clause.span[0] < p.end]
        quote = ingest.frozen_text[clause.span[0] : clause.span[1]].replace("\n", " ")
        line = next(g for g in gold() if g["gold_id"] == clause.gold_id)
        item = record(len(records) + 1, quote, cited, "BINDING" if clause.mandatory else "OPTIONAL")
        records.append(
            item.model_copy(update={"modality": line["modality"], "hazard": clause.hazard})
        )
    by_id = {c.gold_id: c for c in clauses}
    risks = []
    for seed in [g for g in gold() if g["kind"] == "risk_seed"]:
        anchors = [
            p.id
            for p in passages
            for a in seed["anchors"]
            if p.start < by_id[a].span[1] and by_id[a].span[0] < p.end
        ]
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


def write_run(
    run_dir: Path,
    ingest: IngestResult,
    records: list[Requirement],
    risks: list[dict[str, Any]],
    mapped: bool = True,
) -> Path:
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "frozen.txt").write_text(ingest.frozen_text, encoding="utf-8")
    (run_dir / "passages.jsonl").write_text(
        "".join(p.model_dump_json() + "\n" for p in ingest.passages), encoding="utf-8"
    )
    (run_dir / "requirements.jsonl").write_text(
        "".join(r.model_dump_json() + "\n" for r in records), encoding="utf-8"
    )
    (run_dir / "risks.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in risks), encoding="utf-8"
    )
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
