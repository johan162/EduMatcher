#!/usr/bin/env python3
"""Generate the figures for the indexes chapter.

Writes to assets/:
  index-divisor-continuity.png   naive vs divisor-adjusted index level across a constituent replacement
  index-divisor-steps.png        the five steps of a divisor adjustment

Used in src/02-orders-and-matching/15-indexes.md.
Builds SVGs and renders them to PNG with headless Google Chrome.

Usage: python3 scripts/gen_index_figures.py [--chrome PATH]
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
FONT = 'font-family="Helvetica, Arial, sans-serif"'

# The chapter's worked example: shares outstanding and the launch divisor.
SHARES = {"Alpha": 15.0e9, "Beta": 7.4e9, "Gamma": 3.2e9, "Delta": 4.0e9}
START = {"Alpha": 230.00, "Beta": 415.00, "Gamma": 248.00, "Delta": 300.00}
DIVISOR = 7_007_100_000
STEPS, EVENT = 120, 60


def text(x: float, y: float, s: str, size: int = 20, weight: str = "normal",
         fill: str = DARK, anchor: str = "middle", style: str = "normal") -> str:
    return (f'<text x="{x:.1f}" y="{y:.1f}" {FONT} font-size="{size}" font-weight="{weight}" '
            f'font-style="{style}" fill="{fill}" text-anchor="{anchor}">{s}</text>')


def svg(w: int, h: int, body: list[str]) -> str:
    return "\n".join([f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">',
                      f'<rect width="{w}" height="{h}" fill="white"/>', *body, "</svg>"])


def price(name: str, t: int) -> float:
    """A small deterministic wiggle around each company's starting price."""
    phase = {"Alpha": 0.0, "Beta": 1.7, "Gamma": 3.1, "Delta": 4.4}[name]
    return START[name] * (1 + 0.004 * math.sin(t / 7 + phase) + 0.003 * math.sin(t / 3.3 + 2 * phase))


def levels() -> tuple[list[float], list[float]]:
    naive, adjusted = [], []
    divisor = DIVISOR
    for t in range(STEPS + 1):
        basket = ["Alpha", "Beta", "Gamma"] if t < EVENT else ["Alpha", "Beta", "Delta"]
        cap = sum(price(n, t) * SHARES[n] for n in basket)
        if t == EVENT:
            old = sum(price(n, t) * SHARES[n] for n in ["Alpha", "Beta", "Gamma"])
            divisor = DIVISOR * cap / old
        naive.append(cap / DIVISOR)
        adjusted.append(cap / divisor)
    return naive, adjusted


def divisor_continuity() -> tuple[str, int, int]:
    w, h = 1200, 740
    x0, x1, y0, y1 = 130, 1140, 150, 580
    lo, hi = 1020.0, 1120.0
    naive, adjusted = levels()

    def px(t: int) -> float:
        return x0 + (x1 - x0) * t / STEPS

    def py(v: float) -> float:
        return y1 - (y1 - y0) * (v - lo) / (hi - lo)

    body = [text(600, 44, "Replacing Gamma with Delta: why the divisor must change", 28, "bold"),
            text(600, 80, "Same prices, same basket change, two ways of computing the level", 20, fill=MUTED)]
    for v in range(1020, 1121, 20):
        body.append(f'<line x1="{x0}" y1="{py(v):.1f}" x2="{x1}" y2="{py(v):.1f}" stroke="{GREY}" stroke-width="1"/>')
        body.append(text(x0 - 12, py(v) + 6, f"{v:,}", 17, fill=MUTED, anchor="end"))
    body.append(f'<line x1="{x0}" y1="{y1}" x2="{x1}" y2="{y1}" stroke="{DARK}" stroke-width="2"/>')
    for t, label in [(0, "10:00"), (30, "11:00"), (60, "12:00"), (90, "13:00"), (120, "14:00")]:
        body.append(text(px(t), y1 + 30, label, 17, fill=MUTED))
    body.append(text(40, (y0 + y1) / 2, "Index level", 18, fill=MUTED, anchor="middle")
                .replace("<text ", f'<text transform="rotate(-90 40 {(y0 + y1) / 2})" '))

    ex = px(EVENT)
    body.append(f'<line x1="{ex:.1f}" y1="{y0 - 10}" x2="{ex:.1f}" y2="{y1}" stroke="{MUTED}" stroke-width="2" stroke-dasharray="6 6"/>')
    body.append(text(ex, y0 - 18, "12:00  Gamma out, Delta in", 18, "bold", MUTED))

    def path(vals: list[float], start: int) -> str:
        return " ".join(f"{'M' if i == start else 'L'} {px(i):.1f} {py(v):.1f}" for i, v in enumerate(vals) if i >= start)

    body.append(f'<path d="{path(naive, EVENT)}" fill="none" stroke="{RED}" stroke-width="4" stroke-dasharray="10 7"/>')
    body.append(f'<path d="{path(adjusted, 0)}" fill="none" stroke="{BLUE}" stroke-width="5"/>')
    jump_top, jump_bot = py(naive[EVENT]), py(adjusted[EVENT])
    body.append(f'<line x1="{ex + 18:.1f}" y1="{jump_bot - 6:.1f}" x2="{ex + 18:.1f}" y2="{jump_top + 10:.1f}" '
                f'stroke="{RED}" stroke-width="3" marker-end="url(#a-red)"/>')
    body.insert(0, f'<defs><marker id="a-red" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="5" markerHeight="5" '
                   f'orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="{RED}"/></marker></defs>')
    body.append(text(ex + 32, (jump_top + jump_bot) / 2 + 6, "fake +5.6% jump, no price moved", 19, "bold", RED, "start"))
    body.append(text(px(100), py(naive[100]) - 18, "naive: old divisor", 19, "bold", RED))
    body.append(text(px(100), py(adjusted[100]) + 34, "rescaled divisor: continuous", 19, "bold", BLUE))

    body.append(text(600, h - 70, "Old divisor 7,007,100,000  →  new divisor = old × (7,721.0 / 7,314.6) ≈ 7,396,415,265", 19, fill=DARK))
    body.append(text(600, h - 35, "The divisor absorbs the change in the basket; only genuine price moves change the level.", 19, fill=MUTED, style="italic"))
    return svg(w, h, body), w, h


