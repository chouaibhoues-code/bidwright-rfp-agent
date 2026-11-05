"""The one LLM interface: `LLMClient.complete(role, messages, schema=None, tools=None)`.

The client picks the model for a role from `config/models.yaml`, applies a prompt's decoding
block over the role's defaults, retries transient failures with full-jitter backoff (a
provider's `Retry-After` wins), falls back once to the role's fallback model when one is
configured (unless `fallback=False`, as in matrix runs, where a second model would change what
is measured), records or replays cassettes, validates structured output against its Pydantic
model, and reports one `LedgerEntry` per call. The entry's `retries` counts the failed
provider attempts, across the primary and the fallback model, and `retry_reasons` says why
each one failed: `rate_limited`, `timeout`, `server_error`, `transport`, or `quota` for a
spent daily quota. `before_attempt` runs before every attempt, which is where the run budget
is checked (ADR-022).

Two optional parts sit in front of a provider (Iteration 1, step 9). The limiter
(`llm/limits.py`) is called after `before_attempt` with the model and the request's estimated
input tokens, its characters divided by `chars_per_token`; it waits for the per-minute limits
and raises `QuotaExhausted` on a spent daily allowance, which moves the call to its fallback
model. The response cache (`llm/cache.py`) is read before a live attempt and written after one;
a hit is reported as replayed and skips the budget's attempt count and the limiter. Both apply
to provider attempts only: a replayed call never reaches them, and `record` ignores the cache.

The run's journal (Iteration 2, ADR-031) is a cassette store in the run folder. In `live` mode
every answer that parses is saved to it, a cache hit included, whatever the cache's setting.
With `journal_read`, which a resume turns on, a call is looked up in the journal under every
model of its role, primary first, before any attempt, so a call the fallback answered is not
paid again; a hit is reported as replayed, at no cost and with no budget attempt.

An optional circuit breaker (Iteration 2, `harness/recovery.py`) is checked before each
attempt, before the budget's, under the model's provider, tier and name. A transient failure
counts against it and an answer resets it. An open breaker raises `CircuitOpen`, with the retry
reason `circuit`, which moves the call to its fallback model as a spent quota does.
"""

import os
import random
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Literal

from pydantic import BaseModel, ValidationError

from bidwright.config import Config, RoleConfig, TokenPrices
from bidwright.llm.limits import Limiter, model_key, tier_for
from bidwright.llm.replay import CassetteStore, cache_key
from bidwright.llm.schema import provider_schema, sha256_of
from bidwright.llm.types import (
    Backend,
    Breaker,
    CassetteMissing,
    CircuitOpen,
    LLMError,
    Message,
    ProviderError,
    QuotaExhausted,
    RateLimited,
    Request,
    Response,
    ToolCall,
    ToolSpec,
    TransientError,
    UnrecoverableFault,
    Usage,
)
from bidwright.schemas import LedgerEntry, RetryReason

Mode = Literal["live", "record", "replay"]
Decoding = Mapping[str, Mapping[str, object]]

# The settings a prompt's decoding block may override, per provider. Model and provider stay
# with config/models.yaml.
_DECODING_KEYS = frozenset({"thinking", "think", "num_ctx"})


@dataclass(frozen=True)
class Completion:
    text: str
    parsed: BaseModel | None
    parse_error: str | None
    tool_calls: tuple[ToolCall, ...]
    usage: Usage
    latency_ms: int
    provider: str
    model: str
    replayed: bool
    retries: int
    native: object = None
    retry_reasons: tuple[RetryReason, ...] = ()

    def as_message(self) -> Message:
        """The model's turn, ready to append to the conversation."""
        return Message(
            role="assistant", content=self.text, tool_calls=self.tool_calls, native=self.native
        )


@dataclass
class _Attempts:
    """The provider attempts made for one logical call, across the primary and the fallback,
    and why each one that failed did."""

    made: int = 0
    reasons: list[RetryReason] = field(default_factory=list)


