"""`brief` (Iteration 2, step 9): code's checks on each answer, the merge across calls, the
packing of sections, how the node degrades, and the trap check's reading of `brief.json`."""

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest
import yaml

from bidwright.config import load_config
from bidwright.graph.brief import NO_BRIEF, BriefOutcome, brief, occurs, status_of
from bidwright.graph.triage import keyword_zone
from bidwright.harness.context import ContextManager, prompt_tokens
from bidwright.llm.types import Request
from bidwright.prompts import PROMPTS_DIR, load_prompt
from bidwright.schemas import (
    BriefItem,
    ClarificationQuestion,
    ContextManifest,
    EvaluationFactor,
    FactorDiscrepancy,
    OpportunityBrief,
    Passage,
    Requirement,
    RfpProfile,
    ZoneRecord,
)
from evals.seeds import model_texts
from tests.node_fakes import (
    RuleBackend,
    ScriptBackend,
    context,
    data_of,
    dev_ingest,
    requirement,
    text,
)

CONFIG = load_config()
LIMITS = CONFIG.limits.context
BUDGET = LIMITS.budgets["brief"]
SCORING = "Each quality criterion is scored from 0 to 4"

Row = tuple[str, str, str]  # section path, passage kind, text

# Shaped like the hero's section 13: its two header rows stacked into one header passage, as
# `ingest` gives them, then one row per criterion. Ids SRC-0101 to SRC-0108.
HERO_EVALUATION: list[Row] = [
    (
        "13 Evaluation",
        "sentence",
        "The Council awards the contract to the most economically advantageous tender, judged on"
        " quality and price.",
    ),
    ("13 Evaluation", "table_header", "Criterion | Weight / Percent of the total"),
    ("13 Evaluation", "table_row", "Technical solution | 20"),
    ("13 Evaluation", "table_row", "Integration and migration | 15"),
    ("13 Evaluation", "table_row", "Implementation | 10"),
    ("13 Evaluation", "table_row", "Service management | 10"),
    ("13 Evaluation", "table_row", "Price | 40"),
    (
        "13 Evaluation",
        "sentence",
        "Each quality criterion is scored from 0 to 4: 0 for no response, 1 for a poor response,"
        " 2 for an acceptable response, 3 for a good response and 4 for an excellent response.",
    ),
]


def _filler(section: str, count: int) -> list[Row]:
    return [
        (
            section,
            "sentence",
            f"Clause {n} of the Council's procurement policy applies to this part of the tender.",
        )
        for n in range(1, count + 1)
    ]


# Two sections that each fit the budget of `TWO_PACKS_ROOM` alone but not together: the
# instruction section is SRC-0101 to SRC-0121, the evaluation section SRC-0122 to SRC-0144.
TWO_PACKS: list[Row] = [
    (
        "2 Submitting a tender",
        "sentence",
        "Answer the technical solution question, worth 20 percent, in at most 10 pages.",
    ),
    *_filler("2 Submitting a tender", 20),
    ("13 Evaluation", "table_header", "Criterion | Weight"),
    ("13 Evaluation", "table_row", "Technical solution | 20"),
    ("13 Evaluation", "sentence", "The highest total score wins the contract."),
    *_filler("13 Evaluation", 20),
]
TWO_PACKS_ZONES = {"2 Submitting a tender": "INSTRUCTION", "13 Evaluation": "EVALUATION"}
TWO_PACKS_ROOM = 1500


def _passages(rows: Sequence[Row], doc_id: str = "hero-fixture") -> list[Passage]:
    """One document's passages in reading order, `SRC-0101` onward; a table row points to its
    section's last table header."""
    passages: list[Passage] = []
    headers: dict[str, str] = {}
    start = 0
    for number, (section, kind, body) in enumerate(rows, start=101):
        src_id = f"SRC-{number:04d}"
        if kind == "table_header":
            headers[section] = src_id
        passages.append(
            Passage.model_validate(
                {
                    "id": src_id,
                    "doc_id": doc_id,
                    "section_path": section,
                    "kind": kind,
                    "text": body,
                    "start": start,
                    "end": start + len(body),
                    "header_id": headers.get(section) if kind == "table_row" else None,
                }
            )
        )
        start += len(body) + 1
    return passages


