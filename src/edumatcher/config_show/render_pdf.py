"""A4-landscape multi-page PDF, via ReportLab Platypus.

Consumes the same :class:`ConfigView` the terminal renderer uses, but does
*not* reuse the packer: a page has a fixed size, so the layout is a static
frame plan and the only dynamic decision is how many symbol pages are needed.
Sharing the model rather than the layout keeps both renderers simple and
guarantees the two outputs never disagree about content.
"""

from __future__ import annotations

import hashlib
import math
from datetime import datetime
from pathlib import Path
from typing import Any, Sequence

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

from edumatcher.cli_version import package_version
from edumatcher.config_show.model import ConfigView, Symbol
from edumatcher.config_show.panels import (
    SECTION_PROCESS,
    human_bytes,
    human_count,
    human_ns,
    human_pct,
    mask_key,
)

PAGE = landscape(A4)  # 297 x 210 mm
MARGIN = 12 * mm
CONTENT_WIDTH = PAGE[0] - 2 * MARGIN  # 273 mm
SYMBOL_COLUMNS = 3
SYMBOL_ROWS_PER_PAGE = 34

# Print palette: the terminal's semantics, muted for paper.
INK = colors.HexColor("#1a1a1a")
MUTED = colors.HexColor("#6b6b6b")
RULE = colors.HexColor("#c8c8c8")
ZEBRA = colors.HexColor("#f2f4f7")
ACCENT = colors.HexColor("#0b5394")
GOOD = colors.HexColor("#1e7a3c")
WARN = colors.HexColor("#a8620a")
BAD = colors.HexColor("#b3261e")

_STYLES = getSampleStyleSheet()
H1 = ParagraphStyle(
    "cs-h1",
    parent=_STYLES["Heading1"],
    fontName="Helvetica-Bold",
    fontSize=16,
    leading=19,
    textColor=ACCENT,
    spaceAfter=2,
)
H2 = ParagraphStyle(
    "cs-h2",
    parent=_STYLES["Heading2"],
    fontName="Helvetica-Bold",
    fontSize=10.5,
    leading=13,
    textColor=ACCENT,
    spaceBefore=7,
    spaceAfter=3,
)
BODY = ParagraphStyle(
    "cs-body",
    parent=_STYLES["BodyText"],
    fontName="Helvetica",
    fontSize=8.5,
    leading=11,
    textColor=INK,
    alignment=TA_LEFT,
    spaceAfter=0,
)
NOTE = ParagraphStyle("cs-note", parent=BODY, fontSize=7.5, textColor=MUTED)
MONO = ParagraphStyle("cs-mono", parent=BODY, fontName="Courier", fontSize=8)


def _flag(value: Any) -> str:
    if value is True:
        return '<font color="#1e7a3c">on</font>'
    if value is False:
        return '<font color="#6b6b6b">off</font>'
    return '<font color="#6b6b6b">unset</font>'


def _table(
    data: Sequence[Sequence[Any]],
    widths: Sequence[float],
    zebra_from: int = 1,
    mono_columns: Sequence[int] = (),
) -> Table:
    """A ruled, zebra-striped table with a repeating header row."""
    table = Table(list(data), colWidths=list(widths), repeatRows=1, hAlign="LEFT")
    style: list[tuple[Any, ...]] = [
        ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 7.5),
        ("TEXTCOLOR", (0, 0), (-1, 0), MUTED),
        ("FONT", (0, 1), (-1, -1), "Helvetica", 8),
        ("TEXTCOLOR", (0, 1), (-1, -1), INK),
        ("LINEBELOW", (0, 0), (-1, 0), 0.6, RULE),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]
    for column in mono_columns:
        style.append(("FONT", (column, 1), (column, -1), "Courier", 8))
    for row in range(zebra_from, len(data)):
        if (row - zebra_from) % 2 == 1:
            style.append(("BACKGROUND", (0, row), (-1, row), ZEBRA))
    table.setStyle(TableStyle(style))
    return table


