#!/usr/bin/env python3
"""Generate the explanatory figures for the first implied orders chapter.

Writes to assets/:
  implied-wrong-book.png      who trades with whom when C buys an implied February offer
  implied-vector-sum.png      A's January ask + B's spread bid: the January legs cancel
  implied-triangle.png        any two of Jan / Feb / spread imply the third (six formulas)
  implied-shared-leg.png      one January ask shared by two spread bids: naive vs correct depth
  implied-sign-convention.png S = Near − Far on price ladders and the signed number line

Used in src/02-orders-and-matching/13-implied-orders-and-synthetic-liquidity.md.
Builds SVGs and renders them to PNG with headless Google Chrome.

Usage: python3 scripts/gen_implied_intro_figures.py [--chrome PATH]
"""
from __future__ import annotations

import argparse
import subprocess
import tempfile
from pathlib import Path

DEFAULT_CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
ASSETS = Path(__file__).resolve().parent.parent / "assets"

BLUE, ORANGE, GREY, DARK, MUTED = "#2b6cb0", "#dd6b20", "#cbd5e0", "#1a202c", "#4a5568"
GREEN, RED, PURPLE, LIGHT = "#2f855a", "#c53030", "#6b46c1", "#f7fafc"
FONT = 'font-family="Helvetica, Arial, sans-serif"'


def text(x: float, y: float, s: str, size: int = 22, weight: str = "normal",
         fill: str = DARK, anchor: str = "middle", style: str = "normal") -> str:
    return (f'<text x="{x:.1f}" y="{y:.1f}" {FONT} font-size="{size}" font-weight="{weight}" '
            f'font-style="{style}" fill="{fill}" text-anchor="{anchor}">{s}</text>')


def rect(x: float, y: float, w: float, h: float, fill: str, stroke: str = "none",
         dash: bool = False, rx: int = 10, sw: float = 2, opacity: float = 1) -> str:
    d = ' stroke-dasharray="8 6"' if dash else ""
    return (f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" rx="{rx}" fill="{fill}" '
            f'fill-opacity="{opacity}" stroke="{stroke}" stroke-width="{sw}"{d}/>')


def arrow(x1: float, y1: float, x2: float, y2: float, colour: str = DARK, width: float = 4,
          dash: bool = False) -> str:
    d = ' stroke-dasharray="8 6"' if dash else ""
    mid = {DARK: "a-dark", GREEN: "a-green", ORANGE: "a-orange", GREY: "a-grey",
           BLUE: "a-blue", PURPLE: "a-purple", RED: "a-red"}[colour]
    return (f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="{colour}" '
            f'stroke-width="{width}" stroke-linecap="round" marker-end="url(#{mid})"{d}/>')


def svg(w: int, h: int, body: list[str]) -> str:
    markers = "".join(
        f'<marker id="{i}" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="5" markerHeight="5" '
        f'orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="{c}"/></marker>'
        for i, c in [("a-dark", DARK), ("a-green", GREEN), ("a-orange", ORANGE), ("a-grey", "#a0aec0"),
                     ("a-blue", BLUE), ("a-purple", PURPLE), ("a-red", RED)])
    return "\n".join([f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">',
                      f"<defs>{markers}</defs>", f'<rect width="{w}" height="{h}" fill="white"/>', *body, "</svg>"])


def person(x: float, y: float, name: str, role: str, colour: str) -> list[str]:
    return [f'<circle cx="{x}" cy="{y}" r="42" fill="{colour}"/>',
            text(x, y + 11, name, 32, "bold", "white"), text(x, y + 74, role, 19, fill=MUTED)]