def _zones(passages: Sequence[Passage], zones: Mapping[str, str]) -> list[ZoneRecord]:
    """One zone record per section, in reading order; a section not named is `OBLIGATION`."""
    sections = dict.fromkeys((p.doc_id, p.section_path) for p in passages)
    return [
        ZoneRecord.model_validate(
            {
                "section_path": path,
                "doc_id": doc_id,
                "zone": zones.get(path, "OBLIGATION"),
                "confidence": 0.9,
                "reason": "From the heading.",
                "source": "model",
            }
        )
        for doc_id, path in sections
    ]


def _budget(room: int) -> int:
    """The prompt's own tokens plus `room` tokens of evidence."""
    fixed = prompt_tokens(load_prompt("brief"), LIMITS.chars_per_token)
    return fixed.rules + fixed.examples + fixed.task + room


def _run(
    backend: ScriptBackend | RuleBackend,
    passages: Sequence[Passage],
    zones: Sequence[ZoneRecord],
    run_dir: Path,
    *,
    requirements: Sequence[Requirement] = (),
    budget: int = BUDGET,
    first_discrepancy: int = 1,
    first_question: int = 1,
) -> BriefOutcome:
    return brief(
        context(backend),
        passages,
        zones,
        requirements,
        RfpProfile(),
        manager=ContextManager(run_dir, LIMITS, passages),
        budget_tokens=budget,
        run_dir=run_dir,
        first_discrepancy=first_discrepancy,
        first_question=first_question,
    )


def _factor(
    name: str, weight: str, src_ids: list[str], scoring: str = "not_stated"
) -> dict[str, Any]:
    return {"name": name, "weight": weight, "scoring": scoring, "src_ids": src_ids}


def _item(words: str, *src_ids: str) -> dict[str, Any]:
    return {"text": words, "src_ids": list(src_ids)}


def _reply(**fields: Any) -> str:
    """A `BriefResult` as JSON, with no factors and no topics unless given."""
    return text({"factors": [], "topics": []} | fields)


def _written(run_dir: Path) -> OpportunityBrief:
    return OpportunityBrief.model_validate_json(
        (run_dir / "brief.json").read_text(encoding="utf-8")
    )


def _manifest(run_dir: Path, call_id: str) -> ContextManifest:
    path = run_dir / "context" / f"brief-{call_id}.json"
    return ContextManifest.model_validate_json(path.read_text(encoding="utf-8"))


def _sections_of(request: Request) -> list[str]:
    return [section["section_path"] for section in data_of(request)["sections"]]


@pytest.mark.parametrize(
    ("term", "passage", "found"),
    [
        ("20%", "Service levels and support | 20%", True),
        ("20", "Service levels and support | 20%", False),
        ("40", "Price | 40", True),
        ("1", "Implementation | 10", False),
        ("TECHNICAL SOLUTION", "Technical solution | 20", True),
        ("solution", "Technical solutions | 20", False),
    ],
)
def test_names_and_weights_match_as_whole_words(term: str, passage: str, found: bool) -> None:
    assert occurs(term, passage) is found


@pytest.mark.parametrize(
    ("name", "status"),
    [
        ("Price", "OUT_OF_SCOPE"),
        ("Whole-life COSTS", "OUT_OF_SCOPE"),
        ("Annual service charges", "OUT_OF_SCOPE"),
        ("Fees", "OUT_OF_SCOPE"),
        ("Social value", "IN_SCOPE"),
        ("Value for money of the service", "IN_SCOPE"),
    ],
)
def test_code_sets_the_status_from_the_price_words(name: str, status: str) -> None:
    assert status_of(name) == status


