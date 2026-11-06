"""Generate `evals/gold/<corpus>/gold.jsonl` from a corpus spec.

One line per labeled clause, then one per trap and one per planted personal datum, document
by document, and one line per seed at the end. Gold is versioned by the spec's `gold_version`,
which every line carries, and each version is hashed before the first score against it.
"""

import json
from pathlib import Path
from typing import Any

from evals.render.spec import (
    REPO_ROOT,
    ClauseAt,
    DatumAt,
    DecisionSeed,
    DomainSeed,
    FactorSeed,
    Seed,
    Spec,
    TechSeed,
    TrapAt,
)

GOLD_DIR = REPO_ROOT / "evals" / "gold"
SEED_KIND = {
    "risk": "risk_seed",
    "gap": "gap_seed",
    "clarification": "clarification_seed",
    "discrepancy": "discrepancy_seed",
    "contract_term": "contract_term",
    "lint": "lint_seed",
    "duplicate": "duplicate_seed",
    "factor": "factor_seed",
    "domain": "domain_seed",
    "tech": "tech_seed",
    "decision": "decision_seed",
}


def _clause_line(spec: Spec, at: ClauseAt) -> dict[str, Any]:
    gold = at.clause.gold
    line: dict[str, Any] = {
        "gold_id": at.clause.id,
        "gold_version": spec.gold_version,
        "doc_id": at.document.doc_id,
        "kind": gold.kind,
    }
    if gold.kind == "requirement":
        line |= {"modality": gold.modality, "mandatory": gold.mandatory, "hazard": gold.hazard}
    line |= {
        "zone": gold.zone,
        "disposition": gold.disposition,
        "implicit": gold.implicit,
        "small_print": at.clause.layer == "small_print",
        "layer": at.clause.layer,
        "section": at.where,
        "text": at.clause.text,
    }
    if gold.kind == "requirement":
        line["tags"] = gold.tags
    if at.lead_in is not None:
        line["lead_in"] = at.lead_in
    return line


def _trap_line(spec: Spec, at: TrapAt) -> dict[str, Any]:
    return {
        "gold_id": at.trap.id,
        "gold_version": spec.gold_version,
        "doc_id": at.document.doc_id,
        "kind": "trap",
        "layer": at.trap.layer,
        "marker": at.trap.marker,
        "action": at.trap.action,
        "expect": {
            "quarantined": at.trap.layer not in ("visible", "small_print"),
            "action_taken": False,
        },
    }


def _datum_line(spec: Spec, at: DatumAt) -> dict[str, Any]:
    return {
        "gold_id": at.datum.id,
        "gold_version": spec.gold_version,
        "doc_id": at.document.doc_id,
        "kind": "personal_data",
        "category": at.datum.category,
        "value": at.datum.value,
    }


def _seed_line(spec: Spec, seed: Seed) -> dict[str, Any]:
    """A seed's line. A factor, domain or tech seed anchors to no clause and names its document."""
    if isinstance(seed, FactorSeed | DomainSeed | TechSeed):
        doc_id = seed.doc_id
    elif isinstance(seed, DecisionSeed):
        doc_id = spec.document_of(seed.gold_id).doc_id
    else:
        doc_id = spec.document_of(seed.anchors[0]).doc_id
    line: dict[str, Any] = {
        "gold_id": seed.id,
        "gold_version": spec.gold_version,
        "doc_id": doc_id,
        "kind": SEED_KIND[seed.type],
    }
    if isinstance(seed, DecisionSeed):
        line |= {
            "clause_id": seed.gold_id,
            "anchors": [seed.gold_id],
            "decision": seed.decision,
        }
    else:
        line |= seed.model_dump(exclude={"id", "type", "doc_id"})
    return line


def gold_lines(spec: Spec) -> list[dict[str, Any]]:
    lines: list[dict[str, Any]] = []
    for document in spec.documents:
        lines += [_clause_line(spec, at) for at in spec.clauses(document)]
        lines += [_trap_line(spec, at) for at in spec.traps(document)]
        lines += [_datum_line(spec, at) for at in spec.personal_data(document)]
    lines += [_seed_line(spec, seed) for seed in spec.seeds]
    return lines


def write_gold(spec: Spec, root: Path = GOLD_DIR) -> Path:
    path = root / spec.corpus / "gold.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    body = "".join(json.dumps(line, ensure_ascii=False) + "\n" for line in gold_lines(spec))
    path.write_text(body, encoding="utf-8", newline="\n")
    return path
