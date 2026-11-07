"""S-12 method cards evaluation: checks and case runner (Iteration 3, step 18).

evals/s12/cases.yaml holds, under max_cost_usd: 1, one negative case for each
card that a node of this iteration consumes: the card, the node, a fixture of
that node's task model in evals/s12/fixtures/, and a named check in evals/cards.py
that counts a violation in the node's answer. Each check reads the fields of that
node's real answer schema (`ExtractResult`, `ConsolidationResult`, `DecideResult`,
`AssessmentResult`, `OptionsResult`, `BlueprintPlan`, `RiskRegister`) and the case's task,
and counts the violation as a model would commit it: figures or names the answer adds that
the task does not hold, a verdict the evidence cannot carry, a claim with no hedge (step 19).
A card whose consuming node's answer has no field that could show its violation is listed
under `not_testable`, which the report names and nothing runs.

`bidwright-eval cards --repeats 5 --profile P` runs each case once a repeat with
its family off and on through `graph/single.py`'s `call_node`, stops at the cost
cap, and writes evals/results/s12-cards/: per family, its cases' violations summed
per repeat, and S-12's decision by the rule the family's rung of the `s12-cards` block in
evals/hypotheses.yaml names (`superiority` over the off runs' spread).
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class CardCase:
    id: str
    card: str
    family: str
    node: str
    fixture: str
    check: str


def _get_field(obj: Any, name: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


# Each check reads the node's answer and the task the case gave it, both as `model_dump` dicts,
# and counts the card's violation as a model would commit it: words or figures the answer adds
# that the task does not hold, a verdict the evidence cannot carry, or a claim with no hedge.
# Step 19 replaced checks that searched for phrases no model writes ("invented acceptance",
# "silent overwrite"), which counted 0 with the cards off and on alike.

_WORD = re.compile(r"[a-z0-9]+(?:[.'][a-z0-9]+)*")
_NUMBER = re.compile(r"\d+(?:[.,]\d+)?")


def _words(text: str) -> set[str]:
    return set(_WORD.findall(text.lower()))


def _strings(value: Any) -> list[str]:
    """Every string inside an answer or a task, depth first."""
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for v in value.values() for s in _strings(v)]
    if isinstance(value, list):
        return [s for v in value for s in _strings(v)]
    return []


def _passages(task: Any) -> dict[str, str]:
    return {p["src_id"]: p["text"] for p in _get_field(task, "passages", []) or []}


def _added(text: str, source: str, terms: set[str]) -> set[str]:
    """The terms and numbers in `text` that `source` does not hold."""
    have = _words(source)
    found = {w for w in _words(text) if w in terms and w not in have}
    found |= {n for n in _NUMBER.findall(text) if n not in _NUMBER.findall(source)}
    return found


# Words that fix what REQ-001 says to leave open: a frequency, a deadline, a format or an
# acceptance result.
_FIXING = {
    "daily", "weekly", "fortnightly", "monthly", "quarterly", "annually", "annual", "yearly",
    "within", "days", "hours", "deadline", "kpi", "kpis", "sla", "template", "dashboard",
    "signed", "approved", "accuracy", "complete", "completeness", "timeliness",
}  # fmt: skip
_RESOLVES = re.compile(
    r"\b(?:conflict\w*|supersed\w*|overrid\w*|inconsisten\w*|precedence|instead|prevail\w*)\b",
    re.I,
)
_HEDGE = re.compile(
    r"\b(?:unverified|not (?:yet )?(?:verified|confirmed|proven|evidenced)|to be (?:verified|"
    r"confirmed|tested)|subject to|requires? (?:\w+ ){0,3}(?:evidence|testing|confirmation|"
    r"verification)|pending|unknown|not stated|unstated|not specified|cannot (?:confirm|"
    r"verify)|gap|clarif\w*|hypothe\w*|indicative|provisional)\b",
    re.I,
)


def check_extract_req001(output: Any, task: Any) -> int:
    """REQ-001: missing attributes justify clarification, not invented acceptance. An item
    whose statement adds a frequency, deadline, format, acceptance word or number that its
    passages do not hold."""
    passages = _passages(task)
    violations = 0
    for item in _get_field(output, "items", []) or []:
        source = " ".join(passages.get(s, "") for s in _get_field(item, "src_ids", []) or [])
        if _added(_get_field(item, "statement", "") or "", source, _FIXING):
            violations += 1
    return violations


def check_extract_req002(output: Any, task: Any) -> int:
    """REQ-002 on extract: two retention periods with different scopes are not a conflict to
    resolve. An item whose statement resolves them (conflict, supersede, override,
    precedence), or applies a period to the other clause's scope."""
    violations = 0
    for item in _get_field(output, "items", []) or []:
        text = (_get_field(item, "statement", "") or "").lower()
        financial = "financ" in text
        seven = bool(re.search(r"\b(?:7|seven)\b", text))
        five = bool(re.search(r"\b(?:5|five)\b", text))
        if (
            _RESOLVES.search(text)
            or (seven and not financial)
            or (five and financial and not seven)
        ):
            violations += 1
    return violations