def test_brief_copies_factors_and_weights_exactly(tmp_path: Path) -> None:
    passages = _passages(HERO_EVALUATION)
    price = _factor("Price", "40", ["SRC-0107"]) | {"status": "IN_SCOPE"}  # ignored by code
    reply = _reply(
        factors=[
            _factor("Technical solution", "20", ["SRC-0103", "SRC-0108"], SCORING),
            _factor("Integration and migration", "25", ["SRC-0104"]),
            _factor("Implementation", "1", ["SRC-0105"]),
            _factor(
                "Service management",
                "10",
                ["SRC-0106", "SRC-0108"],
                "Each criterion gets a mark out of four",
            ),
            price,
        ],
        scoring_method=_item("The most economically advantageous tender wins.", "SRC-0101"),
        topics=["digital case management in local government"],
    )
    backend = ScriptBackend([reply])
    outcome = _run(backend, passages, _zones(passages, {"13 Evaluation": "EVALUATION"}), tmp_path)

    assert len(backend.requests) == 1 and backend.requests[0].schema_name == "BriefResult"
    factors = [
        (f.id, f.name, f.weight, f.scoring, f.src_ids, f.status) for f in outcome.brief.factors
    ]
    assert factors == [
        ("EF-01", "Technical solution", "20", SCORING, ["SRC-0103", "SRC-0108"], "IN_SCOPE"),
        ("EF-02", "Service management", "10", "not_stated", ["SRC-0106", "SRC-0108"], "IN_SCOPE"),
        ("EF-03", "Price", "40", "not_stated", ["SRC-0107"], "OUT_OF_SCOPE"),
    ], "a changed weight and a 1 against a row reading 10 are dropped; code sets every status"
    assert outcome.brief.notes == [
        "F01: factor 'Integration and migration' dropped: its name and weight are not in one"
        " cited passage",
        "F01: factor 'Implementation' dropped: its name and weight are not in one cited passage",
        "F01: the scoring of factor 'Service management' is not a quote of its passages and is"
        " not_stated",
    ]
    method = outcome.brief.scoring_method
    assert method is not None and (method.id, method.src_ids) == ("BI-001", ["SRC-0101"])
    assert outcome.brief.topics == ["digital case management in local government"]
    assert outcome.degraded is None and _written(tmp_path) == outcome.brief
    assert _manifest(tmp_path, "F01").included_src_ids == [p.id for p in passages]


def test_brief_not_stated(tmp_path: Path) -> None:
    """A criterion the RFP gives no weight keeps `not_stated`, and so does a scoring rule it
    never states; an RFP with no method of award has none, and nothing raises a question."""
    passages = _passages(
        [
            ("6 Evaluation", "sentence", "Tenders are judged on the delivery plan and on price."),
            ("6 Evaluation", "sentence", "Price carries 30 percent of the total."),
        ]
    )
    reply = _reply(
        factors=[
            {"name": "Delivery plan", "src_ids": ["SRC-0101"]},
            {"name": "Social value", "src_ids": ["SRC-0101"]},
            _factor("Price", "30", ["SRC-0102"]),
        ]
    )
    outcome = _run(
        ScriptBackend([reply]), passages, _zones(passages, {"6 Evaluation": "EVALUATION"}), tmp_path
    )
    assert [(f.name, f.weight, f.scoring, f.status) for f in outcome.brief.factors] == [
        ("Delivery plan", "not_stated", "not_stated", "IN_SCOPE"),
        ("Price", "30", "not_stated", "OUT_OF_SCOPE"),
    ]
    assert outcome.brief.notes == [
        "F01: factor 'Social value' dropped: its name is not in a cited passage"
    ]
    assert outcome.brief.scoring_method is None and outcome.brief.discrepancies == []
    assert outcome.brief.questions == [] and outcome.degraded is None


