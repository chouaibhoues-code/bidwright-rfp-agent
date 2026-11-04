"""`triage`: section views in reading order, the keyword rule, and the settling of the model's
answer: the confidence threshold, omitted and invented sections, a call that fails twice, and
the merging of profiles and hazards across calls, recorded once and replayed."""

import json
from pathlib import Path
from typing import Any

from bidwright.candidates import CompiledCues, cue_hits
from bidwright.config import load_config
from bidwright.graph.nodes import RunContext
from bidwright.graph.triage import (
    FALLBACK_REASON,
    TriageOutcome,
    keyword_zone,
    section_views,
    triage,
)
from bidwright.harness.context import ContextManager, prompt_tokens
from bidwright.llm.replay import CassetteStore
from bidwright.prompts import load_prompt
from bidwright.schemas import (
    ControlRegister,
    DocumentEntry,
    Passage,
    SectionView,
    TriageRecord,
)
from tests.node_fakes import Reply, ScriptBackend, context, dev_ingest, text

CONFIG = load_config()
ZONES = CONFIG.zones
PROMPT = load_prompt("triage")


def _passage(number: int, section: str, body: str, start: int) -> Passage:
    return Passage(
        id=f"SRC-{number:04d}",
        doc_id="doc",
        section_path=section,
        kind="sentence",
        text=body,
        start=start,
        end=start + len(body),
    )


def test_sections_follow_reading_order_with_ids_and_cue_counts() -> None:
    passages = [
        _passage(1, "", "Tender for a records service.", 0),
        _passage(2, "1 Background", "The Trust runs three clinics.", 40),
        _passage(3, "1 Background", "It shall not be bound by this text.", 80),
        _passage(4, "1 Background", "Bids close no later than 2027-01-15.", 120),
    ]
    hits = cue_hits(passages, CompiledCues.load(CONFIG.cues))
    register = ControlRegister(
        package="doc",
        precedence_source="rules",
        documents=[
            DocumentEntry(
                doc_id="doc",
                file="annex.pdf",
                sha256="0" * 64,
                format="pdf",
                role="annex",
                title="Annex",
                precedence=1,
                pages=1,
                sanitized=False,
                parser="pdfplumber",
            )
        ],
    )
    first, second = section_views(passages, register=register, cues=hits)
    assert (first.section_path, first.passages) == ("", 1), "text before the first heading"
    assert first.first_text == "[SRC-0001] Tender for a records service."
    assert second.first_text == (
        "[SRC-0002] The Trust runs three clinics. [SRC-0003] It shall not be bound by this text."
    ), "the first two passages, each with its id"
    assert second.role == "annex" and second.passages == 3
    assert second.cue_counts == {"MODAL": 1, "PROHIBITION": 1, "DEADLINE": 1, "DATE": 1}
    assert section_views(passages[:1])[0].role == "main", "no register means main"


def test_the_keyword_rule_follows_zone_order_and_the_default() -> None:
    assert keyword_zone("13 Evaluation > 13.2 Price", ZONES) == ("EVALUATION", "evaluat")
    assert keyword_zone("4 SUBMISSION OF TENDERS", ZONES) == ("INSTRUCTION", "submission")
    assert keyword_zone("2 Background > 2.1 Scope of the service", ZONES)[0] == "OBLIGATION"
    assert keyword_zone("Annex A Optional services", ZONES) == (ZONES.default, None)
    assert keyword_zone("", ZONES) == (ZONES.default, None)
    information = keyword_zone("5 Information security > 5.3 Security requirements", ZONES)
    assert information == ("OBLIGATION", "requirement"), "format inside information is no match"


def test_the_zone_table_is_the_configured_one() -> None:
    for zone, definition in ZONES.zones.items():
        assert f"| {zone} | {definition.definition} |" in PROMPT.system, zone
    assert "[SRC-0961]" in PROMPT.system and '"zone": "BACKGROUND"' in PROMPT.system


def _zone(view: SectionView, zone: str, confidence: float) -> dict[str, Any]:
    return {
        "section_path": view.section_path,
        "doc_id": view.doc_id,
        "zone": zone,
        "confidence": confidence,
        "reason": "From the heading.",
    }


def _profile(**fields: str) -> dict[str, str]:
    return {"buyer": "not_stated", "submission_deadline": "not_stated"} | fields


def _run(ctx: RunContext, run_dir: Path, budget: int) -> TriageOutcome:
    ctx.prompts["triage"] = PROMPT
    passages = dev_ingest().passages
    manager = ContextManager(run_dir, CONFIG.limits.context, passages)
    hits = cue_hits(passages, CompiledCues.load(CONFIG.cues))
    return triage(
        ctx,
        passages,
        manager=manager,
        zones=ZONES,
        budget_tokens=budget,
        run_dir=run_dir,
        cues=hits,
    )


