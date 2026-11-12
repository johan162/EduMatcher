#!/usr/bin/env python3
"""Generate the figures for the price-time priority chapter.

Writes to assets/:
  priority-fifo-vs-prorata.png   the same 60 lots allocated to two resting bids under FIFO and under pro-rata

Used in src/02-orders-and-matching/05-price-time-priority-the-fairness-rule.md.
Builds SVGs and renders them to PNG with headless Google Chrome.

Usage: python3 scripts/gen_priority_figures.py [--chrome PATH]
"""
from __future__ import annotations

import argparse
import subprocess
import tempfile
from pathlib import Path

DEFAULT_CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
ASSETS = Path(__file__).resolve().parent.parent / "assets"

BLUE, ORANGE, RED, GREEN, DARK, MUTED, GREY = "#2b6cb0", "#dd6b20", "#c53030", "#2f855a", "#1a202c", "#4a5568", "#cbd5e0"
PURPLE, LIGHT = "#6b46c1", "#f7fafc"
FONT = 'font-family="Helvetica, Arial, sans-serif"'

# The chapter's example: 60 lots sold into two resting bids, X (100, first) and Y (40, second).
INCOMING = 60
ORDERS = [("X", 100, "arrived first", BLUE), ("Y", 40, "arrived second", PURPLE)]


def text(x: float, y: float, s: str, size: int = 20, weight: str = "normal",
         fill: str = DARK, anchor: str = "middle", style: str = "normal") -> str:
    return (f'<text x="{x:.1f}" y="{y:.1f}" {FONT} font-size="{size}" font-weight="{weight}" '
            f'font-style="{style}" fill="{fill}" text-anchor="{anchor}">{s}</text>')


def rect(x: float, y: float, w: float, h: float, fill: str, stroke: str = "none",
         rx: int = 8, sw: float = 2, dash: bool = False) -> str:
    d = ' stroke-dasharray="7 5"' if dash else ""
    return (f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" rx="{rx}" fill="{fill}" '
            f'stroke="{stroke}" stroke-width="{sw}"{d}/>')


def svg(w: int, h: int, body: list[str]) -> str:
    return "\n".join([f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">',
                      f'<rect width="{w}" height="{h}" fill="white"/>', *body, "</svg>"])


def allocate_fifo() -> list[int]:
    left, out = INCOMING, []
    for _, qty, _, _ in ORDERS:
        take = min(left, qty)
        out.append(take)
        left -= take
    return out


def allocate_prorata() -> list[int]:
    total = sum(q for _, q, _, _ in ORDERS)
    out = [round(INCOMING * q / total) for _, q, _, _ in ORDERS]
    out[0] += INCOMING - sum(out)
    return out


def fifo_vs_prorata() -> tuple[str, int, int]:
    w, h = 1200, 660
    body = [text(600, 44, "60 lots to sell, two resting bids at the same price", 28, "bold"),
            text(600, 80, "X bids for 100 lots and arrived first; Y bids for 40 lots and arrived second", 20, fill=MUTED)]
    scale, x0, bar_h = 7.0, 250, 46
    panels = [("FIFO (price-time)", "Earliest order first: X takes everything", allocate_fifo(), 130),
              ("Pro-rata", "Shared in proportion to size: 60 × 100/140 and 60 × 40/140", allocate_prorata(), 370)]
    for title, sub, fills, top in panels:
        body.append(rect(40, top, 1120, 210, LIGHT, GREY, rx=12))
        body.append(text(70, top + 38, title, 24, "bold", anchor="start"))
        body.append(text(70, top + 66, sub, 18, fill=MUTED, anchor="start", style="italic"))
        for i, ((name, qty, when, colour), got) in enumerate(zip(ORDERS, fills)):
            y = top + 88 + i * (bar_h + 14)
            body.append(text(x0 - 20, y + 31, f"{name} ({when})", 19, "bold", colour, "end"))
            body.append(rect(x0, y, qty * scale, bar_h, "white", colour, sw=2.5, dash=True))
            if got:
                body.append(rect(x0, y, got * scale, bar_h, colour))
                body.append(text(x0 + got * scale / 2, y + 31, f"{got} filled", 19, "bold", "white"))
            body.append(text(x0 + qty * scale + 16, y + 31, f"{qty - got} of {qty} still resting", 18, fill=MUTED, anchor="start"))
    body.append(text(600, h - 26, "FIFO rewards being early; pro-rata rewards being large. Both fill exactly 60 lots.", 20, "bold"))
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
        render(args.chrome, "priority-fifo-vs-prorata", fifo_vs_prorata(), Path(tmp))


if __name__ == "__main__":
    main()