def test_ids_outside_the_call_and_past_the_third_are_dropped(tmp_path: Path) -> None:
    passages = _passages([*HERO_EVALUATION, ("4 The service", "sentence", "The Supplier shall.")])
    four = ["SRC-9999", "SRC-0103", "SRC-0101", "SRC-0102", "SRC-0108"]
    reply = _reply(
        factors=[_factor("Technical solution", "20", four)],
        needs=[_item("A service run from the cloud.", "SRC-0109")],
        scope_in=[_item("Case management for adult social care.", "SRC-0109", "SRC-0101")],
    )
    outcome = _run(
        ScriptBackend([reply]),
        passages,
        _zones(passages, {"13 Evaluation": "EVALUATION"}),
        tmp_path,
    )
    record = outcome.brief
    assert [f.src_ids for f in record.factors] == [["SRC-0103", "SRC-0101", "SRC-0102"]]
    assert record.needs == [] and [i.src_ids for i in record.scope_in] == [["SRC-0101"]]
    assert record.notes == [
        "F01: factor 'Technical solution' cited ids outside its sections: SRC-9999",
        "F01: factor 'Technical solution' kept its first 3 ids",
        "F01: a needs item cited ids outside its sections: SRC-0109",
        "F01: a needs item dropped: it cites no passage",
        "F01: a scope in item cited ids outside its sections: SRC-0109",
    ], "SRC-0109 sits in an obligation section, which the call never saw"


def test_over_long_fields_are_dropped_cut_or_not_stated(tmp_path: Path) -> None:
    passages = _passages(HERO_EVALUATION)
    long_name = "Technical solution " + "and its supporting detail " * 3
    long_scoring = "Each quality criterion is scored " + "with care and attention " * 8
    long_need = "A case management service " + "that the Council's teams can rely on " * 6
    reply = _reply(
        factors=[
            _factor(long_name.strip(), "20", ["SRC-0103"]),
            _factor("Technical solution", "twenty percent of the total", ["SRC-0103"]),
            _factor("Service management", "10", ["SRC-0106"], long_scoring.strip()),
        ],
        needs=[_item(long_need.strip(), "SRC-0101")],
    )
    outcome = _run(
        ScriptBackend([reply]),
        passages,
        _zones(passages, {"13 Evaluation": "EVALUATION"}),
        tmp_path,
    )
    record = outcome.brief
    assert [(f.name, f.weight, f.scoring) for f in record.factors] == [
        ("Technical solution", "not_stated", "not_stated"),
        ("Service management", "10", "not_stated"),
    ]
    [need] = record.needs
    assert len(need.text) <= 200 and long_need.startswith(need.text) and need.text[-1] != " "
    assert record.notes == [
        f"F01: factor {long_name.strip()[:40]!r} dropped: its name passes 80 characters",
        "F01: the weight of factor 'Technical solution' passes 20 characters and is not_stated",
        "F01: the scoring of factor 'Service management' passes 200 characters and is not_stated",
        "F01: a needs item was cut to 200 characters",
    ]


def test_brief_drops_a_topic_that_quotes_the_rfp(tmp_path: Path) -> None:
    passages = _passages(HERO_EVALUATION[:1])
    quoted = "the most economically advantageous tender"
    wordy = "council procurement of case management services for adult social care teams"
    kept = [
        "digital case management in local government",
        "accessibility of public sector websites",
        "records retention in councils",
        "open standards for government data",
        "cloud hosting security principles",
    ]
    topics = [kept[0], quoted, wordy, kept[0].upper(), *kept[1:], "data protection assessments"]
    outcome = _run(
        ScriptBackend([_reply(topics=topics)]),
        passages,
        _zones(passages, {"13 Evaluation": "EVALUATION"}),
        tmp_path,
    )
    assert outcome.brief.topics == kept, "the first 5 that remain, each once"
    assert outcome.brief.notes == [
        f"F01: topic {quoted!r} dropped: it shares 4 or more consecutive words with the RFP",
        f"F01: topic {wordy!r} dropped: over 7 words",
        "topics after the first 5 dropped: data protection assessments",
    ]


