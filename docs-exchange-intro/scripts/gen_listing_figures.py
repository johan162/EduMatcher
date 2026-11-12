#!/usr/bin/env python3
"""Generate the figures for the listing and delisting chapter.

Writes to assets/:
  listing-dcf-value.png   where the value comes from in the chapter's DCF example (five years vs terminal value)

Used in src/01-foundation/06-listing-and-delisting-mechanics.md.
Builds SVGs and renders them to PNG with headless Google Chrome.

Usage: python3 scripts/gen_listing_figures.py [--chrome PATH]
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

# The chapter's worked example: $100m free cash flow, 10% growth for 5 years, then 3% forever, 9% discount rate.
FCF0, GROWTH, TERMINAL_GROWTH, RATE = 100.0, 0.10, 0.03, 0.09


def text(x: float, y: float, s: str, size: int = 20, weight: str = "normal",
         fill: str = DARK, anchor: str = "middle", style: str = "normal") -> str:
    return (f'<text x="{x:.1f}" y="{y:.1f}" {FONT} font-size="{size}" font-weight="{weight}" '
            f'font-style="{style}" fill="{fill}" text-anchor="{anchor}">{s}</text>')


def rect(x: float, y: float, w: float, h: float, fill: str, rx: int = 4) -> str:
    return f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" rx="{rx}" fill="{fill}"/>'


def svg(w: int, h: int, body: list[str]) -> str:
    return "\n".join([f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">',
                      f'<rect width="{w}" height="{h}" fill="white"/>', *body, "</svg>"])


def dcf() -> tuple[list[float], float]:
    flows, cash = [], FCF0
    for year in range(1, 6):
        cash *= 1 + GROWTH
        flows.append(cash / (1 + RATE) ** year)
    terminal = cash * (1 + TERMINAL_GROWTH) / (RATE - TERMINAL_GROWTH) / (1 + RATE) ** 5
    return flows, terminal


def dcf_value() -> tuple[str, int, int]:
    w, h = 1200, 740
    flows, terminal = dcf()
    total = sum(flows) + terminal
    body = [text(600, 44, "Where the value comes from: the chapter's DCF example", 28, "bold"),
            text(600, 80, "Present value of each piece, in $ millions (9% discount rate)", 20, fill=MUTED)]
    base, top, x0 = 560, 130, 120
    scale = (base - top) / 1900
    body.append(f'<line x1="{x0 - 20}" y1="{base}" x2="780" y2="{base}" stroke="{DARK}" stroke-width="2"/>')
    bw, gap = 70, 22
    for i, v in enumerate(flows):
        x = x0 + i * (bw + gap)
        body.append(rect(x, base - v * scale, bw, v * scale, BLUE))
        body.append(text(x + bw / 2, base - v * scale - 10, f"{v:.0f}", 18, "bold", BLUE))
        body.append(text(x + bw / 2, base + 28, f"Year {i + 1}", 17, fill=MUTED))
    tx = x0 + 5 * (bw + gap) + 30
    body.append(rect(tx, base - terminal * scale, bw + 40, terminal * scale, ORANGE))
    body.append(text(tx + (bw + 40) / 2, base - terminal * scale - 10, f"{terminal:,.0f}", 20, "bold", ORANGE))
    body.append(text(tx + (bw + 40) / 2, base + 28, "Terminal", 17, fill=MUTED))
    body.append(text(tx + (bw + 40) / 2, base + 50, "value", 17, fill=MUTED))
    body.append(text(x0 + 2 * (bw + gap) + bw / 2, base - 250, f"Years 1–5 together: {sum(flows):.0f}", 20, "bold", BLUE))

    sx, sw = 900, 140
    share = terminal / total
    body.append(text(sx + sw / 2, top - 8, f"Total ≈ ${total / 1000:.2f}bn", 21, "bold"))
    body.append(rect(sx, top, sw, (base - top) * share, ORANGE, rx=0))
    body.append(rect(sx, top + (base - top) * share, sw, (base - top) * (1 - share), BLUE, rx=0))
    body.append(text(sx + sw / 2, top + (base - top) * share / 2 + 10, f"{share:.0%}", 34, "bold", "white"))
    body.append(text(sx + sw / 2, top + (base - top) * (share + (1 - share) / 2) + 9, f"{1 - share:.0%}", 26, "bold", "white"))
    body.append(text(sx + sw + 16, top + (base - top) * share / 2 + 6, "after year 5", 18, fill=ORANGE, anchor="start"))
    body.append(text(sx + sw + 16, top + (base - top) * (share + (1 - share) / 2) + 6, "years 1–5", 18, fill=BLUE, anchor="start"))

    body.append(text(600, h - 56, "Almost four-fifths of the value rests on cash flows after year five, which nobody can forecast with confidence.",
                     19, fill=DARK))
    body.append(text(600, h - 24, "Change the discount rate by one point and the total moves by hundreds of millions.", 19, fill=MUTED, style="italic"))
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
        render(args.chrome, "listing-dcf-value", dcf_value(), Path(tmp))


if __name__ == "__main__":
    main()
