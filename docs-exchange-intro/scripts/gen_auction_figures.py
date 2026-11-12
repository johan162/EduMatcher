#!/usr/bin/env python3
"""Generate the figures for the opening and closing auction chapter.

Writes to assets/:
  auction-equilibrium.png   cumulative buy/sell curves and executable volume for the worked example

Used in src/02-orders-and-matching/10-the-opening-and-closing-auction.md.
Builds SVGs and renders them to PNG with headless Google Chrome.

Usage: python3 scripts/gen_auction_figures.py [--chrome PATH]
"""
from __future__ import annotations

import argparse
import subprocess
import tempfile
from pathlib import Path

DEFAULT_CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
ASSETS = Path(__file__).resolve().parent.parent / "assets"

BLUE, ORANGE, RED, GREEN, DARK, MUTED, GREY = "#2b6cb0", "#dd6b20", "#c53030", "#2f855a", "#1a202c", "#4a5568", "#cbd5e0"
FONT = 'font-family="Helvetica, Arial, sans-serif"'

BIDS = {152: 500, 151: 1000, 150: 800}
ASKS = {150: 600, 151: 900, 152: 800}
PRICES = [149, 150, 151, 152, 153]


def text(x: float, y: float, s: str, size: int = 20, weight: str = "normal",
         fill: str = DARK, anchor: str = "middle", style: str = "normal") -> str:
    return (f'<text x="{x:.1f}" y="{y:.1f}" {FONT} font-size="{size}" font-weight="{weight}" '
            f'font-style="{style}" fill="{fill}" text-anchor="{anchor}">{s}</text>')


def svg(w: int, h: int, body: list[str]) -> str:
    return "\n".join([f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">',
                      f'<rect width="{w}" height="{h}" fill="white"/>', *body, "</svg>"])


def demand(p: float) -> int:
    return sum(q for lim, q in BIDS.items() if lim >= p)


def supply(p: float) -> int:
    return sum(q for lim, q in ASKS.items() if lim <= p)


def equilibrium() -> tuple[str, int, int]:
    w, h = 1200, 800
    left, right, top, bottom = 130, 880, 90, 660

    def x(p: float) -> float:
        return left + (p - 148.5) / 5 * (right - left)

    def y(q: float) -> float:
        return bottom - q / 2500 * (bottom - top)

    body = [text(600, 45, "Finding the auction price: where the cumulative curves meet", 28, "bold")]
    for q in range(0, 2501, 500):
        body.append(f'<line x1="{left}" y1="{y(q)}" x2="{right}" y2="{y(q)}" stroke="{GREY}" stroke-width="1"/>')
        body.append(text(left - 12, y(q) + 6, f"{q:,}", 17, fill=MUTED, anchor="end"))
    body.append(f'<line x1="{left}" y1="{bottom}" x2="{right}" y2="{bottom}" stroke="{DARK}" stroke-width="2"/>')
    body.append(f'<line x1="{left}" y1="{top}" x2="{left}" y2="{bottom}" stroke="{DARK}" stroke-width="2"/>')
    for p in PRICES:
        body.append(text(x(p), bottom + 30, f"${p}", 19, "bold" if p == 151 else "normal", DARK if p == 151 else MUTED))
    body.append(text((left + right) / 2, bottom + 68, "Candidate auction price", 20, "bold", MUTED))
    body.append(f'<text transform="translate(50,{(top + bottom) / 2}) rotate(-90)" {FONT} font-size="20" '
                f'font-weight="bold" fill="{MUTED}" text-anchor="middle">Shares</text>')

    bw = 70
    for p in PRICES:
        v = min(demand(p), supply(p))
        best = p == 151
        if v:
            body.append(f'<rect x="{x(p) - bw / 2}" y="{y(v)}" width="{bw}" height="{bottom - y(v)}" '
                        f'fill="{ORANGE}" fill-opacity="{0.55 if best else 0.22}" stroke="{ORANGE}" stroke-width="{2 if best else 1}"/>')
        if v:
            body.append(text(x(p), bottom - 16, f"{v:,}", 18, "bold", DARK if best else ORANGE))
        else:
            body.append(text(x(p), bottom - 16, "0", 18, "bold", ORANGE))

    def steps(fn, colour: str) -> list[str]:
        pts = []
        edges = [148.5, 149.5, 150.5, 151.5, 152.5, 153.5]
        for a, b in zip(edges, edges[1:]):
            q = fn((a + b) / 2)
            pts += [f"{x(a):.1f},{y(q):.1f}", f"{x(b):.1f},{y(q):.1f}"]
        out = [f'<polyline points="{" ".join(pts)}" fill="none" stroke="{colour}" stroke-width="4" stroke-linejoin="round"/>']
        out += [f'<circle cx="{x(p):.1f}" cy="{y(fn(p)):.1f}" r="7" fill="{colour}"/>' for p in PRICES]
        return out

    body += steps(demand, BLUE)
    body += steps(supply, RED)

    ex, ey = x(151), y(1500)
    body.append(f'<circle cx="{ex}" cy="{ey}" r="16" fill="none" stroke="{DARK}" stroke-width="3"/>')
    body.append(f'<line x1="{ex - 18}" y1="{ey - 18}" x2="{ex - 85}" y2="{ey - 75}" stroke="{DARK}" stroke-width="2"/>')
    body.append(text(ex - 92, ey - 104, "Curves meet:", 18, "bold", DARK, "end"))
    body.append(text(ex - 92, ey - 80, "buy = sell = 1,500", 18, "bold", DARK, "end"))

    lx = 915
    body.append(f'<line x1="{lx}" y1="120" x2="{lx + 40}" y2="120" stroke="{BLUE}" stroke-width="4"/>')
    body.append(text(lx + 52, 114, "Buy interest", 19, "bold", BLUE, "start"))
    body.append(text(lx + 52, 138, "willing to pay ≥ price", 17, fill=MUTED, anchor="start"))
    body.append(f'<line x1="{lx}" y1="185" x2="{lx + 40}" y2="185" stroke="{RED}" stroke-width="4"/>')
    body.append(text(lx + 52, 179, "Sell interest", 19, "bold", RED, "start"))
    body.append(text(lx + 52, 203, "willing to accept ≤ price", 17, fill=MUTED, anchor="start"))
    body.append(f'<rect x="{lx}" y="235" width="40" height="26" fill="{ORANGE}" fill-opacity="0.4" stroke="{ORANGE}"/>')
    body.append(text(lx + 52, 248, "Executable volume", 19, "bold", ORANGE, "start"))
    body.append(text(lx + 52, 272, "= min(buy, sell)", 17, fill=MUTED, anchor="start"))

    body.append(f'<rect x="{lx - 5}" y="320" width="275" height="200" rx="12" fill="#fffaf0" stroke="{DARK}" stroke-width="2"/>')
    for i, (s, wgt) in enumerate([("Equilibrium: $151", "bold"), ("1,500 shares trade,", "normal"),
                                  ("all at the same price.", "normal"), ("", "normal"),
                                  ("Lower price: too few sellers", "normal"), ("Higher price: too few buyers", "normal")]):
        body.append(text(lx + 132, 355 + 30 * i, s, 20 if wgt == "bold" else 17, wgt, DARK if wgt == "bold" else MUTED))

    body.append(text(600, h - 30, "Move left and buyers outnumber sellers; move right and the reverse. Volume peaks where the curves meet.",
                     18, fill=MUTED, style="italic"))
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
        render(args.chrome, "auction-equilibrium", equilibrium(), Path(tmp))


if __name__ == "__main__":
    main()
