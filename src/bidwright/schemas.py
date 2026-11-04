"""Bidwright's data contract.

Two kinds of model live here:
- stored records, which the app writes under `outputs/<run>/`;
- model-facing request and response models, which an LLM sees or returns.

The model never sees offsets, quote status or ids it did not cite; the app sets them.
Field order in model-facing models is deliberate: the quote comes before the labels.

Iteration 1 adds the guard, ingest, candidate, triage, coverage, lint, consolidation and
context models of its design document (section 5.1). Every field it adds to a `v0.0` record
has a default, so records written by `v0.0` stay valid until the step that fills the field.
"""

from collections.abc import Callable
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

# --- Shared vocabularies -------------------------------------------------------------

Modality = Literal["shall", "must", "will", "should", "may", "none"]
Disposition = Literal["BINDING", "OPTIONAL", "BACKGROUND", "NOT_BINDING", "OUT_OF_SCOPE"]
# What the candidate ledger records per passage: a disposition, or why there is none.
LedgerDisposition = Literal[
    "BINDING",
    "OPTIONAL",
    "BACKGROUND",
    "NOT_BINDING",
    "OUT_OF_SCOPE",
    "NO_OBLIGATION",
    "REJECTED",
    "UNACCOUNTED",
]
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
DataClass = Literal["synthetic", "client"]

# The zones `triage` assigns per section, in the order the keyword fallback tries them
# (ADR-018). `config/zones.yaml` lists the same names, and a test keeps the two equal.
Zone = Literal["INSTRUCTION", "EVALUATION", "ELIGIBILITY", "OBLIGATION", "CONTRACT", "BACKGROUND"]
ZoneSource = Literal["model", "keywords"]
DocFormat = Literal["pdf", "docx", "xlsx"]
DocRole = Literal["main", "annex", "addendum", "form"]
Parser = Literal["docling", "pdfplumber"]
PrecedenceSource = Literal["package.yaml", "rules"]
QuarantineKind = Literal[
    "pdf_invisible",
    "pdf_background_color",
    "pdf_tiny_font",
    "pdf_off_page",
    "ooxml_external_relationship",
    "docx_hidden_run",
    "docx_deleted_revision",
    "docx_comment",
    "docx_alt_text",
    "docx_custom_xml",
    "docx_property",
    "docx_field_instruction",
    "xlsx_hidden_sheet",
    "xlsx_very_hidden_sheet",
    "xlsx_hidden_format",
    "xlsx_comment",
    "xlsx_validation_message",
    "xlsx_defined_name",
]
# The cue kinds `candidates` annotates (ADR-017). `config/cues.yaml` holds the patterns of the
# first nine; TABLE_ROW comes from the passage kind and its header.
CueKind = Literal[
    "MODAL",
    "PROHIBITION",
    "CONDITION",
    "RIGHT",
    "DEADLINE",
    "REJECTION",
    "REFERENCE",
    "AMOUNT",
    "DATE",
    "TABLE_ROW",
]
HazardKind = Literal[
    "DEADLINE", "FORMAT", "FORM", "ELIGIBILITY", "ANONYMITY", "KEY_PERSONNEL", "OTHER"
]
StopReason = Literal["closed", "no_shrink", "max_rounds"]
LintKind = Literal[
    "VAGUE",
    "ESCAPE",
    "OPEN_LIST",
    "TBD",
    "MISSING_UNIT",
    "BROKEN_REFERENCE",
    "NON_SINGULAR",
    "UNDEFINED_TERM",
]
Severity = Literal["question", "note"]
ContractCategory = Literal[
    "LIABILITY", "INDEMNITY", "IP", "DATA", "SERVICE_CREDITS", "TERMINATION", "FLOW_DOWN"
]
DiscrepancyKind = Literal["CONFLICT", "INCONSISTENT_VALUE", "SUPERSEDED"]
DiscrepancyState = Literal["conditional", "established"]
QuestionOrigin = Literal["consolidate", "lint_template"]

SrcId = Annotated[str, Field(pattern=r"^SRC-\d{4}$")]
ReqId = Annotated[str, Field(pattern=r"^REQ-\d{4}$")]
ApproachId = Annotated[str, Field(pattern=r"^APP-\d{3}$")]
RiskId = Annotated[str, Field(pattern=r"^RSK-\d{3}$")]
QuarantineId = Annotated[str, Field(pattern=r"^QR-\d{4}$")]
HazardId = Annotated[str, Field(pattern=r"^HZ-\d{3}$")]
LintId = Annotated[str, Field(pattern=r"^LF-\d{4}$")]
FlagId = Annotated[str, Field(pattern=r"^CF-\d{3}$")]
GroupId = Annotated[str, Field(pattern=r"^RG-\d{3}$")]
DiscrepancyId = Annotated[str, Field(pattern=r"^DS-\d{3}$")]
QuestionId = Annotated[str, Field(pattern=r"^CQ-\d{3}$")]

