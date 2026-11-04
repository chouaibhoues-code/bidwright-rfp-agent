"""Scripted model replies and a run context over the development RFP, for node tests."""

import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from bidwright.config import AgentLimits, RunLimits, load_config
from bidwright.graph.nodes import RunContext
from bidwright.harness.budget import RunBudget
from bidwright.harness.gateway import ToolGateway
from bidwright.ingest import IngestResult, ingest_pdf
from bidwright.llm.client import LLMClient
from bidwright.llm.replay import CassetteStore
from bidwright.llm.types import Request, Response, ToolCall, Usage
from bidwright.prompts import load_prompt
from bidwright.retrieval import PassageIndex
from bidwright.schemas import Requirement
from bidwright.tools import date_tool, search_tool

DEV_RFP = Path(__file__).resolve().parents[1] / "inputs" / "dev" / "dev_rfp.pdf"
PROMPT_IDS = ("extract", "extract_oneshot", "approach", "risk", "draft")
RISK_LIMITS = AgentLimits(max_turns=4, max_tool_calls=6, stop_on_no_progress=True)
USAGE = Usage(tokens_in=500, tokens_out=100)

Reply = Response | str | Callable[[Request], Response]


@dataclass
class ScriptBackend:
    """Answers each call with the next scripted reply, and keeps every request."""

    replies: list[Reply]
    provider: str = "gemini"
    paid: bool = False
    requests: list[Request] = field(default_factory=list)

    def call(self, request: Request) -> Response:
        self.requests.append(request)
        if not self.replies:
            raise AssertionError("the script ran out of replies")
        reply = self.replies.pop(0)
        if callable(reply):
            return reply(request)
        if isinstance(reply, str):
            return Response(text=reply, usage=USAGE)
        return reply


def text(value: Any) -> str:
    return json.dumps(value)


def tools(*calls: tuple[str, dict[str, Any]]) -> Response:
    return Response(
        text="",
        tool_calls=tuple(ToolCall(f"call_{n}", name, args) for n, (name, args) in enumerate(calls)),
        usage=USAGE,
    )


_DATA = re.compile(r"<(data-[0-9a-f]{8})>\n(.*)\n</\1>", re.DOTALL)
_MODAL = re.compile(r"\b(shall|must|should|may)\b")


class RuleBackend:
    """A deterministic stand-in for a model, for whole-run tests: it reads the data block
    and answers each node's schema with simple rules, so every reply is valid and every
    quote is an exact copy."""

    provider = "gemini"
    paid = False

    def __init__(self) -> None:
        self.requests: list[Request] = []

    def call(self, request: Request) -> Response:
        self.requests.append(request)
        user = next(m.content for m in request.messages if m.role == "user")
        found = _DATA.search(user)
        data = json.loads(found.group(2)) if found else {}
        name = request.schema_name
        if request.tools:
            if any(m.role == "tool" for m in request.messages):
                return Response(text="I have the evidence I need.", usage=USAGE)
            return tools(("search_rfp", {"query": "go-live migration"}))
        if name == "ExtractResult":
            return Response(text=json.dumps(_extract(data)), usage=USAGE)
        if name == "ApproachResult":
            items = [
                {
                    "text": f"Deliver: {r['statement']}",
                    "requirement_ids": [r["id"]],
                    "basis": "Stated.",
                }
                for r in data["requirements"]
                if r["mandatory"]
            ]
            result = {"items": items, "unmapped_requirement_ids": [], "open_questions": []}
            return Response(text=json.dumps(result), usage=USAGE)
        if name == "RiskRegister":
            return Response(
                text=json.dumps({"risks": [GOOD_RISK], "open_questions": []}), usage=USAGE
            )
        records = data.get("records", [])
        first = records[0]["id"] if records else None
        body = f"This section covers the records [{first}]." if first else "Nothing to report."
        result = {
            "title": data.get("section_id", "Section"),
            "text": body,
            "cited_ids": [first] if first else [],
        }
        return Response(text=json.dumps(result), usage=USAGE)


