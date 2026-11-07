"""Typed loading of the YAML files in `config/`. Files are read with `yaml.safe_load` only.

Every regular expression in `cues.yaml`, `lint.yaml` and `ingest.yaml` compiles at load time, so
a pattern that does not compile fails start-up with a message naming its file and its rule id
or cue kind (Iteration 1, step 1). Every model forbids unknown fields, so a key that nothing
reads cannot be declared (ADR-025).
"""

import hashlib
import os
import re
from datetime import date
from pathlib import Path
from typing import Annotated, Any, Literal, get_args

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from bidwright.schemas import ContractCategory, CueKind, Severity, Zone

CONFIG_DIR = Path(
    os.environ.get("BIDWRIGHT_CONFIG_DIR", Path(__file__).resolve().parents[2] / "config")
)

Provider = Literal["gemini", "cerebras", "groq", "ollama"]
Thinking = Literal["minimal", "low", "medium", "high"]
# gpt-oss on Cerebras and Groq takes `reasoning_effort` low, medium or high (C7-02).
Effort = Literal["low", "medium", "high"]

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


class ProviderModel(Strict):
    """A model on another provider, which a routed role falls back to (ADR-045)."""

    provider: Provider
    model: str


class RoleConfig(Strict):
    """A role's model on one profile. A role with `same_family_role` is routed (ADR-045): its
    route is set once at run start, to this provider, else `fallback_provider`, else the named
    role's model, of the generator's family. `same_family` says that this provider is the
    generator's family already, as on `local`, so assessments are flagged but the run is not
    degraded. `fallback` is a second model on the same provider, as for every role."""

    provider: Provider
    model: str
    fallback: str | None = None
    thinking: Thinking | None = None
    num_ctx: int | None = None
    think: bool | None = None
    reasoning_effort: Effort | None = None
    fallback_provider: ProviderModel | None = None
    same_family_role: str | None = None
    same_family: bool = False


class ModelsConfig(Strict):
    profiles: dict[str, dict[str, RoleConfig]]

    @model_validator(mode="after")
    def _routes_name_plain_roles(self) -> "ModelsConfig":
        for profile, roles in self.profiles.items():
            for name, role in roles.items():
                target = role.same_family_role
                if target is None:
                    if role.fallback_provider is not None or role.same_family:
                        raise ValueError(
                            f"{profile}.{name}: fallback_provider and same_family belong to a"
                            " routed role, which names its same_family_role"
                        )
                    continue
                if target not in roles or roles[target].same_family_role is not None:
                    raise ValueError(
                        f"{profile}.{name}: same_family_role {target!r} must name an unrouted"
                        " role of the same profile"
                    )
        return self

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
    # Tokens a day (input, output and thinking, as each call reports them), when the provider
    # sets a cap; enforced with `daily: enforce` as `rpd` is (ADR-045).
    tpd: int | None = Field(default=None, gt=0)
    # `enforce`: the limiter stops at the daily limit less the reserve. `observe`: it only
    # counts, and the provider's own daily 429 stops the calls (ADR-029).
    daily: Literal["enforce", "observe"] = "enforce"


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


class BreakerConfig(Strict):
    """The circuit breaker (Iteration 2): consecutive failed attempts that open it, and for how
    long it stays open."""

    failures: int = Field(ge=1)
    cooldown_minutes: float = Field(gt=0)


class SolutionLimits(Strict):
    """Iteration 3's solution path (ADR-039): the needs `decide` takes a run, the claims a
    need may draft, and the technology claims `techcheck` checks a run (ADR-044)."""

    need_cap: int = Field(ge=1)
    claims_per_need: int = Field(ge=1)
    tech_claim_cap: int = Field(ge=1)


class SwitchesConfig(Strict):
    """The switches of section 4.11 of Iteration 3's design, with their defaults."""

    solution: Literal["oneshot", "fixed", "decide", "assess", "manifest"] = "manifest"
    risk_mode: Literal["oneshot", "fixed", "agent"] = "agent"
    reflect: bool = False
    # The extraction switches (step 16): each passage's context, triage, coverage's rounds.
    extract_context: Literal["full", "bare"] = "full"
    triage: bool = True
    coverage: bool = True