def check_extract_req003(output: Any, task: Any) -> int:
    """REQ-003 on extract: two audit clauses with different exceptions stay two obligations.
    One count for each item that cites both passages, one if no item keeps the emergency
    exception, and one for each passage no item cites."""
    items = _get_field(output, "items", []) or []
    passages = list(_passages(task))
    cited = [set(_get_field(item, "src_ids", []) or []) for item in items]
    violations = sum(1 for ids in cited if all(p in ids for p in passages))
    if not any("emergenc" in (_get_field(i, "statement", "") or "").lower() for i in items):
        violations += 1
    violations += sum(1 for p in passages if not any(p in ids for ids in cited))
    return violations


def _members(task: Any) -> list[str]:
    return [m["id"] for m in _get_field(task, "members", []) or []]


def check_consolidate_req002(output: Any, task: Any) -> int:
    """REQ-002 on consolidate: before a shared scope, time and data-category check, a
    discrepancy is conditional. Each discrepancy over the case's members marked
    `established`."""
    members = set(_members(task))
    return sum(
        1
        for d in _get_field(output, "discrepancies", []) or []
        if _get_field(d, "state", "") == "established"
        and members <= set(_get_field(d, "requirement_ids", []) or [])
    )


def check_consolidate_req003(output: Any, task: Any) -> int:
    """REQ-003 on consolidate: the case's two members carry different exceptions, so any
    duplicate pair, or any `SUPERSEDED` discrepancy between them, merges separate
    obligations."""
    members = set(_members(task))
    pairs = len(_get_field(output, "duplicates", []) or [])
    superseded = sum(
        1
        for d in _get_field(output, "discrepancies", []) or []
        if _get_field(d, "kind", "") == "SUPERSEDED"
        and members <= set(_get_field(d, "requirement_ids", []) or [])
    )
    return pairs + superseded


def check_consolidate_cfg001(output: Any, task: Any) -> int:
    """CFG-001: a buyer addendum triggers change review, not silent mutation. One count for
    each duplicate pair over the original clause and its addendum, and one if no discrepancy
    or question names both."""
    members = set(_members(task))
    pairs = sum(
        1
        for pair in _get_field(output, "duplicates", []) or []
        if {_get_field(pair, "requirement_id", ""), _get_field(pair, "duplicate_of", "")} <= members
    )
    named = [
        set(_get_field(d, "requirement_ids", []) or [])
        for d in (_get_field(output, "discrepancies", []) or [])
    ]
    named += [
        set(_get_field(q, "requirement_ids", []) or [])
        for q in (_get_field(output, "questions", []) or [])
    ]
    reviewed = any(members <= ids for ids in named)
    return pairs + (0 if reviewed else 1)


# Products and versions a model may name for a buyer system the task leaves unstated.
_PRODUCTS = re.compile(
    r"\b(?:arcgis|esri|qgis|mapinfo|geoserver|postgis|smallworld|intergraph|geomedia|autocad|"
    r"oracle|sql server|postgresql|postgres|mysql|mongodb|db2|sap|salesforce|dynamics|"
    r"servicenow|northgate|civica|capita|idox|tascomi|uniform)\b",
    re.I,
)
_VERSION = re.compile(r"\b(?:v|version\s*)?\d+\.\d+(?:\.\d+)?\b", re.I)


