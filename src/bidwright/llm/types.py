"""Provider-neutral request, response and error types for the LLM client."""

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

Role = Literal["system", "user", "assistant", "tool"]


@dataclass(frozen=True)
class ToolSpec:
    """A tool offered to the model: name, description and JSON Schema for its arguments."""

    name: str
    description: str
    parameters: dict[str, Any]


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class Message:
    """One conversation turn.

    `native` holds the provider's own turn object when a provider needs it sent back
    unchanged, as Gemini 3 does for function calls and their thought signatures.
    """

    role: Role
    content: str = ""
    tool_calls: tuple[ToolCall, ...] = ()
    tool_call_id: str | None = None
    name: str | None = None
    native: Any = None


@dataclass(frozen=True)
class Usage:
    """Token counts and timings for one call, in one convention for every provider.

    `tokens_in` includes cached input, which `tokens_cached` also counts on its own.
    `tokens_out` is visible output only, and thinking tokens go in `tokens_thinking`. Ollama
    reports no split, so its thinking stays in `tokens_out`. Timings are set only where the
    provider reports them.
    """

    tokens_in: int = 0
    tokens_out: int = 0
    tokens_cached: int = 0
    tokens_thinking: int = 0
    load_ms: int | None = None
    prompt_ms: int | None = None
    gen_ms: int | None = None


@dataclass(frozen=True)
class Request:
    model: str
    messages: tuple[Message, ...]
    schema: dict[str, Any] | None = None
    schema_name: str | None = None
    tools: tuple[ToolSpec, ...] = ()
    settings: dict[str, Any] = field(default_factory=dict)
    timeout_s: float = 60.0


@dataclass(frozen=True)
class Response:
    text: str
    tool_calls: tuple[ToolCall, ...] = ()
    usage: Usage = Usage()
    native: Any = None


class Backend(Protocol):
    """A provider adapter. It makes one call and raises the errors below; it never retries."""

    provider: str
    paid: bool

    def call(self, request: Request) -> Response: ...


class LLMError(Exception):
    """Base for client errors."""


class TransientError(LLMError):
    """A timeout, a connection failure or a 5xx: worth retrying."""


class RateLimited(TransientError):
    """A 429. `retry_after_s` is the provider's own wait, when it gives one."""

    def __init__(self, message: str, retry_after_s: float | None = None) -> None:
        super().__init__(message)
        self.retry_after_s = retry_after_s


class ProviderError(LLMError):
    """A 4xx other than 429, or a response the adapter cannot read: not worth retrying."""


class CassetteMissing(LLMError):
    """Replay mode found no cassette for the request's key."""


class UnrecoverableFault(LLMError):
    """Retries and the fallback are exhausted."""