def wrong_book() -> tuple[str, int, int]:
    w, h = 1200, 760
    xs = [200, 600, 1000]
    body = [text(600, 40, "Three books, three traders: who trades with whom?", 28, "bold")]
    titles = ["January book", "Jan/Feb spread book", "February book"]
    for x, t in zip(xs, titles):
        body.append(rect(x - 170, 70, 340, 200, LIGHT, GREY))
        body.append(text(x, 108, t, 24, "bold"))
    body.append(text(xs[0], 160, "A: sell 50 lots", 22))
    body.append(text(xs[0], 192, "at $75.00", 22))
    body.append(text(xs[1], 155, "B: buy 30 spreads", 22))
    body.append(text(xs[1], 185, "(buy Jan + sell Feb,", 19, fill=MUTED))
    body.append(text(xs[1], 210, "Feb at least $2.00 above Jan)", 19, fill=MUTED))
    body.append(text(xs[2], 145, "no real orders", 20, fill=MUTED, style="italic"))
    body.append(rect(xs[2] - 145, 165, 290, 85, "#fffaf0", ORANGE, dash=True))
    body.append(text(xs[2], 200, "Implied ask: 30 @ $77.00", 21, "bold", ORANGE))
    body.append(text(xs[2], 230, "shown by the engine (A + B)", 18, fill=ORANGE))
    py = 430
    body += person(xs[0], py, "A", "January seller", BLUE)
    body += person(xs[1], py, "B", "spread trader", PURPLE)
    body += person(xs[2], py, "C", "February buyer", GREEN)
    body.append(f'<line x1="{xs[0]}" y1="270" x2="{xs[0]}" y2="{py - 44}" stroke="#a0aec0" stroke-width="2" stroke-dasharray="4 5"/>')
    body.append(f'<line x1="{xs[1]}" y1="270" x2="{xs[1]}" y2="{py - 44}" stroke="#a0aec0" stroke-width="2" stroke-dasharray="4 5"/>')
    body.append(arrow(xs[2], py - 46, xs[2], 262, GREEN, 3))
    body.append(text(xs[2] + 12, 335, "buy 20 Feb", 19, fill=GREEN, anchor="start"))
    body.append(arrow(xs[0] + 50, py, xs[1] - 55, py, BLUE, 5))
    body.append(text((xs[0] + xs[1]) / 2, py - 18, "20 January @ $75.00", 21, "bold", BLUE))
    body.append(arrow(xs[1] + 50, py, xs[2] - 55, py, PURPLE, 5))
    body.append(text((xs[1] + xs[2]) / 2, py - 18, "20 February @ $77.00", 21, "bold", PURPLE))
    body.append(f'<path d="M {xs[0]} {py + 95} Q 600 {py + 230} {xs[2]} {py + 95}" fill="none" '
                f'stroke="{RED}" stroke-width="3" stroke-dasharray="10 8"/>')
    body.append(text(600, py + 205, "✗  A and C never trade with each other", 22, "bold", RED))
    body.append(text(600, h - 50, "Arrows show where the oil goes. All three fills happen together or not at all.", 20, fill=MUTED))
    body.append(text(600, h - 20, "B ends up long 20 Jan and short 20 Feb: exactly the 20 spreads B asked for.", 20, fill=MUTED))
    return svg(w, h, body), w, h


def vector_sum() -> tuple[str, int, int]:
    w, h = 1200, 600
    cols = {"Jan": 560, "Feb": 760, "Cash": 990}
    cw, ch = 150, 70
    body = [text(600, 40, "Adding two orders: the January legs cancel", 28, "bold")]
    for k, x in cols.items():
        body.append(text(x, 100, k if k != "Cash" else "Cash paid c", 24, "bold", MUTED))

    def cell(col: str, y: float, val: str, colour: str | None) -> None:
        x = cols[col]
        if colour:
            body.append(rect(x - cw / 2, y - ch / 2, cw, ch, colour, opacity=0.9))
            body.append(text(x, y + 11, val, 30, "bold", "white"))
        else:
            body.append(text(x, y + 11, val, 30, "bold"))

    rows = [(180, "A: sell Jan @ 75.00", {"Jan": ("−1", RED)}, "−75.00"),
            (290, "B: buy spread @ −2.00", {"Jan": ("+1", GREEN), "Feb": ("−1", RED)}, "−2.00")]
    for y, label, cells, cash in rows:
        body.append(text(70, y + 9, label, 24, anchor="start"))
        for col, (val, colour) in cells.items():
            cell(col, y, val, colour)
        cell("Cash", y, cash, None)
    body.append(f'<line x1="60" y1="360" x2="1110" y2="360" stroke="{DARK}" stroke-width="3"/>')
    body.append(text(70, 362 + 72, "Combined", 24, "bold", anchor="start"))
    yj = 425
    x = cols["Jan"]
    body.append(rect(x - cw / 2, yj - ch / 2, cw, ch, "white", "#a0aec0", dash=True))
    body.append(text(x, yj + 11, "0", 30, "bold", "#a0aec0"))
    body.append(text(x, yj + 62, "−1 + 1 cancel", 18, fill=MUTED))
    cell("Feb", yj, "−1", RED)
    cell("Cash", yj, "−77.00", None)
    body.append(text(cols["Cash"], yj + 62, "−75.00 − 2.00", 18, fill=MUTED))
    body.append(rect(160, 525, 880, 50, "#fffaf0", ORANGE))
    body.append(text(600, 558, "What is left: sell 1 February, receive $77.00 = an implied February ask at $77.00", 21, "bold", ORANGE))
    body.append(rect(60, 75, 22, 22, GREEN, rx=4) + text(90, 93, "buy (+1)", 18, anchor="start"))
    body.append(rect(60, 105, 22, 22, RED, rx=4) + text(90, 123, "sell (−1)", 18, anchor="start"))
    return svg(w, h, body), w, h