def _named(text: str, source: str) -> bool:
    """Whether `text` names a product or version that `source` does not."""
    have = source.lower()
    products = {m.lower() for m in _PRODUCTS.findall(text)} - {
        m.lower() for m in _PRODUCTS.findall(have)
    }
    versions = set(_VERSION.findall(text)) - set(_VERSION.findall(have))
    return bool(products or versions)


def check_decide_ba001(output: Any, task: Any) -> int:
    """BA-001 on decide: map stated states and mark missing ones unknown. Each claim, and the
    reason, gap or question, that names a product or version for the buyer's system that the
    need does not state."""
    source = " ".join(_strings(task))
    texts = [_get_field(c, "text", "") or "" for c in _get_field(output, "claims", []) or []]
    texts += [_get_field(output, k, "") or "" for k in ("reason", "gap", "question")]
    return sum(1 for text in texts if _named(text, source))


_INTEGRATES = re.compile(r"\b(?:integrat\w*|interfac\w*|connect\w*|certif\w*)\b", re.I)


def check_decide_ba003(output: Any, task: Any) -> int:
    """BA-003 on decide: a generic API does not prove integration with a named buyer system.
    Each claim that asserts integration with SAP without a hedge (unverified, to be tested,
    requires evidence, and the like)."""
    violations = 0
    for claim in _get_field(output, "claims", []) or []:
        text = _get_field(claim, "text", "") or ""
        if (
            re.search(r"\bsap\b", text, re.I)
            and _INTEGRATES.search(text)
            and not _HEDGE.search(text)
        ):
            violations += 1
    return violations


def check_assess_ba003(output: Any, task: Any) -> int:
    """BA-003 on assess: generic REST evidence cannot support the named SAP integration, in
    full or in part; a `SUPPORTED` or `PARTIALLY_SUPPORTED` verdict counts."""
    return int(_get_field(output, "disposition", "") in ("SUPPORTED", "PARTIALLY_SUPPORTED"))


_CHOOSES = re.compile(
    r"\b(?:recommend\w*|preferred|best (?:option|choice|value)|optimal|clear winner|should be "
    r"(?:selected|chosen|adopted)|we (?:select|choose)|is selected|is chosen)\b",
    re.I,
)
_COMPLIES = re.compile(
    r"\b(?:no[- ]bid|bid/no|go/no|bid threshold|(?:fully |is |are |be |remains? )compliant|"
    r"ensur\w* (?:full )?compliance|guarantee\w* (?:full )?compliance|achiev\w* (?:full )?"
    r"compliance|meets? (?:all )?(?:statutory|regulatory|legal)|complies with)\b",
    re.I,
)


def _options(output: Any) -> list[str]:
    return [" ".join(_strings(o)) for o in _get_field(output, "options", []) or []]


def check_options_ba002(output: Any, task: Any) -> int:
    """BA-002: a weighted choice is hypothetical unless an approved policy exists. Each option
    whose text declares it the choice (recommended, preferred, optimal) without a hedge."""
    return sum(1 for text in _options(output) if _CHOOSES.search(text) and not _HEDGE.search(text))


def check_options_gov001(output: Any, task: Any) -> int:
    """GOV-001: advisory knowledge sets no bid/no-bid threshold and asserts no regulatory or
    contractual compliance. Each option whose text does either without a hedge."""
    return sum(1 for text in _options(output) if _COMPLIES.search(text) and not _HEDGE.search(text))


def _facts(output: Any, *names: str) -> list[dict[str, Any]]:
    return [f for name in names for f in _get_field(output, name, []) or []]


_ID_FIELDS = ("src_ids", "requirement_ids", "claim_ids", "domain_item_ids")


def check_blueprint_ba001(output: Any, task: Any) -> int:
    """BA-001 on blueprint: map stated current states and mark missing ones unknown. Each
    current-state fact that cites no source and does not say it is unknown, or that names a
    product or version the task does not."""
    source = " ".join(_strings(task))
    violations = 0
    for fact in _facts(output, "current_state"):
        text = _get_field(fact, "text", "") or ""
        unsourced = not any(_get_field(fact, k, []) for k in _ID_FIELDS)
        if (unsourced and not _HEDGE.search(text)) or _named(text, source):
            violations += 1
    return violations


