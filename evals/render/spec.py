"""The corpus spec format: one YAML file per RFP package, holding its text and its gold labels.

A spec describes one package: one or more documents, each a PDF, DOCX or XLSX, with the
labeled clauses, the traps and the personal data planted in them, and the seeds a run should
find. Gold is written only here: `evals/render/gold.py` generates the gold file from the spec,
and `evals/render/package.py` renders the input files. Producer code never reads a spec.
"""

from pathlib import Path
from typing import Annotated, Literal, NamedTuple

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from bidwright.schemas import ContractCategory, DomainKind, FactorStatus, LintKind, Modality, Zone

REPO_ROOT = Path(__file__).resolve().parents[2]
CORPUS_DIR = REPO_ROOT / "evals" / "corpus"

Format = Literal["pdf", "docx", "xlsx"]
Role = Literal["main", "annex", "addendum", "form"]
GoldKind = Literal["requirement", "background", "not_binding", "out_of_scope"]
Implicit = Literal[
    "passive_predicate",
    "table_cell",
    "declarative_instruction",
    "condition",
    "reserved_right",
    "cross_reference",
    "definition",
]
Layer = Literal[
    "visible",
    "small_print",
    "pdf_invisible",
    "pdf_background_color",
    "pdf_tiny_font",
    "pdf_off_page",
    "docx_hidden_run",
    "docx_deleted_revision",
    "docx_comment",
    "xlsx_hidden_sheet",
    "xlsx_very_hidden_sheet",
    "xlsx_hidden_format",
    "xlsx_comment",
]
SheetState = Literal["visible", "hidden", "veryHidden"]
PersonalCategory = Literal["PERSON", "EMAIL", "PHONE"]

VISIBLE_LAYERS = frozenset({"visible", "small_print"})
HIDDEN_LAYERS: dict[str, frozenset[str]] = {
    "pdf": frozenset({"pdf_invisible", "pdf_background_color", "pdf_tiny_font", "pdf_off_page"}),
    "docx": frozenset({"docx_hidden_run", "docx_deleted_revision", "docx_comment"}),
    "xlsx": frozenset(
        {"xlsx_hidden_sheet", "xlsx_very_hidden_sheet", "xlsx_hidden_format", "xlsx_comment"}
    ),
}
# The sheet state a sheet-level trap needs: a hidden-sheet trap sits in a hidden sheet, and
# a hidden-format or comment trap in a visible one.
SHEET_STATE_FOR_LAYER = {
    "visible": "visible",
    "small_print": "visible",
    "xlsx_hidden_sheet": "hidden",
    "xlsx_very_hidden_sheet": "veryHidden",
    "xlsx_hidden_format": "visible",
    "xlsx_comment": "visible",
}
KIND_PREFIX = {"requirement": "GR", "background": "GB", "not_binding": "GN", "out_of_scope": "GO"}
KIND_DISPOSITION = {
    "background": "BACKGROUND",
    "not_binding": "NOT_BINDING",
    "out_of_scope": "OUT_OF_SCOPE",
}


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Gold(Strict):
    kind: GoldKind
    modality: Modality | None = None
    mandatory: bool | None = None
    hazard: bool = False
    zone: Zone | None = None
    implicit: Implicit | None = None
    tags: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _labels_fit_the_kind(self) -> "Gold":
        if self.kind == "requirement":
            if self.modality is None or self.mandatory is None:
                raise ValueError("a requirement needs its modality and mandatory labels")
        elif self.mandatory or self.hazard:
            raise ValueError(f"a {self.kind} clause is never mandatory or a hazard")
        return self

    @property
    def disposition(self) -> str:
        if self.kind == "requirement":
            return "BINDING" if self.mandatory else "OPTIONAL"
        return KIND_DISPOSITION[self.kind]


class Clause(Strict):
    id: str = Field(pattern=r"^G[RBNO]-\d{4}$")
    text: str = Field(min_length=1)
    gold: Gold
    layer: Layer = "visible"

    @model_validator(mode="after")
    def _prefix_matches_kind(self) -> "Clause":
        expected = KIND_PREFIX[self.gold.kind]
        if not self.id.startswith(expected):
            raise ValueError(f"{self.id}: a {self.gold.kind} id starts with {expected}")
        return self


class PersonalDatum(Strict):
    id: str = Field(pattern=r"^PD-\d{2}$")
    value: str = Field(min_length=1)
    category: PersonalCategory


