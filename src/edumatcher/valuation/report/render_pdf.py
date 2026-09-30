"""Report → a printable PDF (``--pdf``, and ``p`` in the report viewer).

Every number comes from the report's own blocks, or, for the charts, from the
Run the report was built from, so the PDF cannot disagree with the terminal or
the Markdown. What the PDF adds is print furniture: a cover, a contents page,
an executive summary, chapters with explanatory prose, charts, running
headers and footers, and a glossary.
"""

from __future__ import annotations

import os
import re
from collections.abc import Sequence
from datetime import date
from pathlib import Path
from typing import Any

import reportlab
from reportlab.graphics.shapes import Drawing
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, LETTER
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import (
    BaseDocTemplate,
    CondPageBreak,
    Flowable,
    Frame,
    KeepTogether,
    NextPageTemplate,
    PageBreak,
    PageTemplate,
)
from reportlab.platypus import Paragraph as P
from reportlab.platypus import Spacer
from reportlab.platypus import Table as RLTable
from reportlab.platypus import TableStyle
from reportlab.platypus.tableofcontents import TableOfContents

from edumatcher.cli_version import package_version
from edumatcher.valuation.glossary import GLOSSARY
from edumatcher.valuation.pipeline import Run
from edumatcher.valuation.report import pdf_charts
from edumatcher.valuation.report.build import (
    Bullets,
    Code,
    Paragraph,
    Report,
    Section,
    Table,
)

PAPER = {"a4": A4, "letter": LETTER}
MARGIN_X, MARGIN_TOP, MARGIN_BOTTOM = 22 * mm, 24 * mm, 22 * mm

INK = colors.HexColor("#1a1a1a")
MUTED = colors.HexColor("#5f6368")
RULE = colors.HexColor("#c8ccd2")
ZEBRA = colors.HexColor("#f5f7f9")
NAVY = colors.HexColor("#1f3a5f")
HEAD_BG = colors.HexColor("#e9eef5")
HIGHLIGHT = colors.HexColor("#fff4d6")
VERDICT_COLOUR = {
    "PROCEED": colors.HexColor("#1e7a3c"),
    "PROCEED (THIN BOOK)": colors.HexColor("#a8620a"),
    "POSTPONE": colors.HexColor("#b3261e"),
}
DISCLAIMER = "Educational simulation of a fictive company. Not investment advice."

# ---------------------------------------------------------------------------
# Fonts and text
# ---------------------------------------------------------------------------

#: Vera ships with ReportLab and is embedded, so the PDF prints the same
#: everywhere. It covers − ≥ × ÷ – —, which the standard Helvetica cannot
#: print, but not the few symbols below; the PDF spells those out.
_FONTS = (("Vera", "Vera.ttf"), ("Vera-Bold", "VeraBd.ttf"),
          ("Vera-Italic", "VeraIt.ttf"), ("Vera-BoldItalic", "VeraBI.ttf"))  # fmt: skip
_SPELLED = (("β × ", "Beta × "), ("β·", "beta × "), ("ΔNWC", "change in NWC"),
            ("Σ PV", "Sum of PV"), ("correlation ρ", "correlation"),
            ("ρ = ", "correlation "), ("✓", "\x01"), ("✗", "\x02"))  # fmt: skip
_CHECKS = {"\x01": ("met", "#1e7a3c"), "\x02": ("not met", "#b3261e")}


def _register_fonts() -> None:
    if "Vera" in pdfmetrics.getRegisteredFontNames():
        return
    folder = os.path.join(os.path.dirname(reportlab.__file__), "fonts")
    for name, file in _FONTS:
        pdfmetrics.registerFont(TTFont(name, os.path.join(folder, file)))
    pdfmetrics.registerFontFamily("Vera", normal="Vera", bold="Vera-Bold",
                                  italic="Vera-Italic", boldItalic="Vera-BoldItalic")  # fmt: skip


def _plain(text: str) -> str:
    """Report text with the symbols Vera lacks spelled out."""
    for symbol, words in _SPELLED:
        text = text.replace(symbol, words)
    for mark, (word, _colour) in _CHECKS.items():
        text = text.replace(mark, word)
    return text


def _markup(text: str) -> str:
    """Report text → ReportLab paragraph markup."""
    for symbol, words in _SPELLED:
        text = text.replace(symbol, words)
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    for mark, (word, colour) in _CHECKS.items():
        text = text.replace(mark, f'<font color="{colour}">{word}</font>')
    return re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)