QUOTE_MAX_CHARS = 300
DEFINITION_MAX_CHARS = 300
PROFILE_FIELD_MAX_CHARS = 200
FIRST_TEXT_MAX_CHARS = 400
CUE_MATCHES_MAX = 5


def _at_most_words(limit: int) -> Callable[[str], str]:
    def check(value: str) -> str:
        if len(value.split()) > limit:
            raise ValueError(f"at most {limit} words")
        return value

    return check


Words12 = Annotated[str, AfterValidator(_at_most_words(12))]
Words20 = Annotated[str, AfterValidator(_at_most_words(20))]
Words25 = Annotated[str, AfterValidator(_at_most_words(25))]
Words30 = Annotated[str, AfterValidator(_at_most_words(30))]
Words50 = Annotated[str, AfterValidator(_at_most_words(50))]


class Record(BaseModel):
    """Base for stored records: unknown fields are errors, so drift fails loudly."""

    model_config = ConfigDict(extra="forbid")


class Facing(BaseModel):
    """Base for what an LLM sees or returns. Extra keys from the model are ignored."""

    model_config = ConfigDict(extra="ignore")


# --- Stored records of v0.0 ----------------------------------------------------------


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
    page: int | None = Field(default=None, ge=1)  # 1-based; None for XLSX
    small_print: bool = False
    suspect: bool = False  # matches an instruction pattern of config/ingest.yaml

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
    zone: Zone | None = None
    page: int | None = Field(default=None, ge=1)
    small_print: bool = False
    repaired: bool = False  # passed only after its quote or number repair

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


class DocumentHash(Record):
    doc_id: str
    file: str
    sha256: str


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
    documents: list[DocumentHash] = Field(default_factory=list)
    data_class: DataClass = "synthetic"  # D-05
    refused_destinations: list[str] = Field(default_factory=list)  # D-05


# --- Model-facing requests and responses ----------------------------------------------


class PassageView(Facing):
    src_id: str
    section_path: str
    text: str
    lead_in: str | None = None
    zone: Zone | None = None  # the section's zone from triage, a hint (step 11)
    cues: list[CueKind] = Field(default_factory=list)  # hints, never a filter (ADR-017)
    small_print: bool = False
    suspect: bool = False  # reads like an instruction to a model; classify it like any text


class ContextPassageView(Facing):
    """A neighbor the model may read but never cite."""

    src_id: str
    text: str


class TermView(Facing):
    term: str
    definition: str


class ExtractBatch(Facing):
    batch_id: str
    passages: list[PassageView]
    context: list[ContextPassageView] = Field(default_factory=list)  # read, never cited
    terms: list[TermView] = Field(default_factory=list)


class ExtractItem(Facing):
    """One obligation. `settle` enforces the 3-id and 300-character limits per item, so one
    long quote never fails its whole pack (ADR-024)."""

    src_ids: list[str] = Field(min_length=1)
    quote: str
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


# Triage (step 10)


class SectionView(Facing):
    section_path: str
    doc_id: str
    role: DocRole
    first_text: str = Field(max_length=FIRST_TEXT_MAX_CHARS)  # the first two passages
    passages: int = Field(ge=0)
    cue_counts: dict[CueKind, int] = Field(default_factory=dict)


class TriageInput(Facing):
    sections: list[SectionView]


class ZoneAssignment(Facing):
    section_path: str
    doc_id: str
    zone: Zone
    confidence: float = Field(ge=0, le=1)
    reason: Words25


class RfpProfile(Facing):
    """The RFP's own words for each field, at most 200 characters, or `not_stated`."""

    buyer: str = Field(default="not_stated", max_length=PROFILE_FIELD_MAX_CHARS)
    procurement: str = Field(default="not_stated", max_length=PROFILE_FIELD_MAX_CHARS)
    submission_deadline: str = Field(default="not_stated", max_length=PROFILE_FIELD_MAX_CHARS)
    submission_format: str = Field(default="not_stated", max_length=PROFILE_FIELD_MAX_CHARS)
    evaluation_method: str = Field(default="not_stated", max_length=PROFILE_FIELD_MAX_CHARS)
    contract_length: str = Field(default="not_stated", max_length=PROFILE_FIELD_MAX_CHARS)


