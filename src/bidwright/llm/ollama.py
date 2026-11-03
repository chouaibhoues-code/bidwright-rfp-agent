"""Local models through Ollama. `num_ctx` is always sent, because the default can truncate.

Ollama evaluates at most `num_ctx` tokens of a prompt and drops the start of a longer one
without an error (S-14), so a call whose evaluated prompt reaches `num_ctx` is failed here
rather than answered from a cut prompt (ADR-024). A probe on 2026-11-03 showed that a cached
prefix does not lower `prompt_eval_count`, so the check holds on repeated prompts too.
"""

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
# A prompt that comes within this many tokens of num_ctx is treated as cut: Ollama reported
# 1,026 evaluated tokens at a num_ctx of 1,024 for a prompt that did not fit.
TRUNCATION_MARGIN = 64
_TRANSPORT_ERRORS = (httpx.TimeoutException, httpx.TransportError, ConnectionError)


class OllamaBackend:
    provider = "ollama"
    paid = False

    def __init__(self, host: str | None = None) -> None:
        self._host = host or os.environ.get("OLLAMA_HOST") or "http://localhost:11434"

    def models(self) -> set[str]:
        """The names of the models pulled on this host, for the run's preconditions."""
        client = ollama.Client(host=self._host, timeout=10)
        try:
            listed = client.list()
        except (ollama.ResponseError, *_TRANSPORT_ERRORS) as exc:
            raise ProviderError(f"ollama at {self._host} did not answer: {exc}") from exc
        return {entry.model for entry in listed.models if entry.model}

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
        except _TRANSPORT_ERRORS as exc:
            raise TransientError(f"ollama transport error: {exc}") from exc
        evaluated = response.prompt_eval_count or 0
        if evaluated >= num_ctx - TRUNCATION_MARGIN:
            raise ProviderError(
                f"ollama evaluated {evaluated} prompt tokens at a num_ctx of {num_ctx}: the"
                " prompt was cut, so the answer is not trusted"
            )
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
