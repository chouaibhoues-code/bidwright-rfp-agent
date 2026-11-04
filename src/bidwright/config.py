"""Typed loading of the YAML files in `config/`. Files are read with `yaml.safe_load` only.

Every regular expression in `cues.yaml`, `lint.yaml` and `ingest.yaml` compiles at load time, so
a pattern that does not compile fails start-up with a message naming its file and its rule id
or cue kind (Iteration 1, step 1). Every model forbids unknown fields, so a key that nothing
reads cannot be declared (ADR-025).
"""

import os
import re
from datetime import date
from pathlib import Path
from typing import Annotated, Any, Literal, get_args

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from bidwright.schemas import ContractCategory, CueKind, Severity, Zone

CONFIG_DIR = Path(
    os.environ.get("BIDWRIGHT_CONFIG_DIR", Path(__file__).resolve().parents[2] / "config")
)

Provider = Literal["gemini", "cerebras", "groq", "ollama"]
Thinking = Literal["minimal", "low", "medium", "high"]

# The zone names of config/zones.yaml, in the order the keyword rule tries them (ADR-018),
# from the `Zone` literal of schemas.py; a test keeps the file equal to it.
ZONE_NAMES: tuple[str, ...] = get_args(Zone)
# The cue kinds config/cues.yaml defines with patterns (ADR-017). TABLE_ROW is added by code.
CUE_KINDS: tuple[str, ...] = tuple(kind for kind in get_args(CueKind) if kind != "TABLE_ROW")
_PLACEHOLDER = re.compile(r"\{(\w+)\}")
_TEMPLATE_FIELDS = frozenset({"match", "requirement_id"})


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


def compile_patterns(patterns: list[str], where: str) -> list[re.Pattern[str]]:
    """Compile each pattern case-insensitively; name `where` in the error for a bad one."""
    compiled = []
    for pattern in patterns:
        try:
            compiled.append(re.compile(pattern, re.IGNORECASE))
        except re.error as exc:
            raise ValueError(f"{where}: pattern {pattern!r} does not compile: {exc}") from exc
    return compiled


def _check_template(template: str | None, where: str) -> None:
    unknown = set(_PLACEHOLDER.findall(template or "")) - _TEMPLATE_FIELDS
    if unknown:
        raise ValueError(f"{where}: question template uses unknown fields {sorted(unknown)}")


# --- models.yaml ----------------------------------------------------------------------------


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


# --- limits.yaml ----------------------------------------------------------------------------


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


class ModelQuota(Strict):
    """A provider's published limits for one model on one tier, for the limiter (step 9)."""

    rpm: int = Field(gt=0)
    tpm: int = Field(gt=0)
    rpd: int = Field(gt=0)
    reserve: float = Field(ge=0, lt=1)  # the share of the daily quota kept free


class ProviderLimits(Strict):
    quota_day_tz: str
    tiers: dict[str, dict[str, ModelQuota]]


class CoverageLimits(Strict):
    max_rounds: int = Field(ge=0)
    gap_pack_size: int = Field(ge=1)


class ClusterLimits(Strict):
    max_members: int = Field(ge=1)
    max_context: int = Field(ge=0)
    duplicate_jaccard: float = Field(ge=0, le=1)


class ContextLimits(Strict):
    budgets: dict[str, Annotated[int, Field(gt=0)]]
    chars_per_token: int = Field(ge=1)
    neighbors: int = Field(ge=0)
    max_terms: int = Field(ge=0)


class CacheConfig(Strict):
    matrix: bool
    single: bool


class RetentionConfig(Strict):
    client_days: int = Field(ge=0)


class LimitsConfig(Strict):
    runs: dict[str, dict[str, RunLimits]]
    call: CallLimits
    concurrency: dict[str, Annotated[int, Field(ge=1)]]
    batch_size: int = Field(ge=1)
    providers: dict[str, ProviderLimits]
    coverage: CoverageLimits
    clusters: ClusterLimits
    context: ContextLimits
    cache: CacheConfig
    second_pass: bool
    retention: RetentionConfig

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

    def quota_for(self, provider: str, tier: str, model: str) -> ModelQuota | None:
        """The limiter's row for a model, or None when the provider or model has none."""
        tiers = self.providers.get(provider)
        if tiers is None:
            return None
        return tiers.tiers.get(tier, {}).get(model)


# --- agents.yaml, thresholds.yaml, pricing.yaml ---------------------------------------------


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


# --- ingest.yaml ----------------------------------------------------------------------------


class FileLimits(Strict):
    file_mb: int = Field(gt=0)
    pages: int = Field(gt=0)
    files: int = Field(gt=0)


class ArchiveLimits(Strict):
    max_members: int = Field(gt=0)
    max_ratio: int = Field(gt=0)
    max_total_mb: int = Field(gt=0)


class HiddenPdfRules(Strict):
    render_mode: int = Field(ge=0, le=7)
    white_tolerance: float = Field(ge=0, le=1)
    max_pt: float = Field(gt=0)


