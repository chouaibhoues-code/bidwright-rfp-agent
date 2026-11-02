"""The corpus spec format: one YAML file per RFP, holding both its text and its gold labels."""

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

REPO_ROOT = Path(__file__).resolve().parents[2]
CORPUS_DIR = REPO_ROOT / "evals" / "corpus"


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Gold(Strict):
    kind: Literal["requirement", "background"]
    modality: Literal["shall", "must", "will", "should", "may", "none"] | None = None
    mandatory: bool | None = None
    hazard: bool = False
    zone: Literal["INSTRUCTION", "EVALUATION", "OBLIGATION", "ELIGIBILITY"] | None = None
    tags: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _requirements_are_fully_labeled(self) -> "Gold":
        if self.kind == "requirement" and (self.modality is None or self.mandatory is None):
            raise ValueError("a requirement needs its modality and mandatory labels")
        if self.kind == "background" and (self.mandatory or self.hazard):
            raise ValueError("a background clause is never mandatory or a hazard")
        return self


class Clause(Strict):
    id: str = Field(pattern=r"^G[RB]-\d{4}$")
    text: str
    gold: Gold

    @model_validator(mode="after")
    def _prefix_matches_kind(self) -> "Clause":
        expected = "GR" if self.gold.kind == "requirement" else "GB"
        if not self.id.startswith(expected):
            raise ValueError(f"{self.id}: a {self.gold.kind} id starts with {expected}")
        return self


class Text(Strict):
    text: str


class Para(Strict):
    """Narrative sentences and clauses joined into one paragraph, in order."""

    para: list[str | Clause] = Field(min_length=1)


class ListSpec(Strict):
    lead_in: str
    items: list[Clause] = Field(min_length=1)


class ListBlock(Strict):
    list: ListSpec


class TableSpec(Strict):
    header: list[str]
    rows: list[list[str]]


class TableBlock(Strict):
    table: TableSpec


Block = Clause | Text | Para | ListBlock | TableBlock


class Layout(Strict):
    columns: Literal[1] = 1
    font_size: float = Field(default=10, gt=0)


class Section(Strict):
    heading: str
    level: Literal[1, 2] = 1
    layout: Layout = Field(default_factory=Layout)
    page_break_before: bool = False
    blocks: list[Block] = Field(default_factory=list)


class Seed(Strict):
    id: str = Field(pattern=r"^RS-\d{2}$")
    type: Literal["risk"]
    note: str
    anchors: list[str] = Field(min_length=1)
    terms: list[list[str]] = Field(min_length=1)


class Spec(Strict):
    corpus: str
    doc_id: str
    output: str
    gold_version: int = Field(ge=1)
    title: str
    subtitle: list[str] = Field(default_factory=list)
    notice: str
    header: str
    sections: list[Section] = Field(min_length=1)
    seeds: list[Seed] = Field(default_factory=list)

    @model_validator(mode="after")
    def _ids_are_unique_and_anchors_exist(self) -> "Spec":
        ids = [clause.id for clause, _, _ in self.clauses()]
        duplicates = {i for i in ids if ids.count(i) > 1}
        if duplicates:
            raise ValueError(f"duplicate clause ids: {sorted(duplicates)}")
        for seed in self.seeds:
            missing = set(seed.anchors) - set(ids)
            if missing:
                raise ValueError(f"{seed.id} anchors unknown clauses: {sorted(missing)}")
        return self

    def clauses(self) -> list[tuple[Clause, Section, str | None]]:
        """Every labeled clause in reading order, with its section and any list lead-in."""
        found: list[tuple[Clause, Section, str | None]] = []
        for section in self.sections:
            for block in section.blocks:
                if isinstance(block, Clause):
                    found.append((block, section, None))
                elif isinstance(block, Para):
                    found += [
                        (part, section, None) for part in block.para if isinstance(part, Clause)
                    ]
                elif isinstance(block, ListBlock):
                    found += [(item, section, block.list.lead_in) for item in block.list.items]
        return found


def load_spec(corpus: str, root: Path = CORPUS_DIR) -> Spec:
    path = root / corpus / "spec.yaml"
    return Spec.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
