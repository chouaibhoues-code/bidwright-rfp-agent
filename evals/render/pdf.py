"""Render a corpus document to PDF with ReportLab.

Output is reproducible: invariant mode fixes the dates and document id, so the same spec
always gives the same bytes and the hash in `inputs/CORPUS.sha256` stays valid. Text uses the
standard Helvetica fonts, without hyphenation or ligatures, so every clause can be found again
in the extracted text.

Iteration 1 adds two-column sections (a page template with two frames), tables with stacked
header rows, small print at 5 pt, and the four hidden layers, each written by a zero-height
flowable after the paragraph that precedes it: text in render mode 3, white text on the white
page, 1 pt text, and text whose origin lies 100 pt beyond the page's right edge.
"""

from collections.abc import Callable
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import (
    BaseDocTemplate,
    Flowable,
    Frame,
    NextPageTemplate,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

from evals.render.spec import (
    Clause,
    Document,
    ListBlock,
    Para,
    Section,
    TableBlock,
    Text,
    TrapBlock,
)

MARGIN = 2.5 * cm
PAGE_WIDTH, PAGE_HEIGHT = A4
GUTTER = 0.8 * cm
FRAME_PADDING = 6  # ReportLab's default on each side of a frame
SMALL_PRINT_PT = 5
TINY_PT = 1
HIDDEN_PT = 9
OFF_PAGE_X = PAGE_WIDTH + 100
FIXED_COLUMN = 2.8 * cm  # a table column that holds no clause
AUTHOR = "Bidwright synthetic corpus"


class HiddenText(Flowable):
    """Text a reader of the page never sees, written with one hidden layer's mechanism.

    The flowable has no height, so it changes nothing in the visible layout: it draws at the
    point where the story stands, right after the paragraph before it.
    """

    def __init__(self, text: str, layer: str) -> None:
        super().__init__()
        self.text = text
        self.layer = layer

    def wrap(self, aW: float, aH: float) -> tuple[float, float]:
        return 0, 0

    def draw(self) -> None:
        canvas = self.canv
        text = canvas.beginText()
        text.setFont("Helvetica", TINY_PT if self.layer == "pdf_tiny_font" else HIDDEN_PT)
        if self.layer == "pdf_invisible":
            text.setTextRenderMode(3)
        elif self.layer == "pdf_background_color":
            text.setFillColorRGB(1, 1, 1)
        elif self.layer == "pdf_off_page":
            x, _ = canvas.absolutePosition(0, 0)
            text.setTextOrigin(OFF_PAGE_X - x, 0)
        text.textLine(self.text)
        canvas.drawText(text)


def _styles(font_size: float) -> dict[str, ParagraphStyle]:
    body = ParagraphStyle(
        "Body", fontName="Helvetica", fontSize=font_size, leading=font_size * 1.35, spaceAfter=6
    )
    item = ParagraphStyle("Item", parent=body, leftIndent=18, spaceAfter=3)
    small = ParagraphStyle(
        "Small", parent=body, fontSize=SMALL_PRINT_PT, leading=SMALL_PRINT_PT * 1.3, spaceAfter=3
    )
    cell = ParagraphStyle("Cell", parent=body, leading=font_size * 1.25, spaceAfter=0)
    return {
        "body": body,
        "item": item,
        "small": small,
        "item_small": ParagraphStyle(
            "ItemSmall", parent=item, fontSize=SMALL_PRINT_PT, leading=6.5
        ),
        "cell": cell,
        "cell_small": ParagraphStyle(
            "CellSmall", parent=cell, fontSize=SMALL_PRINT_PT, leading=SMALL_PRINT_PT * 1.3
        ),
        "h1": ParagraphStyle(
            "H1",
            parent=body,
            fontName="Helvetica-Bold",
            fontSize=font_size * 1.3,
            leading=font_size * 1.7,
            spaceBefore=10,
        ),
        "h2": ParagraphStyle(
            "H2",
            parent=body,
            fontName="Helvetica-Bold",
            fontSize=font_size * 1.2,
            leading=font_size * 1.6,
            spaceBefore=6,
        ),
        "title": ParagraphStyle(
            "Title", parent=body, fontName="Helvetica-Bold", fontSize=20, leading=26
        ),
    }


def _text(text: str, layer: str, styles: dict[str, ParagraphStyle], style: str) -> Flowable:
    if layer == "visible":
        return Paragraph(escape(text), styles[style])
    if layer == "small_print":
        return Paragraph(escape(text), styles[f"{style}_small" if style != "body" else "small"])
    return HiddenText(text, layer)


def _table(block: TableBlock, font_size: float, styles: dict[str, ParagraphStyle], avail: float):
    spec = block.table
    columns = max(len(row) for row in [*spec.header, *spec.rows])
    clause_columns = {
        i for row in spec.rows for i, cell in enumerate(row) if isinstance(cell, Clause)
    }
    data: list[list[object]] = [list(row) for row in spec.header]
    for row in spec.rows:
        data.append(
            [
                Paragraph(
                    escape(cell.text),
                    styles["cell_small" if cell.layer == "small_print" else "cell"],
                )
                if isinstance(cell, Clause)
                else cell
                for cell in row
            ]
        )
    widths = None
    if clause_columns:
        rest = avail - FIXED_COLUMN * (columns - len(clause_columns))
        widths = [
            rest / len(clause_columns) if i in clause_columns else FIXED_COLUMN
            for i in range(columns)
        ]
    table = Table(data, colWidths=widths, hAlign="LEFT")
    commands = [
        ("FONTNAME", (0, 0), (-1, len(spec.header) - 1), "Helvetica-Bold"),
        ("FONTNAME", (0, len(spec.header)), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), font_size),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]
    if clause_columns:
        commands.append(("VALIGN", (0, 0), (-1, -1), "TOP"))
    table.setStyle(TableStyle(commands))
    return [table, Spacer(1, 6)]