class Text(Strict):
    text: str = Field(min_length=1)
    layer: Layer = "visible"
    personal_data: list[PersonalDatum] = Field(default_factory=list)

    @model_validator(mode="after")
    def _personal_data_occur_in_the_text(self) -> "Text":
        for datum in self.personal_data:
            if datum.value not in self.text:
                raise ValueError(f"{datum.id}: the value does not occur in the text")
        return self


class Trap(Strict):
    id: str = Field(pattern=r"^TR-\d{2}$")
    layer: Layer
    marker: str = Field(min_length=1)
    action: str = Field(min_length=1)
    text: str = Field(min_length=1)

    @model_validator(mode="after")
    def _text_holds_the_marker(self) -> "Trap":
        if self.marker not in self.text:
            raise ValueError(f"{self.id}: the text does not hold the marker")
        return self


class TrapBlock(Strict):
    trap: Trap


class Para(Strict):
    """Narrative sentences and clauses joined into one paragraph, in order."""

    para: list[str | Clause] = Field(min_length=1)

    @model_validator(mode="after")
    def _parts_are_visible(self) -> "Para":
        for part in self.para:
            if isinstance(part, Clause) and part.layer != "visible":
                raise ValueError(f"{part.id}: a clause inside a paragraph is visible")
        return self


class ListSpec(Strict):
    lead_in: str
    items: list[Clause] = Field(min_length=1)


class ListBlock(Strict):
    list: ListSpec


class TableSpec(Strict):
    """A table in a PDF or DOCX. A clause in a cell is visible or small print, and a
    requirement there is labeled `implicit: table_cell`."""

    header: list[list[str]] = Field(min_length=1)  # one or more header rows
    rows: list[list[str | Clause]] = Field(default_factory=list)

    @model_validator(mode="after")
    def _clause_cells(self) -> "TableSpec":
        for row in self.rows:
            for cell in row:
                if not isinstance(cell, Clause):
                    continue
                if cell.layer not in VISIBLE_LAYERS:
                    raise ValueError(
                        f"{cell.id}: a clause in a table cell is visible or small print"
                    )
                if cell.gold.kind == "requirement" and cell.gold.implicit != "table_cell":
                    raise ValueError(
                        f"{cell.id}: a requirement in a table cell is implicit: table_cell"
                    )
        return self


class TableBlock(Strict):
    table: TableSpec


Block = Clause | Text | Para | ListBlock | TableBlock | TrapBlock


class Layout(Strict):
    columns: Literal[1, 2] = 1
    font_size: float = Field(default=10, gt=0)


class Section(Strict):
    heading: str
    level: Literal[1, 2] = 1
    layout: Layout = Field(default_factory=Layout)
    page_break_before: bool = False
    blocks: list[Block] = Field(default_factory=list)


class Cell(Strict):
    """A spreadsheet cell with a number format or a comment."""

    text: str
    format: str | None = None
    comment: str | None = None


class Sheet(Strict):
    """A worksheet. A clause or trap in it uses a layer whose sheet state matches the sheet's:
    text in a hidden sheet is `xlsx_hidden_sheet` or `xlsx_very_hidden_sheet`, and a visible
    sheet holds visible text, small print, `;;;` cells and comments."""

    name: str = Field(min_length=1, max_length=31)
    state: SheetState = "visible"
    header: list[str] | None = None
    rows: list[list[str | Clause | Cell]] = Field(default_factory=list)
    trap: Trap | None = None

    @model_validator(mode="after")
    def _layers_fit_the_sheet(self) -> "Sheet":
        owners = [(self.trap.id, self.trap.layer)] if self.trap is not None else []
        owners += [(c.id, c.layer) for row in self.rows for c in row if isinstance(c, Clause)]
        for owner, layer in owners:
            wanted = SHEET_STATE_FOR_LAYER.get(layer)
            if wanted is None:
                raise ValueError(f"{owner}: a sheet cannot hold the layer {layer}")
            if wanted != self.state:
                raise ValueError(f"{owner}: {layer} needs a {wanted} sheet, not {self.state}")
        return self


