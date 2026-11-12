#!/usr/bin/env python3
"""Generate the figures for the risk controls chapter.

Writes to assets/:
  risk-collars-static-dynamic.png   static band around the close vs dynamic band around the last trade
  risk-ace-expansion.png            Automated Corridor Expansion: the worked example's widening collar ladder
  risk-halt-states.png              the circuit-breaker state machine (halt, resumption auction, close)

Used in src/03-risk-and-compliance/02-risk-controls-protecting-the-market.md.
Builds SVGs and renders them to PNG with headless Google Chrome.

Usage: python3 scripts/gen_risk_controls_figures.py [--chrome PATH]
"""
from __future__ import annotations

import argparse
import math
import subprocess
import tempfile
from pathlib import Path

DEFAULT_CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
ASSETS = Path(__file__).resolve().parent.parent / "assets"

BLUE, ORANGE, RED, GREEN, DARK, MUTED, GREY = "#2b6cb0", "#dd6b20", "#c53030", "#2f855a", "#1a202c", "#4a5568", "#cbd5e0"
PURPLE, LIGHT = "#6b46c1", "#f7fafc"
FONT = 'font-family="Helvetica, Arial, sans-serif"'

# Collar figure: an illustrative ±10% static collar around the close and ±3% dynamic collar around the last trade.
CLOSE, STATIC, DYNAMIC = 100.0, 0.10, 0.03
# ACE figure: the chapter's worked example (reference $100, ±10% → ±20% → ±40%, 5-minute calls, indicative $122).
REF, INDICATIVE = 100.0, 122.0
LADDER = [(0, 5, 0.10), (5, 10, 0.20), (10, 15, 0.40)]


def text(x: float, y: float, s: str, size: int = 20, weight: str = "normal",
         fill: str = DARK, anchor: str = "middle", style: str = "normal") -> str:
    return (f'<text x="{x:.1f}" y="{y:.1f}" {FONT} font-size="{size}" font-weight="{weight}" '
            f'font-style="{style}" fill="{fill}" text-anchor="{anchor}">{s}</text>')


def line(x1: float, y1: float, x2: float, y2: float, colour: str, width: float = 2, dash: str = "") -> str:
    d = f' stroke-dasharray="{dash}"' if dash else ""
    return (f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="{colour}" '
            f'stroke-width="{width}"{d}/>')


def svg(w: int, h: int, body: list[str]) -> str:
    return "\n".join([f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">',
                      f'<rect width="{w}" height="{h}" fill="white"/>', *body, "</svg>"])


def cross(x: float, y: float, colour: str = RED, r: float = 11) -> str:
    return (line(x - r, y - r, x + r, y + r, colour, 5) + line(x - r, y + r, x + r, y - r, colour, 5))