def _style(name: str, **kw: Any) -> ParagraphStyle:
    if "parent" in kw:  # inherit everything not given
        return ParagraphStyle(name, **kw)
    base: dict[str, Any] = {"fontName": "Vera", "fontSize": 9.5, "leading": 13.6,
                            "textColor": INK, "allowWidows": 0,
                            "allowOrphans": 0}  # fmt: skip
    return ParagraphStyle(name, **{**base, **kw})


BODY = _style("body", spaceAfter=6)
LEAD = _style("lead", fontSize=10.5, leading=15, spaceAfter=8, textColor=INK)
H1 = _style("h1", fontName="Vera-Bold", fontSize=18, leading=22, textColor=NAVY,
            spaceAfter=10)  # fmt: skip
CONTENTS = _style("contents", parent=H1)  # not an entry in itself
H2 = _style("h2", fontName="Vera-Bold", fontSize=12.5, leading=16, textColor=NAVY,
            spaceBefore=12, spaceAfter=6, keepWithNext=1)  # fmt: skip
H3 = _style("h3", fontName="Vera-Bold", fontSize=10, leading=14, textColor=INK,
            spaceBefore=8, spaceAfter=4, keepWithNext=1)  # fmt: skip
CELL = _style("cell", fontSize=7.8, leading=9.6)
CELL_R = _style("cell-r", parent=CELL, alignment=2)
HEAD = _style("head", fontName="Vera-Bold", fontSize=7.8, leading=9.4)
HEAD_R = _style("head-r", parent=HEAD, alignment=2)
CAPTION = _style("caption", fontName="Vera-Italic", fontSize=8, leading=10.5,
                 textColor=MUTED, spaceBefore=3, spaceAfter=10)  # fmt: skip
BULLET = _style("bullet", leftIndent=12, bulletIndent=2, spaceAfter=3)
CODE = _style("code", fontName="Courier", fontSize=8, leading=10.5)
NOTE = _style("note", fontSize=8, leading=11, textColor=MUTED)

# ---------------------------------------------------------------------------
# Prose: how to read each section. The numbers are in the section itself.
# ---------------------------------------------------------------------------

#: Chapters: title, introduction, and the report sections they hold.
CHAPTERS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("The company and its offering",
     "The registration statement (the S-1 in the United States) is the "
     "document an issuer files before it may sell shares to the public. Its "
     "cover page states who is selling, how many shares, at what indicative "
     "price, and what the underwriters are paid. This chapter reproduces "
     "that page for the simulated company.",
     ("S-1 cover",)),
    ("Operating forecast",
     "A valuation is only as good as the forecast beneath it. The model "
     "builds the company from the bottom up: the market it sells into, the "
     "customers it wins and loses, the price each customer pays, the people "
     "it employs and the costs it carries. From these follow the income "
     "statement and, after tax and reinvestment, the free cash flow that the "
     "valuation discounts.",
     ("Market and customers", "Unit economics", "Headcount", "Income statement",
      "Taxes, reinvestment and FCFF")),
    ("Valuation",
     "Two methods value the company. The discounted cash flow (DCF) asks "
     "what the forecast cash flows are worth today, given the return "
     "investors require for the risk. The comparables method asks what "
     "investors pay for similar listed companies, as a multiple of revenue. "
     "The fair value per share blends the two.",
     ("Discount rates", "DCF", "Bridge and fair value")),
    ("Uncertainty",
     "Every input to the forecast is an estimate. This chapter shows how far "
     "the fair value moves when the estimates move: first one driver at a "
     "time and in named scenarios, then all drivers together in a Monte "
     "Carlo simulation of many possible companies.",
     ("Scenarios, tornado and sensitivity", "Monte Carlo")),
    ("The offering",
     "Fair value is not the offer price. The underwriters set a price range "
     "below fair value, collect orders from investors (book-building), and "
     "choose the price the book supports. This chapter follows that process "
     "and shows what the chosen price means for ownership and for the "
     "stock's prospects of joining the index.",
     ("Pricing", "Capitalisation and dilution", "Lock-ups, free float and index")),
    ("Risks and next steps",
     "The model's warnings, phrased as the risk factors a prospectus would "
     "disclose; the commands that list the stock on EduMatcher; and the "
     "limits of the model itself.",
     ("Risk factors", "Next step", "What this model leaves out")),
)  # fmt: skip