_PRICE = re.compile(
    r"(?:[£$€]\s?\d|\b(?:usd|gbp|eur)\s?\d|\b\d[\d,.]*\s?(?:k|m)?\s?(?:usd|gbp|eur|pounds|dollars|euros)\b)",
    re.I,
)
_FEASIBLE = re.compile(
    r"\b(?:fixed[- ]price|guarantee\w*|on time and (?:on|within) budget|within budget|"
    r"feasib\w+|will be (?:delivered|completed|live) (?:by|in|within))\b",
    re.I,
)


def _plan_texts(output: Any) -> list[str]:
    texts = [
        _get_field(f, "text", "") or ""
        for f in _facts(output, "current_state", "target_state", "assumptions", "ground_rules")
    ]
    texts += [
        f"{_get_field(n, 'name', '')} {_get_field(n, 'deliverable', '')}"
        for n in _get_field(output, "wbs", []) or []
    ]
    texts += [
        f"{_get_field(w, 'name', '')} {_get_field(w, 'objective', '')}"
        for w in _get_field(output, "workstreams", []) or []
    ]
    return texts


def check_blueprint_del001(output: Any, task: Any) -> int:
    """DEL-001: a provisional WBS does not prove price or schedule feasibility. Each text that
    states a price, or asserts feasibility or a guaranteed delivery, without a hedge."""
    return sum(
        1
        for text in _plan_texts(output)
        if _PRICE.search(text) or (_FEASIBLE.search(text) and not _HEDGE.search(text))
    )


_EFFORT = re.compile(
    r"\b\d[\d,.]*\s?(?:person[- ]?(?:days|weeks|months)|man[- ]?(?:days|months)|fte|"
    r"days of effort|hours of effort|effort days)\b",
    re.I,
)
_BASIS = re.compile(
    r"\b(?:basis|based on|assum\w*|estimat\w*|provisional|range|uncertain\w*)\b", re.I
)


def check_blueprint_del002(output: Any, task: Any) -> int:
    """DEL-002: an estimate states its basis, source and uncertainty. Each text that gives an
    effort or cost figure with no basis or uncertainty word."""
    return sum(
        1
        for text in _plan_texts(output)
        if (_EFFORT.search(text) or _PRICE.search(text)) and not _BASIS.search(text)
    )


_DATE = re.compile(
    r"\b(?:\d{4}-\d{2}-\d{2}|(?:january|february|march|april|may|june|july|august|september|"
    r"october|november|december) \d{4}|q[1-4] \d{4}|(?:month|week) \d+|\d+ (?:weeks|months))\b",
    re.I,
)
_DEPENDS = re.compile(
    r"\b(?:after|following|once|depend\w*|subject to|acceptance|checkpoint|milestone|"
    r"prerequisite|lead time|provided that|assum\w*)\b",
    re.I,
)


def check_blueprint_del003(output: Any, task: Any) -> int:
    """DEL-003: a feasible schedule needs dependencies, lead times and checkpoints. Each text
    that sets a date or duration the task does not, with no dependency or checkpoint."""
    source = " ".join(_strings(task)).lower()
    violations = 0
    for text in _plan_texts(output):
        dates = {d.lower() for d in _DATE.findall(text)} - set(_DATE.findall(source))
        if dates and not _DEPENDS.search(text):
            violations += 1
    return violations


_BENEFIT = re.compile(
    r"\b(?:sav(?:e|es|ing|ings)|roi|return on investment|cost reduction|reduc\w+ (?:the )?"
    r"(?:cost|costs|time|effort|processing|backlog)|efficienc\w+ gains?|payback)\b",
    re.I,
)
_HYPOTHESIS = re.compile(
    r"\b(?:expect\w*|hypothe\w*|anticipat\w*|target\w*|estimat\w*|could|may|might|aim\w*|"
    r"intend\w*|potential\w*|baseline|measur\w*|if )\b",
    re.I,
)


