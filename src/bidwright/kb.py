"""The supplier knowledge base: capabilities, case studies, certifications and roles.

Four YAML files under `knowledge_base/capabilities/`, read with `yaml.safe_load` into strict
models. Ids are unique within the base, and every reference from a capability's evidence or a
case study's or role's capabilities resolves. In Iteration 1 only the tests read the base;
`decide` is its first reader, in Iteration 3.

`KnowledgeIndex` (Iteration 3, step 3) is an FTS5 index over every record, built once a run as
`kb.sqlite` in the run folder, with the tokenizer and query escaping of `search_rfp`'s index
(`retrieval.py`). A record's name is a capability's name, a case study's client and sector, a
certification's name and a role's title; its text is a capability's summary, a case study's
summary, a certification's name, holder and expiry, and a role's summary.
"""

import sqlite3
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Annotated, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from bidwright.retrieval import MAX_K, TOKENIZER, match_expression

KB_DIR = Path(__file__).resolve().parents[2] / "knowledge_base" / "capabilities"

CapabilityId = Annotated[str, Field(pattern=r"^CAP-\d{3}$")]
CaseStudyId = Annotated[str, Field(pattern=r"^CS-\d{3}$")]
CertificationId = Annotated[str, Field(pattern=r"^CERT-\d{3}$")]
RoleId = Annotated[str, Field(pattern=r"^ROLE-\d{3}$")]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Capability(Strict):
    id: CapabilityId
    name: str
    summary: str
    evidence: list[str] = Field(default_factory=list)  # case-study and certification ids
    tags: list[Literal["own", "partner"]] = Field(min_length=1)


class CaseStudy(Strict):
    id: CaseStudyId
    client: str
    sector: str
    year: int = Field(ge=2000, le=2100)
    summary: str
    capability_ids: list[CapabilityId] = Field(default_factory=list)


class Certification(Strict):
    id: CertificationId
    name: str
    holder: str
    valid_until: date


class Role(Strict):
    id: RoleId
    title: str
    summary: str
    capability_ids: list[CapabilityId] = Field(default_factory=list)


class KnowledgeBase(Strict):
    capabilities: list[Capability]
    case_studies: list[CaseStudy]
    certifications: list[Certification]
    roles: list[Role]

    @model_validator(mode="after")
    def _ids_are_unique_and_references_resolve(self) -> "KnowledgeBase":
        ids = [record.id for record in self.records()]
        duplicates = sorted({i for i in ids if ids.count(i) > 1})
        if duplicates:
            raise ValueError(f"duplicate knowledge-base ids: {duplicates}")
        capabilities = {c.id for c in self.capabilities}
        evidence = {c.id for c in self.case_studies} | {c.id for c in self.certifications}
        for capability in self.capabilities:
            missing = sorted(set(capability.evidence) - evidence)
            if missing:
                raise ValueError(f"{capability.id} cites unknown evidence: {missing}")
        for holder in [*self.case_studies, *self.roles]:
            missing = sorted(set(holder.capability_ids) - capabilities)
            if missing:
                raise ValueError(f"{holder.id} names unknown capabilities: {missing}")
        return self

    def records(self) -> list[Capability | CaseStudy | Certification | Role]:
        return [*self.capabilities, *self.case_studies, *self.certifications, *self.roles]

    def texts(self) -> list[str]:
        """Every piece of free text in the base, for checks on what it says."""
        found: list[str] = []
        for record in self.records():
            for value in record.model_dump().values():
                if isinstance(value, str):
                    found.append(value)
        return found


def _read(path: Path, key: str) -> list[object]:
    with path.open(encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    return data.get(key, [])


def load_kb(root: Path = KB_DIR) -> KnowledgeBase:
    return KnowledgeBase.model_validate(
        {
            "capabilities": _read(root / "capabilities.yaml", "capabilities"),
            "case_studies": _read(root / "case_studies.yaml", "case_studies"),
            "certifications": _read(root / "certifications.yaml", "certifications"),
            "roles": _read(root / "roles.yaml", "roles"),
        }
    )


# --- the index search_capabilities reads (Iteration 3, step 3) ---------------------------------

RecordKind = Literal["capability", "case_study", "certification", "role"]
INDEX_FILE = "kb.sqlite"
_SCHEMA = (
    "CREATE VIRTUAL TABLE records USING fts5("
    f"id UNINDEXED, kind UNINDEXED, name, text, tokenize = '{TOKENIZER}')"
)
# Column weights for bm25(): id and kind are unindexed; a name hit counts as a text hit.
_RANK = "bm25(records, 0.0, 0.0, 1.0, 1.0)"


@dataclass(frozen=True)
class KbHit:
    id: str
    kind: RecordKind
    name: str
    text: str
    score: float


def record_view(
    record: Capability | CaseStudy | Certification | Role,
) -> tuple[RecordKind, str, str]:
    """A record's kind, name and text, as the index and the assessor see them."""
    if isinstance(record, Capability):
        return "capability", record.name, record.summary
    if isinstance(record, CaseStudy):
        return "case_study", f"{record.client}, {record.sector}", record.summary
    if isinstance(record, Certification):
        held = f"{record.name}, held by {record.holder}, valid until {record.valid_until}"
        return "certification", record.name, held
    return "role", record.title, record.summary


class KnowledgeIndex:
    def __init__(self, path: Path) -> None:
        self.path = path

    @classmethod
    def build(cls, kb: KnowledgeBase, path: Path) -> "KnowledgeIndex":
        """A fresh index of every record of the knowledge base."""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.unlink(missing_ok=True)
        rows = [(record.id, *record_view(record)) for record in kb.records()]
        with sqlite3.connect(path) as db:
            db.execute(_SCHEMA)
            db.executemany("INSERT INTO records (id, kind, name, text) VALUES (?, ?, ?, ?)", rows)
        return cls(path)

    def search(self, query: str, k: int = 5) -> list[KbHit]:
        expression = match_expression(query)
        if not expression:
            return []
        db = sqlite3.connect(self.path)
        try:
            rows = db.execute(
                f"SELECT id, kind, name, text, {_RANK} FROM records"  # noqa: S608
                f" WHERE records MATCH ? ORDER BY {_RANK}, id LIMIT ?",
                (expression, max(1, min(k, MAX_K))),
            ).fetchall()
        finally:
            db.close()
        return [KbHit(i, kind, name, text, round(-rank, 4)) for i, kind, name, text, rank in rows]