def _extract(batch: dict[str, Any]) -> dict[str, Any]:
    items, none = [], []
    for passage in batch["passages"]:
        found = _MODAL.search(passage["text"]) or _MODAL.search(passage.get("lead_in") or "")
        if not found or passage["text"].endswith(":"):
            none.append(passage["src_id"])
            continue
        modality = found.group(1)
        items.append(
            {
                "src_ids": [passage["src_id"]],
                "quote": passage["text"][:300],
                "statement": passage["text"][:300],
                "modality": modality,
                "disposition": "BINDING" if modality in ("shall", "must") else "OPTIONAL",
                "hazard": "UTC" in passage["text"],
            }
        )
    return {"items": items, "no_obligation_src_ids": none}


_INGESTED: list[IngestResult] = []


def dev_ingest() -> IngestResult:
    if not _INGESTED:
        _INGESTED.append(ingest_pdf(DEV_RFP))
    return _INGESTED[0]


def context(
    backend: ScriptBackend | None,
    *,
    mode: str = "live",
    cassettes: CassetteStore | None = None,
    limits: RunLimits | None = None,
) -> RunContext:
    config = load_config()
    client = LLMClient(
        config,
        "free",
        {"gemini": backend} if backend else {},
        mode=mode,  # type: ignore[arg-type]
        cassettes=cassettes,
        run_id="run-test",
        sleep=lambda _: None,
    )
    budget = RunBudget(limits or config.limits.run("dev", "free"))
    prompts = {pid: load_prompt(pid) for pid in PROMPT_IDS}
    passages = {p.id: p for p in dev_ingest().passages}
    return RunContext("run-test", client, budget, prompts, passages)


def gateway(tmp_path: Path, limits: AgentLimits = RISK_LIMITS) -> ToolGateway:
    index = PassageIndex.build(dev_ingest().passages, tmp_path / "search.sqlite")
    return ToolGateway.for_agent(
        "risk",
        allowed=["search_rfp", "date_calc"],
        tools=[search_tool(index), date_tool()],
        max_tool_calls=limits.max_tool_calls or 6,
    )


def requirement(number: int, src_id: str, quote: str, **labels: Any) -> Requirement:
    fields: dict[str, Any] = {
        "statement": quote,
        "modality": "must",
        "mandatory": True,
        "hazard": False,
        "disposition": "BINDING",
    } | labels
    return Requirement(
        id=f"REQ-{number:04d}",
        doc_id="dev-rfp",
        src_ids=[src_id],
        quote=quote,
        quote_status="VERBATIM_VERIFIED",
        **fields,
    )


def dev_requirements() -> list[Requirement]:
    return [
        requirement(
            1,
            "SRC-0015",
            "Proposals must be submitted through the College's procurement portal",
            hazard=True,
        ),
        requirement(
            2, "SRC-0027", "The service must integrate with the College's student records system"
        ),
        requirement(3, "SRC-0032", "The service must be live for students by 2027-01-11"),
        requirement(
            4,
            "SRC-0026",
            "The Supplier should migrate the signed records held in the current tool",
            modality="should",
            mandatory=False,
            disposition="OPTIONAL",
        ),
    ]


GOOD_RISK = {
    "condition": "Go-live is due on 2027-01-11, but migrating the signed records may run"
    " until 2027-02-28.",
    "event": "Staff use the new service while older signed records are still in the current tool.",
    "effect": "Lookups of older records miss documents until the migration ends.",
    "assumptions": ["Migration finishes after go-live."],
    "owner_role": "Delivery lead",
    "trigger": "The migration plan ends after 2027-01-11.",
    "responses": ["Migrate the most used records before go-live."],
    "residual_exposure": "Some lookups need the current tool for seven weeks.",
    "evidence_src_ids": ["SRC-0032", "SRC-0026"],
}
GENERIC_RISK = {
    "condition": "Projects are complex.",
    "event": "Unforeseen delays happen.",
    "effect": "Delivery is late.",
    "assumptions": [],
    "owner_role": "Project manager",
    "trigger": "Delays occur.",
    "responses": ["Monitor closely."],
    "residual_exposure": "Medium.",
    "evidence_src_ids": [],
}