PROSE: dict[str, tuple[str, ...]] = {
    "S-1 cover": (
        "Emerging growth company (EGC) and smaller reporting company (SRC) "
        "status reduce what the issuer must disclose; both depend on revenue "
        "and, for the SRC test, on the public float at the offer price. The "
        "offering table splits the gross proceeds between the underwriters' "
        "discount, the company and any selling stockholders.",
    ),
    "Market and customers": (
        "The customer base follows a logistic path. Each year the company "
        "wins new customers in proportion to the room left in its reachable "
        "market (the serviceable addressable market times the share it can "
        "realistically take) and loses a fixed share to churn. Growth is "
        "therefore fast while the company is small and slows as it "
        "approaches its ceiling, which the Penetration column tracks.",
        "Revenue is customers times the average revenue per customer "
        "(ARPU), counted on the average number of customers during the "
        "year.",
    ),
    "Unit economics": (
        "Unit economics ask whether an average customer is worth what it "
        "costs to win. The lifetime value (LTV) is the gross profit a "
        "customer brings before churning; the full acquisition cost (CAC) is "
        "all sales and marketing spend divided by the customers won. An "
        "LTV/CAC ratio above about three, and a payback within two years, are "
        "the usual marks of a healthy subscription business. These figures "
        "are reported for judgement; the valuation does not use them "
        "directly.",
    ),
    "Headcount": (
        "Staff are the largest cost of a young technology company. Headcount "
        "grows with revenue, but less than proportionally: the elasticity "
        "says by how much. Revenue per employee therefore rises as the "
        "company scales, which is where operating leverage comes from.",
    ),
    "Income statement": (
        "Costs are built line by line: infrastructure and other cost of "
        "revenue, the four staff functions, acquisition spend, stock-based "
        "compensation and depreciation. Stock-based compensation is treated "
        "as a real cost, because it pays employees in shares that dilute "
        "every other holder. EBIT, earnings before interest and taxes, is the "
        "operating profit the cash flow starts from.",
    ),
    "Taxes, reinvestment and FCFF": (
        "Free cash flow to the firm (FCFF) is what remains of operating profit "
        "after tax, capital expenditure and the investment in working capital "
        "that growth requires. Early losses are carried forward (the NOL "
        "balance) and shelter later profits from tax. FCFF belongs to all "
        "providers of capital, so it is discounted at the cost of capital and "
        "debt is deducted afterwards, in the bridge.",
    ),
    "Discount rates": (
        "The discount rate is the return investors require. The model builds "
        "the cost of equity with the capital asset pricing model (CAPM): the "
        "risk-free rate plus beta times the equity risk premium, plus a size "
        "premium and, for the first stage, an execution premium for the risk "
        "that a young company fails to deliver its plan. Where the company "
        "carries debt, the rate is a weighted average cost of capital (WACC).",
        "The rate falls between the two stages because a company that "
        "survives its growth phase is less risky than one that has yet to.",
    ),
    "DCF": (
        "Each year's cash flow is multiplied by a discount factor, the "
        "product of every earlier year's rate. Beyond the forecast horizon a "
        "terminal value captures all later years. It uses the value-driver "
        "formula: growth must be paid for by reinvestment, and the return on "
        "that new investment (RONIC) decides whether growth creates value at "
        "all.",
        "The terminal value's share of enterprise value shows how much of "
        "the valuation rests on the distant future. Above about 75%, small "
        "changes to long-run assumptions dominate the result.",
    ),
    "Bridge and fair value": (
        "The bridge turns the enterprise value of the operations into value "
        "per share: add cash, deduct debt and the costs of the offering, and "
        "divide by the shares outstanding before the IPO. The comparables "
        "value applies the peers' revenue multiple to next year's revenue in "
        "the same way.",
    ),
    "Scenarios, tornado and sensitivity": (
        "The bear and bull scenarios move every driver to its pessimistic or "
        "optimistic value at once. The tornado moves one driver at a time, "
        "with all others at base, and ranks drivers by how far they swing "
        "fair value: the bars at the top are the assumptions worth arguing "
        "about. The two grids show the DCF value per share over pairs of "
        "inputs.",
    ),
    "Monte Carlo": (
        "The simulation draws every driver at random from a range between its "
        "bear and bull values, with a common factor that makes good and bad "
        "outcomes arrive together, as they tend to in practice. Each draw is "
        "a complete company, valued exactly as the base case. The spread of "
        "the results is the honest answer to the question of what the "
        "company is worth.",
        "The share of draws below the offer price is the probability that "
        "IPO buyers pay more than fair value.",
    ),
    "Pricing": (
        "The bankers set the price range below fair value, by the IPO "
        "discount, so that the first day's trading can reward the buyers. "
        "Management may insist on a minimum valuation, which moves the range "
        "up. The book then records how much institutions, retail investors "
        "and any cornerstone investor would buy at every price from 20% "
        "below the range to 20% above it.",
        "Coverage is demand divided by the value of the shares offered. The "
        "deal is priced at the highest price that is still covered at least "
        "at the target. Oversubscription means most investors receive less "
        "than they asked for, and the unfilled demand supports the price on "
        "the first day of trading: the expected first-day pop.",
    ),
    "Capitalisation and dilution": (
        "New investors pay the offer price for shares whose net tangible book "
        "value is far lower; the difference is their dilution. Existing "
        "holders own a smaller share of a company that now holds more cash.",
    ),
    "Lock-ups, free float and index": (
        "Index inclusion brings buying from passive funds. The fictive "
        "rulebook requires a minimum size, a minimum free float and a "
        "seasoning period of trading before a stock can join. When the "
        "lock-up ends, pre-IPO holders may sell: the overhang compares those "
        "shares with the free float.",
    ),
    "Risk factors": (
        "A prospectus lists the risks an investor takes. These are generated "
        "from the model's own warnings about this company.",
    ),
    "Next step": (
        "The offer price becomes a listing on EduMatcher with the command "
        "below; the opening auction then shows whether the market agrees.",
    ),
    "What this model leaves out": (),
}