def divisor_steps() -> tuple[str, int, int]:
    w, h = 1200, 436
    steps = [
        ("Basket change", ["issuance, buyback,", "special dividend,", "add or remove"], ORANGE),
        ("Market cap jumps", ["total cap of the basket", "moves, but no price did"], RED),
        ("Rescale the divisor", ["by the same ratio", "as the aggregate cap"], GREEN),
        ("Level unchanged", ["at the instant of", "the adjustment"], BLUE),
        ("Prices move again", ["and change the level", "as normal"], DARK),
    ]
    bw, gap, top, bh = 196, 45, 110, 190
    x0 = (w - (5 * bw + 4 * gap)) / 2
    body = [f'<defs><marker id="a-dark" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="5" markerHeight="5" '
            f'orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="{DARK}"/></marker></defs>',
            text(600, 44, "How a divisor adjustment keeps the index continuous", 28, "bold"),
            text(600, 78, "The same five steps happen for every change to the basket that is not a genuine price move", 20, fill=MUTED)]
    for i, (title, lines, colour) in enumerate(steps):
        x = x0 + i * (bw + gap)
        body.append(f'<rect x="{x:.1f}" y="{top}" width="{bw}" height="{bh}" rx="14" fill="{colour}"/>')
        body.append(f'<circle cx="{x + bw / 2:.1f}" cy="{top + 38}" r="20" fill="white"/>')
        body.append(text(x + bw / 2, top + 46, str(i + 1), 22, "bold", colour))
        body.append(text(x + bw / 2, top + 92, title, 19, "bold", "white"))
        for k, line in enumerate(lines):
            body.append(text(x + bw / 2, top + 122 + 24 * k, line, 16, fill="white"))
        if i < len(steps) - 1:
            ax = x + bw + 5
            body.append(f'<line x1="{ax:.1f}" y1="{top + bh / 2}" x2="{ax + gap - 12:.1f}" y2="{top + bh / 2}" '
                        f'stroke="{DARK}" stroke-width="3.5" marker-end="url(#a-dark)"/>')
    body.append(f'<rect x="{x0:.1f}" y="{top + bh + 30}" width="{5 * bw + 4 * gap}" height="76" rx="12" '
                f'fill="#f7fafc" stroke="{GREY}" stroke-width="2"/>')
    body.append(text(600, top + bh + 62, "new divisor = old divisor × (new aggregate cap ÷ old aggregate cap)", 20, "bold"))
    body.append(text(600, top + bh + 90, "cap and divisor change by the same factor, so cap ÷ divisor, the index level, stays the same",
                     17, fill=MUTED, style="italic"))
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
        render(args.chrome, "index-divisor-continuity", divisor_continuity(), Path(tmp))
        render(args.chrome, "index-divisor-steps", divisor_steps(), Path(tmp))


if __name__ == "__main__":
    main()
