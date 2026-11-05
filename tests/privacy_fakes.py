"""The D-05 fixtures: the planted personal data of the development RFP, read from its gold,
and a scripted model whose answers quote the passage that holds it. Only `gold` tests call
`planted_values`, since the Docker image holds no gold."""

import json
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path
from typing import Any

from bidwright.llm.types import Request, Response
from tests.node_fakes import USAGE, data_of, tools

GOLD = Path(__file__).resolve().parents[1] / "evals" / "gold" / "dev" / "gold.jsonl"


def planted_values() -> list[str]:
    """The development RFP's planted personal data, from its gold."""
    rows = [json.loads(line) for line in GOLD.read_text(encoding="utf-8").splitlines() if line]
    values = [row["value"] for row in rows if row.get("kind") == "personal_data"]
    assert values, "the development gold plants personal data"
    return values


def stand_in(value: str) -> str:
    """A string of the same length and shape: letters become x and digits 7."""
    return "".join("x" if c.isalpha() else "7" if c.isdigit() else c for c in value)


def _item(src_id: str, quote: str, statement: str) -> dict[str, Any]:
    return {
        "src_ids": [src_id],
        "quote": quote.strip(),
        "statement": statement,
        "modality": "must",
        "disposition": "BINDING",
        "hazard": False,
    }


class ScriptedModel:
    """The D-05 script. It keeps every request and copies no document text into its answers
    except the quotes `extract` makes: for each pack, the first 40 characters of its first
    passage as the request shows them, and for the pack that holds the planted sentence, two
    quotes of that passage, so that its section's cluster has two members and goes to
    `consolidate`'s model. Every other passage of a pack is listed as holding no obligation.
    `risk` calls `search_rfp` once, for "procurement officer", and the other roles get fixed,
    schema-valid answers."""

    provider = "gemini"
    paid = False

    def __init__(self, markers: Sequence[str]) -> None:
        self.markers = list(markers)  # the planted values and their stand-ins
        self.requests: list[Request] = []

    def call(self, request: Request) -> Response:
        self.requests.append(request)
        if request.tools:
            if any(m.role == "tool" for m in request.messages):
                return Response(text="The search answered the question.", usage=USAGE)
            if any(tool.name == "search_capabilities" for tool in request.tools):
                return tools(("search_capabilities", {"query": "case management"}))
            return tools(("search_rfp", {"query": "procurement officer"}))
        return Response(text=json.dumps(self._answer(request)), usage=USAGE)

    def _answer(self, request: Request) -> dict[str, Any]:
        name, data = request.schema_name, data_of(request)
        if name == "ExtractResult":
            return self._extract(data["passages"])
        if name == "TriageResult":
            return {"zones": [], "profile": {}, "hazards": []}
        if name == "BriefResult":
            return {"factors": [], "topics": ["digital service procurement"]}
        if name == "DiscoveryExtract":
            return {"summary": "", "items": [], "needs": [], "open_questions": []}
        if name == "ConsolidationResult":
            return {"topic": "Requirements of one section", "duplicates": [], "references": []}
        if name == "DecideResult":  # Iteration 3: a gap, which copies no document text
            return {"decision": "PROCEED_WITH_GAP", "reason": "No evidence.", "gap": "None."}
        if name == "ApproachResult":
            ids = [r["id"] for r in data["requirements"]]
            item = {"text": "Deliver each requirement.", "requirement_ids": ids, "basis": "Stated."}
            return {"items": [item], "unmapped_requirement_ids": []}
        if name == "RiskRegister":
            return {"risks": [self._risk(request)], "open_questions": []}
        return {"title": "Section", "text": "This section is a placeholder.", "cited_ids": []}

    def _extract(self, passages: list[dict[str, Any]]) -> dict[str, Any]:
        first = passages[0]
        items = [_item(first["src_id"], first["text"][:40], "The supplier meets this.")]
        planted = next((p for p in passages if any(m in p["text"] for m in self.markers)), None)
        if planted is not None:
            shown = planted["text"][:300]
            items += [
                _item(planted["src_id"], shown, "Questions go to the named officer."),
                _item(planted["src_id"], shown[len(shown) // 2 :], "The officer takes calls."),
            ]
        cited = {item["src_ids"][0] for item in items}
        return {
            "items": items,
            "no_obligation_src_ids": [p["src_id"] for p in passages if p["src_id"] not in cited],
        }

    def _risk(self, request: Request) -> dict[str, Any]:
        found = [json.loads(m.content) for m in request.messages if m.role == "tool"]
        hits = [hit["src_id"] for result in found for hit in result.get("data") or []]
        return {
            "condition": "The procurement officer named for this tender may change.",
            "event": "Questions reach an officer who no longer handles the tender.",
            "effect": "Answers to clarification questions arrive late.",
            "assumptions": [],
            "owner_role": "Bid manager",
            "trigger": "The officer's details change.",
            "responses": ["Confirm the contact before sending a question."],
            "residual_exposure": "Late answers to one or two questions.",
            "evidence_src_ids": hits[:1],
        }


def body(request: Request) -> str:
    """A request as a provider receives it: its turns, tool calls, schema and tools."""
    return json.dumps(
        {
            "model": request.model,
            "messages": [
                {"role": m.role, "content": m.content, "tools": [asdict(c) for c in m.tool_calls]}
                for m in request.messages
            ],
            "schema": request.schema,
            "tools": [asdict(t) for t in request.tools],
        },
        ensure_ascii=False,
    )