# ---------------------------------------------------------------------------
# Tables
# ---------------------------------------------------------------------------

_PAD = 3.0
#: Rows set in bold: the totals a reader's eye should land on.
_TOTALS = {"Gross profit", "EBITDA", "EBIT", "FCFF", "Enterprise value",
           "Enterprise value (DCF)", "DCF value per share", "Discount rate",
           "Cost of equity", "Equity value before the IPO"}  # fmt: skip


def _width(text: str, font: str = "Vera-Bold") -> float:
    """Measured in bold, the widest a cell is set in, plus rounding slack."""
    return float(pdfmetrics.stringWidth(_plain(text), font, CELL.fontSize)) + 1.5


def _columns(block: Table, avail: float) -> list[tuple[list[int], list[float]]]:
    """Column widths that fit *avail*, or column groups that each repeat the
    first column when even wrapping every header cannot make it fit."""
    n = len(block.headers)
    natural, floor = [], []
    for i in range(n):
        header, cells = block.headers[i], [row[i] for row in block.rows]
        head_word = max([_width(w) for w in header.split()] + [0.0])
        cell = max([_width(c) for c in cells] + [0.0])
        # Text wraps at words; a short value (a number) never wraps; headers may.
        text = block.align[i] == "l"
        unbroken = max([_width(c) if len(c) <= 20 and not text
                        else max(_width(w) for w in c.split() or [""])
                        for c in cells] + [0.0])  # fmt: skip
        natural.append(max(_width(header), cell) + 2 * _PAD)
        floor.append(max(head_word, unbroken) + 2 * _PAD)
    widths = list(natural)
    excess = sum(widths) - avail
    for i in sorted(range(n), key=lambda i: -widths[i]):  # widest gives first
        if excess <= 0:
            break
        cut = min(excess, widths[i] - floor[i])
        widths[i] -= cut
        excess -= cut
    if excess <= 0:
        return [(list(range(n)), widths)]
    groups: list[list[int]] = []
    current, used = [0], widths[0]
    for i in range(1, n):
        if used + widths[i] <= avail or len(current) == 1:
            current.append(i)
            used += widths[i]
        else:
            groups.append(current)
            current, used = [0, i], widths[0] + widths[i]
    groups.append(current)
    # Even out the parts: 7 + 6 columns reads better than 11 + 2.
    k, rest = len(groups), list(range(1, n))
    size = -(-len(rest) // k)
    even = [[0, *rest[j : j + size]] for j in range(0, len(rest), size)]
    if len(even) == k and all(sum(widths[i] for i in g) <= avail for g in even):
        groups = even
    return [(g, [widths[i] for i in g]) for g in groups]


def _table(block: Table, avail: float, totals: bool = True) -> list[Flowable]:
    marked = {i for i, row in enumerate(block.rows) if any("◀" in c for c in row)}
    rows = [[c.replace("◀", "").strip() for c in row] for row in block.rows]
    header = any(block.headers)
    out: list[Flowable] = []
    for columns, widths in _columns(block, avail):
        data: list[list[Any]] = []
        if header:
            data.append([P(_markup(block.headers[i]),
                           HEAD_R if block.align[i] == "r" else HEAD)
                         for i in columns])  # fmt: skip
        for r, row in enumerate(rows):
            total = row[0] in _TOTALS or row[0].startswith("Fair value =")
            bold = r in marked or (totals and total)
            cells = []
            for i in columns:
                text = _markup(row[i])
                cells.append(P(f"<b>{text}</b>" if bold else text,
                               CELL_R if block.align[i] == "r" else CELL))  # fmt: skip
            data.append(cells)
        first = 1 if header else 0
        style: list[tuple[Any, ...]] = [
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), _PAD),
            ("RIGHTPADDING", (0, 0), (-1, -1), _PAD),
            ("TOPPADDING", (0, 0), (-1, -1), 2.2),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2.2),
            ("LINEBELOW", (0, -1), (-1, -1), 0.6, NAVY),
        ]
        if header:
            style += [("BACKGROUND", (0, 0), (-1, 0), HEAD_BG),
                      ("LINEBELOW", (0, 0), (-1, 0), 0.8, NAVY)]  # fmt: skip
        else:
            style.append(("LINEABOVE", (0, 0), (-1, 0), 0.6, NAVY))
        for r in range(len(rows)):
            if r in marked:
                style.append(("BACKGROUND", (0, first + r), (-1, first + r), HIGHLIGHT))
            elif r % 2:
                style.append(("BACKGROUND", (0, first + r), (-1, first + r), ZEBRA))
        table = RLTable(data, colWidths=widths, repeatRows=first, hAlign="LEFT")
        table.setStyle(TableStyle(style))
        out += [table, Spacer(1, 8)]
    return out