class _Doc(BaseDocTemplate):
    """Adds the running header/footer and 'page N of M'."""

    def __init__(self, path: Path, view: ConfigView, **kwargs: Any) -> None:
        super().__init__(
            str(path),
            pagesize=PAGE,
            leftMargin=MARGIN,
            rightMargin=MARGIN,
            topMargin=MARGIN + 8 * mm,
            bottomMargin=MARGIN + 5 * mm,
            title=f"EduMatcher configuration — {view.source.path.name}",
            author="pm-config-show",
            **kwargs,
        )
        self._view = view
        self._generated = datetime.now().strftime("%Y-%m-%d %H:%M")
        frame = Frame(
            self.leftMargin,
            self.bottomMargin,
            self.width,
            self.height,
            id="body",
            leftPadding=0,
            rightPadding=0,
            topPadding=0,
            bottomPadding=0,
        )
        self.addPageTemplates(
            [
                PageTemplate(id="page", frames=[frame], onPage=self._decorate),
            ]
        )
        self._page_total = 0

    def _decorate(self, canvas: Any, doc: Any) -> None:
        view = self._view
        flags = view.flags
        canvas.saveState()
        top = PAGE[1] - MARGIN - 2 * mm

        canvas.setFont("Helvetica-Bold", 8)
        canvas.setFillColor(ACCENT)
        canvas.drawString(MARGIN, top, f"pm-config-show {package_version()}")
        canvas.setFont("Courier", 8)
        canvas.setFillColor(INK)
        canvas.drawCentredString(PAGE[0] / 2, top, view.source.path.name)
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(MUTED)
        canvas.drawRightString(PAGE[0] - MARGIN, top, self._generated)

        # Repeat the four global flags: a page torn out of the middle must
        # still say whether collars were on.
        canvas.setFont("Helvetica", 7)
        chips = "   ".join(
            f"{label} {'on' if flags.get(key) is True else 'off' if flags.get(key) is False else 'unset'}"
            for label, key in (
                ("sessions", "sessions_enabled"),
                ("collars", "enforce_collars"),
                ("breakers", "enforce_circuit_breakers"),
                ("mm-obligation", "enforce_mm_obligation"),
            )
        )
        canvas.drawString(MARGIN, top - 4.2 * mm, chips)
        canvas.setStrokeColor(RULE)
        canvas.setLineWidth(0.5)
        canvas.line(MARGIN, top - 6 * mm, PAGE[0] - MARGIN, top - 6 * mm)

        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(MUTED)
        total = f" of {self._page_total}" if self._page_total else ""
        canvas.drawRightString(
            PAGE[0] - MARGIN, MARGIN, f"page {canvas.getPageNumber()}{total}"
        )
        canvas.drawString(MARGIN, MARGIN, str(view.source.path))
        canvas.restoreState()


# ---------------------------------------------------------------------------
# page builders
# ---------------------------------------------------------------------------
def _page_overview(view: ConfigView) -> list[Any]:
    source = view.source
    digest = "—"
    try:
        digest = hashlib.sha256(source.path.read_bytes()).hexdigest()[:16]
    except OSError:  # pragma: no cover
        pass
    when = (
        datetime.fromtimestamp(source.mtime).strftime("%Y-%m-%d %H:%M")
        if source.exists
        else "—"
    )

    flow: list[Any] = [
        Paragraph("Engine configuration", H1),
        Paragraph(f'<font face="Courier">{source.path}</font>', BODY),
        Paragraph(
            f"{human_bytes(source.size)} · modified {when} · "
            f"resolved via {source.resolved_via} · sha256:{digest}",
            NOTE,
        ),
        Spacer(1, 3 * mm),
        Paragraph(
            f"sessions {_flag(view.flags.get('sessions_enabled'))} &nbsp;·&nbsp; "
            f"collars {_flag(view.flags.get('enforce_collars'))} &nbsp;·&nbsp; "
            f"breakers {_flag(view.flags.get('enforce_circuit_breakers'))} "
            f"&nbsp;·&nbsp; mm-obligation "
            f"{_flag(view.flags.get('enforce_mm_obligation'))}",
            BODY,
        ),
        Paragraph(
            f"{len(view.symbols)} symbols · {len(view.participants)} "
            f"participants · {len(view.api_gateways)} API gateways · "
            f"{len(view.credentials)} keys · {len(view.listeners)} "
            f"listeners",
            NOTE,
        ),
        Paragraph("Ports and listeners", H2),
    ]

    collisions = view.port_collisions
    rows: list[list[Any]] = [
        ["PORT", "PROTO", "PROCESS", "FUNCTION", "BIND", "SECTION", "ORIGIN"]
    ]
    for listener in view.listeners:
        origin = (
            "COLLISION"
            if listener.port in collisions
            else "off" if not listener.enabled else listener.origin
        )
        rows.append(
            [
                str(listener.port),
                listener.proto,
                listener.process,
                listener.function,
                listener.bind,
                listener.section,
                origin,
            ]
        )
    table = _table(
        rows,
        [16 * mm, 20 * mm, 26 * mm, 70 * mm, 24 * mm, 62 * mm, 25 * mm],
        mono_columns=(0, 4),
    )
    extra: list[tuple[Any, ...]] = []
    for index, listener in enumerate(view.listeners, start=1):
        if listener.port in collisions:
            extra.append(("TEXTCOLOR", (0, index), (-1, index), BAD))
            extra.append(("FONT", (0, index), (-1, index), "Helvetica-Bold", 8))
        elif not listener.enabled or listener.origin in ("fixed", "default"):
            extra.append(("TEXTCOLOR", (0, index), (-1, index), MUTED))
    table.setStyle(TableStyle(extra))
    flow.append(table)
    flow.append(
        Paragraph(
            "‘fixed’ and ‘env’ rows are bound by config.py and appear nowhere in "
            "the YAML. ‘default’ means the section is present but omits port:, so "
            "the runtime default is bound.",
            NOTE,
        )
    )

    if view.schedule.phases:
        flow.append(Paragraph("Session schedule", H2))
        phases = view.schedule.phases
        flow.append(
            _table(
                [[label for label, _ in phases], [hhmm for _, hhmm in phases]],
                [CONTENT_WIDTH / len(phases)] * len(phases),
                zebra_from=2,
                mono_columns=tuple(range(len(phases))),
            )
        )
    return flow