class Document(Strict):
    doc_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*$")
    file: str = Field(min_length=1)
    format: Format
    role: Role
    precedence: int = Field(ge=1)  # 1 is highest
    title: str
    subtitle: list[str] = Field(default_factory=list)
    notice: str = ""
    header: str = ""
    sections: list[Section] = Field(default_factory=list)
    sheets: list[Sheet] = Field(default_factory=list)

    @model_validator(mode="after")
    def _parts_fit_the_format(self) -> "Document":
        if self.format == "xlsx":
            if self.sections or not self.sheets:
                raise ValueError(f"{self.doc_id}: an XLSX document has sheets and no sections")
        elif self.sheets or not self.sections:
            raise ValueError(f"{self.doc_id}: a {self.format} document has sections and no sheets")
        if not self.file.lower().endswith(f".{self.format}"):
            raise ValueError(f"{self.doc_id}: {self.file} is not a .{self.format} file")
        allowed = VISIBLE_LAYERS | HIDDEN_LAYERS[self.format]
        for owner, layer in self.layers():
            if layer not in allowed:
                raise ValueError(
                    f"{self.doc_id}: {owner} uses {layer}, which {self.format} cannot hold"
                )
        return self

    def layers(self) -> list[tuple[str, str]]:
        """Every (owner, layer) pair in the document, for the format check."""
        found: list[tuple[str, str]] = []
        for section in self.sections:
            for block in section.blocks:
                if isinstance(block, Clause):
                    found.append((block.id, block.layer))
                elif isinstance(block, Text):
                    found.append((f"text in {section.heading}", block.layer))
                elif isinstance(block, TrapBlock):
                    found.append((block.trap.id, block.trap.layer))
                elif isinstance(block, ListBlock):
                    found += [(item.id, item.layer) for item in block.list.items]
                elif isinstance(block, TableBlock):
                    for row in block.table.rows:
                        found += [(c.id, c.layer) for c in row if isinstance(c, Clause)]
        for sheet in self.sheets:
            if sheet.trap is not None:
                found.append((sheet.trap.id, sheet.trap.layer))
            for row in sheet.rows:
                found += [(c.id, c.layer) for c in row if isinstance(c, Clause)]
        return found


class RiskSeed(Strict):
    id: str = Field(pattern=r"^RS-\d{2}$")
    type: Literal["risk"]
    note: str
    anchors: list[str] = Field(min_length=1)
    terms: list[list[str]] = Field(min_length=1)


class GapSeed(Strict):
    id: str = Field(pattern=r"^GS-\d{2}$")
    type: Literal["gap"]
    capability: str
    absent_terms: list[str] = Field(min_length=1)
    anchors: list[str] = Field(min_length=1)


class ClarificationSeed(Strict):
    id: str = Field(pattern=r"^CS-\d{2}$")
    type: Literal["clarification"]
    anchors: list[str] = Field(min_length=1)
    about: str


class DiscrepancySeed(Strict):
    id: str = Field(pattern=r"^DQ-\d{2}$")
    type: Literal["discrepancy"]
    anchors: list[str] = Field(min_length=2, max_length=2)
    about: str


class ContractTermSeed(Strict):
    id: str = Field(pattern=r"^CT-\d{2}$")
    type: Literal["contract_term"]
    category: ContractCategory
    anchors: list[str] = Field(min_length=1)


class LintSeed(Strict):
    id: str = Field(pattern=r"^LS-\d{2}$")
    type: Literal["lint"]
    lint_kind: LintKind
    anchors: list[str] = Field(min_length=1)


class DuplicateSeed(Strict):
    id: str = Field(pattern=r"^DP-\d{2}$")
    type: Literal["duplicate"]
    anchors: list[str] = Field(min_length=2, max_length=2)


class FactorSeed(Strict):
    """One row of an RFP's evaluation table (gold v3, Iteration 2): what `brief` must copy
    exactly. It anchors to no clause, so it names its document."""

    id: str = Field(pattern=r"^FS-\d{2}$")
    type: Literal["factor"]
    doc_id: str
    name: str = Field(min_length=1)
    weight: str = Field(min_length=1)
    status: FactorStatus


class DomainSeed(Strict):
    """A pattern, standard or pitfall of the RFP's domain that the RFP never states (gold v3,
    Iteration 2), from a page of a standards body or a public body read directly. Each inner
    list of `terms` holds synonyms; scored from Iteration 3."""

    id: str = Field(pattern=r"^DM-\d{2}$")
    type: Literal["domain"]
    doc_id: str
    category: DomainKind
    terms: list[list[str]] = Field(min_length=1)
    source: str = Field(pattern=r"^https://")