# ---------------------------------------------------------------------------
# Document
# ---------------------------------------------------------------------------


def _base(title: str) -> str:
    """A report section's title without its number."""
    return title.split(". ", 1)[1] if re.match(r"\d+\. ", title) else title


def _find(report: Report, name: str) -> Section | None:
    return next((s for s in report.sections if _base(s.title).startswith(name)), None)


class _Heading(P):
    """A heading that enters the contents and the PDF outline."""

    def __init__(self, text: str, style: ParagraphStyle, outline: str) -> None:
        super().__init__(_markup(text), style)
        self.outline = _plain(outline)


def _heading(text: str, style: ParagraphStyle, outline: str | None = None) -> P:
    return _Heading(text, style, outline or text)


class _Doc(BaseDocTemplate):
    def __init__(self, path: Path, paper: str, report: Report, run: Run) -> None:
        super().__init__(
            str(path), pagesize=PAPER[paper],
            leftMargin=MARGIN_X, rightMargin=MARGIN_X,
            topMargin=MARGIN_TOP, bottomMargin=MARGIN_BOTTOM,
            title=report.title, author=f"pm-valuation {package_version()}",
            subject="IPO valuation report (educational simulation)",
        )  # fmt: skip
        self.report, self.run = report, run
        frame = Frame(self.leftMargin, self.bottomMargin, self.width, self.height,
                      leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)  # fmt: skip
        self.addPageTemplates([PageTemplate("cover", [frame], onPage=self._cover),
                               PageTemplate("body", [frame])])  # fmt: skip

    def afterFlowable(self, flowable: Flowable) -> None:
        if not isinstance(flowable, _Heading) or flowable.style.name not in (
            "h1",
            "h2",
        ):
            return
        level = 0 if flowable.style.name == "h1" else 1
        outline: str = flowable.outline
        key = "h" + re.sub(r"\W", "", outline)
        self.canv.bookmarkPage(key)
        self.canv.addOutlineEntry(outline, key, level=level, closed=level > 0)
        self.notify("TOCEntry", (level, flowable.text, self.page, key))

    def _cover(self, canvas: Canvas, doc: Any) -> None:
        width, height = self.pagesize
        company = self.report.title.split(" — ")[0]
        verdict = self.report.verdict
        kpis = _kpis(self.report)
        canvas.saveState()
        band = 105 * mm
        canvas.setFillColor(NAVY)
        canvas.rect(0, height - band, width, band, stroke=0, fill=1)
        canvas.setFillColor(colors.white)
        canvas.setFont("Vera", 9)
        canvas.drawString(
            MARGIN_X, height - 26 * mm, "I P O   V A L U A T I O N   R E P O R T"
        )
        canvas.setFont("Vera-Bold", 26)
        canvas.drawString(MARGIN_X, height - 58 * mm, company)
        canvas.setFont("Vera", 11)
        v = self.run.resolved.values
        canvas.drawString(MARGIN_X, height - 70 * mm,
                          f"SIC {v['company.sic_code']}  ·  Incorporated in "
                          f"{v['company.incorporation']}  ·  Lead underwriter: "
                          f"{v['company.lead_underwriter']}")  # fmt: skip
        y = height - band - 22 * mm
        canvas.setFillColor(VERDICT_COLOUR.get(verdict, INK))
        canvas.roundRect(
            MARGIN_X, y - 3 * mm, 70 * mm, 14 * mm, 2 * mm, stroke=0, fill=1
        )
        canvas.setFillColor(colors.white)
        canvas.setFont("Vera-Bold", 13)
        canvas.drawCentredString(MARGIN_X + 35 * mm, y + 1.6 * mm, verdict)
        y -= 16 * mm
        for label, value in kpis[:4]:
            canvas.setFillColor(MUTED)
            canvas.setFont("Vera", 10)
            canvas.drawString(MARGIN_X, y, label)
            canvas.setFillColor(INK)
            canvas.setFont("Vera-Bold", 12)
            canvas.drawString(MARGIN_X + 62 * mm, y, value)
            y -= 8 * mm
        canvas.setStrokeColor(RULE)
        canvas.line(MARGIN_X, 42 * mm, width - MARGIN_X, 42 * mm)
        canvas.setFillColor(MUTED)
        canvas.setFont("Vera", 8.5)
        canvas.drawString(MARGIN_X, 35 * mm, f"Prepared {date.today():%d %B %Y} with "
                          f"pm-valuation {package_version()} (EduMatcher)")  # fmt: skip
        canvas.drawString(MARGIN_X, 30 * mm, DISCLAIMER)
        canvas.drawString(MARGIN_X, 25 * mm, "All companies, figures and market "
                          "data in this report are simulated.")  # fmt: skip
        canvas.restoreState()