def test_triage_fallback(tmp_path: Path) -> None:
    passages = dev_ingest().passages
    views = section_views(passages, cues=cue_hits(passages, CompiledCues.load(CONFIG.cues)))
    fixed = prompt_tokens(PROMPT, CONFIG.limits.context.chars_per_token)
    budget = fixed.rules + fixed.examples + fixed.task + 260
    planner = ContextManager(tmp_path / "plan", CONFIG.limits.context, passages)
    packs = planner.pack_sections(views, fixed_tokens=fixed, budget_tokens=budget)
    calls = [planner.sections_in(pack, views) for pack in packs]
    assert len(calls) >= 3 and len(calls[0]) >= 2, [len(c) for c in calls]
    first, second, *rest = calls
    invented = {**_zone(first[0], "OBLIGATION", 0.99), "section_path": "99 Invented"}
    replies: list[Reply] = [
        text(
            {
                "zones": [
                    _zone(first[0], "BACKGROUND", 0.9),
                    _zone(first[1], "CONTRACT", 0.5),
                    invented,
                ],
                "profile": _profile(buyer="Kestrel Vale Community College"),
                "hazards": [
                    {"kind": "DEADLINE", "src_ids": ["SRC-0001"], "summary": "Bids close."},
                    {"kind": "FORM", "src_ids": ["SRC-9999"], "summary": "Outside the RFP."},
                ],
            }
        ),
        "not json",
        "still not json",
    ]
    for members in rest:
        replies.append(
            text(
                {
                    "zones": [_zone(view, "OBLIGATION", 0.8) for view in members],
                    "profile": _profile(buyer="Another buyer", submission_deadline="2027-01-15"),
                    "hazards": [
                        {"kind": "DEADLINE", "src_ids": ["SRC-0001"], "summary": "Again."},
                        {
                            "kind": "FORMAT",
                            "src_ids": ["SRC-0003", "SRC-9999"],
                            "summary": "Keep the format.",
                        },
                    ],
                }
            )
        )
    store = CassetteStore(tmp_path / "cassettes")
    backend = ScriptBackend(replies)
    recorded = _run(context(backend, mode="record", cassettes=store), tmp_path / "run", budget)
    assert backend.replies == [] and len(backend.requests) == len(calls) + 1

    zones = recorded.record.zones
    assert [(z.doc_id, z.section_path) for z in zones] == [
        (v.doc_id, v.section_path) for v in views
    ], "one record per section, in reading order, and no invented section"
    by_path = {z.section_path: z for z in zones}
    assert (by_path[first[0].section_path].zone, by_path[first[0].section_path].source) == (
        "BACKGROUND",
        "model",
    )
    low = by_path[first[1].section_path]
    assert low.source == "keywords" and low.confidence == 0.5, "below the threshold"
    assert low.zone == keyword_zone(first[1].section_path, ZONES)[0]
    for view in first[2:]:
        omitted = by_path[view.section_path]
        assert omitted.source == "keywords" and omitted.confidence == 0.0
    for view in second:
        assert by_path[view.section_path].source == "keywords", "the call failed twice"
    assert recorded.degraded == FALLBACK_REASON
    keyword_records = sum(1 for z in zones if z.source == "keywords")
    assert recorded.record.fallback_sections == keyword_records

    profile = recorded.record.profile
    assert profile.buyer == "Kestrel Vale Community College", "the first stated value wins"
    assert profile.submission_deadline == "2027-01-15" and profile.contract_length == "not_stated"
    assert [(h.id, h.kind, h.src_ids) for h in recorded.hazards] == [
        ("HZ-001", "DEADLINE", ["SRC-0001"]),
        ("HZ-002", "FORMAT", ["SRC-0003"]),
    ], "outside ids dropped, empty and repeated hazards dropped"

    written = TriageRecord.model_validate_json(
        (tmp_path / "run" / "triage.json").read_text(encoding="utf-8")
    )
    assert written == recorded.record
    manifests = sorted(p.name for p in (tmp_path / "run" / "context").glob("triage-*.json"))
    assert manifests == [f"triage-T{n:02d}.json" for n in range(1, len(calls) + 1)]
    first_manifest = json.loads(
        (tmp_path / "run" / "context" / "triage-T01.json").read_text(encoding="utf-8")
    )
    assert first_manifest["included_src_ids"][0] == "SRC-0001"

    replayed = _run(context(None, mode="replay", cassettes=store), tmp_path / "replay", budget)
    assert replayed == recorded, "the same answer from the cassettes, with no model"


def test_a_clean_answer_keeps_the_model_zones(tmp_path: Path) -> None:
    passages = dev_ingest().passages
    views = section_views(passages)
    reply = {
        "zones": [_zone(view, "OBLIGATION", 0.9) for view in views],
        "profile": _profile(),
        "hazards": [],
    }
    backend = ScriptBackend([text(reply)])
    outcome = _run(context(backend), tmp_path, CONFIG.limits.context.budgets["triage"])
    assert len(backend.requests) == 1, "the development RFP's outline fits one call"
    assert outcome.degraded is None and outcome.hazards == []
    assert {z.source for z in outcome.record.zones} == {"model"}
    assert outcome.record.fallback_sections == 0
