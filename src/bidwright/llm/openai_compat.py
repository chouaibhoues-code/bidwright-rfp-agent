"""OpenAI-compatible providers (Cerebras and Groq from Iteration 3) through the `openai` SDK.

The SDK's own retries are off: the client retries with its own backoff and budget. A role's
`reasoning_effort` goes to the provider as is. A 429 that names a daily limit raises
`QuotaExhausted`, which a retry cannot help: Groq's `x-ratelimit-remaining-requests` counts
requests a day, and both providers' error messages name the limit they hit (C7-02, C7-03).
A request that carries an output ceiling sends it as `max_completion_tokens`, which Cerebras
charges to the per-minute token limit before the call runs (step 19).
"""

import json
import re
from typing import Any

import openai
from openai.types import CompletionUsage

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


class OpenAICompatBackend:
    def __init__(self, provider: str, base_url: str, api_key: str, paid: bool = False) -> None:
        self.provider = provider
        self.paid = paid
        self.host = base_url  # for the egress register (D-05)
        self._client = openai.OpenAI(base_url=base_url, api_key=api_key, max_retries=0)

    def call(self, request: Request) -> Response:
        kwargs: dict[str, Any] = {}
        if request.schema is not None:
            kwargs["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": request.schema_name or "response",
                    "schema": request.schema,
                    "strict": True,
                },
            }
        if request.tools:
            kwargs["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": tool.parameters,
                    },
                }
                for tool in request.tools
            ]
        params: dict[str, Any] = {
            "model": request.model,
            "messages": [_message(m) for m in request.messages],
            **kwargs,
        }
        effort = request.settings.get("reasoning_effort")
        if effort is not None:
            params["reasoning_effort"] = effort
        if request.max_completion_tokens is not None:
            params["max_completion_tokens"] = request.max_completion_tokens
        try:
            completion = self._client.with_options(
                timeout=request.timeout_s
            ).chat.completions.create(**params)
        except openai.RateLimitError as exc:
            headers = exc.response.headers if exc.response is not None else {}
            if _daily(self.provider, str(exc), headers):
                raise QuotaExhausted(f"{self.provider} daily limit reached: {exc}") from exc
            retry_after = headers.get("retry-after")
            raise RateLimited(str(exc), float(retry_after) if retry_after else None) from exc
        except openai.APITimeoutError as exc:  # a subclass of APIConnectionError, so first
            raise TransientError(str(exc), "timeout") from exc
        except openai.APIConnectionError as exc:
            raise TransientError(str(exc), "transport") from exc
        except openai.InternalServerError as exc:
            raise TransientError(str(exc), "server_error") from exc
        except openai.APIStatusError as exc:
            raise ProviderError(str(exc)) from exc
        choice = completion.choices[0].message
        calls = tuple(
            ToolCall(
                id=call.id,
                name=call.function.name,
                arguments=json.loads(call.function.arguments or "{}"),
            )
            for call in (choice.tool_calls or [])
            if call.type == "function"
        )
        return Response(text=choice.content or "", tool_calls=calls, usage=_usage(completion.usage))


# A message that names a limit counted over a day: "tokens per day (TPD)", "requests per day",
# "daily". A per-minute limit names minutes, and is retried.
_DAILY = re.compile(r"per[ _-]day|\bdaily\b|\bTPD\b|\bRPD\b", re.IGNORECASE)


def _daily(provider: str, message: str, headers: Any) -> bool:
    """Whether a 429 is a daily limit: its message names one, or, on Groq, whose
    `x-ratelimit-remaining-requests` counts requests a day, none are left. Cerebras documents
    no such header, so only its message counts."""
    if _DAILY.search(message):
        return True
    remaining = headers.get("x-ratelimit-remaining-requests") if headers else None
    return provider == "groq" and remaining is not None and str(remaining).strip() == "0"


def _usage(usage: CompletionUsage | None) -> Usage:
    """OpenAI's `completion_tokens` include reasoning tokens, so they are split out here."""
    if usage is None:
        return Usage()
    details_in = usage.prompt_tokens_details
    details_out = usage.completion_tokens_details
    thinking = (details_out.reasoning_tokens or 0) if details_out else 0
    return Usage(
        tokens_in=usage.prompt_tokens,
        tokens_out=max(usage.completion_tokens - thinking, 0),
        tokens_cached=(details_in.cached_tokens or 0) if details_in else 0,
        tokens_thinking=thinking,
    )


def _message(message: Message) -> dict[str, Any]:
    if message.role == "tool":
        return {"role": "tool", "tool_call_id": message.tool_call_id, "content": message.content}
    out: dict[str, Any] = {"role": message.role, "content": message.content}
    if message.tool_calls:
        out["tool_calls"] = [
            {
                "id": call.id,
                "type": "function",
                "function": {"name": call.name, "arguments": json.dumps(call.arguments)},
            }
            for call in message.tool_calls
        ]
    return out