def _page_access(view: ConfigView, reveal: bool) -> list[Any]:
    flow: list[Any] = [Paragraph("Access", H1), Paragraph("Participants", H2)]
    rows: list[list[Any]] = [
        ["ID", "ROLE", "ON DISCONNECT", "QUOTE REFRESH", "DESCRIPTION"]
    ]
    for participant in view.participants:
        rows.append(
            [
                participant.gid,
                participant.role,
                participant.disconnect,
                participant.quote_policy or "—",
                participant.description or "—",
            ]
        )
    flow.append(_table(rows, [28 * mm, 34 * mm, 46 * mm, 55 * mm, 110 * mm]))

    flow.append(Paragraph("API gateways", H2))
    rows = [
        [
            "GATEWAY",
            "STATE",
            "BIND",
            "SWAGGER",
            "LOG",
            "RETENTION",
            "RATE w/s",
            "TIMEOUTS",
            "STATS DB",
        ]
    ]
    for gateway in view.api_gateways:
        limit = gateway.rate_limit
        timeouts = gateway.timeouts
        rows.append(
            [
                gateway.name,
                "on" if gateway.enabled else "off",
                f"{gateway.host}:{gateway.port}",
                "yes" if gateway.swagger else "no",
                gateway.log_level,
                (
                    f"{gateway.order_retention_sec}s"
                    if gateway.order_retention_sec is not None
                    else "—"
                ),
                f"{limit.get('writes_per_second', '—')}/{limit.get('burst', '—')}",
                "/".join(
                    str(timeouts.get(k, "—"))
                    for k in ("engine_auth_sec", "engine_reply_sec", "wait_ack_sec")
                ),
                gateway.stats_db,
            ]
        )
    flow.append(
        _table(
            rows,
            [
                26 * mm,
                15 * mm,
                34 * mm,
                18 * mm,
                15 * mm,
                22 * mm,
                20 * mm,
                30 * mm,
                93 * mm,
            ],
            mono_columns=(2, 8),
        )
    )

    flow.append(Paragraph("API keys", H2))
    rows = [["GATEWAY ID", "API GATEWAY", "ROLE", "API KEY", "DESCRIPTION"]]
    for cred in view.credentials:
        rows.append(
            [
                cred.gateway_id or "—",
                cred.owner_gateway,
                cred.role,
                cred.api_key if reveal else mask_key(cred.api_key),
                cred.description or "—",
            ]
        )
    flow.append(
        _table(rows, [28 * mm, 30 * mm, 34 * mm, 105 * mm, 76 * mm], mono_columns=(3,))
    )
    if not reveal:
        flow.append(
            Paragraph(
                "Keys are masked. Re-run with --all to include " "them in full.", NOTE
            )
        )
    return flow


