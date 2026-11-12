#!/usr/bin/env python3
"""Generate the graph figures for the multi-layer implied orders chapter.

Writes to assets/:
  implied-hub-78-edges.png      12 months + $ hub: every book is one line
  implied-routes-by-gen.png     routes from $ to December, generations 0-3
  implied-cancel-ripple.png     books one cancelled order can affect, by depth
  implied-route-wall.png        cumulative route count per generation (log scale)

Used in src/02-orders-and-matching/14-multi-layer-implied-orders-and-the-combinatorial-wall.md.
Builds SVGs and renders them to PNG with headless Google Chrome.

Usage: python3 scripts/gen_implied_multilayer_figures.py [--chrome PATH]
"""
from __future__ import annotations

import argparse
import itertools
import math
import subprocess
import tempfile
from pathlib import Path

DEFAULT_CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
ASSETS = Path(__file__).resolve().parent.parent / "assets"

M = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
CASH = "$"
BLUE, ORANGE, GREY, DARK = "#2b6cb0", "#dd6b20", "#cbd5e0", "#1a202c"
RED, AMBER, GOLD = "#c53030", "#ed8936", "#ecc94b"
FONT = 'font-family="Helvetica, Arial, sans-serif"'


def text(x: float, y: float, s: str, size: int = 22, weight: str = "normal",
         fill: str = DARK, anchor: str = "middle") -> str:
    return (f'<text x="{x:.1f}" y="{y:.1f}" {FONT} font-size="{size}" font-weight="{weight}" '
            f'fill="{fill}" text-anchor="{anchor}">{s}</text>')


def layout(cx: float, cy: float, r: float) -> dict[str, tuple[float, float]]:
    pos = {m: (cx + r * math.sin(2 * math.pi * i / 12), cy - r * math.cos(2 * math.pi * i / 12))
           for i, m in enumerate(M)}
    pos[CASH] = (cx, cy)
    return pos


def line(pos: dict[str, tuple[float, float]], a: str, b: str, colour: str,
         opacity: float, width: float, arrow: bool = False) -> str:
    (x1, y1), (x2, y2) = pos[a], pos[b]
    if arrow:  # stop short of the target node so the arrow head stays visible
        d = math.hypot(x2 - x1, y2 - y1)
        x2, y2 = x2 - (x2 - x1) * 30 / d, y2 - (y2 - y1) * 30 / d
    marker = ' marker-end="url(#arrow)"' if arrow else ""
    return (f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="{colour}" '
            f'stroke-opacity="{opacity:.2f}" stroke-width="{width}" stroke-linecap="round"{marker}/>')


def nodes(pos: dict[str, tuple[float, float]], r: int = 24, size: int = 15,
          highlight: frozenset[str] = frozenset()) -> list[str]:
    out = []
    for n, (x, y) in pos.items():
        fill = DARK if n == CASH else (RED if n in highlight else BLUE)
        out.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r}" fill="{fill}" stroke="white" stroke-width="3"/>')
        out.append(text(x, y + size * 0.36, n, size, "bold", "white"))
    return out


ALL_EDGES = [(m, CASH) for m in M] + list(itertools.combinations(M, 2))


def svg(w: int, h: int, body: list[str]) -> str:
    defs = (f'<defs><marker id="arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="5" '
            f'markerHeight="5" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="{DARK}"/></marker></defs>')
    return "\n".join([f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">',
                      defs, f'<rect width="{w}" height="{h}" fill="white"/>', *body, "</svg>"])


def hub() -> tuple[str, int, int]:
    w, h = 1200, 1000
    pos = layout(600, 440, 340)
    body = [line(pos, a, b, ORANGE, 0.5, 2) for a, b in ALL_EDGES if b != CASH]
    body += [line(pos, m, CASH, BLUE, 0.9, 4) for m in M]
    body += nodes(pos, 36, 22)
    body.append(f'<line x1="170" y1="870" x2="220" y2="870" stroke="{BLUE}" stroke-width="5"/>')
    body.append(text(232, 878, "12 spokes = 12 outright books (month ↔ cash)", 22, anchor="start"))
    body.append(f'<line x1="170" y1="910" x2="220" y2="910" stroke="{ORANGE}" stroke-width="4"/>')
    body.append(text(232, 918, "66 chords = 66 spread books (month ↔ month)", 22, anchor="start"))
    body.append(text(600, 975, "13 points, every pair joined: 13 × 12 / 2 = 78 lines = 78 books", 26, "bold"))
    return svg(w, h, body), w, h


def routes(gen: int) -> list[list[str]]:
    others = M[:-1]
    return [[CASH, *mid, "Dec"] for mid in itertools.permutations(others, gen)]