def collars() -> tuple[str, int, int]:
    w, h = 1200, 760
    x0, x1, y0, y1 = 120, 1130, 120, 560
    lo, hi = 83.0, 112.0
    steps = 200

    def px(i: float) -> float:
        return x0 + (x1 - x0) * i / steps

    def py(v: float) -> float:
        return y1 - (y1 - y0) * (v - lo) / (hi - lo)

    def price(i: int) -> float:
        """A slow drift down from the close, with small wiggles."""
        return CLOSE - 8.6 * i / steps + 0.6 * math.sin(i / 9) + 0.35 * math.sin(i / 3.7)

    body = [text(600, 44, "Two collars, two jobs", 28, "bold"),
            text(600, 78, "Illustrative bands: static ±10% around yesterday's close, dynamic ±3% around the last trade", 20, fill=MUTED)]
    top, bot = CLOSE * (1 + STATIC), CLOSE * (1 - STATIC)
    body.append(f'<rect x="{x0}" y="{py(top):.1f}" width="{x1 - x0}" height="{py(bot) - py(top):.1f}" '
                f'fill="{ORANGE}" fill-opacity="0.08"/>')
    for v in (top, bot):
        body.append(line(x0, py(v), x1, py(v), ORANGE, 3, "12 7"))
    body.append(line(x0, py(CLOSE), x1, py(CLOSE), GREY, 2, "4 6"))
    body.append(text(x0 + 8, py(CLOSE) - 8, "yesterday's close $100", 16, fill=MUTED, anchor="start"))
    body.append(text(x1 - 6, py(top) - 10, "static collar: $110", 18, "bold", ORANGE, "end"))
    body.append(text(x1 - 6, py(bot) + 26, "static collar: $90", 18, "bold", ORANGE, "end"))
    for v in range(85, 114, 5):
        body.append(text(x0 - 12, py(v) + 6, f"${v}", 16, fill=MUTED, anchor="end"))

    upper = [price(i) * (1 + DYNAMIC) for i in range(steps + 1)]
    lower = [price(i) * (1 - DYNAMIC) for i in range(steps + 1)]
    band = " ".join(f"L {px(i):.1f} {py(v):.1f}" for i, v in enumerate(upper))
    band += " " + " ".join(f"L {px(i):.1f} {py(v):.1f}" for i, v in reversed(list(enumerate(lower))))
    body.append(f'<path d="M{band[1:]} Z" fill="{BLUE}" fill-opacity="0.15" stroke="none"/>')
    body.append('<path d="' + " ".join(f"{'M' if i == 0 else 'L'} {px(i):.1f} {py(price(i)):.1f}" for i in range(steps + 1)) +
                f'" fill="none" stroke="{BLUE}" stroke-width="4"/>')
    body.append(text(px(18), py(upper[18]) - 14, "dynamic collar moves with the last trade", 18, "bold", BLUE, "start"))

    ia = 40
    body.append(cross(px(ia), py(86.0)))
    body.append(text(px(ia) + 20, py(86.0) + 7, "fat-finger sell at $86: rejected by both collars", 18, "bold", RED, "start"))
    ib = 72
    pb = price(ib) * (1 - DYNAMIC) - 2.0
    body.append(cross(px(ib), py(pb)))
    body.append(text(px(ib) + 20, py(pb) + 7, f"sudden sell at ${pb:.2f}: inside the static band,", 18, "bold", RED, "start"))
    body.append(text(px(ib) + 20, py(pb) + 31, "rejected only by the dynamic collar", 18, "bold", RED, "start"))
    ic = 186
    body.append(f'<circle cx="{px(ic):.1f}" cy="{py(bot):.1f}" r="11" fill="none" stroke="{ORANGE}" stroke-width="4"/>')
    body.append(line(px(ic), py(bot) - 12, px(ic) - 30, py(106.2) + 10, ORANGE, 2))
    body.append(text(x1 - 6, py(107.6), "slow drift: every step stays inside the dynamic band,", 18, "bold", ORANGE, "end"))
    body.append(text(x1 - 6, py(107.6) + 24, "but nothing may trade below $90: the static collar caps the day's move", 18, "bold", ORANGE, "end"))

    body.append(line(x0, y1 + 40, x1, y1 + 40, GREY, 1))
    body.append(text(x0, y1 + 80, "Static collar: catches outright mistakes and caps the drift over the day.", 19, anchor="start"))
    body.append(text(x0, y1 + 108, "Dynamic collar: catches sudden jumps away from where the market has just traded.", 19, anchor="start"))
    return svg(w, h - 60, body), w, h - 60