def _canvas_maker(header: str, pagesize: tuple[float, float]) -> type[Canvas]:
    class NumberedCanvas(Canvas):
        """Defers each page so the footer can say "page X of Y"."""

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, **kwargs)
            self._pages: list[dict[str, Any]] = []

        def showPage(self) -> None:  # noqa: N802 - ReportLab's name
            self._pages.append(dict(self.__dict__))
            self._startPage()  # pyright: ignore[reportAttributeAccessIssue]

        def save(self) -> None:
            total = len(self._pages)
            for state in self._pages:
                self.__dict__.update(state)
                if self.getPageNumber() > 1:
                    self._furniture(total)
                super().showPage()
            super().save()

        def _furniture(self, total: int) -> None:
            width, height = pagesize
            self.saveState()
            self.setFont("Vera", 7.5)
            self.setFillColor(MUTED)
            top = height - MARGIN_TOP + 9 * mm
            self.drawString(MARGIN_X, top, header)
            self.drawRightString(width - MARGIN_X, top, "IPO valuation report")
            self.setStrokeColor(RULE)
            self.setLineWidth(0.5)
            self.line(MARGIN_X, top - 2.5 * mm, width - MARGIN_X, top - 2.5 * mm)
            bottom = MARGIN_BOTTOM - 11 * mm
            self.line(MARGIN_X, bottom + 4 * mm, width - MARGIN_X, bottom + 4 * mm)
            self.drawString(MARGIN_X, bottom, DISCLAIMER)
            self.drawRightString(width - MARGIN_X, bottom,
                                 f"Page {self.getPageNumber()} of {total}")  # fmt: skip
            self.restoreState()

    return NumberedCanvas


def _kpis(report: Report) -> list[tuple[str, str]]:
    verdict = _find(report, "Verdict")
    table = (
        next((b for b in verdict.blocks if isinstance(b, Table)), None)
        if verdict
        else None
    )
    return [(row[0], row[1]) for row in table.rows] if table else []


def _bullets(items: Sequence[str]) -> list[Flowable]:
    return [P(_markup(item), BULLET, bulletText="•") for item in items]


def _code(text: str) -> Flowable:
    box = RLTable([[P(_markup(text).replace("\n", "<br/>"), CODE)]],
                  colWidths=[None], hAlign="LEFT")  # fmt: skip
    box.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), ZEBRA),
                             ("BOX", (0, 0), (-1, -1), 0.5, RULE),
                             ("LEFTPADDING", (0, 0), (-1, -1), 6),
                             ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                             ("TOPPADDING", (0, 0), (-1, -1), 5),
                             ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]))  # fmt: skip
    return box


