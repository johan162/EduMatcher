#!/usr/bin/env python3
"""Generate assets/implied-78-books.png (12 months + 66 calendar spreads = 78 books).

Used in src/02-orders-and-matching/13-implied-orders-and-synthetic-liquidity.md.
Builds an SVG and renders it to PNG with headless Google Chrome.

Usage: python3 scripts/gen_implied_78_books.py [--chrome PATH]
"""
from __future__ import annotations

import argparse
import math
import subprocess
import tempfile
from pathlib import Path

DEFAULT_CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
OUT = Path(__file__).resolve().parent.parent / "assets" / "implied-78-books.png"


def build_svg() -> tuple[str, int, int]:
    M=["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]
    W,H=1200,1080; cx,cy,R=600,430,330
    BLUE="#2b6cb0"; ORANGE="#dd6b20"
    o=[f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">',
       f'<rect width="{W}" height="{H}" fill="white"/>']
    pts=[(cx+R*math.sin(2*math.pi*i/12), cy-R*math.cos(2*math.pi*i/12)) for i in range(12)]
    for i in range(12):
        for j in range(i+1,12):
            (x1,y1),(x2,y2)=pts[i],pts[j]
            o.append(f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="{ORANGE}" stroke-opacity="0.55" stroke-width="2"/>')
    for (x,y),m in zip(pts,M):
        o.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="36" fill="{BLUE}" stroke="white" stroke-width="3"/>')
        o.append(f'<text x="{x:.1f}" y="{y+8:.1f}" font-family="Helvetica, Arial, sans-serif" font-size="22" font-weight="bold" fill="white" text-anchor="middle">{m}</text>')
    f='font-family="Helvetica, Arial, sans-serif"'
    o.append(f'<circle cx="215" cy="830" r="14" fill="{BLUE}"/><text x="239" y="837" {f} font-size="22" fill="#222">12 months = 12 outright books</text>')
    o.append(f'<line x1="565" y1="830" x2="615" y2="830" stroke="{ORANGE}" stroke-width="4"/><text x="627" y="837" {f} font-size="22" fill="#222">66 lines = 66 spread books (12 × 11 / 2)</text>')
    # fading row of books
    y0=900; bw,bh,gap=38,58,6; x=40
    pairs=[(i,j) for i in range(12) for j in range(i+1,12)]
    items=[("o",m,"") for m in M]+[("s",M[i],M[j]) for i,j in pairs]
    shown=22
    for k,(t,a,b) in enumerate(items[:shown]):
        op=1.0 if k<12 else max(0.08,1-(k-11)/(shown-10))
        col=BLUE if t=="o" else ORANGE
        o.append(f'<g opacity="{op:.2f}"><rect x="{x}" y="{y0}" width="{bw}" height="{bh}" rx="4" fill="{col}"/>')
        if t=="o":
            o.append(f'<text x="{x+bw/2}" y="{y0+35}" {f} font-size="13" font-weight="bold" fill="white" text-anchor="middle">{a}</text></g>')
        else:
            o.append(f'<text x="{x+bw/2}" y="{y0+24}" {f} font-size="12" font-weight="bold" fill="white" text-anchor="middle">{a}/</text><text x="{x+bw/2}" y="{y0+41}" {f} font-size="12" font-weight="bold" fill="white" text-anchor="middle">{b}</text></g>')
        x+=bw+gap
    o.append(f'<text x="{x+8}" y="{y0+37}" {f} font-size="22" fill="#555">· · · {78-shown} more</text>')
    o.append(f'<text x="{W/2}" y="{y0+110}" {f} font-size="26" font-weight="bold" fill="#222" text-anchor="middle">12 outright books + 66 spread books = 78 separate order books</text>')
    o.append('</svg>')
    return "\n".join(o), W, H


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--chrome", default=DEFAULT_CHROME, help="Chrome/Chromium executable")
    args = ap.parse_args()
    svg, w, h = build_svg()
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "implied-78-books.svg"
        src.write_text(svg, encoding="utf-8")
        subprocess.run(
            [args.chrome, "--headless=new", "--disable-gpu", "--hide-scrollbars",
             "--force-device-scale-factor=2", f"--window-size={w},{h}",
             f"--screenshot={OUT}", src.as_uri()],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    main()
