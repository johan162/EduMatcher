#!/usr/bin/env python3
"""Generate the figures for the clearing and settlement chapter.

Writes to assets/:
  clearing-novation.png          bilateral exposures before novation vs hub-and-spoke after
  clearing-default-waterfall.png the order in which a CCP uses resources when a clearing member defaults

Used in src/03-risk-and-compliance/05-clearing-and-settlement-when-the-trade-becomes-real.md.
Builds SVGs and renders them to PNG with headless Google Chrome.

Usage: python3 scripts/gen_clearing_figures.py [--chrome PATH]
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


def text(x: float, y: float, s: str, size: int = 20, weight: str = "normal",
         fill: str = DARK, anchor: str = "middle", style: str = "normal") -> str:
    return (f'<text x="{x:.1f}" y="{y:.1f}" {FONT} font-size="{size}" font-weight="{weight}" '
            f'font-style="{style}" fill="{fill}" text-anchor="{anchor}">{s}</text>')


def rect(x: float, y: float, w: float, h: float, fill: str, stroke: str = "none",
         rx: int = 10, sw: float = 2) -> str:
    return (f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" rx="{rx}" fill="{fill}" '
            f'stroke="{stroke}" stroke-width="{sw}"/>')


def svg(w: int, h: int, body: list[str]) -> str:
    marker = (f'<marker id="a-dark" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="5" markerHeight="5" '
              f'orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="{DARK}"/></marker>')
    return "\n".join([f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">',
                      f"<defs>{marker}</defs>", f'<rect width="{w}" height="{h}" fill="white"/>', *body, "</svg>"])


def novation() -> tuple[str, int, int]:
    w, h = 1200, 680
    names = ["A", "B", "C", "D", "E", "F"]
    body = [text(600, 44, "Novation: from everyone-to-everyone to everyone-to-the-CCP", 28, "bold")]
    for cx, title, sub in [(300, "Before: bilateral", "6 traders → 15 exposures"),
                           (900, "After: central counterparty", "6 traders → 6 exposures")]:
        body.append(rect(cx - 270, 80, 540, 520, LIGHT, GREY))
        body.append(text(cx, 122, title, 24, "bold"))
        body.append(text(cx, 575, sub, 21, "bold", RED if cx == 300 else GREEN))
    r, cy = 175, 345
    pts = {}
    for side, cx in [("L", 300), ("R", 900)]:
        for i, n in enumerate(names):
            a = -math.pi / 2 + i * 2 * math.pi / len(names)
            pts[(side, n)] = (cx + r * math.cos(a), cy + r * math.sin(a))
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            (x1, y1), (x2, y2) = pts[("L", a)], pts[("L", b)]
            body.append(f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="{RED}" '
                        f'stroke-width="2.5" stroke-opacity="0.55"/>')
    for n in names:
        x, y = pts[("R", n)]
        body.append(f'<line x1="900" y1="{cy}" x2="{x:.1f}" y2="{y:.1f}" stroke="{GREEN}" stroke-width="4"/>')
    body.append(f'<circle cx="900" cy="{cy}" r="58" fill="{PURPLE}"/>')
    body.append(text(900, cy + 10, "CCP", 30, "bold", "white"))
    for (side, n), (x, y) in pts.items():
        body.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="32" fill="{BLUE}"/>')
        body.append(text(x, y + 10, n, 26, "bold", "white"))
    body.append(text(600, h - 40, "Each trader now needs to trust only one counterparty: the CCP, which is buyer to every seller and seller to every buyer.",
                     19, fill=MUTED, style="italic"))
    return svg(w, h, body), w, h


def default_waterfall() -> tuple[str, int, int]:
    w, h = 1200, 820
    layers = [
        ("1", "Defaulting member's margin", "Initial and variation margin it posted for its own positions", RED),
        ("2", "Defaulting member's default-fund contribution", "Its own share of the pool every clearing member pays into", ORANGE),
        ("3", "CCP's own capital (\"skin in the game\")", "A slice of the clearing house's equity, so it shares the pain", PURPLE),
        ("4", "Surviving members' default-fund contributions", "Mutualised: the innocent members pay only when all else is gone", BLUE),
    ]
    body = [text(600, 46, "The CCP default waterfall: who pays, in which order", 28, "bold"),
            text(600, 82, "A clearing member defaults and its positions are closed out at a loss", 20, fill=MUTED)]
    x0, bw, top, lh, gap = 180, 840, 120, 120, 40
    body.append(rect(x0, top, bw, 50, "#fff5f5", RED))
    body.append(text(600, top + 33, "Loss to cover", 22, "bold", RED))
    y = top + 50 + gap
    body.append(f'<line x1="600" y1="{top + 52}" x2="600" y2="{y - 4}" stroke="{DARK}" stroke-width="4" marker-end="url(#a-dark)"/>')
    for i, (num, title, sub, colour) in enumerate(layers):
        body.append(rect(x0, y, bw, lh - 20, colour))
        body.append(f'<circle cx="{x0 + 55}" cy="{y + (lh - 20) / 2:.1f}" r="28" fill="white"/>')
        body.append(text(x0 + 55, y + (lh - 20) / 2 + 10, num, 28, "bold", colour))
        body.append(text(x0 + 110, y + 40, title, 24, "bold", "white", "start"))
        body.append(text(x0 + 110, y + 72, sub, 19, fill="white", anchor="start"))
        if i < len(layers) - 1:
            yb = y + lh - 20
            body.append(f'<line x1="600" y1="{yb + 2}" x2="600" y2="{yb + gap - 4}" stroke="{DARK}" stroke-width="4" marker-end="url(#a-dark)"/>')
            body.append(text(615, yb + gap / 2 + 7, "if not enough", 17, fill=MUTED, anchor="start", style="italic"))
        y += lh - 20 + gap
    body.append(text(600, h - 30, "Each layer is used only when every layer above it is exhausted.", 20, fill=MUTED, style="italic"))
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
        for name, fn in [("clearing-novation", novation), ("clearing-default-waterfall", default_waterfall)]:
            render(args.chrome, name, fn(), Path(tmp))


if __name__ == "__main__":
    main()
