#!/usr/bin/env python3
"""Generate the figures for the "Putting It All Together" chapter.

Writes to assets/:
  together-message-flow.png   the message flow of steps 1-11 as a vertical timeline

Used in src/02-orders-and-matching/12-putting-it-all-together.md.
Builds SVGs and renders them to PNG with headless Google Chrome.

Usage: python3 scripts/gen_putting_together_figures.py [--chrome PATH]
"""
from __future__ import annotations

import argparse
import subprocess
import tempfile
from pathlib import Path

DEFAULT_CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
ASSETS = Path(__file__).resolve().parent.parent / "assets"

DARK, MUTED, GREY = "#1a202c", "#4a5568", "#cbd5e0"
FONT = 'font-family="Helvetica, Arial, sans-serif"'

ACTORS = {
    "INV": ("Investor", "#2b6cb0"),
    "GW3": ("GW03", "#3182ce"),
    "ME": ("Engine", "#1a202c"),
    "GW1": ("GW01 (MM)", "#6b46c1"),
    "PUB": ("PUB socket", "#2f855a"),
    "DC": ("Drop copy", "#b7791f"),
    "CL": ("Clearing", "#c53030"),
}

PHASES = [
    ("1. Order entry (steps 1–2)", "#ebf8ff", [
        ("INV", "GW3", "FIX: SELL 50,000 AAPL LIMIT $150.20"),
        ("GW3", "ME", "Validated order (internal format)"),
        ("ME", "GW3", "ACK: order NEW (UUID assigned)"),
        ("GW3", "INV", "Execution report: NEW"),
    ]),
    ("2. Sweep, repeated for each fill at $150.35, $150.30, $150.25 (steps 3–10)", "#f0fff4", [
        ("ME", "PUB", "Trade event (price, qty, both sides)"),
        ("PUB", "GW1", "Fill notification → market maker FILLED"),
        ("PUB", "GW3", "Fill notification → investor PARTIAL"),
        ("PUB", "DC", "Drop copy fill event (seq numbered)"),
        ("PUB", "CL", "Position update"),
    ]),
    ("3. Price band breached: halt (step 7)", "#fff5f5", [
        ("ME", "ME", "Next bid $150.20 is below the lower band → HALT"),
        ("ME", "PUB", "Session state: CONTINUOUS → HALTED"),
        ("PUB", "GW1", "Cancel all MM quotes (stale during halt)"),
        ("PUB", "DC", "HALT event (seq numbered)"),
    ]),
    ("4. Resume (step 11)", "#faf5ff", [
        ("ME", "ME", "Scheduler: RESUME"),
        ("ME", "PUB", "Session state: HALTED → CONTINUOUS"),
        ("GW1", "ME", "Fresh two-sided quote re-submitted"),
    ]),
]


def text(x: float, y: float, s: str, size: int = 20, weight: str = "normal",
         fill: str = DARK, anchor: str = "middle", style: str = "normal") -> str:
    return (f'<text x="{x:.1f}" y="{y:.1f}" {FONT} font-size="{size}" font-weight="{weight}" '
            f'font-style="{style}" fill="{fill}" text-anchor="{anchor}">{s}</text>')


def pill(cx: float, cy: float, key: str, w: float = 150, h: float = 38) -> list[str]:
    name, colour = ACTORS[key]
    return [f'<rect x="{cx - w / 2}" y="{cy - h / 2}" width="{w}" height="{h}" rx="19" fill="{colour}"/>',
            text(cx, cy + 7, name, 18, "bold", "white")]


def svg(w: int, h: int, body: list[str]) -> str:
    marker = (f'<marker id="a" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" '
              f'orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="{MUTED}"/></marker>')
    return "\n".join([f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">',
                      f"<defs>{marker}</defs>", f'<rect width="{w}" height="{h}" fill="white"/>', *body, "</svg>"])


def message_flow() -> tuple[str, int, int]:
    w, row, head, gap = 1000, 56, 50, 22
    xs, xr, xt = 105, 305, 400
    body = [text(w / 2, 42, "Message flow: a large sell order sweeps the book and trips a halt", 26, "bold"),
            text(xs, 95, "From", 17, "bold", MUTED), text(xr, 95, "To", 17, "bold", MUTED),
            text(xt, 95, "Message", 17, "bold", MUTED, "start"),
            f'<line x1="20" y1="110" x2="{w - 20}" y2="110" stroke="{GREY}" stroke-width="2"/>']
    y = 130
    for i, (title, bg, msgs) in enumerate(PHASES):
        if i == 3:
            body.append(f'<rect x="20" y="{y}" width="{w - 40}" height="50" rx="10" fill="#fffff0" '
                        f'stroke="#b7791f" stroke-dasharray="8 6" stroke-width="2"/>')
            body.append(text(w / 2, y + 32, "⏸  5-minute halt period: no trading", 20, "bold", "#b7791f"))
            y += 50 + gap
        ph = head + len(msgs) * row + 10
        body.append(f'<rect x="20" y="{y}" width="{w - 40}" height="{ph}" rx="12" fill="{bg}"/>')
        body.append(text(40, y + 33, title, 20, "bold", DARK, "start"))
        cy = y + head + row / 2
        for src, dst, msg in msgs:
            body += pill(xs, cy, src)
            if src == dst:
                body.append(f'<path d="M {xs + 75} {cy - 10} C {xs + 140} {cy - 30}, {xs + 140} {cy + 30}, {xs + 78} {cy + 10}" '
                            f'fill="none" stroke="{MUTED}" stroke-width="3" marker-end="url(#a)"/>')
                body.append(text(xr, cy + 7, "(internal)", 17, fill=MUTED, style="italic"))
            else:
                body.append(f'<line x1="{xs + 80}" y1="{cy}" x2="{xr - 82}" y2="{cy}" stroke="{MUTED}" '
                            f'stroke-width="3" marker-end="url(#a)"/>')
                body += pill(xr, cy, dst)
            body.append(text(xt, cy + 7, msg, 19, anchor="start"))
            cy += row
        y += ph + gap
    body.append(text(w / 2, y + 20, "Read top to bottom: each row is one message, sent from the left pill to the right pill.",
                     17, fill=MUTED, style="italic"))
    return svg(w, int(y + 45), body), w, int(y + 45)


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
        render(args.chrome, "together-message-flow", message_flow(), Path(tmp))


if __name__ == "__main__":
    main()