class HazardProposal(Facing):
    kind: HazardKind
    src_ids: list[str] = Field(min_length=1, max_length=3)
    summary: Words30


class TriageResult(Facing):
    zones: list[ZoneAssignment]
    profile: RfpProfile
    hazards: list[HazardProposal] = Field(default_factory=list)


# Consolidate (step 14)


class ClusterMember(Facing):
    id: str
    statement: str
    modality: Modality
    disposition: Disposition
    quote: str
    doc_id: str
    section_path: str


class PrecedenceEntry(Facing):
    doc_id: str
    role: DocRole
    precedence: int = Field(ge=1)  # 1 is highest


class ClusterLintView(Facing):
    id: str
    kind: LintKind
    requirement_id: str
    match: str


class ClusterTask(Facing):
    cluster_id: str
    members: list[ClusterMember]
    context: list[ClusterMember] = Field(default_factory=list)  # linked clusters, read-only
    precedence: list[PrecedenceEntry] = Field(default_factory=list)
    precedence_clause: list[ContextPassageView] = Field(default_factory=list)
    lint: list[ClusterLintView] = Field(default_factory=list)


class DuplicatePair(Facing):
    requirement_id: str
    duplicate_of: str


class DiscrepancyProposal(Facing):
    requirement_ids: list[str] = Field(min_length=2)
    kind: DiscrepancyKind
    state: DiscrepancyState
    description: Words50
    resolved_by: str | None = None  # the precedence rule in the RFP's words


class QuestionProposal(Facing):
    text: Words50
    requirement_ids: list[str] = Field(default_factory=list)
    lint_finding_ids: list[str] = Field(default_factory=list)
    reason: Words20

    @field_validator("text")
    @classmethod
    def _is_a_question(cls, value: str) -> str:
        if not value.rstrip().endswith("?"):
            raise ValueError("a question ends with a question mark")
        return value


class ReferenceLink(Facing):
    requirement_id: str
    target: str  # as written
    resolved_ids: list[str] = Field(default_factory=list)


class ConsolidationResult(Facing):
    topic: Words12
    duplicates: list[DuplicatePair] = Field(default_factory=list)
    discrepancies: list[DiscrepancyProposal] = Field(default_factory=list)
    questions: list[QuestionProposal] = Field(default_factory=list)
    references: list[ReferenceLink] = Field(default_factory=list)


# --- Stored records of Iteration 1 ---------------------------------------------------

# Guard (step 6)


class QuarantineRecord(Record):
    id: QuarantineId
    doc_id: str
    file: str
    kind: QuarantineKind
    location: str  # for a PDF, "page 3, box (72.0, 410.2, 301.5, 418.0)"
    text: str
    text_sha256: str
    chars: int = Field(ge=0)


class GuardFile(Record):
    file: str
    doc_id: str
    sha256: str
    format: DocFormat | None = None  # None for a refused file of unknown format
    bytes: int = Field(ge=0)
    pages: int | None = None  # None for XLSX
    scanned: bool = False
    accepted: bool
    reason: str | None = None


class GuardReport(Record):
    files: list[GuardFile]
    quarantined: int = Field(ge=0)
    small_print_chars: int = Field(ge=0)
    limits: dict[str, int]  # the limits applied


# Ingest (step 7)


class DocumentEntry(Record):
    doc_id: str
    file: str
    sha256: str
    format: DocFormat
    role: DocRole
    title: str
    precedence: int = Field(ge=1)  # 1 is highest
    pages: int | None = None
    sanitized: bool = False
    parser: Parser


class ControlRegister(Record):
    package: str  # folder or file name
    documents: list[DocumentEntry]
    precedence_source: PrecedenceSource


# Candidates (step 8)


class CueHit(Record):
    src_id: SrcId
    kinds: list[CueKind] = Field(default_factory=list)  # empty for a passage with no cue
    matches: list[str] = Field(default_factory=list, max_length=CUE_MATCHES_MAX)


class DefinedTerm(Record):
    term: str
    definition: str = Field(max_length=DEFINITION_MAX_CHARS)  # copied from the passage
    src_id: SrcId


# Triage (step 10)


class ZoneRecord(Record):
    section_path: str
    doc_id: str
    zone: Zone
    confidence: float = Field(ge=0, le=1)
    reason: str
    source: ZoneSource