class _Figures:
    """Numbers the figures in order of appearance."""

    def __init__(self) -> None:
        self.count = 0

    def __call__(self, drawing: Drawing, caption: str) -> Flowable:
        self.count += 1
        return KeepTogether(
            [drawing, P(f"Figure {self.count}. {_markup(caption)}", CAPTION)]
        )


def _executive_summary(report: Report, avail: float) -> list[Flowable]:
    verdict = report.verdict
    company = report.title.split(" — ")[0]
    out: list[Flowable] = [
        _heading("Executive summary", H1),
        P(f"This report values {_markup(company)} with a two-stage discounted "
          "cash flow and comparable companies, and simulates the book-building "
          "that sets the price of its initial public offering. The verdict and "
          "the headline figures follow. Chapters 1 to 6 give the working, and "
          "Appendix A lists every assumption with its source.", LEAD),
    ]  # fmt: skip
    colour = VERDICT_COLOUR.get(verdict, INK)
    banner = RLTable([[P(f'<font color="white"><b>{verdict}</b></font>',
                         _style("banner", fontName="Vera-Bold", fontSize=15, leading=18))]],
                     colWidths=[avail])  # fmt: skip
    banner.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), colour),
                                ("LEFTPADDING", (0, 0), (-1, -1), 10),
                                ("TOPPADDING", (0, 0), (-1, -1), 7),
                                ("BOTTOMPADDING", (0, 0), (-1, -1), 8)]))  # fmt: skip
    out += [banner, Spacer(1, 10)]
    kpis = _kpis(report)
    per_row = 4
    tile_w = avail / per_row
    label = _style("tile-label", fontSize=7.5, leading=9, textColor=MUTED)
    value = _style("tile-value", fontName="Vera-Bold", fontSize=14, leading=17)
    cells = [[P(_markup(k), label), P(_markup(v), value)] for k, v in kpis]
    grid: list[list[Any]] = [
        cells[i : i + per_row] for i in range(0, len(cells), per_row)
    ]
    if grid:
        empty = per_row - len(grid[-1])
        grid[-1] += [""] * empty
        tiles = RLTable(grid, colWidths=[tile_w] * per_row)
        tiles.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), ZEBRA),
                                   ("BACKGROUND", (per_row - empty, -1), (-1, -1),
                                    colors.white),
                                   ("GRID", (0, 0), (-1, -1), 3, colors.white),
                                   ("VALIGN", (0, 0), (-1, -1), "TOP"),
                                   ("TOPPADDING", (0, 0), (-1, -1), 6),
                                   ("BOTTOMPADDING", (0, 0), (-1, -1), 8)]))  # fmt: skip
        out += [tiles, Spacer(1, 12)]
    section = _find(report, "Verdict")
    lists = [b for b in section.blocks if isinstance(b, Bullets)] if section else []
    if lists:
        out += [_heading("Why", H3), *_bullets(lists[0].items)]
    if len(lists) > 1:
        out += [_heading("What the model flags", H3), *_bullets(lists[1].items)]
    risks = _find(report, "Risk factors")
    risk_items = (
        [i for b in risks.blocks if isinstance(b, Bullets) for i in b.items]
        if risks
        else []
    )
    if risk_items:
        out += [_heading("Principal risks", H3), *_bullets(risk_items)]
    step = _find(report, "Next step")
    if step:
        out.append(_heading("Next step", H3))
        for b in step.blocks:
            if isinstance(b, Code):
                out += [_code(b.text), Spacer(1, 4)]
            elif isinstance(b, Paragraph):
                out.append(P(_markup(b.text), BODY))
    return out


