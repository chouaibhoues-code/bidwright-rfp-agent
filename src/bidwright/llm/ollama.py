"""Local models through Ollama. `num_ctx` is always sent, because the default can truncate."""

import os
from typing import Any

import httpx
import ollama

from bidwright.llm.types import (
    Message,
    ProviderError,
    Request,
    Response,
    ToolCall,
    ToolSpec,
    TransientError,
    Usage,
)

_NS_PER_MS = 1_000_000


class OllamaBackend:
    provider = "ollama"
    paid = False

    def __init__(self, host: str | None = None) -> None:
        self._host = host or os.environ.get("OLLAMA_HOST") or "http://localhost:11434"

    def call(self, request: Request) -> Response:
        num_ctx = request.settings.get("num_ctx")
        if not num_ctx:
            raise ProviderError("ollama calls must set num_ctx explicitly")
        client = ollama.Client(host=self._host, timeout=request.timeout_s)
        try:
            response = client.chat(
                model=request.model,
                messages=[_message(m) for m in request.messages],
                tools=[_tool(t) for t in request.tools] or None,
                format=request.schema,
                think=request.settings.get("think"),
                options={"num_ctx": num_ctx},
            )
        except ollama.ResponseError as exc:
            if exc.status_code >= 500:
                raise TransientError(f"ollama {exc.status_code}: {exc.error}") from exc
            raise ProviderError(f"ollama {exc.status_code}: {exc.error}") from exc
        except (httpx.TimeoutException, httpx.TransportError, ConnectionError) as exc:
            raise TransientError(f"ollama transport error: {exc}") from exc
        calls = tuple(
            ToolCall(
                id=f"call_{index}",
                name=call.function.name,
                arguments=dict(call.function.arguments or {}),
            )
            for index, call in enumerate(response.message.tool_calls or [])
        )
        usage = Usage(
            tokens_in=response.prompt_eval_count or 0,
            tokens_out=response.eval_count or 0,
            load_ms=_ms(response.load_duration),
            prompt_ms=_ms(response.prompt_eval_duration),
            gen_ms=_ms(response.eval_duration),
        )
        return Response(text=response.message.content or "", tool_calls=calls, usage=usage)


def _ms(nanoseconds: int | None) -> int | None:
    return None if nanoseconds is None else nanoseconds // _NS_PER_MS


def _message(message: Message) -> dict[str, Any]:
    out: dict[str, Any] = {"role": message.role, "content": message.content}
    if message.tool_calls:
        out["tool_calls"] = [
            {"function": {"name": call.name, "arguments": call.arguments}}
            for call in message.tool_calls
        ]
    if message.role == "tool" and message.name:
        out["tool_name"] = message.name
    return out


def _tool(tool: ToolSpec) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.parameters,
        },
    }