def _page_risk(view: ConfigView) -> list[Any]:
    flow: list[Any] = [Paragraph("Risk and market making", H1)]

    if view.risk_levels:
        flow.append(Paragraph("Price collars", H2))
        rows: list[list[Any]] = [
            ["LEVEL", "STATIC BAND", "DYNAMIC BAND", "SYMBOLS", "DEFAULT"]
        ]
        for level in view.risk_levels:
            rows.append(
                [
                    level.name,
                    human_pct(level.static_band_pct),
                    human_pct(level.dynamic_band_pct),
                    str(level.n_symbols),
                    "yes" if level.is_default else "",
                ]
            )
        flow.append(_table(rows, [50 * mm, 30 * mm, 32 * mm, 24 * mm, 24 * mm]))
        flow.append(
            Paragraph(
                f"enforce_collars: {'on' if view.flags.get('enforce_collars') else 'off'}",
                NOTE,
            )
        )

    if view.cb_levels:
        flow.append(Paragraph("Circuit breakers", H2))
        rows = [["LEVEL", "PRICE SHIFT", "HALT DURATION"]]
        for breaker in view.cb_levels:
            rows.append(
                [
                    breaker.name,
                    human_pct(breaker.price_shift_pct),
                    (
                        human_ns(breaker.halt_duration_ns)
                        if breaker.halt_duration_ns
                        else "rest of session"
                    ),
                ]
            )
        flow.append(_table(rows, [50 * mm, 30 * mm, 45 * mm]))
        notes = [f"reference window {human_ns(view.cb_reference_window_ns)}"]
        reopening = view.cb_reopening
        if reopening:
            ladder = " → ".join(
                f"+{float(step.get('widen_pct', 0)):.0%} for at least "
                f"{human_ns(step.get('min_duration_ns'))}"
                for step in reopening.get("expansions", [])
                if isinstance(step, dict)
            )
            notes.append(
                f"reopening {'enabled' if reopening.get('enabled') else 'disabled'}, "
                f"initial band {float(reopening.get('initial_band_pct', 0)):.0%}"
                + (f"; ladder {ladder}" if ladder else "")
            )
        flow.append(Paragraph(" · ".join(notes), NOTE))

    flow.append(Paragraph("Market-maker obligations", H2))
    defaults = view.mm_defaults
    rows = [["SCOPE", "ENFORCED", "MAX SPREAD (ticks)", "MIN QUANTITY"]]
    rows.append(
        [
            "default",
            "yes" if defaults.get("enforce_mm_obligation") else "no",
            str(defaults.get("mm_max_spread_ticks", "—")),
            str(defaults.get("mm_min_qty", "—")),
        ]
    )
    for symbol, override in view.mm_symbol_overrides.items():
        override = override if isinstance(override, dict) else {}
        rows.append(
            [
                symbol,
                "yes" if override.get("enforce_mm_obligation") else "no",
                str(override.get("mm_max_spread_ticks", "—")),
                str(override.get("mm_min_qty", "—")),
            ]
        )
    flow.append(_table(rows, [40 * mm, 26 * mm, 42 * mm, 34 * mm]))

    if view.combos:
        flow.append(Paragraph("Seed combos", H2))
        rows = [["COMBO", "TYPE", "TIF", "LEGS"]]
        for combo in view.combos:
            legs = "; ".join(
                f"{leg.get('side', '?')} {leg.get('quantity', '?')} "
                f"{leg.get('symbol', '?')} {leg.get('order_type', '')} "
                f"@{leg.get('price', '—')}".strip()
                for leg in combo.legs
            )
            rows.append([combo.combo_id, combo.combo_type, combo.tif, legs])
        flow.append(_table(rows, [55 * mm, 20 * mm, 16 * mm, 182 * mm]))
    return flow


def _symbol_rows(chunk: Sequence[Symbol], default_level: str | None) -> list[list[Any]]:
    rows: list[list[Any]] = [["SYMBOL", "DEC", "LAST", "LEVEL", "Q", "SHARES", "OVR"]]
    for symbol in chunk:
        price = symbol.price
        decimals = symbol.tick_decimals if symbol.tick_decimals is not None else 2
        rows.append(
            [
                symbol.name,
                str(symbol.tick_decimals) if symbol.tick_decimals is not None else "—",
                f"{price:,.{decimals}f}" if price is not None else "—",
                symbol.level or (default_level or "—"),
                str(symbol.n_quotes) if symbol.n_quotes else "·",
                human_count(symbol.outstanding),
                symbol.override_flags,
            ]
        )
    return rows


