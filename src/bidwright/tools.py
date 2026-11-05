"""The agent tools, `search_rfp` and `date_calc` (0a) and `ask_research` (Iteration 2), with
their argument schemas; `start_research`'s argument schema too, whose tool `discover` builds.

Each tool validates its arguments with a Pydantic model, and its JSON Schema, offered to the
model, is generated from that same model. A tool returns a typed `ToolResult` with status
`OK`, `EMPTY` or `FAILED`. `ToolGateway` adds `DENIED`, and turns an exception into `FAILED`:
`search_rfp` and `date_calc` never raise, while `ask_research` passes on a research provider's.
"""

import calendar
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Annotated, Any, Literal, Protocol
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field

from bidwright.llm.schema import clean_schema
from bidwright.llm.types import ToolSpec
from bidwright.retrieval import MAX_K, PassageIndex
from bidwright.schemas import AskResult, ToolResult

NO_HOLIDAYS = "Business days skip Saturdays and Sundays only; public holidays are not considered."


class SearchArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=200, description="Plain search words.")
    k: int = Field(default=5, ge=1, le=MAX_K, description="How many passages to return, 1 to 8.")


class StartResearchArgs(BaseModel):
    """`start_research` (Iteration 2): the model plans the question; code builds the query
    from the research envelope and binds the notebook, so no notebook appears here (G2)."""

    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1, max_length=300, description="What to research.")
    topics: list[Annotated[str, Field(min_length=1, max_length=80)]] = Field(
        min_length=1, max_length=5, description="The brief's topics the question covers."
    )


class AskResearchArgs(BaseModel):
    """`ask_research` (Iteration 2): one stand-alone question for the bound notebook or pack."""

    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1, max_length=300, description="One stand-alone question.")


class DateArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    date: str = Field(description="An ISO 8601 date, or a date and time.")
    op: Literal["add", "subtract", "diff", "weekday"]
    amount: int | None = Field(default=None, ge=0, description="Units to add or subtract.")
    unit: Literal["days", "business_days", "weeks", "months"] = "days"
    tz: str | None = Field(default=None, description="An IANA time zone, such as Europe/London.")
    other_date: str | None = Field(default=None, description="The second date, for diff.")


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    args_model: type[BaseModel]
    run: Callable[[Any], ToolResult]

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(self.name, self.description, parameters_schema(self.args_model))


def parameters_schema(model: type[BaseModel]) -> dict[str, Any]:
    """The model's JSON Schema without titles, keeping only its required fields required."""
    return clean_schema(model.model_json_schema(), frozenset({"title"}), close=False)


# --- search_rfp --------------------------------------------------------------------------


# A requirement id as a model may write it: any case, with a hyphen, a space or nothing
# before the number, and with or without leading zeros. Ids are 'REQ-' plus 4 digits.
REQUIREMENT_ID = re.compile(r"\bREQ[- ]?(\d{1,4})\b", re.IGNORECASE)


def requirement_ids(query: str) -> list[str]:
    """The requirement ids named in a query, in canonical form, such as REQ-0003."""
    return [f"REQ-{int(number):04d}" for number in REQUIREMENT_ID.findall(query)]


def search_tool(
    index: PassageIndex, requirement_sources: Mapping[str, Sequence[str]] | None = None
) -> Tool:
    """`requirement_sources` maps requirement ids to the passages they quote, so a query that
    names a requirement id returns those passages first. Models do look requirements up by id:
    the first live run searched only for ids, which match no RFP words. Results carry the
    index's text, which `ingest` builds from the run's text view (D-05), so a tool result shows
    a model nothing the view does not."""
    sources = requirement_sources or {}

    def run(args: SearchArgs) -> ToolResult:
        named = [s for req in requirement_ids(args.query) for s in sources.get(req, [])]
        words = REQUIREMENT_ID.sub(" ", args.query)
        hits = index.get(named)
        seen = {h.src_id for h in hits}
        hits += [h for h in index.search(words, args.k) if h.src_id not in seen]
        hits = hits[: args.k]
        if not hits:
            return ToolResult(status="EMPTY", data=[], reason="no passage matched the query")
        data = [
            {"src_id": h.src_id, "section_path": h.section_path, "text": h.text, "score": h.score}
            for h in hits
        ]
        return ToolResult(status="OK", data=data)

    return Tool(
        name="search_rfp",
        description=(
            "Search the RFP's passages by words, such as 'go-live migration deadline'. A"
            " requirement id such as REQ-0003 returns the passages that requirement quotes."
            " Returns up to k passages, best first, each with its SRC id, section path and text."
        ),
        args_model=SearchArgs,
        run=run,
    )


# --- date_calc ---------------------------------------------------------------------------


def date_tool() -> Tool:
    return Tool(
        name="date_calc",
        description=(
            "Date arithmetic. add or subtract an amount of days, business_days, weeks or months;"
            " diff counts days or business days from date to other_date; weekday names the day."
            " With tz, times are read and returned in that IANA time zone."
        ),
        args_model=DateArgs,
        run=date_calc,
    )


def date_calc(args: DateArgs) -> ToolResult:
    try:
        zone = ZoneInfo(args.tz) if args.tz else None
        moment = _parse(args.date, zone)
        if args.op == "weekday":
            name = calendar.day_name[_day(moment).weekday()]
            return _ok(name, f"{_day(moment).isoformat()} is a {name}.")
        if args.op == "diff":
            if args.other_date is None:
                return _failed("diff needs other_date")
            return _diff(moment, _parse(args.other_date, zone), args.unit)
        if args.amount is None:
            return _failed(f"{args.op} needs amount")
        sign = 1 if args.op == "add" else -1
        result = _shift(moment, sign * args.amount, args.unit)
        verb = "plus" if sign > 0 else "minus"
        note = f" {NO_HOLIDAYS}" if args.unit == "business_days" else ""
        text = f"{_iso(moment)} {verb} {args.amount} {args.unit} is {_iso(result)}.{note}"
        return _ok(_iso(result), text)
    except ZoneInfoNotFoundError:
        return _failed(f"unknown time zone {args.tz!r}")
    except (ValueError, OverflowError) as exc:
        return _failed(str(exc))


