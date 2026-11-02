"""JSON Schemas sent to providers, built from the Pydantic models in `bidwright.schemas`.

Providers accept different JSON Schema subsets, so the client sends one conservative form:
references inlined, every object closed with `additionalProperties: false`, every property
required, and no `title` or `default` keys. S-04 showed Gemini accepts both this form and
Pydantic's `$defs` form; inlining keeps Ollama and the OpenAI-compatible providers safe too.
The app still validates every response against the Pydantic model itself.
"""

import copy
import hashlib
import json
from typing import Any

from pydantic import BaseModel

_DROPPED_KEYS = {"title", "default"}


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_of(value: Any) -> str:
    text = value if isinstance(value, str) else canonical_json(value)
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def _inline(schema: dict[str, Any]) -> dict[str, Any]:
    defs = schema.pop("$defs", {})

    def walk(node: Any, seen: tuple[str, ...]) -> Any:
        if isinstance(node, dict):
            ref = node.get("$ref")
            if isinstance(ref, str):
                name = ref.rsplit("/", 1)[-1]
                if name in seen:
                    raise ValueError(f"recursive schema reference to {name!r} cannot be inlined")
                return walk(copy.deepcopy(defs[name]), (*seen, name))
            return {key: walk(value, seen) for key, value in node.items()}
        if isinstance(node, list):
            return [walk(value, seen) for value in node]
        return node

    return walk(schema, ())


def _close(node: Any) -> Any:
    if isinstance(node, dict):
        closed = {key: _close(value) for key, value in node.items() if key not in _DROPPED_KEYS}
        if closed.get("type") == "object" and "properties" in closed:
            closed["additionalProperties"] = False
            closed["required"] = list(closed["properties"])
        return closed
    if isinstance(node, list):
        return [_close(value) for value in node]
    return node


def provider_schema(model: type[BaseModel]) -> dict[str, Any]:
    """The schema sent to every provider for `model`."""
    return _close(_inline(model.model_json_schema()))
