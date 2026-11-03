"""Bidwright's data contract for Iteration 0a.

Two kinds of model live here:
- stored records, which the app writes under `outputs/<run>/`;
- model-facing request and response models, which an LLM sees or returns.

The model never sees offsets, quote status or ids it did not cite; the app sets them.
Field order in model-facing models is deliberate: the quote comes before the labels.
"""

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

# --- Shared vocabularies -------------------------------------------------------------

Modality = Literal["shall", "must", "will", "should", "may", "none"]
Disposition = Literal["BINDING", "OPTIONAL", "BACKGROUND", "NOT_BINDING", "OUT_OF_SCOPE"]
QuoteStatus = Literal["VERBATIM_VERIFIED", "NORMALIZED_MATCH", "REJECTED"]
PassageKind = Literal["sentence", "list_item", "table_header", "table_row"]
EvidenceClass = Literal[
    "RFP_SOURCE",
    "CAPABILITY_EVIDENCE",
    "DOMAIN_METHOD",
    "PROJECT_NORMATIVE",
    "EVALUATION_REFERENCE",
    "EXTERNAL_RESEARCH",
    "ASSUMPTION",
]
RunStatus = Literal[
    "RUNNING",
    "WAITING_HUMAN",
    "WAITING_RESEARCH",
    "QUOTA_PAUSED",
    "STOPPED",
    "BUDGET_EXCEEDED",
    "COMPLETED",
    "DEGRADED",
    "POLICY_BLOCKED",
    "UNRECOVERABLE_FAULT",
]
SectionStatus = Literal["CURRENT", "STALE", "FAILED"]
ToolStatus = Literal["OK", "EMPTY", "DENIED", "FAILED"]

SrcId = Annotated[str, Field(pattern=r"^SRC-\d{4}$")]
ReqId = Annotated[str, Field(pattern=r"^REQ-\d{4}$")]
ApproachId = Annotated[str, Field(pattern=r"^APP-\d{3}$")]
RiskId = Annotated[str, Field(pattern=r"^RSK-\d{3}$")]

QUOTE_MAX_CHARS = 300


class Record(BaseModel):
    """Base for stored records: unknown fields are errors, so drift fails loudly."""

    model_config = ConfigDict(extra="forbid")


# --- Stored records ------------------------------------------------------------------


class Passage(Record):
    id: SrcId
    doc_id: str
    section_path: str
    kind: PassageKind
    text: str
    start: int = Field(ge=0)
    end: int
    lead_in_id: SrcId | None = None
    header_id: SrcId | None = None

    @model_validator(mode="after")
    def _span_is_ordered(self) -> "Passage":
        if self.end <= self.start:
            raise ValueError("end must be greater than start")
        return self


class Requirement(Record):
    id: ReqId
    doc_id: str
    statement: str
    modality: Modality
    mandatory: bool
    hazard: bool
    disposition: Disposition
    src_ids: list[SrcId] = Field(min_length=1, max_length=3)
    quote: str = Field(max_length=QUOTE_MAX_CHARS)
    quote_status: QuoteStatus
    quote_span: tuple[int, int] | None = None

    @model_validator(mode="after")
    def _mandatory_follows_disposition(self) -> "Requirement":
        if self.mandatory != (self.disposition == "BINDING"):
            raise ValueError("mandatory is true exactly when the disposition is BINDING")
        return self


class OpenQuestion(Record):
    text: str
    src_ids: list[SrcId] = Field(default_factory=list)


class ApproachItem(Record):
    id: ApproachId
    text: str
    requirement_ids: list[ReqId] = Field(min_length=1)
    basis: str
    evidence_class: EvidenceClass
    source_ids: list[str] = Field(default_factory=list)


class Risk(Record):
    id: RiskId
    condition: str
    event: str
    effect: str
    assumptions: list[str] = Field(default_factory=list)
    owner_role: str
    trigger: str
    responses: list[str] = Field(min_length=1)
    residual_exposure: str
    evidence_src_ids: list[SrcId] = Field(min_length=1)


class SolutionSummary(Record):
    """The assignment's output. Lists hold record ids; the JSON twin adds full records."""

    run_id: str
    status: Literal["UNREVIEWED_DRAFT"] = "UNREVIEWED_DRAFT"
    hazards: list[ReqId] = Field(default_factory=list)
    requirements: list[ReqId] = Field(default_factory=list)
    approach: list[ApproachId] = Field(default_factory=list)
    risks: list[RiskId] = Field(default_factory=list)
    open_questions: list[OpenQuestion] = Field(default_factory=list)
    counts: dict[str, int] = Field(default_factory=dict)