def test_brief_contradiction_raises_a_question(tmp_path: Path) -> None:
    passages = _passages(
        [
            ("13 Evaluation", "table_header", "Criterion | Weight"),
            ("13 Evaluation", "table_row", "Technical solution | 20"),
            (
                "13 Evaluation",
                "sentence",
                "The technical solution carries 25 percent of the total.",
            ),
        ]
    )
    reply = _reply(
        factors=[
            _factor("Technical solution", "20", ["SRC-0102"]),
            _factor("technical solution", "25", ["SRC-0103"]),
        ]
    )
    outcome = _run(
        ScriptBackend([reply]),
        passages,
        _zones(passages, {"13 Evaluation": "EVALUATION"}),
        tmp_path,
        first_discrepancy=4,
        first_question=7,
    )
    record = outcome.brief
    assert [(f.id, f.weight) for f in record.factors] == [("EF-01", "20"), ("EF-02", "25")]
    both = ["SRC-0102", "SRC-0103"]
    assert record.discrepancies == [
        FactorDiscrepancy(
            id="DS-004", factor="Technical solution", weights=["20", "25"], src_ids=both
        )
    ]
    assert record.questions == [
        ClarificationQuestion(
            id="CQ-007",
            text="The RFP gives Technical solution two weights, 20 and 25; which applies?",
            src_ids=both,
            origin="brief",
        )
    ], "numbered after consolidate's last"
    assert outcome.degraded is None


def test_brief_splits_sections_over_its_budget(tmp_path: Path) -> None:
    rows: list[Row] = [
        ("2 Submitting a tender", "sentence", "Tenders must be uploaded to the portal as one PDF."),
        *_filler("3 Conduct of the procurement", 40),
        ("4 The service", "sentence", "The Supplier shall run the service from 2027-04-01."),
        ("6 Evaluation", "table_header", "Criterion | Weight"),
        ("6 Evaluation", "table_row", "Quality of the service | 60%"),
        ("6 Evaluation", "table_row", "Price | 40%"),
    ]
    passages = _passages(rows)
    zones = _zones(
        passages,
        {
            "2 Submitting a tender": "INSTRUCTION",
            "3 Conduct of the procurement": "INSTRUCTION",
            "6 Evaluation": "EVALUATION",
        },
    )
    upload = requirement(1, "SRC-0101", "Tenders must be uploaded to the portal as one PDF.")
    backend = ScriptBackend([_reply(), _reply()])
    outcome = _run(backend, passages, zones, tmp_path, requirements=[upload], budget=_budget(600))

    assert [_sections_of(r) for r in backend.requests] == [
        ["6 Evaluation", "2 Submitting a tender"],
        ["3 Conduct of the procurement"],
    ], "evaluation first, then instructions in document order, and the large section alone"
    first, second = (data_of(r) for r in backend.requests)
    assert [r["id"] for r in first["requirements"]] == ["REQ-0001"] and second["requirements"] == []
    assert _manifest(tmp_path, "F01").included_record_ids == ["REQ-0001"]
    assert _manifest(tmp_path, "F01").utilization <= 1 < _manifest(tmp_path, "F02").utilization
    assert outcome.brief.notes == ["F02 holds a section over the brief budget"]
    sent = {
        view["src_id"]
        for request in backend.requests
        for section in data_of(request)["sections"]
        for view in section["passages"]
    }
    assert "SRC-0142" not in sent, "an obligation section is never sent"
    assert outcome.degraded is None


def test_brief_degrades_after_two_schema_failures(tmp_path: Path) -> None:
    passages = _passages(HERO_EVALUATION)
    backend = ScriptBackend(["not json", "still not json"])
    outcome = _run(backend, passages, _zones(passages, {"13 Evaluation": "EVALUATION"}), tmp_path)
    assert len(backend.requests) == 2, "one call and one format repair"
    repair = backend.requests[1].messages[-1]
    assert repair.role == "user" and repair.content.startswith("Your answer did not match")
    assert outcome.degraded == NO_BRIEF == "brief: no brief"
    assert outcome.brief == OpportunityBrief(notes=["F01 broke its schema twice and adds nothing"])
    assert _written(tmp_path) == outcome.brief