def _pages_symbols(view: ConfigView) -> list[Any]:
    if not view.symbols:
        return []
    ordered = sorted(view.symbols, key=lambda s: s.name)
    per_page = SYMBOL_COLUMNS * SYMBOL_ROWS_PER_PAGE
    pages = math.ceil(len(ordered) / per_page)
    sub_width = (CONTENT_WIDTH - 8 * mm) / SYMBOL_COLUMNS
    widths = [sub_width * f for f in (0.22, 0.09, 0.22, 0.21, 0.07, 0.19)]

    flow: list[Any] = []
    for page in range(pages):
        block = ordered[page * per_page : (page + 1) * per_page]
        rows_per = math.ceil(len(block) / SYMBOL_COLUMNS)
        chunks = [
            block[i * rows_per : (i + 1) * rows_per] for i in range(SYMBOL_COLUMNS)
        ]
        flow.append(PageBreak())
        flow.append(
            Paragraph("Symbols" + (f" ({page + 1}/{pages})" if pages > 1 else ""), H1)
        )
        flow.append(
            Paragraph(
                f"{len(view.symbols)} configured · DEC = tick decimals · "
                f"Q = seeded MM quotes · OVR = Collar/Breaker/Mm override",
                NOTE,
            )
        )
        flow.append(Spacer(1, 2 * mm))
        cells = [
            (
                _table(
                    _symbol_rows(chunk, view.default_risk_level),
                    widths + [sub_width * 0.10],
                    mono_columns=(2,),
                )
                if chunk
                else Paragraph("", BODY)
            )
            for chunk in chunks
        ]
        outer = Table(
            [cells], colWidths=[sub_width + 4 * mm] * SYMBOL_COLUMNS, hAlign="LEFT"
        )
        outer.setStyle(
            TableStyle(
                [
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 0),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 4 * mm),
                ]
            )
        )
        flow.append(outer)
    return flow


def _page_appendix(view: ConfigView, reveal: bool) -> list[Any]:
    flow: list[Any] = [PageBreak(), Paragraph("Appendix", H1)]

    if view.gateway_sections:
        flow.append(Paragraph("Gateway tuning", H2))
        rows: list[list[Any]] = [
            ["SECTION", "PROCESS", "HEARTBEAT", "IDLE", "QUEUE", "OTHER"]
        ]
        for key, section in view.gateway_sections.items():
            other = ", ".join(
                f"{k}={v}"
                for k, v in section.items()
                if k
                not in {
                    "heartbeat_interval_sec",
                    "idle_timeout_sec",
                    "max_client_queue",
                    "port",
                    "bind_address",
                    "host",
                    "name",
                    "enabled",
                }
            )
            rows.append(
                [
                    key,
                    SECTION_PROCESS.get(key, "—"),
                    str(section.get("heartbeat_interval_sec", "—")),
                    str(section.get("idle_timeout_sec", "—")),
                    human_count(section.get("max_client_queue")),
                    other,
                ]
            )
        flow.append(
            _table(rows, [42 * mm, 30 * mm, 24 * mm, 18 * mm, 20 * mm, 139 * mm])
        )

    flow.append(Paragraph("Engine tuning", H2))
    if view.tuning:
        rows = [["SETTING", "VALUE"]]
        rows += [[k, str(v)] for k, v in view.tuning.items()]
        flow.append(_table(rows, [70 * mm, 50 * mm]))
    else:
        flow.append(Paragraph("Not configured; engine defaults apply.", NOTE))

    if view.indices:
        flow.append(Paragraph("Indices", H2))
        rows = [["INDEX", "BASE", "INTERVAL", "CONSTITUENTS", "DESCRIPTION"]]
        for index in view.indices:
            rows.append(
                [
                    index.idx_id,
                    str(index.base_value),
                    f"{index.publish_interval_sec}s",
                    f"{len(index.constituents)}: " + ", ".join(index.constituents),
                    index.description or "—",
                ]
            )
        flow.append(_table(rows, [32 * mm, 22 * mm, 22 * mm, 120 * mm, 77 * mm]))

    if reveal and view.unknown_keys:
        flow.append(Paragraph("Unrecognised top-level keys", H2))
        flow.append(Paragraph(", ".join(view.unknown_keys), MONO))
        flow.append(
            Paragraph(
                "These are ignored by every pm-* process. A typo "
                "in a section name looks exactly like this.",
                NOTE,
            )
        )
    return flow


# ---------------------------------------------------------------------------
def render_pdf(view: ConfigView, target: Path, density: int, reveal: bool) -> Path:
    """Write the whole configuration to ``target`` as an A4-landscape PDF."""
    target.parent.mkdir(parents=True, exist_ok=True)
    doc = _Doc(target, view)

    story: list[Any] = []
    story += _page_overview(view)
    story.append(PageBreak())
    story += _page_access(view, reveal)
    story.append(PageBreak())
    story += _page_risk(view)
    story += _pages_symbols(view)
    if density >= 1:
        story += _page_appendix(view, reveal)

    # Two passes: the first only counts pages so the second can print
    # "page N of M". Platypus consumes the story, so each pass gets a copy.
    doc.build(list(story))
    total_pages = doc.page

    final = _Doc(target, view)
    final._page_total = total_pages
    final.build(list(story))
    return target
