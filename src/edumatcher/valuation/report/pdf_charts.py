"""Vector charts for the PDF report, drawn with ReportLab graphics.

Print rules: one axis per chart, thin marks, recessive grid, ink-coloured
text, and colour that carries meaning (a legend names every colour).
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Literal

from reportlab.graphics.shapes import Circle, Drawing, Line, PolyLine, Rect, String
from reportlab.lib import colors

from edumatcher.valuation.model.forecast import YearRow
from edumatcher.valuation.model.offering import BookLine
from edumatcher.valuation.model.scenarios import TornadoBar

INK = colors.HexColor("#1a1a1a")
MUTED = colors.HexColor("#5f6368")
GRID = colors.HexColor("#dfe3e8")
BAND = colors.HexColor("#eef1f5")
BLUE = colors.HexColor("#2a78d6")
ORANGE = colors.HexColor("#eb6834")
RED = colors.HexColor("#e34948")
FONT, BOLD = "Vera", "Vera-Bold"


Anchor = Literal["start", "middle", "end"]


def _box(x: float, y: float, width: float, height: float, colour: colors.Color) -> Rect:
    """A filled rectangle. (The stubs mistype Rect's keywords, so set attributes.)"""
    rect = Rect(x, y, width, height)
    rect.fillColor, rect.strokeColor = colour, None
    return rect


def _dot(x: float, y: float, radius: float, colour: colors.Color) -> Circle:
    dot = Circle(x, y, radius)
    dot.fillColor, dot.strokeColor = colour, colors.white
    dot.strokeWidth = 0 if radius < 2 else 1
    return dot


def _minus(text: str) -> str:
    return text.replace("-", "−")


def _ticks(lo: float, hi: float, count: int = 5) -> list[float]:
    """Round tick values covering [lo, hi]."""
    if hi <= lo:
        hi = lo + 1
    raw = (hi - lo) / count
    magnitude = 10 ** math.floor(math.log10(raw))
    step = next(m * magnitude for m in (1, 2, 2.5, 5, 10) if m * magnitude >= raw)
    first = math.floor(lo / step) * step
    return [first + i * step for i in range(math.ceil((hi - first) / step) + 1)]


def _label(value: float, step: float) -> str:
    return _minus(f"{value:,.0f}" if step >= 1 else f"{value:,.1f}")


def _text(d: Drawing, x: float, y: float, text: str, size: float = 7,
          anchor: Anchor = "start", colour: colors.Color = MUTED,
          font: str = FONT) -> None:  # fmt: skip
    d.add(String(x, y, text, fontName=font, fontSize=size, fillColor=colour,
                 textAnchor=anchor))  # fmt: skip


def _legend(
    d: Drawing, x: float, y: float, items: Sequence[tuple[str, colors.Color]]
) -> None:
    for label, colour in items:
        d.add(_box(x, y - 1, 7, 7, colour))
        _text(d, x + 10, y, label, 7.5, colour=INK)
        x += 18 + len(label) * 4.2


def _value_axis(d: Drawing, left: float, right: float, bottom: float, top: float,
                lo: float, hi: float) -> tuple[list[float], float]:  # fmt: skip
    """Horizontal grid lines and labels on the left; returns ticks and scale."""
    ticks = _ticks(lo, hi)
    lo, hi = ticks[0], ticks[-1]
    scale = (top - bottom) / (hi - lo)
    step = ticks[1] - ticks[0]
    for t in ticks:
        y = bottom + (t - lo) * scale
        d.add(Line(left, y, right, y, strokeColor=GRID if t else MUTED,
                   strokeWidth=0.4 if t else 0.7))  # fmt: skip
        _text(d, left - 4, y - 2.5, _label(t, step), anchor="end")
    return ticks, scale


def cash_flows(years: Sequence[YearRow], width: float) -> Drawing:
    """Revenue and free cash flow per forecast year, USD m."""
    height = 180.0
    d = Drawing(width, height)
    left, right, bottom, top = 40.0, width - 4, 16.0, height - 22
    revenue = [y.revenue / 1e6 for y in years]
    fcff = [y.fcff / 1e6 for y in years]
    ticks, scale = _value_axis(d, left, right, bottom, top,
                               min(0.0, *fcff), max(revenue))  # fmt: skip
    zero = bottom - ticks[0] * scale
    slot = (right - left) / len(years)
    bar = min(12.0, slot * 0.34)
    for i, (r, f) in enumerate(zip(revenue, fcff)):
        x = left + slot * i + slot / 2
        for value, colour, dx in ((r, BLUE, -bar - 1), (f, ORANGE, 1)):
            y0, y1 = sorted((zero, zero + value * scale))
            d.add(_box(x + dx, y0, bar, max(y1 - y0, 0.3), colour))
        _text(d, x, bottom - 10, f"Y{i + 1}", anchor="middle")
    _text(d, left - 36, top + 12, "USD m", 7, colour=MUTED)
    _legend(d, left + 20, top + 12,
            (("Revenue", BLUE), ("Free cash flow to the firm", ORANGE)))  # fmt: skip
    return d


def tornado(bars: Sequence[TornadoBar], base: float, width: float) -> Drawing:
    """Fair value per share with one driver at its bear or bull value."""
    rows = [b for b in bars if b.bear is not None or b.bull is not None]
    row_h, label_w = 15.0, 138.0
    height = row_h * len(rows) + 48
    d = Drawing(width, height)
    left, right, bottom, top = label_w, width - 30, 26.0, height - 10
    ends = [base] + [v for b in rows for v in (b.bear, b.bull) if v is not None]
    ticks = _ticks(min(ends), max(ends))
    lo, hi = ticks[0], ticks[-1]
    scale = (right - left) / (hi - lo)
    step = ticks[1] - ticks[0]

    def x_of(v: float) -> float:
        return left + (v - lo) * scale

    for t in ticks:
        d.add(Line(x_of(t), bottom, x_of(t), top, strokeColor=GRID, strokeWidth=0.4))
        _text(d, x_of(t), bottom - 10, _label(t, step), anchor="middle")
    for i, b in enumerate(rows):
        y = top - row_h * (i + 1) + 4
        _text(d, left - 6, y + 1, b.label, 7.5, anchor="end", colour=INK)
        for value, colour in ((b.bear, RED), (b.bull, BLUE)):
            if value is None:
                continue
            x0, x1 = sorted((x_of(base), x_of(value)))
            d.add(_box(x0, y - 1, max(x1 - x0, 0.5), 8, colour))
            outside = x_of(value) + (3 if value >= base else -3)
            _text(d, outside, y + 1, _minus(f"{value:.2f}"), 6.5,
                  anchor="start" if value >= base else "end")  # fmt: skip
    d.add(Line(x_of(base), bottom, x_of(base), top + 2, strokeColor=INK,
               strokeWidth=0.9))  # fmt: skip
    _text(d, x_of(base), top + 4, _minus(f"Base {base:.2f}"), 7, anchor="middle",
          colour=INK)  # fmt: skip
    _legend(d, left, 2, (("Driver at its bear value", RED),
                         ("Driver at its bull value", BLUE)))  # fmt: skip
    return d


def histogram(values: Sequence[float], offer: float | None, base: float,
              width: float) -> Drawing:  # fmt: skip
    """The Monte Carlo distribution of fair value per share."""
    height = 185.0
    d = Drawing(width, height)
    left, right, bottom, top = 40.0, width - 6, 26.0, height - 30
    ordered = sorted(values)
    lo = ordered[int(0.005 * (len(ordered) - 1))]
    hi = ordered[int(0.995 * (len(ordered) - 1))]
    edges = _ticks(min(lo, base, offer or base), max(hi, base, offer or base), 24)
    bins = len(edges) - 1
    counts = [0] * bins
    width_bin = edges[1] - edges[0]
    for v in values:
        counts[min(bins - 1, max(0, int((v - edges[0]) // width_bin)))] += 1
    _, scale = _value_axis(d, left, right, bottom, top, 0, max(counts))
    xscale = (right - left) / (edges[-1] - edges[0])

    def x_of(v: float) -> float:
        return left + (v - edges[0]) * xscale

    for i, count in enumerate(counts):
        centre = edges[i] + width_bin / 2
        colour = ORANGE if offer is not None and centre < offer else BLUE
        d.add(_box(x_of(edges[i]) + 0.8, bottom, width_bin * xscale - 1.6,
                   count * scale, colour))  # fmt: skip
    step = edges[1] - edges[0]
    for e in edges[:: max(1, bins // 8)]:
        _text(d, x_of(e), bottom - 10, _label(e, step), anchor="middle")
    _text(d, left - 36, top + 20, "Draws", 7)
    _text(d, right, bottom - 21, "Fair value per share", 7, anchor="end")
    base_left = offer is not None and base < offer  # labels point away
    marks = [(base, f"Base {base:.2f}", MUTED, base_left)]
    if offer is not None:
        marks.append((offer, f"Offer {offer:.2f}", INK, not base_left))
    for value, label, colour, to_left in marks:
        x = x_of(value)
        line = Line(x, bottom, x, top + 4, strokeColor=colour, strokeWidth=0.9)
        if colour is MUTED:
            line.strokeDashArray = [2, 2]
        d.add(line)
        _text(d, x - 3 if to_left else x + 3, top, _minus(label), 7,
              anchor="end" if to_left else "start", colour=colour)  # fmt: skip
    if offer is not None:
        _legend(d, left + 20, top + 20, (("Fair value below the offer price", ORANGE),
                                         ("At or above it", BLUE)))  # fmt: skip
    return d


def coverage(book: Sequence[BookLine], offer: float | None, target: float,
             price_range: tuple[float, float], width: float) -> Drawing:  # fmt: skip
    """Book coverage at every price the bankers considered."""
    height = 175.0
    d = Drawing(width, height)
    left, right, bottom, top = 40.0, width - 8, 26.0, height - 22
    prices = [b.price for b in book]
    ticks, scale = _value_axis(d, left, right, bottom, top, 0,
                               max(max(b.coverage for b in book), target))  # fmt: skip
    x_ticks = _ticks(min(prices), max(prices), 8)
    xlo, xhi = x_ticks[0], x_ticks[-1]
    xscale = (right - left) / (xhi - xlo)

    def x_of(v: float) -> float:
        return left + (v - xlo) * xscale

    def y_of(v: float) -> float:
        return bottom + (v - ticks[0]) * scale

    low, high = price_range
    d.add(_box(x_of(low), bottom, x_of(high) - x_of(low), top - bottom, BAND))
    _text(d, (x_of(low) + x_of(high)) / 2, top - 9, "Price range", 7, anchor="middle")
    step = x_ticks[1] - x_ticks[0]
    for t in x_ticks:
        _text(d, x_of(t), bottom - 10, _label(t, step if step < 1 else 1.0),
              anchor="middle")  # fmt: skip
    goal = Line(left, y_of(target), right, y_of(target), strokeColor=INK,
                strokeWidth=0.7)  # fmt: skip
    goal.strokeDashArray = [3, 2]
    d.add(goal)
    _text(d, right, y_of(target) + 3, _minus(f"Target {target:g}×"), 7,
          anchor="end", colour=INK)  # fmt: skip
    points = [(x_of(b.price), y_of(b.coverage)) for b in book]
    d.add(PolyLine([c for p in points for c in p], strokeColor=BLUE, strokeWidth=1.4))
    for x, y in points:
        d.add(_dot(x, y, 1.6, BLUE))
    for b in book:
        if offer is not None and abs(b.price - offer) < 1e-9:
            x, y = x_of(b.price), y_of(b.coverage)
            d.add(_dot(x, y, 3.4, INK))
            label = f"Offer {b.price:.2f} at {b.coverage:.2f}×"
            near_right = x > (left + right) / 2
            _text(d, x - 6 if near_right else x + 6, y + 6, label, 7.5,
                  anchor="end" if near_right else "start", colour=INK,
                  font=BOLD)  # fmt: skip
    _text(d, left - 36, top + 12, "Coverage (×)", 7)
    _text(d, right, bottom - 21, "Offer price", 7, anchor="end")
    return d