class SmallPrintRules(Strict):
    min_pt: float = Field(gt=0)
    max_pt: float = Field(gt=0)  # up to, but not including

    @model_validator(mode="after")
    def _ordered(self) -> "SmallPrintRules":
        if self.max_pt <= self.min_pt:
            raise ValueError("small_print.max_pt must be greater than min_pt")
        return self


class ScannedRules(Strict):
    min_chars_per_page: int = Field(ge=0)


class ParserChoice(Strict):
    pdf: Literal["docling", "pdfplumber"]
    docx: Literal["docling"]
    xlsx: Literal["docling"]


class DoclingConfig(Strict):
    url: str
    timeout_s: float = Field(gt=0)
    retries: int = Field(ge=0)
    health_timeout_s: float = Field(gt=0)
    options: dict[str, Any]


class IngestConfig(Strict):
    limits: FileLimits
    archive: ArchiveLimits
    input_root: str
    hidden_pdf: HiddenPdfRules
    small_print: SmallPrintRules
    line_tolerance_pt: float = Field(gt=0)
    scanned: ScannedRules
    parsers: ParserChoice
    docling: DoclingConfig
    suspect_patterns: list[str]

    @model_validator(mode="after")
    def _patterns_compile(self) -> "IngestConfig":
        compile_patterns(self.suspect_patterns, "config/ingest.yaml: suspect_patterns")
        return self


# --- cues.yaml ------------------------------------------------------------------------------


class CuesConfig(Strict):
    kinds: dict[str, list[str]]
    table_row_headers: list[str]

    @model_validator(mode="after")
    def _kinds_are_known_and_compile(self) -> "CuesConfig":
        unknown = sorted(set(self.kinds) - set(CUE_KINDS))
        if unknown:
            raise ValueError(f"config/cues.yaml: unknown cue kinds {unknown}")
        for kind, patterns in self.kinds.items():
            compile_patterns(patterns, f"config/cues.yaml: cue kind {kind}")
        return self


# --- zones.yaml -----------------------------------------------------------------------------


class ZoneDefinition(Strict):
    definition: str
    keywords: list[str] = Field(min_length=1)


class ZonesConfig(Strict):
    confidence_threshold: float = Field(ge=0, le=1)
    default: str
    zones: dict[str, ZoneDefinition]

    @model_validator(mode="after")
    def _default_is_a_zone(self) -> "ZonesConfig":
        if self.default not in self.zones:
            raise ValueError(f"config/zones.yaml: default {self.default!r} is not a zone")
        return self


# --- lint.yaml ------------------------------------------------------------------------------


class LintRule(Strict):
    id: str
    kind: Literal["VAGUE", "ESCAPE", "OPEN_LIST", "TBD"]
    severity: Severity
    patterns: list[str] = Field(min_length=1)
    question: str | None = None


class ContractRule(Strict):
    id: str
    category: ContractCategory
    patterns: list[str] = Field(min_length=1)


class LintCheck(Strict):
    kind: Literal["MISSING_UNIT", "BROKEN_REFERENCE", "NON_SINGULAR", "UNDEFINED_TERM"]
    severity: Severity
    question: str | None = None


class LintConfig(Strict):
    rules: list[LintRule]
    contract: list[ContractRule]
    units: list[str] = Field(min_length=1)
    checks: dict[str, LintCheck]

    @model_validator(mode="after")
    def _rules_compile_and_ids_are_unique(self) -> "LintConfig":
        for rule in self.rules:
            compile_patterns(rule.patterns, f"config/lint.yaml: rule {rule.id}")
            _check_template(rule.question, f"config/lint.yaml: rule {rule.id}")
        for contract in self.contract:
            compile_patterns(contract.patterns, f"config/lint.yaml: contract rule {contract.id}")
        for name, check in self.checks.items():
            _check_template(check.question, f"config/lint.yaml: check {name}")
        ids = [r.id for r in self.rules] + [c.id for c in self.contract] + list(self.checks)
        duplicates = sorted({i for i in ids if ids.count(i) > 1})
        if duplicates:
            raise ValueError(f"config/lint.yaml: duplicate rule ids {duplicates}")
        return self


# --- egress.yaml (ADR-026) ------------------------------------------------------------------


class Destination(Strict):
    hosts: list[str] = Field(min_length=1)
    local: bool
    receives: Literal["prompts", "spans", "documents", "queries"]


class EgressConfig(Strict):
    destinations: dict[str, Destination]


# --- all of it ------------------------------------------------------------------------------


class Config(Strict):
    models: ModelsConfig
    limits: LimitsConfig
    agents: AgentsConfig
    thresholds: ThresholdsConfig
    pricing: PricingConfig
    ingest: IngestConfig
    cues: CuesConfig
    zones: ZonesConfig
    lint: LintConfig
    egress: EgressConfig


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
        ingest=_load(root / "ingest.yaml", IngestConfig),
        cues=_load(root / "cues.yaml", CuesConfig),
        zones=_load(root / "zones.yaml", ZonesConfig),
        lint=_load(root / "lint.yaml", LintConfig),
        egress=_load(root / "egress.yaml", EgressConfig),
    )