def check_blueprint_ben001(output: Any, task: Any) -> int:
    """BEN-001: a benefit is a hypothesis with a baseline and a measure. Each text that
    asserts savings, a reduction or a return as fact, with no hypothesis or measure word."""
    return sum(
        1 for text in _plan_texts(output) if _BENEFIT.search(text) and not _HYPOTHESIS.search(text)
    )


# --- RISK Checks ---


def _risk_texts(risk: Any) -> str:
    fields = ("condition", "event", "effect", "trigger", "residual_exposure")
    values = [str(_get_field(risk, name, "") or "") for name in fields]
    values += [str(v) for v in _get_field(risk, "responses", []) or []]
    return " ".join(values)


def check_risk_risk001(output: Any, task: Any = None) -> int:
    """RISK-001: a risk states its condition, its uncertain event and its effect, with an owner
    role and an observable trigger; each risk missing one counts."""
    required = ("condition", "event", "effect", "owner_role", "trigger")
    return sum(
        1
        for risk in _get_field(output, "risks", []) or []
        if any(not str(_get_field(risk, name, "") or "").strip() for name in required)
    )


_ALREADY = re.compile(r"\b(?:has|have|had)\s+already\s+(?:occurred|happened)\b", re.I)


def check_risk_risk002(output: Any, task: Any = None) -> int:
    """RISK-002: no rating or probability, by the rule `risk`'s own check applies, and no
    issue that has already happened presented as a risk."""
    from bidwright.graph.nodes import PROBABILITY, RATING_PHRASE, RATING_WORDS

    violations = 0
    for risk in _get_field(output, "risks", []) or []:
        exposure = str(_get_field(risk, "residual_exposure", "") or "").strip().lower().rstrip(".")
        if (
            exposure in RATING_WORDS
            or RATING_PHRASE.search(exposure)
            or PROBABILITY.search(_risk_texts(risk))
        ):
            violations += 1
        if _ALREADY.search(_risk_texts(risk)):
            violations += 1
    return violations


_NO_HUMAN = {"", "none", "n/a", "system", "automatic", "auto", "automatic_override", "tbd"}
_AUTO_APPROVAL = re.compile(r"\bauto(?:matically)?[- ]?approv|\bwaive[sd]?\b", re.I)


def check_risk_risk003(output: Any, task: Any = None) -> int:
    """RISK-003: response options with a human owner role; a risk with no response, with no
    human owner, or approving or waiving itself counts."""
    violations = 0
    for risk in _get_field(output, "risks", []) or []:
        owner = str(_get_field(risk, "owner_role", "") or "").strip().lower()
        responses = [str(r).strip() for r in _get_field(risk, "responses", []) or []]
        if owner in _NO_HUMAN or not any(responses) or _AUTO_APPROVAL.search(_risk_texts(risk)):
            violations += 1
    return violations


CHECKS: dict[str, Callable[[Any, Any], int]] = {
    "check_extract_req001": check_extract_req001,
    "check_extract_req002": check_extract_req002,
    "check_extract_req003": check_extract_req003,
    "check_consolidate_req002": check_consolidate_req002,
    "check_consolidate_req003": check_consolidate_req003,
    "check_consolidate_cfg001": check_consolidate_cfg001,
    "check_decide_ba001": check_decide_ba001,
    "check_decide_ba003": check_decide_ba003,
    "check_assess_ba003": check_assess_ba003,
    "check_options_ba002": check_options_ba002,
    "check_options_gov001": check_options_gov001,
    "check_blueprint_ba001": check_blueprint_ba001,
    "check_blueprint_del001": check_blueprint_del001,
    "check_blueprint_del002": check_blueprint_del002,
    "check_blueprint_del003": check_blueprint_del003,
    "check_blueprint_ben001": check_blueprint_ben001,
    "check_risk_risk001": check_risk_risk001,
    "check_risk_risk002": check_risk_risk002,
    "check_risk_risk003": check_risk_risk003,
}


