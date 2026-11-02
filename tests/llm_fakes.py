"""Test doubles for the LLM client."""

from dataclasses import dataclass, field
from typing import TypedDict

from bidwright.llm.types import Request, Response, Usage


class CallIds(TypedDict):
    node: str
    agent: str
    prompt_hash: str
    input_hash: str


CALL: CallIds = {
    "node": "extract",
    "agent": "extract",
    "prompt_hash": "sha256:p",
    "input_hash": "sha256:i",
}

EXTRACT_JSON = (
    '{"items": ['
    '{"src_ids": ["SRC-0001"], "quote": "The Supplier shall keep an audit record.",'
    ' "statement": "Keep an audit record.", "modality": "shall", "disposition": "BINDING",'
    ' "hazard": false},'
    '{"src_ids": ["SRC-0003"], "quote": "Bids are due by 2026-12-01 12:00 UTC.",'
    ' "statement": "Submit by the deadline.", "modality": "none", "disposition": "BINDING",'
    ' "hazard": true}'
    '], "no_obligation_src_ids": ["SRC-0002"]}'
)


@dataclass
class FakeBackend:
    """Returns `text` for every call and records the requests it received."""

    text: str = EXTRACT_JSON
    provider: str = "gemini"
    paid: bool = False
    requests: list[Request] = field(default_factory=list)

    @property
    def models(self) -> list[str]:
        return [request.model for request in self.requests]

    def call(self, request: Request) -> Response:
        self.requests.append(request)
        return Response(text=self.text, usage=Usage(tokens_in=1000, tokens_out=200))
