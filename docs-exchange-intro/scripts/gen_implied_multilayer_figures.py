#!/usr/bin/env python3
"""Generate the graph figures for the multi-layer implied orders chapter.

Writes to assets/:
  implied-hub-78-edges.png      12 months + $ hub: every book is one line
  implied-routes-by-gen.png     routes from $ to December, generations 0-3
  implied-cancel-ripple.png     books one cancelled order can affect, by depth
  implied-route-wall.png        cumulative route count per generation (log scale)
  implied-edge-rules.png        the four kinds of edge: outright/spread, bid/ask
  implied-relaxation.png        one Bellman-Ford relaxation step
  implied-bellman-ford-rounds.png  the cheapest-March search, one panel per round
  implied-crossed-cycle.png     a cycle of resting orders, uncrossed and crossed

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


GREEN, MUTED = "#2f855a", "#4a5568"


def arrow(x1: float, y1: float, x2: float, y2: float, colour: str, width: float,
          bend: float = 0, gap: float = 40, opacity: float = 1) -> str:
    """Arrow from node centre (x1, y1) to node centre (x2, y2), stopping `gap` short of each
    end; `bend` > 0 curves it to the left of the direction of travel."""
    d = math.hypot(x2 - x1, y2 - y1)
    ux, uy = (x2 - x1) / d, (y2 - y1) / d
    sx, sy, ex, ey = x1 + ux * gap, y1 + uy * gap, x2 - ux * (gap + 6), y2 - uy * (gap + 6)
    cx, cy = (sx + ex) / 2 + uy * bend, (sy + ey) / 2 - ux * bend
    return (f'<path d="M {sx:.1f} {sy:.1f} Q {cx:.1f} {cy:.1f} {ex:.1f} {ey:.1f}" fill="none" '
            f'stroke="{colour}" stroke-opacity="{opacity:.2f}" stroke-width="{width}" '
            f'marker-end="url(#arrow-{colour[1:]})"/>')


def node(x: float, y: float, name: str, r: int = 38, size: int = 22) -> list[str]:
    fill = DARK if name == CASH else BLUE
    return [f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r}" fill="{fill}" stroke="white" stroke-width="3"/>',
            text(x, y + size * 0.36, name, size, "bold", "white")]


def tag(x: float, y: float, s: str, colour: str, size: int = 22, weight: str = "bold") -> list[str]:
    """A label on a white backing box, so it stays readable on top of lines."""
    w = len(s) * size * 0.56 + 16
    return [f'<rect x="{x - w / 2:.1f}" y="{y - size * 0.9:.1f}" width="{w:.1f}" height="{size * 1.3:.1f}" '
            f'rx="6" fill="white" stroke="{colour}" stroke-width="2"/>',
            text(x, y, s, size, weight, colour)]


def svg_arrows(w: int, h: int, body: list[str]) -> str:
    defs = "".join(f'<marker id="arrow-{c[1:]}" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="4" '
                   f'markerHeight="4" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="{c}"/></marker>'
                   for c in (DARK, ORANGE, GREY, GREEN, RED, BLUE))
    return "\n".join([f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">',
                      f"<defs>{defs}</defs>", f'<rect width="{w}" height="{h}" fill="white"/>', *body, "</svg>"])


def edge_rules() -> tuple[str, int, int]:
    """The four kinds of edge, drawn between Jan, Feb and $."""
    w, h = 1200, 720
    pos = {"Jan": (300, 170), "Feb": (900, 170), CASH: (600, 560)}
    body: list[str] = []
    for (a, b, colour, l1, l2, lx, ly) in [
        ("Jan", CASH, GREEN, "Jan bid 74.40", "weight +74.40", 620, 400),
        (CASH, "Jan", RED, "Jan ask 75.00", "weight −75.00", 230, 420),
        ("Jan", "Feb", GREEN, "Jan/Feb spread bid −2.00", "weight −2.00", 600, 70),
        ("Feb", "Jan", RED, "Jan/Feb spread ask −1.80", "weight +1.80", 650, 260),
    ]:
        body.append(arrow(*pos[a], *pos[b], colour, 4, bend=70))
        body.append(text(lx, ly, l1, 22, "bold", colour))
        body.append(text(lx, ly + 28, l2, 20, fill=MUTED))
    body.append(f'<line x1="{pos["Feb"][0]}" y1="{pos["Feb"][1]}" x2="{pos[CASH][0]}" y2="{pos[CASH][1]}" '
                f'stroke="{GREY}" stroke-width="2" stroke-dasharray="6 6"/>')
    body.append(text(860, 420, "(Feb outright book:", 18, fill=MUTED))
    body.append(text(860, 444, "same rules)", 18, fill=MUTED))
    for n, (x, y) in pos.items():
        body += node(x, y, n, 46, 26)
    body.append(text(600, 660, "Every arrow runs FROM what the order buys TO what it gives up.", 24, "bold"))
    body.append(text(600, 694, "Green = a bid (the order buys the first-named instrument); red = an ask.", 20, fill=MUTED))
    return svg_arrows(w, h, body), w, h


def relaxation() -> tuple[str, int, int]:
    """One relaxation step: can going via u improve the best known cost of v?"""
    w, h = 1200, 470
    ux, vx, y = 230, 700, 200
    body = [arrow(ux, y, vx, y, ORANGE, 5, gap=56)]
    body += tag((ux + vx) / 2, y - 22, "edge cost 0.60", ORANGE, 20)
    body.append(text((ux + vx) / 2, y + 40, "Jan/Feb spread bid −2.00 turns", 18, fill=MUTED))
    body.append(text((ux + vx) / 2, y + 62, "one January lot into one February lot", 18, fill=MUTED))
    body += node(ux, y, "Jan", 50, 26) + node(vx, y, "Feb", 50, 26)
    body += tag(ux, y - 80, "best: 70.00", DARK, 20)
    body += tag(vx, y - 80, "best so far: 70.70", DARK, 20)
    tx = 840
    body.append(text(tx, 150, "Is 70.00 + 0.60 &lt; 70.70 ?", 24, "bold", anchor="start"))
    body.append(text(tx, 186, "70.60 &lt; 70.70: yes.", 22, anchor="start"))
    body.append(text(tx, 230, "So: Feb's best = 70.60,", 22, "bold", GREEN, anchor="start"))
    body.append(text(tx, 262, "reached via Jan.", 22, "bold", GREEN, anchor="start"))
    body.append(f'<line x1="40" y1="330" x2="{w - 40}" y2="330" stroke="{GREY}" stroke-width="1"/>')
    body.append(text(600, 378, "Relaxing an edge u → v:  if best(u) + cost(u → v) &lt; best(v),", 24, "bold"))
    body.append(text(600, 414, "set best(v) to the smaller value and remember that it came from u.", 24, "bold"))
    body.append(text(600, 450, "Bellman–Ford does nothing else: it relaxes every edge, round after round.", 20, fill=MUTED))
    return svg_arrows(w, h, body), w, h


BF_EDGES = [(CASH, "Jan", 70.00), (CASH, "Feb", 70.70), (CASH, "Mar", 71.20),
            ("Jan", "Feb", 0.60), ("Feb", "Mar", 0.45), ("Jan", "Mar", 1.10)]


def bellman_ford_rounds() -> tuple[str, int, int]:
    """The step-by-step search for the cheapest March lot, one panel per round."""
    w, h = 1200, 1180
    best: dict[str, float] = {CASH: 0.0}
    via: dict[str, str] = {}
    panels = []
    for k in range(1, 5):
        prev, changed = dict(best), {}
        for a, b, c in BF_EDGES:
            if a in prev and prev[a] + c < best.get(b, math.inf) - 1e-9:
                best[b], via[b] = prev[a] + c, a
                changed[b] = a
        panels.append((k, dict(best), changed, dict(via)))
    subtitles = {1: "at most 1 order: generation 0", 2: "at most 2 orders: generation ≤ 1",
                 3: "at most 3 orders: generation ≤ 2", 4: "no change: stop"}
    body: list[str] = []
    for i, (k, b, changed, v) in enumerate(panels):
        ox, oy = 600 * (i % 2), 560 * (i // 2)
        pos = {CASH: (ox + 300, oy + 420), "Jan": (ox + 110, oy + 230), "Feb": (ox + 300, oy + 230),
               "Mar": (ox + 490, oy + 230)}
        final = k == 4
        route = {("Feb", "Mar"), ("Jan", "Feb"), (CASH, "Jan")} if final else set()
        for a, bb, c in BF_EDGES:
            hot = changed.get(bb) == a
            colour, width = (DARK, 6) if (a, bb) in route else (ORANGE, 6) if hot else (GREY, 2.5)
            bend = 150 if (a, bb) == ("Jan", "Mar") else 0
            body.append(arrow(*pos[a], *pos[bb], colour, width, bend=bend, gap=36))
            (x1, y1), (x2, y2) = pos[a], pos[bb]
            lx, ly = (x1 + x2) / 2, (y1 + y2) / 2 - 10
            if bend:
                ly -= 80
            elif a == CASH:  # beside the spoke, not on it
                lx, ly = (x1 + x2) / 2 + (-40 if bb == "Jan" else 40), (y1 + y2) / 2 + 20
            body.append(text(lx, ly, f"{c:.2f}", 17, "bold", DARK if colour != GREY else MUTED))
        for n, (x, y) in pos.items():
            body += node(x, y, n, 32, 20)
            if n == CASH:
                body.append(text(x, y + 56, "start: cost 0", 17, fill=MUTED))
                continue
            if n not in b:
                body += tag(x, y - 52, "—", GREY, 18)
            else:
                body += tag(x, y - 52, f"{b[n]:.2f}", ORANGE if n in changed else DARK, 18)
        body.append(text(ox + 300, oy + 50, f"Round {k}", 28, "bold"))
        body.append(text(ox + 300, oy + 82, subtitles[k], 20, fill=MUTED))
        if k == 2:
            body.append(text(ox + 490, oy + 300, "Mar candidates:", 15, fill=MUTED))
            body.append(text(ox + 490, oy + 320, "71.20 · 71.15 · 71.10", 15, fill=MUTED))
        if final:
            body.append(text(ox + 300, oy + 510, "Best March ask 71.05 via $ → Jan → Feb → Mar", 19, "bold"))
    body.append(f'<line x1="600" y1="20" x2="600" y2="1100" stroke="{GREY}" stroke-width="1"/>')
    body.append(f'<line x1="20" y1="560" x2="1180" y2="560" stroke="{GREY}" stroke-width="1"/>')
    body.append(text(600, 1145, "Boxes: cheapest known cost to get long each month. Orange: improved this round, "
                     "and the edge that improved it.", 19, fill=MUTED))
    return svg_arrows(w, h, body), w, h


def crossed_cycle() -> tuple[str, int, int]:
    """A cycle of three resting orders: uncrossed (weight < 0) and crossed (weight >= 0)."""
    w, h = 1200, 640
    body: list[str] = []
    for i, (feb_bid, colour, verdict, note) in enumerate([
        (76.93, GREEN, "Sum −0.02 &lt; 0: not crossed", "Feb bid 76.93 is below the implied ask 76.95"),
        (76.97, RED, "Sum +0.02 ≥ 0: crossed", "the three orders can trade with each other"),
    ]):
        ox = 600 * i
        pos = {CASH: (ox + 300, 470), "Jan": (ox + 120, 200), "Feb": (ox + 480, 200)}
        for a, b, wt, label, lx, ly in [
            (CASH, "Jan", -74.95, "Jan ask 74.95", ox + 115, 360),
            ("Jan", "Feb", -2.00, "spread bid −2.00", ox + 300, 120),
            ("Feb", CASH, feb_bid, f"Feb bid {feb_bid:.2f}", ox + 485, 360),
        ]:
            body.append(arrow(*pos[a], *pos[b], colour, 4.5, bend=45, gap=42))
            body.append(text(lx, ly, label, 19, "bold", colour))
            body.append(text(lx, ly + 26, f"weight {wt:+.2f}".replace("-", "−"), 18, fill=MUTED))
        for n, (x, y) in pos.items():
            body += node(x, y, n, 40, 24)
        body.append(text(ox + 300, 50, f"With a February bid at {feb_bid:.2f}", 24, "bold"))
        body.append(text(ox + 300, 560, verdict, 23, "bold", colour))
        body.append(text(ox + 300, 592, note, 18, fill=MUTED))
    body.append(f'<line x1="600" y1="20" x2="600" y2="620" stroke="{GREY}" stroke-width="1"/>')
    return svg_arrows(w, h, body), w, h


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
                         ("implied-cancel-ripple", ripple), ("implied-route-wall", wall),
                         ("implied-edge-rules", edge_rules), ("implied-relaxation", relaxation),
                         ("implied-bellman-ford-rounds", bellman_ford_rounds),
                         ("implied-crossed-cycle", crossed_cycle)]:
            render(args.chrome, name, fn(), Path(tmp))


if __name__ == "__main__":
    main()