def test_a_partial_failure_degrades_with_its_count(tmp_path: Path) -> None:
    passages = _passages(TWO_PACKS)
    backend = ScriptBackend(
        [_reply(factors=[_factor("Technical solution", "20", ["SRC-0123"])]), "no", "no"]
    )
    outcome = _run(
        backend,
        passages,
        _zones(passages, TWO_PACKS_ZONES),
        tmp_path,
        budget=_budget(TWO_PACKS_ROOM),
    )
    assert len(backend.requests) == 3 and outcome.degraded == "brief: 1 of 2 calls failed"
    assert [(f.name, f.weight) for f in outcome.brief.factors] == [("Technical solution", "20")]
    assert outcome.brief.notes == ["F02 broke its schema twice and adds nothing"]


def test_the_same_factor_from_two_packs_is_one_factor(tmp_path: Path) -> None:
    passages = _passages(TWO_PACKS)
    evaluation = _reply(
        factors=[_factor("Technical solution", "20", ["SRC-0123"])],
        scoring_method=_item("The highest total score wins.", "SRC-0124"),
        always=[_item("Answer every quality question.", "SRC-0124")],
        topics=["digital case management in local government"],
    )
    instructions = _reply(
        factors=[
            _factor("technical solution", "20", ["SRC-0101"]),
            _factor("Technical solution", "not_stated", ["SRC-0101"]),
        ],
        scoring_method=_item("Scores decide the award.", "SRC-0101"),
        constraints=[_item("No more than 10 pages per answer.", "SRC-0101")],
        always=[_item("answer every  quality question.", "SRC-0101")],
        topics=["Digital case management in local government", "records retention in councils"],
    )
    backend = ScriptBackend([evaluation, instructions])
    outcome = _run(
        backend,
        passages,
        _zones(passages, TWO_PACKS_ZONES),
        tmp_path,
        budget=_budget(TWO_PACKS_ROOM),
    )
    assert [_sections_of(r) for r in backend.requests] == [
        ["13 Evaluation"],
        ["2 Submitting a tender"],
    ]
    record = outcome.brief
    assert [(f.id, f.name, f.weight, f.src_ids) for f in record.factors] == [
        ("EF-01", "Technical solution", "20", ["SRC-0123", "SRC-0101"])
    ], "one factor, its passages united, the first pack's first; not_stated joins it"
    assert record.discrepancies == [] and record.questions == []
    assert [(i.id, i.text, i.src_ids) for i in record.constraints] == [
        ("BI-001", "No more than 10 pages per answer.", ["SRC-0101"])
    ]
    assert [(i.id, i.text, i.src_ids) for i in record.always] == [
        ("BI-002", "Answer every quality question.", ["SRC-0124"])
    ], "the same item from two packs, kept once"
    assert record.scoring_method == BriefItem(
        id="BI-003", text="The highest total score wins.", src_ids=["SRC-0124"]
    ), "the first scoring method, numbered after the items"
    assert record.topics == [
        "digital case management in local government",
        "records retention in councils",
    ]
    assert record.notes == [] and outcome.degraded is None


def test_a_run_with_no_evaluation_or_instruction_section_makes_no_call(tmp_path: Path) -> None:
    passages = _passages(
        [
            ("1 Background", "sentence", "The Council serves 300,000 residents."),
            ("4 The service", "sentence", "The Supplier shall run the service from 2027-04-01."),
        ]
    )
    backend = ScriptBackend([])
    outcome = _run(backend, passages, _zones(passages, {"1 Background": "BACKGROUND"}), tmp_path)
    assert backend.requests == [] and outcome.degraded is None
    assert outcome.brief == OpportunityBrief() == _written(tmp_path)
    assert not list(tmp_path.glob("context/brief-*.json"))