def routes_by_gen() -> tuple[str, int, int]:
    w, h = 1200, 1300
    examples = {0: [CASH, "Dec"], 1: [CASH, "Mar", "Dec"], 2: [CASH, "Mar", "Aug", "Dec"],
                3: [CASH, "Feb", "Sep", "May", "Dec"]}
    body = []
    for g in range(4):
        cx, cy = 300 + 600 * (g % 2), 300 + 600 * (g // 2)
        pos = layout(cx, cy, 220)
        rs = routes(g)
        use: dict[frozenset[str], int] = {}
        for r in rs:
            for a, b in zip(r, r[1:]):
                use[frozenset((a, b))] = use.get(frozenset((a, b)), 0) + 1
        top = max(use.values())
        for a, b in ALL_EDGES:
            n = use.get(frozenset((a, b)), 0)
            body.append(line(pos, a, b, ORANGE, 0.15 + 0.75 * n / top, 2.5) if n
                        else line(pos, a, b, GREY, 0.35, 1))
        ex = examples[g]
        body += [line(pos, a, b, DARK, 1, 5, arrow=True) for a, b in zip(ex, ex[1:])]
        body += nodes(pos, highlight=frozenset({"Dec"}))
        label = "direct" if g == 0 else f"{g} intermediate month{'s' if g > 1 else ''}"
        body.append(text(cx, cy + 275, f"Generation {g}: {len(rs):,} route{'s' if len(rs) > 1 else ''}", 26, "bold"))
        body.append(text(cx, cy + 305, f"({label}; example: {' → '.join(ex)})", 18, fill="#4a5568"))
    body.append(text(600, 1275, "Implied December ask: every simple path from $ to Dec. Darker lines are used by more routes.", 20))
    return svg(w, h, body), w, h


def ripple() -> tuple[str, int, int]:
    w, h = 1100, 1530
    gen0 = {frozenset(("Jun", CASH))}
    gen1 = {frozenset((m, CASH)) for m in M} | {frozenset(("Jun", m)) for m in M if m != "Jun"}
    gen2 = {frozenset(e) for e in ALL_EDGES}
    panels = [
        ("The cancelled order", ["June ask: 1 book"], [(gen0, RED, "the June book itself")]),
        ("Generation ≤ 1", ["23 books can change"],
         [(gen1 - gen0, AMBER, "+ 11 outrights, + 11 June spreads"), (gen0, RED, "")]),
        ("Generation ≤ 2", ["all 78 books can change"],
         [(gen2 - gen1, GOLD, "+ the other 55 spreads"), (gen1 - gen0, AMBER, ""), (gen0, RED, "")]),
    ]
    body = []
    for i, (title, subs, layers) in enumerate(panels):
        cx, cy = 280, 255 + 505 * i
        pos = layout(cx, cy, 210)
        lit = set().union(*(s for s, _, _ in layers))
        body += [line(pos, a, b, GREY, 0.35, 1) for a, b in ALL_EDGES if frozenset((a, b)) not in lit]
        for s, colour, _ in layers:
            body += [line(pos, *sorted(e, key=lambda n: n == CASH), colour, 0.95, 3.5 if colour == RED else 2.5)
                     for e in s]
        body += nodes(pos, highlight=frozenset({"Jun"}))
        tx = 580
        body.append(text(tx, cy - 40, title, 32, "bold", anchor="start"))
        for k, sub in enumerate(subs):
            body.append(text(tx, cy + 5 + 34 * k, sub, 26, anchor="start"))
        y = cy + 60
        for _, colour, label in layers:
            if label:
                body.append(f'<line x1="{tx}" y1="{y - 7}" x2="{tx + 40}" y2="{y - 7}" stroke="{colour}" stroke-width="5"/>')
                body.append(text(tx + 52, y, label, 20, anchor="start"))
                y += 34
        if i < 2:
            body.append(f'<line x1="40" y1="{cy + 252}" x2="{w - 40}" y2="{cy + 252}" stroke="{GREY}" stroke-width="1"/>')
    return svg(w, h, body), w, h


def wall() -> tuple[str, int, int]:
    w, h = 1200, 720
    exact = [math.factorial(11) // math.factorial(11 - g) for g in range(12)]
    cum = list(itertools.accumulate(exact))
    x0, y0, plot_w, plot_h = 140, 620, 1010, 520
    body = []
    for k in range(9):  # 10^0 .. 10^8
        y = y0 - plot_h * k / 8
        body.append(f'<line x1="{x0}" y1="{y:.1f}" x2="{x0 + plot_w}" y2="{y:.1f}" stroke="{GREY}" stroke-width="1"/>')
        body.append(text(x0 - 12, y + 7, f"{10 ** k:,}", 17, anchor="end", fill="#4a5568"))
    bw = plot_w / 12
    for g, c in enumerate(cum):
        bh = plot_h * math.log10(c) / 8
        x = x0 + g * bw + bw * 0.15
        body.append(f'<rect x="{x:.1f}" y="{y0 - bh:.1f}" width="{bw * 0.7:.1f}" height="{max(bh, 2):.1f}" fill="{ORANGE}"/>')
        body.append(text(x + bw * 0.35, y0 - bh - 10, f"{c:,}", 15, "bold"))
        body.append(text(x + bw * 0.35, y0 + 28, str(g), 20))
    body.append(text(x0 + plot_w / 2, y0 + 62, "Maximum generation allowed", 22, "bold"))
    body.append(text(x0 + plot_w / 2, 45, "Routes from $ to December, up to each generation (12-month strip, log scale)", 24, "bold"))
    body.append(f'<text transform="translate(40,{y0 - plot_h / 2}) rotate(-90)" {FONT} font-size="20" '
                f'fill="{DARK}" text-anchor="middle">Number of routes (each gridline = ×10)</text>')
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
        for name, fn in [("implied-hub-78-edges", hub), ("implied-routes-by-gen", routes_by_gen),
                         ("implied-cancel-ripple", ripple), ("implied-route-wall", wall)]:
            render(args.chrome, name, fn(), Path(tmp))


if __name__ == "__main__":
    main()