def ace() -> tuple[str, int, int]:
    w, h = 1200, 800
    x0, x1, y0, y1 = 120, 1130, 110, 600
    t_lo, t_hi = -4.0, 19.0
    lo, hi = 54.0, 146.0

    def px(t: float) -> float:
        return x0 + (x1 - x0) * (t - t_lo) / (t_hi - t_lo)

    def py(v: float) -> float:
        return y1 - (y1 - y0) * (v - lo) / (hi - lo)

    body = [text(600, 44, "Automated Corridor Expansion: the worked example", 28, "bold"),
            text(600, 78, "Reference $100, collar ±10%, then widened in published steps until the indicative price fits", 20, fill=MUTED)]
    for v in range(60, 141, 20):
        body.append(line(x0, py(v), x1, py(v), GREY, 1))
        body.append(text(x0 - 12, py(v) + 6, f"${v}", 16, fill=MUTED, anchor="end"))

    colours = [RED, ORANGE, GREEN]
    for (t0, t1, pct), colour in zip(LADDER, colours):
        top, bot = REF * (1 + pct), REF * (1 - pct)
        body.append(f'<rect x="{px(t0):.1f}" y="{py(top):.1f}" width="{px(t1) - px(t0):.1f}" '
                    f'height="{py(bot) - py(top):.1f}" fill="{colour}" fill-opacity="0.12" stroke="{colour}" stroke-width="2.5"/>')
        ly = py(top) - 12 if pct > 0.3 else py(bot) + 26
        body.append(text((px(t0) + px(t1)) / 2, ly, f"±{pct:.0%}: ${bot:.0f}–${top:.0f}", 18, "bold", colour))
    body.append(line(px(0), py(REF), px(15), py(REF), DARK, 2, "6 6"))
    body.append(text(px(0) + 6, py(REF) + 24, "latched reference $100", 16, fill=MUTED, anchor="start"))

    pre = [(-4, 101.5), (-3.2, 102.8), (-2.4, 102.0), (-1.6, 105.5), (-0.8, 107.8), (0, 110.0)]
    body.append('<path d="' + " ".join(f"{'M' if i == 0 else 'L'} {px(t):.1f} {py(v):.1f}" for i, (t, v) in enumerate(pre)) +
                f'" fill="none" stroke="{BLUE}" stroke-width="4"/>')
    body.append(f'<circle cx="{px(0):.1f}" cy="{py(110):.1f}" r="8" fill="{BLUE}"/>')
    body.append(text(px(0) - 10, py(110) - 16, "hits $110: trigger", 18, "bold", BLUE, "end"))

    body.append(line(px(0.5), py(INDICATIVE), px(15), py(INDICATIVE), PURPLE, 4, "10 6"))
    body.append(text(px(0.6), py(INDICATIVE) - 12, "indicative price $122 (dry-run uncross)", 18, "bold", PURPLE, "start"))
    for t, ok in [(5, False), (10, False), (15, True)]:
        x, y = px(t), py(INDICATIVE)
        if ok:
            body.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="14" fill="{GREEN}"/>')
            body.append(f'<path d="M {x - 7:.1f} {y:.1f} L {x - 2:.1f} {y + 6:.1f} L {x + 8:.1f} {y - 6:.1f}" '
                        f'fill="none" stroke="white" stroke-width="4"/>')
        else:
            body.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="14" fill="white" stroke="{RED}" stroke-width="3"/>')
            body.append(cross(x, y, RED, 7))
    body.append(text(px(5), py(INDICATIVE) + 40, "outside: widen", 17, "bold", RED))
    body.append(text(px(10), py(INDICATIVE) + 40, "outside: widen", 17, "bold", RED))
    body.append(text(px(15) + 8, py(INDICATIVE) + 40, "inside: reopen", 17, "bold", GREEN, "start"))

    post = [(15, 122.0), (15.8, 121.2), (16.6, 123.0), (17.4, 122.4), (18.2, 124.0), (19, 123.2)]
    body.append('<path d="' + " ".join(f"{'M' if i == 0 else 'L'} {px(t):.1f} {py(v):.1f}" for i, (t, v) in enumerate(post)) +
                f'" fill="none" stroke="{BLUE}" stroke-width="4"/>')

    for t in range(0, 20, 5):
        body.append(text(px(t), y1 + 28, f"{t} min", 16, fill=MUTED))
    sy = y1 + 52
    phases = [(t_lo, 0, "continuous", BLUE), (0, 5, "call phase 1", RED), (5, 10, "call phase 2", ORANGE),
              (10, 15, "call phase 3", GREEN), (15, t_hi, "continuous", BLUE)]
    for t0, t1, label, colour in phases:
        body.append(f'<rect x="{px(t0) + 2:.1f}" y="{sy}" width="{px(t1) - px(t0) - 4:.1f}" height="38" rx="6" fill="{colour}"/>')
        body.append(text((px(t0) + px(t1)) / 2, sy + 25, label, 17, "bold", "white"))
    body.append(text(600, h - 40, "Orders keep arriving and resting throughout; nothing trades in this one instrument until the price fits.",
                     19, fill=DARK))
    body.append(text(600, h - 12, "Each step adds a fixed share of the original $100 reference: the band grows by dollars, it does not compound.",
                     18, fill=MUTED, style="italic"))
    return svg(w, h, body), w, h


def state_box(cx: float, cy: float, name: str, colour: str, note: str = "", w: float = 300) -> list[str]:
    h = 84
    out = [f'<rect x="{cx - w / 2:.1f}" y="{cy - h / 2:.1f}" width="{w}" height="{h}" rx="42" fill="{colour}"/>',
           text(cx, cy + 9, name, 23, "bold", "white")]
    if note:
        out.append(text(cx, cy + h / 2 + 28, note, 17, fill=MUTED, style="italic"))
    return out