Moment = date | datetime


def _parse(value: str, zone: ZoneInfo | None) -> Moment:
    text = value.strip()
    if "T" not in text and " " not in text:
        return date.fromisoformat(text)
    moment = datetime.fromisoformat(text)
    if zone is None:
        return moment
    return moment.replace(tzinfo=zone) if moment.tzinfo is None else moment.astimezone(zone)


def _day(moment: Moment) -> date:
    return moment.date() if isinstance(moment, datetime) else moment


def _iso(moment: Moment) -> str:
    return moment.isoformat()


def _shift(moment: Moment, amount: int, unit: str) -> Moment:
    if unit == "days":
        return moment + timedelta(days=amount)
    if unit == "weeks":
        return moment + timedelta(weeks=amount)
    if unit == "months":
        month_index = moment.month - 1 + amount
        year, month = moment.year + month_index // 12, month_index % 12 + 1
        last_day = calendar.monthrange(year, month)[1]
        return moment.replace(year=year, month=month, day=min(moment.day, last_day))
    step = 1 if amount >= 0 else -1
    remaining = abs(amount)
    while remaining:
        moment = moment + timedelta(days=step)
        if _day(moment).weekday() < 5:
            remaining -= 1
    return moment


def _diff(first: Moment, second: Moment, unit: str) -> ToolResult:
    start, end = _day(first), _day(second)
    if unit == "business_days":
        low, high = sorted((start, end))
        count = sum(1 for n in range((high - low).days) if (low + timedelta(days=n)).weekday() < 5)
        count = count if end >= start else -count
        text = (
            f"From {start.isoformat()} up to but not including {end.isoformat()}"
            f" there are {count} business days. {NO_HOLIDAYS}"
        )
        return _ok(count, text)
    days = (end - start).days
    if unit == "weeks":
        return _ok(
            round(days / 7, 2), f"From {start} to {end} is {days} days, {days / 7:.2f} weeks."
        )
    if unit == "months":
        return _failed("diff counts days, business_days or weeks, not months")
    return _ok(days, f"From {start.isoformat()} to {end.isoformat()} is {days} calendar days.")


def _ok(result: object, explanation: str) -> ToolResult:
    return ToolResult(status="OK", data={"result": result, "explanation": explanation})


def _failed(reason: str) -> ToolResult:
    return ToolResult(status="FAILED", data=None, reason=reason)


# --- ask_research (Iteration 2) ------------------------------------------------------------

NOT_IN_PACK = "NOT_IN_PACK"  # a research pack holds nothing on the question
NO_SOURCED_ANSWER = "no answer with a source"  # a live question no source supports


class Asks(Protocol):
    """What `ask_research` needs of a research provider."""

    def ask(self, question: str) -> AskResult: ...


def ask_tool(provider: Asks, *, max_excerpts: int, empty_reason: str = NOT_IN_PACK) -> Tool:
    """`ask_research` over a research provider: a research pack answers by ADR-034's rule, and
    NotebookLM from its bound notebook (step 11). The result holds the answer, `None` when only
    excerpts matched, and at most `max_excerpts` excerpts, each with its source's title and
    tier. A quarantined excerpt, or one whose source the answer does not carry, never returns;
    with no excerpt left, the result is `EMPTY` with `empty_reason`, since an answer without a
    source is no answer. A provider that raises, as NotebookLM can, gives the gateway's
    `FAILED` result."""

    def run(args: AskResearchArgs) -> ToolResult:
        result = provider.ask(args.question)
        sources = {source.id: source for source in result.sources}
        excerpts = [e for e in result.excerpts if not e.quarantined and e.source_id in sources]
        if not excerpts:
            return ToolResult(status="EMPTY", data=None, reason=empty_reason)
        views = [
            {
                "id": excerpt.id,
                "source": sources[excerpt.source_id].title,
                "tier": sources[excerpt.source_id].tier,
                "text": excerpt.text,
            }
            for excerpt in excerpts[:max_excerpts]
        ]
        return ToolResult(status="OK", data={"answer": result.answer, "excerpts": views})

    return Tool(
        name="ask_research",
        description=(
            "Ask one stand-alone question about the RFP's domain, in general words. Returns the"
            f" research's answer when one matches, and up to {max_excerpts} excerpts, each with"
            " its id, its source's title, the source's authority tier (1 highest, 4 lowest) and"
            " its text. EMPTY means the research holds nothing on the question."
        ),
        args_model=AskResearchArgs,
        run=run,
    )


# --- start_research (Iteration 2, step 11) ---------------------------------------------------


def start_tool(run: Callable[[StartResearchArgs], ToolResult]) -> Tool:
    """`start_research`: the model plans one research question; `run`, which `discover`
    supplies, builds the query from the research envelope, starts the job on the notebook code
    bound, and returns the job's label and state, never an id. A call whose query a recorded
    job already holds starts nothing and returns that job's label."""
    return Tool(
        name="start_research",
        description=(
            "Start one deep research job on the RFP's domain: one question in general domain"
            " words, and the brief's topics it covers. Returns the job's label, J1 or J2, and its"
            " state. Code waits for the job and brings its report, so never ask about progress."
        ),
        args_model=StartResearchArgs,
        run=run,
    )