def _section(number: str, section: Section, run: Run, avail: float,
             figure: _Figures) -> list[Flowable]:  # fmt: skip
    name = _base(section.title)
    key = next((k for k in PROSE if name.startswith(k)), name)
    out: list[Flowable] = [CondPageBreak(60 * mm),
                           _heading(f"{number} {name}", H2)]  # fmt: skip
    out += [P(text, BODY) for text in PROSE.get(key, ())]
    offer = run.pricing.listing.price if run.pricing.listing else None
    pieces: list[list[Flowable]] = []  # one per block, kept together below
    for block in section.blocks:
        piece: list[Flowable] = []
        if isinstance(block, Table):
            piece += _table(block, avail)
            if block.headers[:1] == ("Driver",) and run.scenarios is not None:
                piece.append(figure(pdf_charts.tornado(run.scenarios.tornado,
                                                       run.valuation.fair_value, avail),
                                    "Fair value per share with one driver at a time "
                                    "at its bear or bull value, widest swing first."))  # fmt: skip
            if block.headers[:1] == ("Price",) and run.pricing.book:
                piece.append(figure(pdf_charts.coverage(
                    run.pricing.book, offer,
                    float(run.resolved["investors.target_coverage"]),
                    run.pricing.price_range, avail),
                    "Coverage of the book at each price, with the target and the "
                    "price range."))  # fmt: skip
        elif isinstance(block, Paragraph):
            piece.append(P(_markup(block.text), BODY))
        elif isinstance(block, Bullets):
            piece += _bullets(block.items) + [Spacer(1, 6)]
        elif key == "Monte Carlo" and run.mc is not None:  # the text histogram
            values = [s.fair_value for s in run.mc.samples]
            piece.append(figure(pdf_charts.histogram(values, offer,
                                                     run.valuation.fair_value, avail),
                                "Distribution of fair value per share over the "
                                "simulated companies."))  # fmt: skip
        else:
            piece += [_code(block.text), Spacer(1, 8)]
        pieces.append(piece)
    # A caption stays with the table after it; a short table with its notes.
    blocks = section.blocks
    for k, piece in enumerate(pieces):
        block, after = blocks[k], blocks[k + 1] if k + 1 < len(blocks) else None
        if isinstance(block, Paragraph) and isinstance(after, Table):
            piece[-1].keepWithNext = True
        if (
            isinstance(block, Table)
            and isinstance(after, Bullets)
            and len(block.rows) <= 15
        ):
            pieces[k + 1] = [KeepTogether(piece + pieces[k + 1])]
            piece.clear()
    out += [f for piece in pieces for f in piece]
    if key == "Taxes, reinvestment and FCFF":
        horizon = int(run.resolved["rates.horizon"])
        out.append(figure(pdf_charts.cash_flows(run.valuation.years[:horizon], avail),
                          "Revenue and free cash flow to the firm over the "
                          "forecast horizon, USD m."))  # fmt: skip
    return out


def _story(report: Report, run: Run, avail: float) -> list[Flowable]:
    toc = TableOfContents(dotsMinLevel=0)
    toc.levelStyles = [
        _style("toc0", fontName="Vera-Bold", fontSize=10.5, leading=15,
               spaceBefore=6, textColor=NAVY),
        _style("toc1", fontSize=9.5, leading=13, leftIndent=14),
    ]  # fmt: skip
    story: list[Flowable] = [NextPageTemplate("body"), Spacer(1, 1), PageBreak(),
                             P("Contents", CONTENTS), toc, PageBreak()]  # fmt: skip
    story += _executive_summary(report, avail)
    figure = _Figures()
    for c, (title, intro, names) in enumerate(CHAPTERS, start=1):
        sections = [s for n in names if (s := _find(report, n)) is not None]
        story += [PageBreak(), _heading(f"{c} {title}", H1), P(intro, LEAD)]
        for i, section in enumerate(sections, start=1):
            story += _section(f"{c}.{i}", section, run, avail, figure)
    assumptions = _find(report, "Assumptions")
    story += [
        PageBreak(),
        _heading("Appendix A  Assumptions", H1, "Appendix A Assumptions"),
    ]
    if assumptions:
        for block in assumptions.blocks:
            if isinstance(block, Paragraph):
                story.append(P(_markup(block.text), LEAD))
            elif isinstance(block, Table):  # name each interview page once
                rows = [(("" if r and row[0] == block.rows[r - 1][0] else row[0]),
                         *row[1:]) for r, row in enumerate(block.rows)]  # fmt: skip
                story += _table(Table(block.headers, tuple(rows), block.align), avail)
    glossary = Table(("Term", "Meaning"), tuple((t, m) for t, m in GLOSSARY), "ll")
    story += [PageBreak(), _heading("Appendix B  Glossary", H1, "Appendix B Glossary"),
              *_table(glossary, avail, totals=False)]  # fmt: skip
    return story


def write_pdf(run: Run, report: Report, path: Path, paper: str = "a4") -> None:
    """Write *report* as a printable PDF: cover, contents, summary, chapters."""
    _register_fonts()
    doc = _Doc(path, paper, report, run)
    header = report.title
    doc.multiBuild(
        _story(report, run, doc.width), canvasmaker=_canvas_maker(header, PAPER[paper])
    )