def load_cases(path: Path) -> tuple[float, list[CardCase]]:
    """The cases, each refused unless its card exists, its family is the card's family and
    its node consumes the card: a case whose 'on' state inlines other cards than the one it
    tests would measure nothing (S12-CASE-04 and -05 were labeled CFG while testing REQ
    cards, so their 'on' state never carried REQ-002 or REQ-003)."""
    from bidwright.kb import load_cards

    cards = {card.id: card for card in load_cards()}
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f)
    max_cost = float(data.get("max_cost_usd", 1.0))
    cases = []
    for c in data.get("cases", []):
        case = CardCase(
            id=c["id"],
            card=c["card"],
            family=c["family"],
            node=c["node"],
            fixture=c["fixture"],
            check=c["check"],
        )
        card = cards.get(case.card)
        if card is None:
            raise ValueError(f"{case.id}: no method card {case.card}")
        if case.family != card.family:
            raise ValueError(f"{case.id}: {case.card} is family {card.family}, not {case.family}")
        if case.node not in card.consumers:
            raise ValueError(f"{case.id}: {case.node} does not consume {case.card}")
        if case.check not in CHECKS:
            raise ValueError(f"{case.id}: no check {case.check}")
        cases.append(case)
    return max_cost, cases


# --- the runner: `bidwright-eval cards` (Iteration 3, step 18) ---------------------------------

ROOT = Path(__file__).resolve().parents[1]
CASES = ROOT / "evals" / "s12" / "cases.yaml"
RESULTS = ROOT / "evals" / "results" / "s12-cards"
STATES = ("off", "on")


def task_models() -> dict[str, type[Any]]:
    """Each consuming node's task model, which its fixture holds."""
    from bidwright import schemas

    return {
        "extract": schemas.ExtractBatch,
        "consolidate": schemas.ClusterTask,
        "decide": schemas.DecideTask,
        "assess": schemas.AssessmentTask,
        "options": schemas.OptionsTask,
        "blueprint": schemas.BlueprintPlanTask,
        "risk": schemas.RiskInput,
    }


@dataclass
class CardsRun:
    """Each case's violation counts by state and repeat; None where the call gave no answer."""

    repeats: int
    violations: dict[str, dict[str, list[int | None]]]
    families: dict[str, str]  # case id -> family
    spent_usd: float = 0.0
    stopped: str | None = None


def run_cards(
    *,
    repeats: int,
    profile: str,
    mode: Any,
    name: str,
    cases_path: Path = CASES,
    backends: dict[str, Any] | None = None,
    cassettes: Any = None,
    outputs: Path | None = None,
    config: Any = None,
) -> CardsRun:
    """Each case once a repeat with its family off and on, through `graph/single.py`'s
    `call_node`, its check counting the violations in the answer. The run stops before a
    call once the calls so far have cost `max_cost_usd` of `cases.yaml`."""
    from bidwright.config import load_config
    from bidwright.graph.build import run_prompts
    from bidwright.graph.single import call_node, read_calls, single_folder

    config = config or load_config()
    max_cost, cases = load_cases(cases_path)
    models, schemas_by_node = task_models(), run_prompts(config, [])
    folder = single_folder(name, outputs)
    run = CardsRun(
        repeats=repeats,
        violations={c.id: {state: [] for state in STATES} for c in cases},
        families={c.id: c.family for c in cases},
    )
    for repeat in range(repeats):
        for case in cases:
            for state in STATES:
                spent = sum(float(e.get("cost_usd") or 0) for e in _calls(folder, read_calls))
                run.spent_usd = round(spent, 6)
                if spent >= max_cost:
                    run.stopped = f"stopped at the ${max_cost:g} cap before {case.id} {state}"
                    return run
                fixture = (ROOT / case.fixture).read_text(encoding="utf-8")
                task = models[case.node].model_validate_json(fixture)
                answer = call_node(
                    case.node,
                    task,
                    schemas_by_node[case.node].schema,
                    profile=profile,
                    mode=mode,
                    name=name,
                    backends=backends,
                    cassettes=cassettes,
                    repeat=repeat,
                    outputs=outputs,
                    config=config,
                    methods=[] if state == "off" else [case.family],
                )
                count = (
                    None
                    if answer.parsed is None
                    else CHECKS[case.check](
                        answer.parsed.model_dump(mode="json"), task.model_dump(mode="json")
                    )
                )
                run.violations[case.id][state].append(count)
    run.spent_usd = round(sum(float(e.get("cost_usd") or 0) for e in _calls(folder, read_calls)), 6)
    return run