class ProposalSection(Record):
    id: str
    title: str
    text: str
    cited_ids: list[str] = Field(default_factory=list)
    input_hash: str
    status: SectionStatus


class ToolRequest(Record):
    tool: str
    args: dict[str, Any] = Field(default_factory=dict)
    agent: str
    turn: int = Field(ge=1)


class ToolResult(Record):
    status: ToolStatus
    data: Any = None
    reason: str | None = None


class LedgerEntry(Record):
    run_id: str
    node: str
    agent: str
    provider: str
    model: str
    prompt_hash: str
    input_hash: str
    repeat: int = Field(ge=0)
    tokens_in: int = Field(ge=0)
    tokens_out: int = Field(ge=0)
    tokens_cached: int = Field(default=0, ge=0)
    tokens_thinking: int = Field(default=0, ge=0)
    streamed: bool = False
    latency_ms: int = Field(ge=0)
    ttft_ms: int | None = None
    load_ms: int | None = None
    prompt_ms: int | None = None
    gen_ms: int | None = None
    cost_usd: float = Field(ge=0)
    shadow_cost_usd: float = Field(ge=0)
    replayed: bool
    retries: int = Field(default=0, ge=0)


class RunTotals(Record):
    requests: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    tokens_cached: int = 0
    tokens_thinking: int = 0
    cost_usd: float = 0.0
    shadow_cost_usd: float = 0.0
    active_seconds: float = 0.0


class RunManifest(Record):
    run_id: str
    commit: str
    profile: str
    models: dict[str, str]  # configured, by role
    models_used: dict[str, list[str]] = Field(default_factory=dict)  # answered, by node
    prompt_hashes: dict[str, str] = Field(default_factory=dict)
    input_hashes: dict[str, str] = Field(default_factory=dict)
    started: datetime
    ended: datetime | None = None
    status: RunStatus
    status_reason: str | None = None
    overrides: list[str] = Field(default_factory=list)
    totals: RunTotals = Field(default_factory=RunTotals)


# --- Model-facing requests and responses ----------------------------------------------


class Facing(BaseModel):
    """Base for what an LLM sees or returns. Extra keys from the model are ignored."""

    model_config = ConfigDict(extra="ignore")


class PassageView(Facing):
    src_id: str
    section_path: str
    text: str
    lead_in: str | None = None


class ExtractBatch(Facing):
    batch_id: str
    passages: list[PassageView]


class ExtractItem(Facing):
    src_ids: list[str] = Field(min_length=1, max_length=3)
    quote: str = Field(max_length=QUOTE_MAX_CHARS)
    statement: str
    modality: Modality
    disposition: Disposition
    hazard: bool


class ExtractResult(Facing):
    items: list[ExtractItem]
    no_obligation_src_ids: list[str] = Field(default_factory=list)


class RequirementView(Facing):
    id: str
    statement: str
    modality: Modality
    mandatory: bool
    hazard: bool


class ApproachInput(Facing):
    requirements: list[RequirementView]


class ApproachProposal(Facing):
    text: str
    requirement_ids: list[str] = Field(min_length=1)
    basis: str


class ApproachQuestion(Facing):
    """`approach` sees requirement ids only; the app resolves them to passage ids."""

    text: str
    requirement_ids: list[str] = Field(min_length=1)


class ApproachResult(Facing):
    items: list[ApproachProposal]
    unmapped_requirement_ids: list[str] = Field(default_factory=list)
    open_questions: list[ApproachQuestion] = Field(default_factory=list)


class ApproachItemView(Facing):
    id: str
    text: str
    requirement_ids: list[str]


class RiskInput(Facing):
    requirements: list[RequirementView]
    approach: list[ApproachItemView]
    hazards: list[str] = Field(default_factory=list)


class RiskProposal(Facing):
    condition: str
    event: str
    effect: str
    assumptions: list[str] = Field(default_factory=list)
    owner_role: str
    trigger: str
    responses: list[str] = Field(min_length=1)
    residual_exposure: str
    evidence_src_ids: list[str] = Field(default_factory=list)


class RiskQuestion(Facing):
    """`risk` finds passages through `search_rfp`, so it cites passage ids directly."""

    text: str
    src_ids: list[str] = Field(default_factory=list)


class RiskRegister(Facing):
    risks: list[RiskProposal]
    open_questions: list[RiskQuestion] = Field(default_factory=list)


class DraftTask(Facing):
    section_id: Literal["understanding", "approach", "risks_and_assumptions"]
    records: list[dict[str, Any]]


class DraftResult(Facing):
    title: str
    text: str
    cited_ids: list[str] = Field(default_factory=list)