class LLMClient:
    def __init__(
        self,
        config: Config,
        profile: str,
        backends: dict[str, Backend] | None = None,
        *,
        mode: Mode = "live",
        cassettes: CassetteStore | None = None,
        run_id: str = "",
        on_ledger: Callable[[LedgerEntry], None] | None = None,
        before_attempt: Callable[[], None] | None = None,
        limiter: Limiter | None = None,
        cache: CassetteStore | None = None,
        journal: CassetteStore | None = None,
        journal_read: bool = False,
        breaker: Breaker | None = None,
        fallback: bool = True,
        sleep: Callable[[float], None] = time.sleep,
        rng: Callable[[], float] = random.random,
        clock: Callable[[], float] = time.perf_counter,
        today: Callable[[], date] = date.today,
    ) -> None:
        if mode != "live" and cassettes is None:
            raise ValueError(f"mode {mode!r} needs a cassette store")
        self.config = config
        self.profile = profile
        self.backends = backends or {}
        self.mode = mode
        self.cassettes = cassettes
        self.run_id = run_id
        self.on_ledger = on_ledger
        self.before_attempt = before_attempt
        self.limiter = limiter
        self.cache = cache
        self.journal = journal
        self.journal_read = journal_read
        self.breaker = breaker
        self.fallback = fallback
        self._sleep = sleep
        self._rng = rng
        self._clock = clock
        self._today = today

    def complete(
        self,
        role: str,
        messages: Sequence[Message],
        schema: type[BaseModel] | None = None,
        tools: Sequence[ToolSpec] | None = None,
        *,
        node: str,
        agent: str,
        prompt_hash: str,
        input_hash: str,
        repeat: int = 0,
        decoding: Decoding | None = None,
    ) -> Completion:
        """One call for `role`. `decoding` is a prompt's front-matter block, keyed by provider."""
        role_config = _with_decoding(self.config.models.role(self.profile, role), decoding)
        schema_json = provider_schema(schema) if schema is not None else None
        tool_specs = tuple(tools or ())
        tools_hash = (
            sha256_of([[t.name, t.description, t.parameters] for t in tool_specs])
            if tool_specs
            else None
        )
        settings = _settings(role_config)
        fallback = role_config.fallback if self.fallback else None
        models = [role_config.model] + ([fallback] if fallback else [])
        schema_hash = sha256_of(schema_json) if schema_json is not None else None
        timeout_s = self.config.limits.call.timeout_for(self.profile)
        plans = [
            (
                cache_key(
                    prompt_hash=prompt_hash,
                    schema_hash=schema_hash,
                    tools_hash=tools_hash,
                    model=model,
                    settings=settings,
                    input_hash=input_hash,
                    repeat=repeat,
                ),
                Request(
                    model=model,
                    messages=tuple(messages),
                    schema=schema_json,
                    schema_name=schema.__name__ if schema is not None else None,
                    tools=tool_specs,
                    settings=settings,
                    timeout_s=timeout_s,
                ),
            )
            for model in models
        ]
        journaled = self._journaled(plans)
        if journaled is not None:
            request, response = journaled
            completion = _completion(
                response, schema, 0, role_config.provider, request.model, True, 0
            )
            self._report(role, node, agent, completion, None, prompt_hash, input_hash, repeat)
            return completion
        last_error: LLMError | None = None
        attempts = _Attempts()
        for key, request in plans:
            model = request.model
            try:
                response, latency_ms, replayed, backend = self._obtain(
                    role_config, request, key, attempts
                )
            except (UnrecoverableFault, CassetteMissing, QuotaExhausted, CircuitOpen) as exc:
                # A replayed run that fell back has its cassette under the fallback model, and
                # a spent daily quota moves straight to the fallback, with no backoff; its
                # refused attempt still counts. An open breaker moves it the same way.
                if isinstance(exc, QuotaExhausted):
                    attempts.reasons.append("quota")
                elif isinstance(exc, CircuitOpen):
                    attempts.reasons.append("circuit")
                last_error = exc
                continue
            # Every failed attempt left its reason, including the ones before an answer the
            # cache gave, so the two ledger fields always agree.
            retries = len(attempts.reasons)
            completion = _completion(
                response,
                schema,
                latency_ms,
                role_config.provider,
                model,
                replayed,
                retries,
                tuple(attempts.reasons),
            )
            if self.mode == "live" and completion.parse_error is None:
                # Only an answer that parsed is kept: a malformed one is a fault to retry, not
                # a result a later run should be handed again. The journal is written before
                # the ledger entry, so a kill between the two never makes a resume pay again.
                self._keep(key, role_config, request, response, from_cache=replayed)
            self._report(role, node, agent, completion, backend, prompt_hash, input_hash, repeat)
            return completion
        if isinstance(last_error, CassetteMissing | QuotaExhausted | CircuitOpen):
            raise last_error
        raise UnrecoverableFault(f"{role} failed on every model: {last_error}")

    def _journaled(self, plans: Sequence[tuple[str, Request]]) -> tuple[Request, Response] | None:
        """On a resume, the answer the run's journal holds for this call, under the role's
        models in order, primary first."""
        if self.mode != "live" or self.journal is None or not self.journal_read:
            return None
        for key, request in plans:
            response = self.journal.load(key)
            if response is not None:
                return request, response
        return None

    def _keep(
        self,
        key: str,
        role_config: RoleConfig,
        request: Request,
        response: Response,
        *,
        from_cache: bool,
    ) -> None:
        """Save an answer that parsed: to the shared cache when the model gave it, and to the
        run's journal whatever its source, so the journal holds every answer the run had."""
        meta = {**_meta(role_config, request), "run_id": self.run_id}
        if self.cache is not None and not from_cache:
            self.cache.save(key, meta, response)
        if self.journal is not None:
            self.journal.save(key, meta, response)

    def _store(self) -> CassetteStore:
        if self.cassettes is None:
            raise ValueError(f"mode {self.mode!r} needs a cassette store")
        return self.cassettes

    def _obtain(
        self, role_config: RoleConfig, request: Request, key: str, attempts: _Attempts
    ) -> tuple[Response, int, bool, Backend | None]:
        if self.mode == "replay":
            response = self._store().load(key)
            if response is None:
                raise CassetteMissing(f"no cassette {key} for {request.model}")
            return response, 0, True, None
        cache = self.cache if self.mode == "live" else None
        if cache is not None:
            cached = cache.load(key)
            if cached is not None:
                return cached, 0, True, None
        backend = self.backends.get(role_config.provider)
        if backend is None:
            raise ProviderError(f"no backend configured for provider {role_config.provider!r}")
        call = self.config.limits.call
        tokens = _estimated_tokens(request, self.config.limits.context.chars_per_token)
        circuit = model_key(role_config.provider, tier_for(self.profile), request.model)
        retries = 0
        while True:
            if self.breaker is not None:
                self.breaker.check(circuit, request.model)
            if self.before_attempt is not None:
                self.before_attempt()
            attempts.made += 1
            if self.limiter is not None:
                self.limiter.acquire(role_config.provider, request.model, tokens)
            started = self._clock()
            try:
                response = backend.call(request)
            except TransientError as exc:
                if self.breaker is not None:
                    self.breaker.failure(circuit)
                attempts.reasons.append(exc.reason)
                if retries >= call.retries:
                    raise UnrecoverableFault(f"{request.model}: {exc}") from exc
                wait = (
                    exc.retry_after_s
                    if isinstance(exc, RateLimited) and exc.retry_after_s is not None
                    else self._rng() * min(call.backoff_cap_s, call.backoff_base_s * 2**retries)
                )
                retries += 1
                self._sleep(wait)
                continue
            latency_ms = int((self._clock() - started) * 1000)
            if self.breaker is not None:
                self.breaker.success(circuit)
            break
        if self.mode == "record":
            self._store().save(key, _meta(role_config, request), response)
        return response, latency_ms, False, backend

    def _report(
        self,
        role: str,
        node: str,
        agent: str,
        completion: Completion,
        backend: Backend | None,
        prompt_hash: str,
        input_hash: str,
        repeat: int,
    ) -> None:
        if self.on_ledger is None:
            return
        today = self._today()
        own_price = self.config.pricing.price(completion.model, today)
        shadow_model = self.config.pricing.shadow_model.get(role, completion.model)
        shadow_price = self.config.pricing.price(shadow_model, today) or own_price
        paid = backend.paid if backend is not None else False
        usage = completion.usage
        self.on_ledger(
            LedgerEntry(
                run_id=self.run_id,
                node=node,
                agent=agent,
                provider=completion.provider,
                model=completion.model,
                prompt_hash=prompt_hash,
                input_hash=input_hash,
                repeat=repeat,
                tokens_in=usage.tokens_in,
                tokens_out=usage.tokens_out,
                tokens_cached=usage.tokens_cached,
                tokens_thinking=usage.tokens_thinking,
                streamed=False,
                latency_ms=completion.latency_ms,
                ttft_ms=None,
                load_ms=usage.load_ms,
                prompt_ms=usage.prompt_ms,
                gen_ms=usage.gen_ms,
                cost_usd=_cost(usage, own_price) if paid else 0.0,
                shadow_cost_usd=_cost(usage, shadow_price),
                replayed=completion.replayed,
                retries=completion.retries,
                retry_reasons=list(completion.retry_reasons),
            )
        )


