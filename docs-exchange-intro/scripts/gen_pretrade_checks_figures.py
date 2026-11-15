#!/usr/bin/env python3
"""Generate the figure for the pre-trade risk controls chapter.

Writes to assets/:
  risk-pretrade-check-order.png   the eight gateway checks in fail-fast order, cheapest first

Used in src/03-risk-and-compliance/01-pre-trade-risk-controls-before-the-matching-engine.md.
Builds an SVG and renders it to PNG with headless Google Chrome.

Usage: python3 scripts/gen_pretrade_checks_figures.py [--chrome PATH]
"""
from __future__ import annotations

import argparse
import subprocess
import tempfile
from pathlib import Path

DEFAULT_CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
ASSETS = Path(__file__).resolve().parent.parent / "assets"

BLUE, ORANGE, RED, GREEN, DARK, MUTED, GREY = "#2b6cb0", "#dd6b20", "#c53030", "#2f855a", "#1a202c", "#4a5568", "#cbd5e0"
LIGHT = "#f7fafc"
FONT = 'font-family="Helvetica, Arial, sans-serif"'

# (question, what it costs, outcome, reason); outcome colour is red except for the SMP cancel.
CHECKS = [
    ("Format &amp; syntax valid?", "the message alone, no lookups", "REJECTED", "malformed message"),
    ("Symbol valid &amp; tradeable?", "reference-data table lookup", "REJECTED", "unknown or halted symbol"),
    ("Within gateway rate limit?", "in-memory counter per gateway", "REJECTED or QUEUED", "throttle limit exceeded"),
    ("Price within fat-finger band?", "cached reference price", "REJECTED", "price too far from reference"),
    ("Quantity &amp; notional OK?", "order fields + configured limits", "REJECTED", "size or value limit exceeded"),
    ("Short-sale marking valid?", "marking + restriction state", "REJECTED", "missing or invalid marking"),
    ("Position &amp; credit OK?", "live positions from clearing", "REJECTED", "position or credit limit breached"),
    ("SMP pre-check clear?", "partial: gateway cannot see the book", "CANCELLED", "self-match, per SMP policy"),
]


def text(x: float, y: float, s: str, size: int = 20, weight: str = "normal",
         fill: str = DARK, anchor: str = "middle", style: str = "normal", extra: str = "") -> str:
    return (f'<text x="{x:.1f}" y="{y:.1f}" {FONT} font-size="{size}" font-weight="{weight}" '
            f'font-style="{style}" fill="{fill}" text-anchor="{anchor}"{extra}>{s}</text>')


def arrow(x1: float, y1: float, x2: float, y2: float, colour: str, marker: str) -> str:
    return (f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="{colour}" stroke-width="3.5" '
            f'marker-end="url(#{marker})"/>')


def marker(name: str, colour: str) -> str:
    return (f'<marker id="{name}" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="5" markerHeight="5" '
            f'orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="{colour}"/></marker>')


def svg(w: int, h: int, body: list[str]) -> str:
    return "\n".join([f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">',
                      f'<rect width="{w}" height="{h}" fill="white"/>', *body, "</svg>"])


def check_order() -> tuple[str, int, int]:
    w, h = 1200, 1230
    cx0, cx1 = 130, 660          # check boxes
    rx0, rx1 = 780, 1160         # outcome boxes
    top, box_h, pitch = 210, 76, 110
    mid = (cx0 + cx1) / 2
    body = [f'<defs>{marker("a-dark", DARK)}{marker("a-red", RED)}{marker("a-orange", ORANGE)}{marker("a-green", GREEN)}'
            f'<linearGradient id="cost" x1="0" y1="0" x2="0" y2="1">'
            f'<stop offset="0" stop-color="{GREEN}"/><stop offset="0.55" stop-color="{ORANGE}"/>'
            f'<stop offset="1" stop-color="{RED}"/></linearGradient></defs>',
            text(600, 44, "Pre-trade checks in fail-fast order", 28, "bold"),
            text(600, 78, "Cheapest checks first: most bad orders are rejected before any external state is consulted",
                 20, fill=MUTED)]

    body.append(f'<rect x="{mid - 140:.1f}" y="112" width="280" height="54" rx="27" fill="{BLUE}"/>')
    body.append(text(mid, 147, "Incoming order", 22, "bold", "white"))
    body.append(arrow(mid, 166, mid, top - 4, DARK, "a-dark"))

    last = top + (len(CHECKS) - 1) * pitch + box_h
    priciest = last - pitch  # step 7, position & credit; the SMP pre-check is a cheap partial check
    body.append(f'<rect x="62" y="{top}" width="22" height="{priciest - top}" rx="11" fill="url(#cost)"/>')
    body.append(text(40, (top + priciest) / 2, "cost per check rises  →", 19, "bold", MUTED,
                     extra=f' transform="rotate(90 40 {(top + priciest) / 2:.1f})"'))

    for i, (question, cost, outcome, reason) in enumerate(CHECKS):
        y = top + i * pitch
        cy = y + box_h / 2
        body.append(f'<rect x="{cx0}" y="{y}" width="{cx1 - cx0}" height="{box_h}" rx="10" fill="{LIGHT}" '
                    f'stroke="{BLUE}" stroke-width="2.5"/>')
        body.append(f'<circle cx="{cx0 + 38}" cy="{cy:.1f}" r="22" fill="{BLUE}"/>')
        body.append(text(cx0 + 38, cy + 8, str(i + 1), 22, "bold", "white"))
        body.append(text(cx0 + 76, y + 33, question, 22, "bold", anchor="start"))
        body.append(text(cx0 + 76, y + 59, cost, 18, fill=MUTED, anchor="start", style="italic"))

        colour, mk = (ORANGE, "a-orange") if outcome == "CANCELLED" else (RED, "a-red")
        body.append(arrow(cx1, cy, rx0 - 4, cy, colour, mk))
        body.append(text((cx1 + rx0) / 2, cy - 10, "self-match" if outcome == "CANCELLED" else "fail",
                         17, "bold", colour))
        body.append(f'<rect x="{rx0}" y="{y + 6}" width="{rx1 - rx0}" height="{box_h - 12}" rx="10" '
                    f'fill="{colour}" fill-opacity="0.10" stroke="{colour}" stroke-width="2.5"/>')
        body.append(text((rx0 + rx1) / 2, y + 34, outcome, 20, "bold", colour))
        body.append(text((rx0 + rx1) / 2, y + 58, reason, 18, fill=DARK))

        nxt = y + pitch if i < len(CHECKS) - 1 else last + 34
        body.append(arrow(mid, y + box_h, mid, nxt - 4, GREEN, "a-green"))
        body.append(text(mid + 12, y + box_h + 24, "pass" if i < len(CHECKS) - 1 else "clear", 17, "bold", GREEN,
                         anchor="start"))

    ey = last + 34
    body.append(f'<rect x="{mid - 170:.1f}" y="{ey}" width="340" height="60" rx="30" fill="{GREEN}"/>')
    body.append(text(mid, ey + 38, "→ Matching engine", 23, "bold", "white"))

    body.append(text(600, h - 40, "Failing at step 1 takes nanoseconds; step 7 must consult position data from clearing.",
                     19, fill=DARK))
    body.append(text(600, h - 12, "The real self-match check runs inside the engine's sweep; step 8 only catches the obvious cases.",
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
        render(args.chrome, "risk-pretrade-check-order", check_order(), Path(tmp))


if __name__ == "__main__":
    main()