class MethodsConfig(Strict):
    """The method-card families a run inlines by default (Iteration 3, step 18): none
    until S-12 measures a family and an ADR switches it on."""

    enabled: list[Literal["REQ", "CFG", "BA", "DEL", "BEN", "RISK", "GOV"]] = Field(
        default_factory=list
    )


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
    breaker: BreakerConfig
    solution: SolutionLimits
    switches: SwitchesConfig = Field(default_factory=SwitchesConfig)
    methods: MethodsConfig = Field(default_factory=MethodsConfig)

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

    def quota_tier(self, provider: str, tier: str) -> str:
        """The tier whose rows apply: the profile's, or a provider's only tier, which one
        account's limits give on every profile, as Cerebras's trial does."""
        tiers = self.providers.get(provider)
        if tiers is None or tier in tiers.tiers or len(tiers.tiers) != 1:
            return tier
        return next(iter(tiers.tiers))

    def quota_for(self, provider: str, tier: str, model: str) -> ModelQuota | None:
        """The limiter's row for a model, or None when the provider or model has none."""
        tiers = self.providers.get(provider)
        if tiers is None:
            return None
        return tiers.tiers.get(self.quota_tier(provider, tier), {}).get(model)


# --- agents.yaml, thresholds.yaml, pricing.yaml ---------------------------------------------


class AgentLimits(Strict):
    """The limits the `risk` loop enforces. A function's one call and one repair are fixed in
    the node code, so no field declares them (ADR-025)."""

    max_turns: int | None = None
    max_tool_calls: int | None = None
    stop_on_no_progress: bool = False
    # Iteration 3 (ADR-047): the gated reflect tool, off unless a ladder rung turns it on.
    reflect: bool = False


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


# --- a bid policy (Iteration 3, ADR-042), loaded only when `--bid-policy` names one -------------

BidWhen = Literal[
    "hazard_on_gap",
    "gap_on_mandatory",
    "contract_flag",
    "deadline_within_days",
    "every_option_needs_proof",
]
BidInput = Literal["capability_map", "options", "manifest", "tech_validations"]


class BidRule(Strict):
    """One fatal trigger or condition, from the fixed set code evaluates."""

    id: str = Field(min_length=1)
    when: BidWhen
    categories: list[ContractCategory] = Field(default_factory=list)  # contract_flag only
    days: int | None = Field(default=None, ge=0)  # deadline_within_days only

    @model_validator(mode="after")
    def _its_parameters(self) -> "BidRule":
        if (self.when == "contract_flag") != bool(self.categories):
            raise ValueError(f"{self.id}: contract_flag, and only it, names its categories")
        if (self.when == "deadline_within_days") != (self.days is not None):
            raise ValueError(f"{self.id}: deadline_within_days, and only it, sets days")
        return self


class BidPolicy(Strict):
    """An approved bid policy. The approver is a role, never a name."""

    approved_by: str = Field(min_length=1)
    approved_on: date
    version: int = Field(ge=1)
    fatal: list[BidRule] = Field(default_factory=list)
    conditions: list[BidRule] = Field(default_factory=list)
    min_covered_share: float | None = Field(default=None, ge=0, le=1)
    required_inputs: list[BidInput] = Field(default_factory=list)


def load_bid_policy(path: Path) -> tuple[BidPolicy, str]:
    """The policy in `path` and its file's hash, which the run manifest records."""
    data = path.read_bytes()
    policy = BidPolicy.model_validate(yaml.safe_load(data.decode("utf-8")))
    return policy, f"sha256:{hashlib.sha256(data).hexdigest()}"


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
    """An egress destination. An `http` one lists its hosts; a `stdio` one (Iteration 3: the
    sequential-thinking server behind `reflect`) is a local subprocess and lists none."""

    transport: Literal["http", "stdio"] = "http"
    hosts: list[str] = Field(default_factory=list)
    local: bool
    receives: Literal["prompts", "spans", "documents", "queries", "thoughts"]

    @model_validator(mode="after")
    def _hosts_follow_the_transport(self) -> "Destination":
        if self.transport == "http" and not self.hosts:
            raise ValueError("an http destination lists its hosts")
        if self.transport == "stdio" and (self.hosts or not self.local):
            raise ValueError("a stdio destination is a local subprocess and lists no hosts")
        return self


class EgressConfig(Strict):
    destinations: dict[str, Destination]


# --- research.yaml and mcp_pins.yaml (Iteration 2, ADR-032 to ADR-036) -------------------------

ResearchMode = Literal["off", "pack", "live"]
RESEARCH_MODES: tuple[str, ...] = get_args(ResearchMode)
_TOOL_HASH = r"^sha256:[0-9a-f]{64}$"


class SelectionConfig(Strict):
    min_keyword_matches: int = Field(ge=1)