def _section(section: Section, avail: float) -> list[Flowable]:
    styles = _styles(section.layout.font_size)
    story: list[Flowable] = [Paragraph(escape(section.heading), styles[f"h{section.level}"])]
    for block in section.blocks:
        if isinstance(block, Text | Clause):
            story.append(_text(block.text, block.layer, styles, "body"))
        elif isinstance(block, Para):
            text = " ".join(part if isinstance(part, str) else part.text for part in block.para)
            story.append(Paragraph(escape(text), styles["body"]))
        elif isinstance(block, ListBlock):
            story.append(Paragraph(escape(block.list.lead_in), styles["body"]))
            story += [_text(item.text, item.layer, styles, "item") for item in block.list.items]
        elif isinstance(block, TableBlock):
            story += _table(block, section.layout.font_size, styles, avail)
        elif isinstance(block, TrapBlock):
            story.append(_text(block.trap.text, block.trap.layer, styles, "body"))
    return story


def _page_decoration(header: str) -> Callable[[Canvas, BaseDocTemplate], None]:
    """The same header on every page, and a page number in the footer."""

    def draw(canvas: Canvas, doc: BaseDocTemplate) -> None:
        canvas.saveState()
        canvas.setFont("Helvetica", 8)
        canvas.drawString(MARGIN, PAGE_HEIGHT - 1.5 * cm, header)
        canvas.drawRightString(PAGE_WIDTH - MARGIN, 1.5 * cm, f"Page {doc.page}")
        canvas.restoreState()

    return draw


def render_pdf(document: Document, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = BaseDocTemplate(
        str(path),
        pagesize=A4,
        leftMargin=MARGIN,
        rightMargin=MARGIN,
        topMargin=MARGIN,
        bottomMargin=MARGIN,
        title=document.title,
        author=AUTHOR,
        subject=document.notice,
        creator="evals/render/pdf.py",
        invariant=1,
    )
    decorate = _page_decoration(document.header)
    column = (doc.width - GUTTER) / 2
    one = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="normal")
    left = Frame(doc.leftMargin, doc.bottomMargin, column, doc.height, id="left")
    right = Frame(
        doc.leftMargin + column + GUTTER, doc.bottomMargin, column, doc.height, id="right"
    )
    doc.addPageTemplates(
        [
            PageTemplate(id="one", frames=[one], onPage=decorate, pagesize=A4),
            PageTemplate(id="two", frames=[left, right], onPage=decorate, pagesize=A4),
        ]
    )
    styles = _styles(document.sections[0].layout.font_size)
    story: list[Flowable] = [Paragraph(escape(document.title), styles["title"])]
    story += [Paragraph(escape(line), styles["body"]) for line in document.subtitle]
    story += [Paragraph(escape(document.notice), styles["body"]), Spacer(1, 12)]
    columns = 1
    for section in document.sections:
        if section.layout.columns != columns:
            columns = section.layout.columns
            story += [NextPageTemplate("two" if columns == 2 else "one"), PageBreak()]
        elif section.page_break_before:
            story.append(PageBreak())
        avail = (column if columns == 2 else doc.width) - 2 * FRAME_PADDING
        story += _section(section, avail)
    doc.build(story)