class TriageRecord(Record):
    """The stored form of `triage.json`."""

    zones: list[ZoneRecord]
    profile: RfpProfile
    fallback_sections: int = Field(ge=0)


class SubmissionHazard(Record):
    id: HazardId
    kind: HazardKind
    src_ids: list[SrcId] = Field(min_length=1, max_length=3)
    summary: str
    requirement_ids: list[ReqId] = Field(default_factory=list)  # filled by `verify`


# Verify and coverage (steps 11 and 12)


class CandidateRow(Record):
    src_id: SrcId
    doc_id: str
    zone: Zone | None = None  # None under B0
    cues: list[CueKind] = Field(default_factory=list)
    dispositions: list[LedgerDisposition] = Field(min_length=1)
    requirement_ids: list[ReqId] = Field(default_factory=list)
    reasons: list[str]  # one per entry of dispositions
    round: int = Field(ge=0)  # the coverage round that settled the row

    @model_validator(mode="after")
    def _one_reason_per_disposition(self) -> "CandidateRow":
        if len(self.reasons) != len(self.dispositions):
            raise ValueError("reasons holds one string per entry of dispositions")
        return self


class CoverageRound(Record):
    round: int = Field(ge=1)
    gaps: list[SrcId] = Field(default_factory=list)
    resolved: list[SrcId] = Field(default_factory=list)


class CoverageReport(Record):
    rounds: list[CoverageRound] = Field(default_factory=list)
    stop_reason: StopReason
    passages: int = Field(ge=0)
    with_disposition: int = Field(ge=0)
    unaccounted: int = Field(ge=0)
    rejected_only: int = Field(ge=0)


# Lint (step 13)


class LintFinding(Record):
    id: LintId
    rule: str
    kind: LintKind
    requirement_id: ReqId
    src_id: SrcId
    match: str
    severity: Severity


class ContractFlag(Record):
    id: FlagId
    category: ContractCategory
    src_id: SrcId
    quote: str = Field(max_length=QUOTE_MAX_CHARS)  # the passage text
    why: str  # rule id and matched words
    status: Literal["NEEDS_LEGAL_REVIEW"] = "NEEDS_LEGAL_REVIEW"


# Consolidate (step 14)


class RequirementGroup(Record):
    id: GroupId
    member_ids: list[ReqId] = Field(min_length=1)
    context_ids: list[ReqId] = Field(default_factory=list)
    topic: str
    duplicates: list[DuplicatePair] = Field(default_factory=list)
    references: list[ReferenceLink] = Field(default_factory=list)
    discrepancy_ids: list[DiscrepancyId] = Field(default_factory=list)
    question_ids: list[QuestionId] = Field(default_factory=list)
    llm: bool  # false for a singleton


class Discrepancy(Record):
    id: DiscrepancyId
    group_id: GroupId
    requirement_ids: list[ReqId] = Field(min_length=2)
    kind: DiscrepancyKind
    state: DiscrepancyState
    description: str
    resolved_by: str | None = None


class ClarificationQuestion(Record):
    id: QuestionId
    group_id: GroupId
    text: str
    requirement_ids: list[ReqId] = Field(default_factory=list)
    src_ids: list[SrcId] = Field(default_factory=list)  # resolved by code
    lint_finding_ids: list[LintId] = Field(default_factory=list)
    origin: QuestionOrigin


# Context (step 9)


class LayerTokens(Record):
    rules: int = Field(default=0, ge=0)
    examples: int = Field(default=0, ge=0)
    evidence: int = Field(default=0, ge=0)
    task: int = Field(default=0, ge=0)


class ContextManifest(Record):
    node: str
    call_id: str
    included_src_ids: list[SrcId] = Field(default_factory=list)
    context_src_ids: list[SrcId] = Field(default_factory=list)
    terms: list[str] = Field(default_factory=list)
    dropped_src_ids: list[SrcId] = Field(default_factory=list)  # always empty: overflow splits
    tokens_by_layer: LayerTokens = Field(default_factory=LayerTokens)
    budget_tokens: int = Field(ge=1)
    utilization: float = Field(ge=0)


class ContextPack(Record):
    """What one LLM call sees. Built in code, never stored as a file."""

    call_id: str
    passages: list[PassageView]
    context: list[ContextPassageView] = Field(default_factory=list)
    terms: list[TermView] = Field(default_factory=list)
    manifest: ContextManifest