class JobsConfig(Strict):
    max_per_run: int = Field(ge=1)
    mode: Literal["deep", "fast"]
    wait_minutes: float = Field(gt=0)
    poll_seconds: float = Field(gt=0)
    import_sources: Literal["cited", "all"] = Field(alias="import")


class QuestionsConfig(Strict):
    max_per_run: int = Field(ge=0)
    max_matches: int = Field(ge=1)
    match_share: float = Field(gt=0, le=1)
    min_terms: int = Field(ge=1)


class OutboundConfig(Strict):
    max_shared_words: int = Field(ge=1)  # a query sharing one more consecutive word is denied


class HttpServer(Strict):
    transport: Literal["http"]
    url: str = Field(min_length=1)
    timeout_s: float = Field(gt=0)
    tool_timeout_s: float = Field(gt=0)
    package: str | None = None
    version: str | None = None
    # The variable holding a key sent as `Authorization: Bearer`, when it is set and not empty
    # (Iteration 3: Context7's CONTEXT7_API_KEY).
    bearer_env: str | None = Field(default=None, pattern=r"^[A-Z][A-Z0-9_]*$")


class StdioServer(Strict):
    """A server Bidwright starts as a subprocess: the sequential-thinking server behind
    `reflect` (Iteration 3), and test servers. It has no host, so the egress check refuses one
    unless `config/egress.yaml` lists it as a local `stdio` destination."""

    transport: Literal["stdio"]
    command: str = Field(min_length=1)
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    timeout_s: float = Field(gt=0)
    tool_timeout_s: float = Field(gt=0)
    package: str | None = None
    version: str | None = None


ServerConfig = Annotated[HttpServer | StdioServer, Field(discriminator="transport")]


class TiersConfig(Strict):
    """Authority tiers by host. The file writes tiers 1 to 3 as keys, each a list of host
    entries, and `default` for a host no entry matches."""

    hosts: dict[int, list[str]]
    default: int = Field(ge=1, le=4)

    @model_validator(mode="before")
    @classmethod
    def _from_file(cls, data: Any) -> Any:
        if isinstance(data, dict) and "hosts" not in data:
            entries = dict(data)
            default = entries.pop("default", 4)
            return {"hosts": entries, "default": default}
        return data

    @model_validator(mode="after")
    def _keys_are_tiers(self) -> "TiersConfig":
        bad = sorted(key for key in self.hosts if not 1 <= key <= 3)
        if bad:
            raise ValueError(f"config/research.yaml: tiers keys must be 1 to 3, not {bad}")
        return self


class ResearchConfig(Strict):
    mode: ResearchMode
    packs_dir: str = Field(min_length=1)  # resolved against HOME where it is used
    selection: SelectionConfig
    jobs: JobsConfig
    questions: QuestionsConfig
    outbound: OutboundConfig
    servers: dict[str, ServerConfig]
    tiers: TiersConfig

    @field_validator("mode", mode="before")
    @classmethod
    def _off_is_a_mode(cls, value: Any) -> Any:
        """YAML 1.1 reads a bare `off` as false; the file means the mode `off`."""
        return "off" if value is False else value


class ServerIdentity(Strict):
    """What a server's `initialize` reports. NotebookLM's reports the MCP SDK's version."""

    name: str
    version: str


class ServerPins(Strict):
    server: ServerIdentity | None = None
    package: str | None = None  # the package as research.yaml declares it, "name==version"
    tools: dict[str, Annotated[str, Field(pattern=_TOOL_HASH)]] = Field(default_factory=dict)


class PinsConfig(Strict):
    """`config/mcp_pins.yaml`, written by `bidwright research pin`. A server with no pinned
    tools is refused."""

    servers: dict[str, ServerPins]


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
    research: ResearchConfig
    pins: PinsConfig


def _load[ModelT: BaseModel](path: Path, model: type[ModelT]) -> ModelT:
    with path.open(encoding="utf-8") as handle:
        return model.model_validate(yaml.safe_load(handle))


def load_config(root: Path = CONFIG_DIR) -> Config:
    with (root / "agents.yaml").open(encoding="utf-8") as handle:
        agents = AgentsConfig.model_validate({"agents": yaml.safe_load(handle)})
    with (root / "mcp_pins.yaml").open(encoding="utf-8") as handle:
        pins = PinsConfig.model_validate({"servers": yaml.safe_load(handle) or {}})
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
        research=_load(root / "research.yaml", ResearchConfig),
        pins=pins,
    )