def _meta(role_config: RoleConfig, request: Request) -> dict[str, object]:
    """What a cassette or cache entry records about its request, beside the response."""
    return {
        "provider": role_config.provider,
        "model": request.model,
        "request": {
            "schema_name": request.schema_name,
            "tools": [t.name for t in request.tools],
            "settings": request.settings,
        },
    }


def _estimated_tokens(request: Request, chars_per_token: int) -> int:
    """The request's input tokens as the limiter counts them: its characters, divided."""
    chars = sum(len(message.content) for message in request.messages)
    return -(-chars // chars_per_token)


def _with_decoding(role_config: RoleConfig, decoding: Decoding | None) -> RoleConfig:
    """Apply the decoding block's entry for this role's provider over the role's defaults."""
    overrides = dict((decoding or {}).get(role_config.provider, {}))
    unknown = sorted(set(overrides) - _DECODING_KEYS)
    if unknown:
        raise ValueError(f"decoding for {role_config.provider} may not set {unknown}")
    if not overrides:
        return role_config
    return RoleConfig.model_validate({**role_config.model_dump(), **overrides})


def _settings(role_config: RoleConfig) -> dict[str, object]:
    candidates = {
        "thinking": role_config.thinking,
        "think": role_config.think,
        "num_ctx": role_config.num_ctx,
    }
    return {key: value for key, value in candidates.items() if value is not None}


def _completion(
    response: Response,
    schema: type[BaseModel] | None,
    latency_ms: int,
    provider: str,
    model: str,
    replayed: bool,
    retries: int,
    retry_reasons: tuple[RetryReason, ...] = (),
) -> Completion:
    parsed: BaseModel | None = None
    parse_error: str | None = None
    if schema is not None and not response.tool_calls:
        try:
            parsed = schema.model_validate_json(response.text)
        except ValidationError as exc:
            parse_error = str(exc)
    return Completion(
        text=response.text,
        parsed=parsed,
        parse_error=parse_error,
        tool_calls=response.tool_calls,
        usage=response.usage,
        latency_ms=latency_ms,
        provider=provider,
        model=model,
        replayed=replayed,
        retries=retries,
        native=response.native,
        retry_reasons=retry_reasons,
    )


def _cost(usage: Usage, price: TokenPrices | None) -> float:
    if price is None:
        return 0.0
    per_token = 1 / 1_000_000
    uncached = max(usage.tokens_in - usage.tokens_cached, 0)
    cached_rate = price.cached_input if price.cached_input is not None else price.input
    return round(
        (
            uncached * price.input
            + usage.tokens_cached * cached_rate
            + usage.tokens_out * price.output
            + usage.tokens_thinking * price.thinking
        )
        * per_token,
        8,
    )


def default_backends(*, paid: bool = False) -> dict[str, Backend]:
    """Live backends from the environment. Missing keys leave that provider out."""
    from bidwright.llm.ollama import OllamaBackend

    backends: dict[str, Backend] = {"ollama": OllamaBackend()}
    key_name = "GEMINI_PAID_API_KEY" if paid else "GEMINI_API_KEY"
    key = os.environ.get(key_name, "")
    if key:
        from bidwright.llm.genai import GenaiBackend

        backends["gemini"] = GenaiBackend(api_key=key, paid=paid)
    return backends


__all__ = ["Completion", "LLMClient", "default_backends"]
