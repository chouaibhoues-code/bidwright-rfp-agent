"""Cassettes: recorded responses keyed by everything that should change a response.

The key covers the prompt text's hash, the schema hash, the tool definitions' hash, the
model, the decoding and thinking settings, the input's hash taken before delimiters are
inserted, and the repeat index. Delimiter tags are seeded per run, so they never enter it.

The same store holds the test cassettes, the response cache (`llm/cache.py`) and, from
Iteration 2, each run's journal (ADR-031). Each entry is written whole through
`fileio.write_atomic`. An entry keeps the backend's native turn when the response has one, such
as Gemini's `types.Content` with its thought signatures, dumped to JSON without its unset
fields; `load` returns it as a dict, which the Gemini adapter validates back into its type, and
an entry written without one loads as before. The native turn is not part of the key.
"""

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from bidwright.fileio import write_atomic
from bidwright.llm.schema import sha256_of
from bidwright.llm.types import Response, ToolCall, Usage

_CASSETTE = re.compile(r"^[0-9a-f]{64}$")  # a cassette's file stem: its key's digest


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
    """One JSON file per key under `root`. `used` collects the keys this store loaded or saved
    in this process, and `prune` deletes every other cassette, which is how a fill leaves a
    recording holding exactly the calls of one replayable run."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.used: set[str] = set()

    def _path(self, key: str) -> Path:
        return self.root / f"{key.removeprefix('sha256:')}.json"

    def load(self, key: str) -> Response | None:
        path = self._path(key)
        if not path.exists():
            return None
        self.used.add(key)
        body = json.loads(path.read_text(encoding="utf-8"))["response"]
        return Response(
            text=body["text"],
            tool_calls=tuple(ToolCall(**call) for call in body["tool_calls"]),
            usage=Usage(**body["usage"]),
            native=body.get("native"),
        )

    def save(self, key: str, meta: dict[str, Any], response: Response) -> None:
        body: dict[str, Any] = {
            "text": response.text,
            "tool_calls": [
                {"id": c.id, "name": c.name, "arguments": c.arguments} for c in response.tool_calls
            ],
            "usage": response.usage.__dict__,
        }
        native = _native(response.native)
        if native is not None:
            body["native"] = native
        record = {
            "key": key,
            **meta,
            "response": body,
            "recorded": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        write_atomic(self._path(key), json.dumps(record, ensure_ascii=False, indent=1) + "\n")
        self.used.add(key)

    def keys(self) -> list[str]:
        """The key of every cassette in the store, in name order."""
        if not self.root.is_dir():
            return []
        return [
            f"sha256:{p.stem}" for p in sorted(self.root.glob("*.json")) if _CASSETTE.match(p.stem)
        ]

    def prune(self, keep: set[str]) -> list[str]:
        """Delete every cassette whose key is not in `keep`, such as `recording.json`'s
        neighbours a fill did not use; other files stay. The keys deleted."""
        gone = [key for key in self.keys() if key not in keep]
        for key in gone:
            self._path(key).unlink()
        return gone


def _native(native: Any) -> Any:
    """A native turn as JSON. A Pydantic model, such as Gemini's `types.Content`, is dumped
    without its unset fields, and its bytes, such as thought signatures, as base64; a turn read
    back from a store is a dict already."""
    if native is None or isinstance(native, dict):
        return native
    if isinstance(native, BaseModel):
        return native.model_dump(mode="json", exclude_none=True)
    raise TypeError(f"a native turn is a Pydantic model or a dict, not {type(native).__name__}")
