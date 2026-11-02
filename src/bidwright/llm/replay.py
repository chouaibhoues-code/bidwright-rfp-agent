"""Cassettes: recorded responses keyed by everything that should change a response.

The key covers the prompt text's hash, the schema hash, the tool definitions' hash, the
model, the decoding and thinking settings, the input's hash taken before delimiters are
inserted, and the repeat index. Delimiter tags are seeded per run, so they never enter it.
"""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from bidwright.llm.schema import sha256_of
from bidwright.llm.types import Response, ToolCall, Usage


def cache_key(
    *,
    prompt_hash: str,
    schema_hash: str | None,
    tools_hash: str | None,
    model: str,
    settings: dict[str, Any],
    input_hash: str,
    repeat: int,
) -> str:
    return sha256_of(
        {
            "prompt_text_hash": prompt_hash,
            "schema_hash": schema_hash,
            "tools_hash": tools_hash,
            "model": model,
            "settings": settings,
            "input_hash": input_hash,
            "repeat": repeat,
        }
    )


class CassetteStore:
    """One JSON file per key under `root`."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def _path(self, key: str) -> Path:
        return self.root / f"{key.removeprefix('sha256:')}.json"

    def load(self, key: str) -> Response | None:
        path = self._path(key)
        if not path.exists():
            return None
        body = json.loads(path.read_text(encoding="utf-8"))["response"]
        return Response(
            text=body["text"],
            tool_calls=tuple(ToolCall(**call) for call in body["tool_calls"]),
            usage=Usage(**body["usage"]),
        )

    def save(self, key: str, meta: dict[str, Any], response: Response) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        record = {
            "key": key,
            **meta,
            "response": {
                "text": response.text,
                "tool_calls": [
                    {"id": c.id, "name": c.name, "arguments": c.arguments}
                    for c in response.tool_calls
                ],
                "usage": response.usage.__dict__,
            },
            "recorded": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        self._path(key).write_text(
            json.dumps(record, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
        )
