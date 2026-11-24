#!/usr/bin/env python3
"""Generate the strip-wide fan-out figures for the first implied orders chapter.

Writes to assets/:
  implied-fanout-matrix.png   which implied quotes one changed book side makes dirty
  implied-fanout-latency.png  measured recalculation latency per book change

Used in src/02-orders-and-matching/13-implied-orders-and-synthetic-liquidity.md.
Builds SVGs and renders them to PNG with headless Google Chrome.

Usage: python3 scripts/gen_implied_fanout_figures.py [--chrome PATH]
"""
from __future__ import annotations

import argparse
import itertools
import subprocess
import tempfile
from pathlib import Path

DEFAULT_CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
ASSETS = Path(__file__).resolve().parent.parent / "assets"

BLUE, ORANGE, GREY, DARK, MUTED = "#2b6cb0", "#dd6b20", "#cbd5e0", "#1a202c", "#4a5568"
PURPLE, LIGHT = "#6b46c1", "#f7fafc"
FONT = 'font-family="Helvetica, Arial, sans-serif"'
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

# Median ns from scripts/implied_fanout_benchmark.c, depth 2: (label, detail, warm, cold).
LATENCY = [
    ("Spread order changes", "only dirty quotes: 2 quotes, 22 pair() calls", 209, 426),
    ("Outright order changes", "only dirty quotes: 22 quotes, 132 pair() calls", 1152, 1468),
    ("Outright order changes, recompute all", "all 156 quotes, 396 pair() calls", 3414, 3655),
    ("Spread order, spread-from-spread on", "only dirty quotes: 22 quotes, 242 pair() calls", 2496, 3006),
    ("Spread order, spread-from-spread, recompute all", "all 156 quotes, 1,716 pair() calls", 13435, 14273),
]


def text(x: float, y: float, s: str, size: int = 22, weight: str = "normal",
         fill: str = DARK, anchor: str = "middle") -> str:
    return (f'<text x="{x:.1f}" y="{y:.1f}" {FONT} font-size="{size}" font-weight="{weight}" '
            f'fill="{fill}" text-anchor="{anchor}">{s}</text>')


def rect(x: float, y: float, w: float, h: float, fill: str, stroke: str = "none", rx: int = 4) -> str:
    return f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" rx="{rx}" fill="{fill}" stroke="{stroke}"/>'


def svg(w: int, h: int, body: list[str]) -> str:
    return "\n".join([f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">',
                      f'<rect width="{w}" height="{h}" fill="white"/>', *body, "</svg>"])


def dependants() -> dict[tuple[int, int, str], set[tuple[int, int, str]]]:
    """Map each book side to the implied quotes built from it. Outright m is the key (m, m, side)."""
    deps: dict[tuple[int, int, str], set[tuple[int, int, str]]] = {}
    for n, f in itertools.combinations(range(12), 2):
        na, nb, fa, fb, sa, sb = (n, n, "A"), (n, n, "B"), (f, f, "A"), (f, f, "B"), (n, f, "A"), (n, f, "B")
        for target, a, b in [(fa, na, sb), (fb, nb, sa), (na, fa, sa), (nb, fb, sb), (sa, na, fb), (sb, nb, fa)]:
            deps.setdefault(a, set()).add(target)
            deps.setdefault(b, set()).add(target)
    return deps


def panel(x0: int, y0: int, title: str, sub: str, changed: tuple[int, int, str],
          dirty: set[tuple[int, int, str]]) -> list[str]:
    c = 40
    body = [text(x0 + 6 * c, y0 - 70, title, 25, "bold"), text(x0 + 6 * c, y0 - 40, sub, 19, fill=MUTED)]
    for i, m in enumerate(MONTHS):
        body.append(text(x0 + i * c + c / 2, y0 - 9, m, 15, "bold", MUTED))
        body.append(text(x0 - 8, y0 + i * c + c / 2 + 5, m, 15, "bold", MUTED, "end"))
    for r in range(12):
        for col in range(r, 12):
            x, y = x0 + col * c, y0 + r * c
            hit = {t[2] for t in dirty if t[:2] == (r, col)}
            if changed[:2] == (r, col):
                body.append(rect(x + 1, y + 1, c - 2, c - 2, PURPLE))
                body.append(text(x + c / 2, y + 27, changed[2], 20, "bold", "white"))
            elif hit:
                body.append(rect(x + 1, y + 1, c - 2, c - 2, BLUE if r == col else ORANGE))
                body.append(text(x + c / 2, y + 27, "".join(sorted(hit)), 20, "bold", "white"))
            else:
                body.append(rect(x + 1, y + 1, c - 2, c - 2, "#eef1f5" if r != col else "#d5dce6"))
    return body


