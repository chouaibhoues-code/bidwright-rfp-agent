"""Render a corpus document to DOCX with python-docx.

Headings, paragraphs, numbered lists and tables carry the visible text. The three hidden
layers use the mechanisms the guard must find: a hidden run (`w:vanish`), a comment, and a
tracked deletion written as raw WordprocessingML, which python-docx has no call for. The core
properties and every zip entry carry fixed dates, so two renders give identical bytes.
"""

from pathlib import Path

import docx
from docx.document import Document as DocxDocument
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Pt
from docx.text.paragraph import Paragraph

from evals.render.office import AUTHOR, FIXED_TIME, FIXED_TIME_NAIVE, freeze_zip
from evals.render.spec import (
    Block,
    Clause,
    Document,
    ListBlock,
    Para,
    TableBlock,
    Text,
    TrapBlock,
)

SMALL_PRINT = Pt(5)
REVISION_DATE = FIXED_TIME.strftime("%Y-%m-%dT%H:%M:%SZ")


class _Writer:
    def __init__(self, doc: DocxDocument) -> None:
        self.doc = doc
        self.revisions = 0
        self.anchor: Paragraph | None = None  # the last visible paragraph, for comments

    def heading(self, text: str, level: int) -> None:
        self.anchor = self.doc.add_heading(text, level=level)

    def paragraph(self, text: str, layer: str, style: str | None = None) -> None:
        if layer in ("visible", "small_print"):
            paragraph = self.doc.add_paragraph(style=style)
            run = paragraph.add_run(text)
            if layer == "small_print":
                run.font.size = SMALL_PRINT
            self.anchor = paragraph
        elif layer == "docx_hidden_run":
            run = self.doc.add_paragraph(style=style).add_run(text)
            run.font.hidden = True
        elif layer == "docx_deleted_revision":
            self._deleted(self.doc.add_paragraph(style=style), text)
        elif layer == "docx_comment":
            anchor = self.anchor if self.anchor is not None else self.doc.add_paragraph(" ")
            comment = self.doc.add_comment(anchor.runs, text=text, author=AUTHOR, initials="BC")
            comment._comment_elm.date = FIXED_TIME  # the only way to fix the comment's date
        else:
            raise ValueError(f"a DOCX cannot hold the layer {layer}")

    def _deleted(self, paragraph: Paragraph, text: str) -> None:
        """A tracked deletion: `w:del` around a run whose text sits in `w:delText`."""
        self.revisions += 1
        deleted = OxmlElement("w:del")
        deleted.set(qn("w:id"), str(self.revisions))
        deleted.set(qn("w:author"), AUTHOR)
        deleted.set(qn("w:date"), REVISION_DATE)
        run = OxmlElement("w:r")
        del_text = OxmlElement("w:delText")
        del_text.set(qn("xml:space"), "preserve")
        del_text.text = text
        run.append(del_text)
        deleted.append(run)
        paragraph._p.append(deleted)

    def table(self, block: TableBlock) -> None:
        spec = block.table
        columns = max(len(row) for row in [*spec.header, *spec.rows])
        table = self.doc.add_table(rows=0, cols=columns)
        table.style = "Table Grid"
        for header in spec.header:
            cells = table.add_row().cells
            for index, text in enumerate(header):
                cells[index].paragraphs[0].add_run(text).bold = True
        for row in spec.rows:
            cells = table.add_row().cells
            for index, cell in enumerate(row):
                text = cell.text if isinstance(cell, Clause) else cell
                run = cells[index].paragraphs[0].add_run(text)
                if isinstance(cell, Clause) and cell.layer == "small_print":
                    run.font.size = SMALL_PRINT

    def block(self, block: Block) -> None:
        if isinstance(block, Text | Clause):
            self.paragraph(block.text, block.layer)
        elif isinstance(block, Para):
            text = " ".join(part if isinstance(part, str) else part.text for part in block.para)
            self.paragraph(text, "visible")
        elif isinstance(block, ListBlock):
            self.paragraph(block.list.lead_in, "visible")
            for item in block.list.items:
                self.paragraph(item.text, item.layer, style="List Number")
        elif isinstance(block, TableBlock):
            self.table(block)
        elif isinstance(block, TrapBlock):
            self.paragraph(block.trap.text, block.trap.layer)


def render_docx(document: Document, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = docx.Document()
    properties = doc.core_properties
    properties.title = document.title
    properties.author = AUTHOR
    properties.subject = document.notice
    properties.created = FIXED_TIME_NAIVE
    properties.modified = FIXED_TIME_NAIVE
    properties.last_printed = FIXED_TIME_NAIVE
    properties.revision = 1
    if document.header:
        doc.sections[0].header.paragraphs[0].text = document.header
    writer = _Writer(doc)
    writer.heading(document.title, level=0)
    for line in document.subtitle:
        writer.paragraph(line, "visible")
    if document.notice:
        writer.paragraph(document.notice, "visible")
    for section in document.sections:
        if section.page_break_before:
            doc.add_page_break()
        writer.heading(section.heading, level=section.level)
        for block in section.blocks:
            writer.block(block)
    doc.save(str(path))
    freeze_zip(path)