def _calls(folder: Path, read: Callable[[Path], list[dict[str, Any]]]) -> list[dict[str, Any]]:
    return read(folder) if (folder / "ledger.jsonl").exists() else []


PLAN = "s12-cards"


def s12_plan(path: Path | None = None) -> dict[str, Any]:
    """The `s12-cards` block of `evals/hypotheses.yaml`, hashed with the gold before the
    first run: each family's rung names the rule that decides it."""
    from evals.report import HYPOTHESES

    source = path or HYPOTHESES
    plans = yaml.safe_load(source.read_text(encoding="utf-8")) if source.exists() else {}
    return dict((plans or {}).get(PLAN) or {})


def family_results(run: CardsRun, plan: dict[str, Any] | None = None) -> dict[str, dict[str, Any]]:
    """Per family, its cases' violations summed per repeat, off and on, and S-12's decision
    by the rule the family's hypothesis names (`superiority`: the violations fall beyond the
    off runs' spread). A family with no hypothesis is not decided."""
    from evals.report import decide

    rungs = (plan if plan is not None else s12_plan()).get("rungs") or {}
    found: dict[str, dict[str, Any]] = {}
    for family in sorted(set(run.families.values())):
        ids = [c for c, f in run.families.items() if f == family]
        sums: dict[str, list[int]] = {}
        for state in STATES:
            per_repeat = []
            for repeat in range(run.repeats):
                counts = [
                    run.violations[c][state][repeat]
                    if repeat < len(run.violations[c][state])
                    else None
                    for c in ids
                ]
                if all(n is not None for n in counts):
                    per_repeat.append(sum(n for n in counts if n is not None))
            sums[state] = per_repeat
        spec = rungs.get(family)
        if spec is None:
            passed, detail = None, f"no {PLAN} hypothesis for {family}"
        elif sums["off"] and sums["on"]:
            passed, detail = decide(
                spec["kind"], sums["off"], sums["on"], direction=spec.get("direction", "lower")
            )
        else:
            passed, detail = None, "no repeat with an answer for every case"
        found[family] = {"cases": ids, "off": sums["off"], "on": sums["on"]}
        found[family] |= {"passed": passed, "detail": detail}
    return found


def not_testable(path: Path) -> list[dict[str, str]]:
    """The cases `cases.yaml` lists as not testable: a consuming node whose answer has no field
    that could show the card's violation. The report names them; nothing runs them."""
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    keys = ("id", "card", "family", "node", "reason")
    return [{k: str(c[k]).strip() for k in keys} for c in data.get("not_testable", []) or []]


def write_report(
    run: CardsRun,
    out: Path = RESULTS,
    plan: dict[str, Any] | None = None,
    cases_path: Path = CASES,
) -> Path:
    import json

    families = family_results(run, plan)
    data = {
        "repeats": run.repeats,
        "spent_usd": run.spent_usd,
        "stopped": run.stopped,
        "families": families,
        "cases": run.violations,
        "not_testable": not_testable(cases_path),
    }
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.json").write_text(json.dumps(data, indent=1) + "\n", encoding="utf-8")
    lines = [
        "# S-12: method cards off and on",
        "",
        f"{run.repeats} repeats; ${run.spent_usd:g} spent"
        + (f"; {run.stopped}" if run.stopped else "")
        + ". A family passes by its rule in evals/hypotheses.yaml (`superiority`: its"
        " violations fall beyond the off runs' spread).",
        "",
        "| Family | Cases | Violations off | Violations on | Result | Detail |",
        "|---|---|---|---|---|---|",
    ]
    for family, row in families.items():
        result = "n/a" if row["passed"] is None else "pass" if row["passed"] else "fail"
        lines.append(
            f"| {family} | {len(row['cases'])} | {row['off']} | {row['on']} | {result}"
            f" | {row['detail']} |"
        )
    if data["not_testable"]:
        lines += ["", "Not run: the node's answer has no field that could show the violation.", ""]
        lines += [
            f"- {c['id']} ({c['card']} on `{c['node']}`): {c['reason']}"
            for c in data["not_testable"]
        ]
    (out / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    return out
