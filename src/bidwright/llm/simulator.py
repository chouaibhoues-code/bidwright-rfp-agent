"""`ProviderSimulator`: injects scripted faults in front of another backend.

A fault script is a list of entries keyed by call number (1-based), for example:

    - {call: 1, fault: http_429, retry_after_s: 1}
    - {call: 2, fault: timeout}
    - {call: 3, fault: malformed_json}
    - {call: 4, fault: missing_ids, drop: [SRC-0003]}

Faults are offline test fixtures. They never count as live behavior.
"""

import json
from collections.abc import Sequence
from dataclasses import replace
from typing import Any

from bidwright.llm.types import Backend, RateLimited, Request, Response, TransientError

FAULTS = {"http_429", "timeout", "server_error", "malformed_json", "missing_ids"}


class ProviderSimulator:
    def __init__(self, inner: Backend, script: Sequence[dict[str, Any]]) -> None:
        unknown = {entry["fault"] for entry in script} - FAULTS
        if unknown:
            raise ValueError(f"unknown faults in script: {sorted(unknown)}")
        self.inner = inner
        self.provider = inner.provider
        self.paid = inner.paid
        self.calls = 0
        self._script = {int(entry["call"]): entry for entry in script}

    def call(self, request: Request) -> Response:
        self.calls += 1
        entry = self._script.get(self.calls)
        if entry is None:
            return self.inner.call(request)
        fault = entry["fault"]
        if fault == "http_429":
            raise RateLimited("simulated 429", retry_after_s=entry.get("retry_after_s"))
        if fault == "timeout":
            raise TransientError("simulated timeout")
        if fault == "server_error":
            raise TransientError("simulated 503")
        if fault == "malformed_json":
            return Response(text='{"items": [', usage=self.inner.call(request).usage)
        response = self.inner.call(request)
        return replace(response, text=_drop_items(response.text, set(entry.get("drop", []))))


def _drop_items(text: str, drop: set[str]) -> str:
    body = json.loads(text)
    body["items"] = [
        item for item in body.get("items", []) if not drop.intersection(item.get("src_ids", []))
    ]
    return json.dumps(body)