def matrix() -> tuple[str, int, int]:
    w, h = 1240, 790
    deps = dependants()
    jun_ask, spread_bid = (5, 5, "A"), (5, 8, "B")
    body = [text(w / 2, 40, "One changed book side, and the implied quotes it makes dirty", 29, "bold")]
    body += panel(70, 180, "A June ask changes", "22 quotes to recompute: 11 OUT + 11 IN", jun_ask, deps[jun_ask])
    body += panel(690, 180, "A Jun/Sep spread bid changes", "2 quotes to recompute: both OUT", spread_bid,
                  deps[spread_bid])
    y = 695
    for x, colour, label in [(90, PURPLE, "changed book side"), (375, BLUE, "implied OUT (outright)"),
                             (710, ORANGE, "implied IN (spread)"), (1000, "#eef1f5", "unaffected")]:
        body.append(rect(x, y - 21, 28, 28, colour))
        body.append(text(x + 38, y, label, 20, anchor="start"))
    body.append(text(w / 2, 750, "Diagonal cells are outright books. Every other cell is the spread "
                                 "(row month / column month). A = ask, B = bid.", 19, fill=MUTED))
    return svg(w, h, body), w, h


def latency() -> tuple[str, int, int]:
    w, h = 1240, 860
    left, right, top = 70, 1120, 165
    scale = (right - left) / 16.0
    body = [text(w / 2, 42, "Recalculation time for one book change", 29, "bold"),
            text(w / 2, 76, "12-month strip, top 2 implied levels, one Xeon W-2295 core, median", 20, fill=MUTED)]
    body.append(rect(left, 103, 24, 24, BLUE))
    body.append(text(left + 34, 122, "data already in CPU cache", 20, anchor="start"))
    body.append(rect(left + 360, 103, 24, 24, ORANGE))
    body.append(text(left + 394, 122, "L1 and L2 cache evicted first", 20, anchor="start"))
    plot_bottom = top + len(LATENCY) * 122
    for tick in range(0, 17, 2):
        x = left + tick * scale
        body.append(f'<line x1="{x:.1f}" y1="{top}" x2="{x:.1f}" y2="{plot_bottom}" stroke="#e2e8f0" stroke-width="1.5"/>')
        body.append(text(x, plot_bottom + 30, f"{tick} µs", 19, fill=MUTED))
    for i, (label, detail, warm, cold) in enumerate(LATENCY):
        y = top + i * 122
        body.append(text(left + 10, y + 25, label, 21, "bold", anchor="start"))
        body.append(text(left + 10, y + 50, detail, 18, fill=MUTED, anchor="start"))
        for k, (ns, colour) in enumerate([(warm, BLUE), (cold, ORANGE)]):
            by = y + 62 + k * 24
            body.append(rect(left, by, max(ns / 1000 * scale, 4), 20, colour))
            body.append(text(left + ns / 1000 * scale + 9, by + 16, f"{ns / 1000:.2f} µs", 18, "bold", anchor="start"))
    body.append(f'<line x1="{left}" y1="{top}" x2="{left}" y2="{plot_bottom}" stroke="{MUTED}" stroke-width="2"/>')
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
        for name, fn in [("implied-fanout-matrix", matrix), ("implied-fanout-latency", latency)]:
            render(args.chrome, name, fn(), Path(tmp))


if __name__ == "__main__":
    main()
