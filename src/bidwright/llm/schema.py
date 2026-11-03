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

_DROPPED_KEYS = frozenset({"title", "default"})


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


def clean_schema(node: Any, drop: frozenset[str] = _DROPPED_KEYS, *, close: bool = True) -> Any:
    """Drop the annotation keys in `drop`; with `close`, also close every object and make
    every property required.

    Keys inside `properties` are field names, not annotations, so a field called `title`
    survives. Dropping it once made the draft model omit `DraftResult.title` on every call.
    Tool argument schemas use `close=False`, so their optional arguments stay optional.
    """
    if isinstance(node, list):
        return [clean_schema(value, drop, close=close) for value in node]
    if not isinstance(node, dict):
        return node
    cleaned: dict[str, Any] = {}
    for key, value in node.items():
        if key in drop:
            continue
        if key == "properties" and isinstance(value, dict):
            cleaned[key] = {
                name: clean_schema(schema, drop, close=close) for name, schema in value.items()
            }
        else:
            cleaned[key] = clean_schema(value, drop, close=close)
    if close and cleaned.get("type") == "object" and "properties" in cleaned:
        cleaned["additionalProperties"] = False
        cleaned["required"] = list(cleaned["properties"])
    return cleaned


def provider_schema(model: type[BaseModel]) -> dict[str, Any]:
    """The schema sent to every provider for `model`."""
    return clean_schema(_inline(model.model_json_schema()))
