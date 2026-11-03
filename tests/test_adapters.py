"""Offline checks that each provider adapter maps the provider's fields as documented."""

import json
from types import SimpleNamespace
from typing import Any

import ollama
import pytest
from google.genai import errors as genai_errors
from google.genai import types
from openai.types import CompletionUsage
from openai.types.completion_usage import CompletionTokensDetails, PromptTokensDetails

from bidwright.llm.genai import _content, _response, _translate
from bidwright.llm.ollama import TRUNCATION_MARGIN, OllamaBackend
from bidwright.llm.openai_compat import _usage
from bidwright.llm.types import (
    Message,
    ProviderError,
    QuotaExhausted,
    RateLimited,
    Request,
    ToolCall,
    Usage,
)


def test_genai_keeps_cached_and_thinking_counts_and_the_model_turn() -> None:
    turn = types.Content(role="model", parts=[types.Part(text='{"risks": []}')])
    response = types.GenerateContentResponse(
        candidates=[types.Candidate(content=turn)],
        usage_metadata=types.GenerateContentResponseUsageMetadata(
            prompt_token_count=1200,
            tool_use_prompt_token_count=30,
            candidates_token_count=80,
            cached_content_token_count=1024,
            thoughts_token_count=40,
        ),
    )
    mapped = _response(response)
    assert mapped.text == '{"risks": []}'
    assert mapped.usage == Usage(
        tokens_in=1230, tokens_out=80, tokens_cached=1024, tokens_thinking=40
    )
    assert mapped.native == turn


def test_genai_function_calls_become_tool_calls_with_no_text() -> None:
    call = types.FunctionCall(name="search_rfp", args={"query": "audit record"})
    turn = types.Content(role="model", parts=[types.Part(function_call=call)])
    mapped = _response(types.GenerateContentResponse(candidates=[types.Candidate(content=turn)]))
    assert mapped.text == ""
    assert [(c.name, c.arguments) for c in mapped.tool_calls] == [
        ("search_rfp", {"query": "audit record"})
    ]
    assert mapped.usage == Usage()


def test_genai_sends_the_model_turn_back_unchanged() -> None:
    signed = types.Part(
        function_call=types.FunctionCall(name="date_calc", args={}), thought_signature=b"sig"
    )
    native = types.Content(role="model", parts=[signed])
    message = Message("assistant", tool_calls=(ToolCall("call_0", "date_calc", {}),), native=native)
    assert _content(message) is native


def test_genai_tool_results_become_function_responses() -> None:
    result = json.dumps({"status": "OK", "data": []})
    content = _content(Message("tool", result, tool_call_id="call_0", name="search_rfp"))
    parts = content.parts or []
    response = parts[0].function_response
    assert content.role == "user" and response is not None
    assert response.name == "search_rfp"
    assert response.response == {"result": {"status": "OK", "data": []}}


def _quota_error(quota_id: str, delay: str | None = None) -> genai_errors.APIError:
    details: list[dict[str, Any]] = [
        {
            "@type": "type.googleapis.com/google.rpc.QuotaFailure",
            "violations": [{"quotaId": quota_id, "quotaValue": "20"}],
        }
    ]
    if delay:
        details.append({"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": delay})
    body = {
        "error": {
            "code": 429,
            "status": "RESOURCE_EXHAUSTED",
            "message": "quota",
            "details": details,
        }
    }
    return genai_errors.APIError(429, body)


def test_genai_a_spent_daily_quota_is_not_retried() -> None:
    error = _translate(_quota_error("GenerateRequestsPerDayPerProjectPerModel-FreeTier"))
    assert isinstance(error, QuotaExhausted)


def test_genai_a_per_minute_429_is_retried_after_its_delay() -> None:
    error = _translate(_quota_error("GenerateRequestsPerMinutePerProjectPerModel-FreeTier", "7s"))
    assert isinstance(error, RateLimited) and error.retry_after_s == 7.0


def test_openai_usage_splits_reasoning_out_of_completion_tokens() -> None:
    usage = CompletionUsage(
        prompt_tokens=900,
        completion_tokens=300,
        total_tokens=1200,
        prompt_tokens_details=PromptTokensDetails(cached_tokens=512),
        completion_tokens_details=CompletionTokensDetails(reasoning_tokens=120),
    )
    assert _usage(usage) == Usage(
        tokens_in=900, tokens_out=180, tokens_cached=512, tokens_thinking=120
    )


def test_openai_usage_without_details() -> None:
    usage = CompletionUsage(prompt_tokens=130, completion_tokens=211, total_tokens=341)
    assert _usage(usage) == Usage(tokens_in=130, tokens_out=211)


def test_ollama_refuses_a_call_without_num_ctx() -> None:
    request = Request(model="qwen3.5:4b", messages=(Message("user", "hello"),))
    with pytest.raises(ProviderError, match="num_ctx"):
        OllamaBackend("http://127.0.0.1:9").call(request)


def _ollama_client(prompt_eval_count: int) -> type:
    class FakeClient:
        def __init__(self, host: str | None = None, timeout: float | None = None) -> None:
            pass

        def chat(self, **kwargs: Any) -> Any:
            return SimpleNamespace(
                message=SimpleNamespace(content="OK", tool_calls=None),
                prompt_eval_count=prompt_eval_count,
                eval_count=2,
                load_duration=None,
                prompt_eval_duration=None,
                eval_duration=None,
            )

    return FakeClient


_LOCAL = Request(
    model="qwen3.5:2b", messages=(Message("user", "hello"),), settings={"num_ctx": 16384}
)


@pytest.mark.parametrize("evaluated", [16384 - TRUNCATION_MARGIN, 16384, 16400])
def test_ollama_fails_a_call_whose_prompt_reached_num_ctx(
    monkeypatch: pytest.MonkeyPatch, evaluated: int
) -> None:
    """S-14: Ollama drops the start of a prompt longer than num_ctx without an error."""
    monkeypatch.setattr(ollama, "Client", _ollama_client(evaluated))
    with pytest.raises(ProviderError, match="cut"):
        OllamaBackend("http://127.0.0.1:9").call(_LOCAL)


def test_ollama_answers_a_prompt_that_fits(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ollama, "Client", _ollama_client(16384 - TRUNCATION_MARGIN - 1))
    response = OllamaBackend("http://127.0.0.1:9").call(_LOCAL)
    assert response.text == "OK" and response.usage.tokens_in == 16384 - TRUNCATION_MARGIN - 1


def test_ollama_models_reports_an_unreachable_host() -> None:
    with pytest.raises(ProviderError, match="did not answer"):
        OllamaBackend("http://127.0.0.1:9").models()