def arrow(x1: float, y1: float, x2: float, y2: float, colour: str = DARK) -> str:
    return (f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="{colour}" stroke-width="3.5" '
            f'marker-end="url(#a-dark)"/>')


def halt_states() -> tuple[str, int, int]:
    w, h = 1200, 620
    body = [f'<defs><marker id="a-dark" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="5" markerHeight="5" '
            f'orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="{DARK}"/></marker></defs>',
            text(600, 44, "The circuit-breaker state machine", 28, "bold"),
            text(600, 78, "A sub-machine inside the trading session; it can run many times in one day", 20, fill=MUTED)]
    cont, halt, auct, closed = (190, 330), (600, 190), (600, 470), (1010, 190)
    body += state_box(*cont, "CONTINUOUS", BLUE, "normal matching")
    body += state_box(*halt, "HALTED", RED, w=250)
    body.append(text(halt[0], halt[1] - 58, "orders rest, no matching", 17, fill=MUTED, style="italic"))
    body += state_box(*auct, "RESUMPTION_AUCTION", ORANGE, "price discovery before resuming")
    body += state_box(*closed, "CLOSED", DARK, "rest of the day", w=250)

    body.append(arrow(cont[0] + 110, cont[1] - 45, halt[0] - 125, halt[1] + 8))
    body.append(text(300, 222, "price moves beyond the", 17, "bold", RED, "end"))
    body.append(text(300, 245, "threshold from the reference", 17, "bold", RED, "end"))
    body.append(arrow(halt[0], halt[1] + 46, auct[0], auct[1] - 48))
    body.append(text(halt[0] + 14, 322, "halt duration expires", 17, "bold", ORANGE, "start"))
    body.append(text(halt[0] + 14, 345, "(minimum + possible extension)", 17, fill=MUTED, anchor="start"))
    body.append(arrow(auct[0] - 150, auct[1] - 8, cont[0] + 110, cont[1] + 45))
    body.append(text(300, 445, "equilibrium found,", 17, "bold", BLUE, "end"))
    body.append(text(300, 468, "uncross complete", 17, "bold", BLUE, "end"))
    body.append(arrow(halt[0] + 127, halt[1], closed[0] - 131, closed[1]))
    body.append(text(805, 222, "Level 3 halt,", 17, "bold", DARK))
    body.append(text(805, 245, "or end of day", 17, "bold", DARK))
    body.append(text(805, 268, "during a halt", 17, "bold", DARK))
    lx, ly = auct[0] + 150, auct[1]
    body.append(f'<path d="M {lx:.1f} {ly - 22:.1f} C {lx + 110:.1f} {ly - 70:.1f}, {lx + 110:.1f} {ly + 70:.1f}, '
                f'{lx + 6:.1f} {ly + 22:.1f}" fill="none" stroke="{DARK}" stroke-width="3.5" marker-end="url(#a-dark)"/>')
    body.append(text(lx + 100, ly - 10, "indicative price still outside", 17, "bold", ORANGE, "start"))
    body.append(text(lx + 100, ly + 13, "the extension band:", 17, "bold", ORANGE, "start"))
    body.append(text(lx + 100, ly + 36, "auction extended", 17, "bold", ORANGE, "start"))
    body.append(text(600, h - 24, "Every halt returns to continuous trading through an auction, never directly.", 19, fill=DARK))
    return svg(w, h, body), w, h


def render(chrome: str, name: str, built: tuple[str, int, int], tmp: Path) -> None:
    content, w, h = built
    src = tmp / f"{name}.svg"
    src.write_text(content, encoding="utf-8")
    out = ASSETS / f"{name}.png"
    subprocess.run([chrome, "--headless=new", "--disable-gpu", "--hide-scrollbars",
                    "--force-device-scale-factor=2", f"--window-size={w},{h}",
                    f"--screenshot={out}", src.as_uri()],
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print(f"Wrote {out}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--chrome", default=DEFAULT_CHROME, help="Chrome/Chromium executable")
    args = ap.parse_args()
    with tempfile.TemporaryDirectory() as tmp:
        for name, fn in [("risk-collars-static-dynamic", collars), ("risk-ace-expansion", ace),
                         ("risk-halt-states", halt_states)]:
            render(args.chrome, name, fn(), Path(tmp))


if __name__ == "__main__":
    main()