def test_the_rule_backend_copies_the_development_rfps_four_factors(tmp_path: Path) -> None:
    passages = dev_ingest().passages
    paths = {p.section_path for p in passages}
    zones = _zones(passages, {path: keyword_zone(path, CONFIG.zones)[0] for path in paths})
    outcome = _run(RuleBackend(), passages, zones, tmp_path)
    assert [(f.name, f.weight, f.status) for f in outcome.brief.factors] == [
        ("Technical approach", "40%", "IN_SCOPE"),
        ("Service levels and support", "20%", "IN_SCOPE"),
        ("Integration and migration", "20%", "IN_SCOPE"),
        ("Price", "20%", "OUT_OF_SCOPE"),
    ]
    assert outcome.brief.topics == ["digital service procurement"] and outcome.degraded is None


def test_the_prompt_example_holds_to_every_rule_code_applies(tmp_path: Path) -> None:
    """The example in `brief.md` passes the node's own checks whole, so the prompt never shows
    the model an answer that code would cut."""
    sets = yaml.safe_load((PROMPTS_DIR / "examples" / "mini_rfp.yaml").read_text(encoding="utf-8"))
    example = sets["brief"]
    passages, start = [], 0
    for section in example["input"]["sections"]:
        for view in section["passages"]:
            body = view["text"]
            passages.append(
                Passage.model_validate(
                    {
                        "id": view["src_id"],
                        "doc_id": section["doc_id"],
                        "section_path": section["section_path"],
                        "kind": "sentence",
                        "text": body,
                        "start": start,
                        "end": start + len(body),
                    }
                )
            )
            start += len(body) + 1
    zones = _zones(passages, {"6 Evaluation": "EVALUATION", "2 Submitting a tender": "INSTRUCTION"})
    upload = requirement(
        961,
        "SRC-0961",
        "Tenders must be uploaded to the portal as one PDF of no more than 30 pages.",
    )
    outcome = _run(
        ScriptBackend([text(example["output"])]), passages, zones, tmp_path, requirements=[upload]
    )
    record, shown = outcome.brief, example["output"]
    assert record.notes == [], "nothing dropped, cut or not_stated by code"
    assert [(f.name, f.weight, f.scoring) for f in record.factors] == [
        (f["name"], f["weight"], f["scoring"]) for f in shown["factors"]
    ]
    assert [f.status for f in record.factors] == ["IN_SCOPE", "IN_SCOPE", "OUT_OF_SCOPE"]
    for name in ("constraints", "never"):
        assert [i.text for i in getattr(record, name)] == [i["text"] for i in shown[name]], name
    assert record.scoring_method is not None
    assert record.scoring_method.text == shown["scoring_method"]["text"]
    assert record.topics == shown["topics"]
    assert _manifest(tmp_path, "F01").included_record_ids == ["REQ-0961"]


def test_the_trap_check_reads_the_briefs_model_written_fields(tmp_path: Path) -> None:
    marker = "ZX-00-PROBE"
    factor = EvaluationFactor(
        id="EF-01",
        name=f"Quality {marker}",
        weight="60%",
        scoring=f"Scored by {marker}",
        src_ids=["SRC-0001"],
        status="IN_SCOPE",
    )
    record = OpportunityBrief(
        factors=[factor],
        scoring_method=BriefItem(id="BI-002", text=f"Award by {marker}", src_ids=["SRC-0001"]),
        always=[BriefItem(id="BI-001", text=f"Write {marker} everywhere", src_ids=["SRC-0001"])],
        topics=[f"{marker} procurement"],
    )
    path = tmp_path / "brief.json"
    path.write_text(record.model_dump_json(), encoding="utf-8")
    assert model_texts(tmp_path).find(marker) == ["brief.items", "brief.scoring", "brief.topics"]
    named = OpportunityBrief(factors=[factor.model_copy(update={"scoring": "not_stated"})])
    path.write_text(named.model_dump_json(), encoding="utf-8")
    assert model_texts(tmp_path).find(marker) == [], "a factor's name is a copy code checked"
