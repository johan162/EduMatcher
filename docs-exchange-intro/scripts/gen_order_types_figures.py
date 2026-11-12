#!/usr/bin/env python3
"""Generate the figures for the order types chapter.

Writes to assets/:
  order-trailing-stop.png   a trailing stop ratcheting up behind a rising price, freezing, then triggering

Used in src/02-orders-and-matching/02-order-types-the-vocabulary-of-intent.md.
Builds SVGs and renders them to PNG with headless Google Chrome.

Usage: python3 scripts/gen_order_types_figures.py [--chrome PATH]
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

# The chapter's example: bought at $150, trail distance $5, highs at $160 and $170, trigger at $165.
TRAIL = 5.0
PATH = [(0, 150.0), (8, 153.0), (14, 151.0), (22, 160.0), (28, 157.5), (36, 164.0), (44, 170.0),
        (50, 168.0), (56, 167.0), (62, 168.5), (70, 166.2), (76, 165.0)]
FILL = 164.95


def text(x: float, y: float, s: str, size: int = 20, weight: str = "normal",
         fill: str = DARK, anchor: str = "middle", style: str = "normal") -> str:
    return (f'<text x="{x:.1f}" y="{y:.1f}" {FONT} font-size="{size}" font-weight="{weight}" '
            f'font-style="{style}" fill="{fill}" text-anchor="{anchor}">{s}</text>')


def svg(w: int, h: int, body: list[str]) -> str:
    marker = (f'<marker id="a-dark" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="5" markerHeight="5" '
              f'orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="{DARK}"/></marker>')
    return "\n".join([f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">',
                      f"<defs>{marker}</defs>", f'<rect width="{w}" height="{h}" fill="white"/>', *body, "</svg>"])


def price_at(t: float) -> float:
    for (t0, p0), (t1, p1) in zip(PATH, PATH[1:]):
        if t0 <= t <= t1:
            return p0 + (p1 - p0) * (t - t0) / (t1 - t0)
    return PATH[-1][1]


def trailing_stop() -> tuple[str, int, int]:
    w, h = 1200, 720
    x0, x1, y0, y1 = 110, 1120, 110, 590
    lo, hi = 142.0, 172.0
    t_end = PATH[-1][0]

    def px(t: float) -> float:
        return x0 + (x1 - x0) * t / (t_end + 6)

    def py(v: float) -> float:
        return y1 - (y1 - y0) * (v - lo) / (hi - lo)

    body = [text(600, 44, "A trailing stop with a $5.00 trail distance", 28, "bold"),
            text(600, 78, "The stop follows each new high up, never down, and fires when the price falls back to it", 20, fill=MUTED)]
    for v in range(145, 172, 5):
        body.append(f'<line x1="{x0}" y1="{py(v):.1f}" x2="{x1}" y2="{py(v):.1f}" stroke="{GREY}" stroke-width="1"/>')
        body.append(text(x0 - 12, py(v) + 6, f"${v}", 17, fill=MUTED, anchor="end"))
    body.append(f'<line x1="{x0}" y1="{y1}" x2="{x1}" y2="{y1}" stroke="{DARK}" stroke-width="2"/>')
    body.append(text((x0 + x1) / 2, y1 + 34, "time →", 18, fill=MUTED))

    steps = [i / 4 for i in range(0, t_end * 4 + 1)]
    price = [price_at(t) for t in steps]
    stop, high = [], 0.0
    for p in price:
        high = max(high, p)
        stop.append(high - TRAIL)
    body.append('<path d="' + " ".join(f"{'M' if i == 0 else 'L'} {px(t):.1f} {py(s):.1f}"
                                       for i, (t, s) in enumerate(zip(steps, stop))) +
                f'" fill="none" stroke="{RED}" stroke-width="4" stroke-dasharray="10 6"/>')
    body.append('<path d="' + " ".join(f"{'M' if i == 0 else 'L'} {px(t):.1f} {py(p):.1f}"
                                       for i, (t, p) in enumerate(zip(steps, price))) +
                f'" fill="none" stroke="{BLUE}" stroke-width="5"/>')

    body.append(f'<circle cx="{px(0):.1f}" cy="{py(150):.1f}" r="8" fill="{BLUE}"/>')
    body.append(text(px(0) + 14, py(143.6), "bought at $150, stop starts at $145", 18, fill=BLUE, anchor="start"))
    for t, p in [(22, 160.0), (44, 170.0)]:
        body.append(f'<circle cx="{px(t):.1f}" cy="{py(p):.1f}" r="7" fill="{BLUE}"/>')
        body.append(f'<line x1="{px(t):.1f}" y1="{py(p) + 9:.1f}" x2="{px(t):.1f}" y2="{py(p - TRAIL) - 6:.1f}" '
                    f'stroke="{MUTED}" stroke-width="2" marker-end="url(#a-dark)"/>')
        body.append(text(px(t) - 10, py(p) - 16, f"new high ${p:.0f}", 18, "bold", BLUE, "end"))
        ly = py(p - TRAIL) + 26 if p < 165 else py(p - TRAIL) - 14
        body.append(text(px(t) + 10, ly, f"stop ratchets up to ${p - TRAIL:.0f}", 18, "bold", RED, "start"))
    body.append(text(px(59), py(165) + 30, "price dips: stop stays frozen at $165", 18, fill=RED, style="italic"))
    tx, ty = px(t_end), py(165)
    body.append(f'<circle cx="{tx:.1f}" cy="{ty:.1f}" r="14" fill="none" stroke="{RED}" stroke-width="4"/>')
    body.append(f'<circle cx="{tx:.1f}" cy="{py(FILL) + 14:.1f}" r="7" fill="{ORANGE}"/>')
    body.append(text(tx + 6, ty + 66, "trigger at $165 → market sell order,", 19, "bold", RED, "end"))
    body.append(text(tx + 6, ty + 92, f"fills at the best bid, ${FILL:.2f}", 19, "bold", ORANGE, "end"))

    lx = x0 + 20
    body.append(f'<line x1="{lx}" y1="{h - 52}" x2="{lx + 50}" y2="{h - 52}" stroke="{BLUE}" stroke-width="5"/>')
    body.append(text(lx + 62, h - 45, "last trade price", 18, anchor="start"))
    body.append(f'<line x1="{lx + 260}" y1="{h - 52}" x2="{lx + 310}" y2="{h - 52}" stroke="{RED}" stroke-width="4" stroke-dasharray="10 6"/>')
    body.append(text(lx + 322, h - 45, "stop price = highest price so far − $5.00 (hidden, not in the book)", 18, anchor="start"))
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
        render(args.chrome, "order-trailing-stop", trailing_stop(), Path(tmp))


if __name__ == "__main__":
    main()
