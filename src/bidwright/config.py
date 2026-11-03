"""Typed loading of the YAML files in `config/`. Files are read with `yaml.safe_load` only."""

import os
from datetime import date
from pathlib import Path
from typing import Annotated, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

CONFIG_DIR = Path(
    os.environ.get("BIDWRIGHT_CONFIG_DIR", Path(__file__).resolve().parents[2] / "config")
)

Provider = Literal["gemini", "cerebras", "groq", "ollama"]
Thinking = Literal["minimal", "low", "medium", "high"]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RoleConfig(Strict):
    provider: Provider
    model: str
    fallback: str | None = None
    thinking: Thinking | None = None
    num_ctx: int | None = None
    think: bool | None = None


class ModelsConfig(Strict):
    profiles: dict[str, dict[str, RoleConfig]]

    def role(self, profile: str, role: str) -> RoleConfig:
        try:
            return self.profiles[profile][role]
        except KeyError as exc:
            raise KeyError(f"no model for role {role!r} in profile {profile!r}") from exc


class RunLimits(Strict):
    requests: int = Field(gt=0)
    tokens: int = Field(gt=0)
    active_minutes: float = Field(gt=0)


class CallLimits(Strict):
    timeout_s: dict[str, Annotated[float, Field(gt=0)]]
    retries: int = Field(ge=0)
    backoff_base_s: float = Field(gt=0)
    backoff_cap_s: float = Field(gt=0)

    def timeout_for(self, profile: str) -> float:
        try:
            return self.timeout_s[profile]
        except KeyError as exc:
            raise KeyError(f"no call timeout for profile {profile!r}") from exc


class LimitsConfig(Strict):
    runs: dict[str, dict[str, RunLimits]]
    call: CallLimits
    concurrency: dict[str, Annotated[int, Field(ge=1)]]
    batch_size: int = Field(ge=1)

    def run(self, corpus: str, profile: str) -> RunLimits:
        try:
            return self.runs[corpus][profile]
        except KeyError as exc:
            raise KeyError(f"no run limits for {corpus!r} on {profile!r}") from exc

    def concurrency_for(self, profile: str) -> int:
        """How many `Send` workers run at once on this profile."""
        try:
            return self.concurrency[profile]
        except KeyError as exc:
            raise KeyError(f"no concurrency for profile {profile!r}") from exc


class AgentLimits(Strict):
    """The limits the `risk` loop enforces. A function's one call and one repair are fixed in
    the node code, so no field declares them (ADR-025)."""

    max_turns: int | None = None
    max_tool_calls: int | None = None
    stop_on_no_progress: bool = False


class AgentConfig(Strict):
    kind: Literal["agent", "function"]
    input: str
    output: str
    prompt: str
    model_role: str
    tools: list[str] = Field(default_factory=list)
    limits: AgentLimits = Field(default_factory=AgentLimits)


class AgentsConfig(Strict):
    agents: dict[str, AgentConfig]


class ThresholdsConfig(Strict):
    block: dict[str, float]
    warn: dict[str, float]


class TokenPrices(Strict):
    input: float = Field(ge=0)
    output: float = Field(ge=0)
    thinking: float = Field(ge=0)
    cached_input: float | None = None


class PriceEntry(Strict):
    model: str
    effective_from: date | None = None
    effective_to: date | None = None
    read_on: date
    usd_per_mtok: TokenPrices
    source: str


class PricingConfig(Strict):
    models: list[PriceEntry]
    shadow_model: dict[str, str]

    def price(self, model: str, on: date) -> TokenPrices | None:
        """The price in force for `model` on a given day, or None when it has no list price."""
        for entry in self.models:
            starts_ok = entry.effective_from is None or entry.effective_from <= on
            ends_ok = entry.effective_to is None or on <= entry.effective_to
            if entry.model == model and starts_ok and ends_ok:
                return entry.usd_per_mtok
        return None


class Config(Strict):
    models: ModelsConfig
    limits: LimitsConfig
    agents: AgentsConfig
    thresholds: ThresholdsConfig
    pricing: PricingConfig


def _load[ModelT: BaseModel](path: Path, model: type[ModelT]) -> ModelT:
    with path.open(encoding="utf-8") as handle:
        return model.model_validate(yaml.safe_load(handle))


def load_config(root: Path = CONFIG_DIR) -> Config:
    with (root / "agents.yaml").open(encoding="utf-8") as handle:
        agents = AgentsConfig.model_validate({"agents": yaml.safe_load(handle)})
    return Config(
        models=_load(root / "models.yaml", ModelsConfig),
        limits=_load(root / "limits.yaml", LimitsConfig),
        agents=agents,
        thresholds=_load(root / "thresholds.yaml", ThresholdsConfig),
        pricing=_load(root / "pricing.yaml", PricingConfig),
    )
