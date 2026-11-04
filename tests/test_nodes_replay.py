"""The 0a node chain recorded once on scripted replies, then replayed with no model at all."""

from pathlib import Path
from typing import Any

import pytest

from bidwright.graph.nodes import (
    RunContext,
    approach,
    assign_requirements,
    draft,
    extract_batch,
    risk,
    section_records,
)
from bidwright.llm.replay import CassetteStore
from tests.node_fakes import (
    GOOD_RISK,
    RISK_LIMITS,
    ScriptBackend,
    context,
    dev_ingest,
    gateway,
    text,
    tools,
)

pytestmark = pytest.mark.replay

SECTION_4 = [p for p in dev_ingest().passages if "4 Requirements >" in p.section_path]
EXTRACT = {
    "items": [
        {
            "src_ids": ["SRC-0020"],
            "quote": "The Supplier shall keep an audit record of every signature event",
            "statement": "Keep an audit record of every signature event.",
            "modality": "shall",
            "disposition": "BINDING",
            "hazard": False,
        }
    ],
    "no_obligation_src_ids": [f"SRC-{n:04d}" for n in range(21, 29)],
}
APPROACH = {
    "items": [{"text": "Audit log.", "requirement_ids": ["REQ-0001"], "basis": "Stated."}],
    "unmapped_requirement_ids": [],
    "open_questions": [],
}
SECTION = {
    "title": "Section",
    "text": "We keep an audit log [REQ-0001].",
    "cited_ids": ["REQ-0001"],
}


def _chain(ctx: RunContext, tmp_path: Path) -> dict[str, Any]:
    outcome = extract_batch(ctx, SECTION_4, "B01")
    requirements, rejected = assign_requirements([outcome], dev_ingest().passages, "dev-rfp")
    plan = approach(ctx, requirements)
    found = risk(ctx, requirements, plan.items, gateway(tmp_path), RISK_LIMITS)
    sections = [
        draft(ctx, section, section_records(section, requirements, plan.items, found.risks, []))
        for section in ("understanding", "approach", "risks_and_assumptions")
    ]
    return {
        "requirements": [r.model_dump() for r in requirements],
        "rejected": rejected,
        "approach": [a.model_dump() for a in plan.items],
        "risks": [r.model_dump() for r in found.risks],
        "sections": [s.model_dump() for s in sections],
    }


def test_the_chain_replays_without_a_model(tmp_path: Path) -> None:
    store = CassetteStore(tmp_path / "cassettes")
    script = ScriptBackend(
        [
            text(EXTRACT),
            text(APPROACH),
            tools(("search_rfp", {"query": "go-live migration"})),
            "Done.",
            text({"risks": [GOOD_RISK], "open_questions": []}),
            text(SECTION),
            text(SECTION),
            text(SECTION),
        ]
    )
    recorded_ctx = context(script, mode="record", cassettes=store)
    recorded = _chain(recorded_ctx, tmp_path / "a")
    assert script.replies == []
    replay_ctx = context(None, mode="replay", cassettes=store)
    replayed = _chain(replay_ctx, tmp_path / "b")
    assert replayed == recorded
    assert len(replay_ctx.ledger) == len(recorded_ctx.ledger) == 8
    assert all(entry.replayed for entry in replay_ctx.ledger)
    assert replay_ctx.budget.requests == 0
