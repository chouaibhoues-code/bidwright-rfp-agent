"""Gemini through the native `google-genai` SDK (ADR-001).

Gemini 3 function calling needs the model's turn sent back unchanged, with its thought
signatures, so each response keeps the model's `Content` as `Response.native`. The native
usage metadata is also the documented source of cached and thinking token counts.
"""

import json
from typing import Any

import httpx
from google import genai
from google.genai import errors as genai_errors
from google.genai import types

from bidwright.llm.types import (
    Message,
    ProviderError,
    QuotaExhausted,
    RateLimited,
    Request,
    Response,
    ToolCall,
    TransientError,
    Usage,
)


class GenaiBackend:
    provider = "gemini"
    host = "generativelanguage.googleapis.com"  # for the egress register (D-05)

    def __init__(self, api_key: str, paid: bool = False) -> None:
        self.paid = paid
        self._client = genai.Client(api_key=api_key)

    def call(self, request: Request) -> Response:
        system = "\n\n".join(m.content for m in request.messages if m.role == "system")
        contents = [_content(m) for m in request.messages if m.role != "system"]
        config = types.GenerateContentConfig(
            system_instruction=system or None,
            http_options=types.HttpOptions(
                timeout=int(request.timeout_s * 1000),
                retry_options=types.HttpRetryOptions(attempts=1),
            ),
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )
        thinking = request.settings.get("thinking")
        if thinking:
            config.thinking_config = types.ThinkingConfig(thinking_level=thinking)
        if request.schema is not None:
            config.response_mime_type = "application/json"
            config.response_json_schema = request.schema
        if request.tools:
            config.tools = [
                types.Tool(
                    function_declarations=[
                        types.FunctionDeclaration(
                            name=tool.name,
                            description=tool.description,
                            parameters_json_schema=tool.parameters,
                        )
                        for tool in request.tools
                    ]
                )
            ]
        try:
            response = self._client.models.generate_content(
                model=request.model, contents=contents, config=config
            )
        except genai_errors.APIError as exc:
            raise _translate(exc) from exc
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            raise TransientError(f"gemini transport error: {exc}") from exc
        return _response(response)


def _content(message: Message) -> types.Content:
    if message.native is not None:
        return message.native
    if message.role == "tool":
        try:
            payload: Any = json.loads(message.content)
        except json.JSONDecodeError:
            payload = message.content
        return types.Content(
            role="user",
            parts=[
                types.Part.from_function_response(
                    name=message.name or "tool", response={"result": payload}
                )
            ],
        )
    parts = [types.Part(text=message.content)] if message.content else []
    parts += [
        types.Part(function_call=types.FunctionCall(name=call.name, args=call.arguments))
        for call in message.tool_calls
    ]
    return types.Content(role="model" if message.role == "assistant" else "user", parts=parts)


def _translate(exc: genai_errors.APIError) -> Exception:
    if exc.code == 429:
        quota_ids, retry_after = _quota_details(exc.details)
        if any("PerDay" in quota_id for quota_id in quota_ids):
            return QuotaExhausted(f"gemini daily quota spent: {', '.join(quota_ids)}")
        return RateLimited(f"gemini 429: {exc.message or exc}", retry_after_s=retry_after)
    if exc.code and exc.code >= 500:
        return TransientError(f"gemini {exc.code}: {exc.message or exc}")
    return ProviderError(f"gemini {exc.code}: {exc.message or exc}")


def _quota_details(details: Any) -> tuple[list[str], float | None]:
    """The quota ids a 429 names, and its retry delay in seconds when it gives one."""
    if not isinstance(details, dict):
        return [], None
    quota_ids: list[str] = []
    retry_after: float | None = None
    for item in details.get("error", {}).get("details", []) or []:
        for violation in item.get("violations", []) or []:
            if violation.get("quotaId"):
                quota_ids.append(str(violation["quotaId"]))
        delay = str(item.get("retryDelay", ""))
        if delay.endswith("s"):
            try:
                retry_after = float(delay[:-1])
            except ValueError:
                retry_after = None
    return quota_ids, retry_after


def _response(response: types.GenerateContentResponse) -> Response:
    candidate = response.candidates[0] if response.candidates else None
    native = candidate.content if candidate else None
    calls = tuple(
        ToolCall(
            id=call.id or f"call_{index}", name=call.name or "", arguments=dict(call.args or {})
        )
        for index, call in enumerate(response.function_calls or [])
    )
    meta = response.usage_metadata
    # The four counts are disjoint: total = prompt + tool-use prompt + candidates + thoughts.
    # `prompt_token_count` already includes cached input.
    usage = Usage(
        tokens_in=((meta.prompt_token_count or 0) + (meta.tool_use_prompt_token_count or 0))
        if meta
        else 0,
        tokens_out=(meta.candidates_token_count or 0) if meta else 0,
        tokens_cached=(meta.cached_content_token_count or 0) if meta else 0,
        tokens_thinking=(meta.thoughts_token_count or 0) if meta else 0,
    )
    text = "" if calls else (response.text or "")
    return Response(text=text, tool_calls=calls, usage=usage, native=native)
