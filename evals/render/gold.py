"""Generate `evals/gold/<corpus>/gold.jsonl` from a corpus spec.

One line per labeled clause, then one line per seed. Gold is versioned by the spec's
`gold_version`, and step 13 hashes each version before the first score against it.
"""

import json
from pathlib import Path
from typing import Any

from evals.render.spec import REPO_ROOT, Spec

GOLD_DIR = REPO_ROOT / "evals" / "gold"


def gold_lines(spec: Spec) -> list[dict[str, Any]]:
    lines: list[dict[str, Any]] = []
    for clause, section, lead_in in spec.clauses():
        gold = clause.gold
        line: dict[str, Any] = {
            "gold_id": clause.id,
            "gold_version": spec.gold_version,
            "doc_id": spec.doc_id,
            "kind": gold.kind,
            "section": section.heading,
            "text": clause.text,
        }
        if gold.kind == "requirement":
            line |= {
                "modality": gold.modality,
                "mandatory": gold.mandatory,
                "hazard": gold.hazard,
                "zone": gold.zone,
                "tags": gold.tags,
            }
        if lead_in is not None:
            line["lead_in"] = lead_in
        lines.append(line)
    for seed in spec.seeds:
        lines.append(
            {
                "gold_id": seed.id,
                "gold_version": spec.gold_version,
                "doc_id": spec.doc_id,
                "kind": f"{seed.type}_seed",
                "note": seed.note,
                "anchors": seed.anchors,
                "terms": seed.terms,
            }
        )
    return lines


def write_gold(spec: Spec, root: Path = GOLD_DIR) -> Path:
    path = root / spec.corpus / "gold.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    body = "".join(json.dumps(line, ensure_ascii=False) + "\n" for line in gold_lines(spec))
    path.write_text(body, encoding="utf-8", newline="\n")
    return path