def triangle() -> tuple[str, int, int]:
    w, h = 1150, 1300
    rows = [
        ("feb", "Implied OUT to February", "January + spread → February",
         ["Feb ask = Jan ask − Spread bid", "Feb bid = Jan bid − Spread ask"],
         "Opposite side: a spread bid makes a Feb ask."),
        ("jan", "Implied OUT to January", "February + spread → January",
         ["Jan ask = Feb ask + Spread ask", "Jan bid = Feb bid + Spread bid"],
         "Same side: a spread ask makes a Jan ask."),
        ("spr", "Implied IN to the spread", "January + February → spread",
         ["Spread ask = Jan ask − Feb bid", "Spread bid = Jan bid − Feb ask"],
         "Opposite sides: a Jan ask with a Feb bid."),
    ]
    body = []
    for i, (target, title, sub, formulas, rule) in enumerate(rows):
        oy = 60 + 420 * i
        pos = {"jan": (130, oy + 40), "feb": (430, oy + 40), "spr": (280, oy + 300)}
        names = {"jan": "January", "feb": "February", "spr": "Jan/Feb spread"}
        for a, b in [("jan", "feb"), ("feb", "spr"), ("spr", "jan")]:
            (x1, y1), (x2, y2) = pos[a], pos[b]
            body.append(f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{GREY}" stroke-width="3"/>')
        for k, (x, y) in pos.items():
            if k == target:
                continue
            tx, ty = pos[target]
            d = ((tx - x) ** 2 + (ty - y) ** 2) ** 0.5
            body.append(arrow(x + (tx - x) * 70 / d, y + (ty - y) * 70 / d,
                              tx - (tx - x) * 80 / d, ty - (ty - y) * 80 / d, ORANGE, 6))
        for k, (x, y) in pos.items():
            hl = k == target
            body.append(rect(x - 85, y - 32, 170, 64, "#fffaf0" if hl else BLUE, ORANGE if hl else "none",
                             dash=hl, sw=3))
            label = names[k] if k != "spr" else "Spread"
            body.append(text(x, y + 9, label, 22, "bold", ORANGE if hl else "white"))
        tx = 600
        body.append(text(tx, oy + 30, title, 30, "bold", anchor="start"))
        body.append(text(tx, oy + 68, sub, 22, fill=MUTED, anchor="start"))
        for k, f in enumerate(formulas):
            body.append(text(tx, oy + 130 + 42 * k, f, 25, "bold", anchor="start"))
        body.append(text(tx, oy + 245, rule, 20, fill=MUTED, anchor="start", style="italic"))
        if i < 2:
            body.append(f'<line x1="30" y1="{oy + 385}" x2="{w - 30}" y2="{oy + 385}" stroke="{GREY}" stroke-width="1"/>')
    body.append(text(w / 2, h - 20, "Any two of the three books imply the third: 3 targets × 2 sides = 6 formulas.", 22, "bold"))
    return svg(w, h, body), w, h


def shared_leg() -> tuple[str, int, int]:
    w, h = 1200, 640
    body = [text(600, 40, "One January ask, two spread bids: the shared leg", 28, "bold")]
    body.append(rect(40, 230, 260, 110, BLUE))
    body.append(text(170, 273, "A: January ask", 22, "bold", "white"))
    body.append(text(170, 310, "40 lots @ $75.00", 22, fill="white"))
    for y, who, n in [(110, "B", 30), (420, "H", 15)]:
        body.append(rect(400, y, 260, 110, PURPLE))
        body.append(text(530, y + 43, f"{who}: spread bid", 22, "bold", "white"))
        body.append(text(530, y + 80, f"{n} spreads @ −$2.00", 22, fill="white"))
        body.append(arrow(300, 285, 395, y + 55, ORANGE, 4))
    body.append(text(170, 375, "both draw on", 19, "bold", ORANGE))
    body.append(text(170, 400, "the same 40 lots", 19, "bold", ORANGE))
    base, scale, bw = 560, 8, 140
    for x, label, parts, caption in [
        (790, "Naive", [(30, PURPLE, "30 (A+B)"), (10, PURPLE, "10 (A+H)"), (5, RED, "+5 phantom")],
         "min(40,30) + min(40,15) = 45"),
        (1010, "Correct", [(40, ORANGE, "40 shared")], "min(40, 30 + 15) = 40"),
    ]:
        y = base
        for n, colour, t in parts:
            hh = n * scale
            y -= hh
            if colour == RED:
                body.append(f'<rect x="{x - bw / 2}" y="{y}" width="{bw}" height="{hh}" fill="white" stroke="{RED}" '
                            f'stroke-width="3" stroke-dasharray="6 5"/>')
                body.append(text(x, y + hh / 2 + 7, t, 18, "bold", RED))
            else:
                body.append(f'<rect x="{x - bw / 2}" y="{y}" width="{bw}" height="{hh}" fill="{colour}" '
                            f'stroke="white" stroke-width="2"/>')
                body.append(text(x, y + hh / 2 + 8, t, 20, "bold", "white"))
        body.append(text(x, y - 15, f"{label}: {sum(p[0] for p in parts)} lots", 22, "bold"))
        body.append(text(x, base + 30, caption, 17, fill=MUTED))
    body.append(f'<line x1="700" y1="{base}" x2="1110" y2="{base}" stroke="{DARK}" stroke-width="2"/>')
    body.append(f'<line x1="700" y1="{base - 40 * scale}" x2="1110" y2="{base - 40 * scale}" stroke="{BLUE}" '
                f'stroke-width="2" stroke-dasharray="6 5"/>')
    body.append(text(1115, base - 40 * scale + 6, "A has 40", 17, "bold", BLUE, anchor="start"))
    body.append(text(900, 90, "Implied February ask at $77.00", 22, "bold"))
    body.append(text(600, h - 15, "The naive sum counts some of A's January lots twice; only 40 February lots can ever be delivered.", 19, fill=MUTED))
    return svg(w, h, body), w, h


def sign_convention() -> tuple[str, int, int]:
    w, h = 1200, 1100
    body = [text(600, 42, "The sign convention: S = Near − Far = Jan − Feb", 30, "bold")]

    def py(p: float) -> float:
        return 470 - (p - 74.5) * 100

    panels = [(300, "Contango: far month dearer", 75.00, 77.00, RED),
              (900, "Backwardation: near month dearer", 76.50, 76.00, GREEN)]
    for cx, title, jan, feb, colour in panels:
        s = jan - feb
        body.append(rect(cx - 280, 70, 560, 470, LIGHT, GREY))
        body.append(text(cx, 108, title, 23, "bold"))
        ax = cx - 170
        body.append(f'<line x1="{ax}" y1="{py(77.5)}" x2="{ax}" y2="{py(74.5)}" stroke="{MUTED}" stroke-width="2"/>')
        for p in (75.0, 75.5, 76.0, 76.5, 77.0):
            body.append(f'<line x1="{ax - 8}" y1="{py(p)}" x2="{ax}" y2="{py(p)}" stroke="{MUTED}" stroke-width="2"/>')
            body.append(text(ax - 14, py(p) + 6, f"{p:.2f}", 16, fill=MUTED, anchor="end"))
        for p, label, x in ((jan, "Jan (near)", ax + 60), (feb, "Feb (far)", ax + 60)):
            body.append(f'<line x1="{ax}" y1="{py(p)}" x2="{ax + 230}" y2="{py(p)}" stroke="{GREY}" stroke-width="2" stroke-dasharray="5 5"/>')
            body.append(f'<circle cx="{x}" cy="{py(p)}" r="9" fill="{BLUE}"/>')
            body.append(text(x + 18, py(p) + 7, f"{label} ${p:.2f}", 20, "bold", anchor="start"))
        sx = ax + 260
        body.append(arrow(sx, py(feb), sx, py(jan) + (6 if jan < feb else -6), colour, 5))
        signed = f"{s:+.2f}".replace("-", "−")
        body.append(text(sx + 18, (py(jan) + py(feb)) / 2 + 8, f"S = {signed}", 24, "bold", colour, "start"))
        body.append(text(cx, 505, f"S = {jan:.2f} − {feb:.2f} = {signed}", 21, fill=MUTED))
    body.append(text(600, 580, "Read S as the step from Feb to Jan: a step down is negative, a step up is positive.", 20, fill=MUTED, style="italic"))

    y0, x_lo, x_hi = 780, 120, 1080

    def nx(v: float) -> float:
        return x_lo + (v + 3.0) / 4.0 * (x_hi - x_lo)

    body.append(text(600, 640, "Spread prices live on a signed number line", 24, "bold"))
    body.append(arrow(x_lo - 30, y0, x_hi + 40, y0, DARK, 3))
    for i in range(9):
        v = -3.0 + 0.5 * i
        lab = "0" if v == 0 else f"{v:+.2f}".replace("-", "−")
        body.append(f'<line x1="{nx(v)}" y1="{y0 - 10}" x2="{nx(v)}" y2="{y0 + 10}" stroke="{DARK}" stroke-width="2"/>')
        body.append(text(nx(v), y0 + 38, lab, 18, "bold" if v == 0 else "normal", MUTED))
    body.append(text(x_lo - 30, y0 - 22, "lower", 18, fill=MUTED, anchor="start"))
    body.append(text(x_hi + 40, y0 - 22, "higher", 18, fill=MUTED, anchor="end"))
    body.append(f'<circle cx="{nx(-2.0)}" cy="{y0}" r="10" fill="{RED}"/>')
    body.append(f'<circle cx="{nx(0.5)}" cy="{y0}" r="10" fill="{GREEN}"/>')
    body.append(f'<path d="M {nx(-2.0)} {y0 - 16} Q {nx(-1.75)} {y0 - 70} {nx(-1.5) - 4} {y0 - 20}" fill="none" '
                f'stroke="{PURPLE}" stroke-width="4" marker-end="url(#a-purple)"/>')
    body.append(text(nx(-1.5) + 30, y0 - 58, "S rises −2.00 → −1.50: a spread buyer gains $0.50/bbl = $500 per lot",
                     19, "bold", PURPLE, "start"))
    body.append(text(nx(-2.0), y0 + 72, "contango example", 18, fill=RED))
    body.append(text(nx(0.5), y0 + 72, "backwardation example", 18, fill=GREEN))

    body.append(rect(80, 870, 500, 100, "#f0fff4", GREEN))
    body.append(text(330, 908, "Buy 1 spread = buy 1 Jan + sell 1 Feb", 21, "bold", GREEN))
    body.append(text(330, 945, "profits when S rises; best bid = highest S", 19, fill=MUTED))
    body.append(rect(620, 870, 500, 100, "#fff5f5", RED))
    body.append(text(870, 908, "Sell 1 spread = sell 1 Jan + buy 1 Feb", 21, "bold", RED))
    body.append(text(870, 945, "profits when S falls; best ask = lowest S", 19, fill=MUTED))
    body.append(text(600, 1020, "A bid of −1.90 beats a bid of −2.00; an ask of −2.10 beats an ask of −2.00.", 20, fill=DARK))
    body.append(text(600, 1060, "Feb = Jan − S   and   Jan = Feb + S   (with S = −2.00: Feb = 75.00 − (−2.00) = 77.00)", 20, "bold", DARK))
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
        for name, fn in [("implied-wrong-book", wrong_book), ("implied-vector-sum", vector_sum),
                         ("implied-triangle", triangle), ("implied-shared-leg", shared_leg),
                         ("implied-sign-convention", sign_convention)]:
            render(args.chrome, name, fn(), Path(tmp))


if __name__ == "__main__":
    main()