Seed = Annotated[
    RiskSeed
    | GapSeed
    | ClarificationSeed
    | DiscrepancySeed
    | ContractTermSeed
    | LintSeed
    | DuplicateSeed
    | FactorSeed
    | DomainSeed,
    Field(discriminator="type"),
]


class ClauseAt(NamedTuple):
    clause: Clause
    document: Document
    where: str  # the section heading, or the sheet name
    lead_in: str | None


class TrapAt(NamedTuple):
    trap: Trap
    document: Document


class DatumAt(NamedTuple):
    datum: PersonalDatum
    document: Document
    text: str


def _document_clauses(document: Document) -> list[ClauseAt]:
    found: list[ClauseAt] = []
    for section in document.sections:
        for block in section.blocks:
            if isinstance(block, Clause):
                found.append(ClauseAt(block, document, section.heading, None))
            elif isinstance(block, Para):
                found += [
                    ClauseAt(part, document, section.heading, None)
                    for part in block.para
                    if isinstance(part, Clause)
                ]
            elif isinstance(block, ListBlock):
                found += [
                    ClauseAt(item, document, section.heading, block.list.lead_in)
                    for item in block.list.items
                ]
            elif isinstance(block, TableBlock):
                for row in block.table.rows:
                    found += [
                        ClauseAt(cell, document, section.heading, None)
                        for cell in row
                        if isinstance(cell, Clause)
                    ]
    for sheet in document.sheets:
        for row in sheet.rows:
            found += [
                ClauseAt(cell, document, sheet.name, None)
                for cell in row
                if isinstance(cell, Clause)
            ]
    return found


class Spec(Strict):
    corpus: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*$")
    gold_version: int = Field(ge=1)
    package: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*$")  # the folder under inputs/
    documents: list[Document] = Field(min_length=1)
    seeds: list[Seed] = Field(default_factory=list)

    @model_validator(mode="after")
    def _ids_are_unique_and_anchors_exist(self) -> "Spec":
        for label, ids in (
            ("clause", [at.clause.id for at in self.clauses()]),
            ("trap", [at.trap.id for at in self.traps()]),
            ("personal datum", [at.datum.id for at in self.personal_data()]),
            ("seed", [seed.id for seed in self.seeds]),
            ("document", [document.doc_id for document in self.documents]),
            ("file", [document.file for document in self.documents]),
        ):
            duplicates = sorted({i for i in ids if ids.count(i) > 1})
            if duplicates:
                raise ValueError(f"duplicate {label} ids: {duplicates}")
        known = {at.clause.id for at in self.clauses()}
        documents = {document.doc_id for document in self.documents}
        for seed in self.seeds:
            if isinstance(seed, FactorSeed | DomainSeed):
                if seed.doc_id not in documents:
                    raise ValueError(f"{seed.id} names an unknown document: {seed.doc_id}")
                continue
            missing = sorted(set(seed.anchors) - known)
            if missing:
                raise ValueError(f"{seed.id} anchors unknown clauses: {missing}")
        return self

    def clauses(self, document: Document | None = None) -> list[ClauseAt]:
        """Every labeled clause in reading order, with its document, section and lead-in."""
        documents = [document] if document is not None else self.documents
        return [at for doc in documents for at in _document_clauses(doc)]

    def traps(self, document: Document | None = None) -> list[TrapAt]:
        found: list[TrapAt] = []
        for doc in [document] if document is not None else self.documents:
            for section in doc.sections:
                found += [
                    TrapAt(block.trap, doc)
                    for block in section.blocks
                    if isinstance(block, TrapBlock)
                ]
            found += [TrapAt(sheet.trap, doc) for sheet in doc.sheets if sheet.trap is not None]
        return found

    def personal_data(self, document: Document | None = None) -> list[DatumAt]:
        found: list[DatumAt] = []
        for doc in [document] if document is not None else self.documents:
            for section in doc.sections:
                for block in section.blocks:
                    if isinstance(block, Text):
                        found += [DatumAt(d, doc, block.text) for d in block.personal_data]
        return found

    def document_of(self, clause_id: str) -> Document:
        for at in self.clauses():
            if at.clause.id == clause_id:
                return at.document
        raise KeyError(clause_id)


def load_spec(corpus: str, root: Path = CORPUS_DIR) -> Spec:
    path = root / corpus / "spec.yaml"
    return Spec.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
