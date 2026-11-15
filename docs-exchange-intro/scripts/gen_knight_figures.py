#!/usr/bin/env python3
"""Generate the figure for the Knight Capital chapter.

Writes to assets/:
  risk-knight-timeline.png   the set-up, the 45 minutes on 1 August 2012, and the aftermath

Used in src/03-risk-and-compliance/08-a-cautionary-tale-knight-capital-august-1-2012.md.
Builds an SVG and renders it to PNG with headless Google Chrome.

Usage: python3 scripts/gen_knight_figures.py [--chrome PATH]
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

# Every fact below is from the chapter (SEC Release No. 34-70694).
SETUP = [("2003", ["Power Peg last used;", "code left in SMARS"]),
         ("Years later", ["fill counter moved: Power Peg", "can no longer tell when to stop"]),
         ("2012", ["new RLP code reuses the", "old Power Peg flag"]),
         ("Deployment", ["new code reaches 7 of 8", "servers; nobody verifies"])]
AFTERMATH = [("2 August", ["pre-tax loss of about", "$440 million announced"]),
             ("Two trading days", ["share price down by", "roughly three-quarters"]),
             ("Rescue", ["$400 million for", "majority ownership"]),
             ("Later", ["merged with Getco as KCG;", "Virtu buys KCG in 2017"])]
STATS = [("4 million+", "executions"), ("397 million", "shares"), ("154", "stocks"), ("$6.65 billion", "gross exposure")]


def text(x: float, y: float, s: str, size: int = 20, weight: str = "normal",
         fill: str = DARK, anchor: str = "middle", style: str = "normal") -> str:
    return (f'<text x="{x:.1f}" y="{y:.1f}" {FONT} font-size="{size}" font-weight="{weight}" '
            f'font-style="{style}" fill="{fill}" text-anchor="{anchor}">{s}</text>')


def line(x1: float, y1: float, x2: float, y2: float, colour: str, width: float = 2, dash: str = "") -> str:
    d = f' stroke-dasharray="{dash}"' if dash else ""
    return (f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="{colour}" '
            f'stroke-width="{width}"{d}/>')


def arrow(x1: float, y1: float, x2: float, y2: float, colour: str = DARK) -> str:
    return (f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="{colour}" stroke-width="3.5" '
            f'marker-end="url(#a-dark)"/>')


def svg(w: int, h: int, body: list[str]) -> str:
    return "\n".join([f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">',
                      f'<rect width="{w}" height="{h}" fill="white"/>', *body, "</svg>"])


def band_title(y: float, title: str, colour: str) -> list[str]:
    return [f'<rect x="40" y="{y - 26}" width="8" height="34" rx="3" fill="{colour}"/>',
            text(62, y, title, 23, "bold", colour, "start")]


def chain(y: float, items: list[tuple[str, list[str]]], colour: str) -> list[str]:
    """A row of four boxes joined by arrows, read left to right."""
    out = []
    bw, gap = 250, 40
    x = (1200 - len(items) * bw - (len(items) - 1) * gap) / 2
    for i, (head, lines) in enumerate(items):
        out.append(f'<rect x="{x}" y="{y}" width="{bw}" height="112" rx="10" fill="{colour}" fill-opacity="0.08" '
                   f'stroke="{colour}" stroke-width="2.5"/>')
        out.append(text(x + bw / 2, y + 34, head, 20, "bold", colour))
        for k, s in enumerate(lines):
            out.append(text(x + bw / 2, y + 66 + 24 * k, s, 17))
        if i < len(items) - 1:
            out.append(arrow(x + bw + 4, y + 56, x + bw + gap - 6, y + 56))
        x += bw + gap
    return out


def server_row(x: float, y: float, title: str, bad: int) -> list[str]:
    """Eight servers; the last `bad` of them treat the flag as Power Peg."""
    out = [text(x + 192, y - 14, title, 19, "bold")]
    for i in range(8):
        colour = RED if i >= 8 - bad else GREEN
        out.append(f'<rect x="{x + i * 48}" y="{y}" width="40" height="54" rx="5" fill="{colour}"/>')
        out.append(text(x + i * 48 + 20, y + 33, str(i + 1), 18, "bold", "white"))
    return out


def timeline() -> tuple[str, int, int]:
    w, h = 1200, 1300
    body = [f'<defs><marker id="a-dark" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="5" markerHeight="5" '
            f'orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="{DARK}"/></marker></defs>',
            text(600, 44, "Knight Capital: how the loss happened", 28, "bold"),
            text(600, 78, "Old code, a reused flag and one missed server, then 45 minutes nobody could stop in time",
                 20, fill=MUTED)]

    body += band_title(140, "The set-up", BLUE)
    body += chain(162, SETUP, BLUE)

    # The morning: 8:00 to 10:30 on one axis.
    body += band_title(350, "The morning of 1 August 2012", RED)
    x0, x1 = 90, 1110

    def px(minutes: float) -> float:
        return x0 + (x1 - x0) * minutes / 150

    by0, by1 = 450, 510
    body.append(f'<rect x="{px(1):.1f}" y="{by0}" width="{px(90) - px(1):.1f}" height="{by1 - by0}" '
                f'fill="{BLUE}" fill-opacity="0.08"/>')
    for k in range(97):
        x = px(1 + 89 * k / 96)
        body.append(line(x, by0 + 12, x, by1 - 12, BLUE, 2))
    body.append(text((px(1) + px(90)) / 2, by0 - 34, "97 automated e-mails: “Power Peg disabled”", 19, "bold", BLUE))
    body.append(text((px(1) + px(90)) / 2, by0 - 10, "nobody treats them as an alarm", 17, fill=MUTED, style="italic"))
    body.append(f'<rect x="{px(90):.1f}" y="{by0}" width="{px(135) - px(90):.1f}" height="{by1 - by0}" fill="{RED}"/>')
    body.append(text((px(90) + px(135)) / 2, by0 + 38, "45 minutes", 22, "bold", "white"))
    body.append(text((px(90) + px(135)) / 2, by0 - 34, "runaway child orders", 19, "bold", RED))
    body.append(text((px(90) + px(135)) / 2, by0 - 10, "every one valid to NYSE", 17, fill=MUTED, style="italic"))
    body.append(line(x0, by1, x1, by1, DARK, 2))
    for m, label in [(0, "8:00"), (30, "8:30"), (60, "9:00"), (90, "9:30"), (120, "10:00"), (135, "10:15"),
                     (150, "10:30")]:
        bold = "bold" if m in (90, 135) else "normal"
        body.append(line(px(m), by1, px(m), by1 + 8, DARK, 2))
        body.append(text(px(m), by1 + 30, label, 17, bold, DARK if bold == "bold" else MUTED))
    body.append(text(px(90), by1 + 54, "NYSE opens", 17, "bold", RED))
    body.append(text(px(135), by1 + 54, "stopped", 17, "bold", RED))

    sy = 650
    body += server_row(90, sy, "At the open: one server still runs old code", 1)
    body += server_row(726, sy, "After the rollback: all eight", 8)
    body.append(arrow(90 + 8 * 48 + 20, sy + 27, 726 - 24, sy + 27))
    body.append(text(600, sy + 8, "staff uninstall the new", 16, "bold", ORANGE))
    body.append(text(600, sy + 70, "code from the 7 good ones", 16, "bold", ORANGE))
    body.append(f'<rect x="90" y="{sy + 92}" width="18" height="18" rx="3" fill="{GREEN}"/>')
    body.append(text(116, sy + 107, "flag means “RLP order”", 17, anchor="start"))
    body.append(f'<rect x="340" y="{sy + 92}" width="18" height="18" rx="3" fill="{RED}"/>')
    body.append(text(366, sy + 107, "flag means “Power Peg”: buy at the offer, sell at the bid, never stop",
                     17, anchor="start"))

    ty = 800
    tw = 1020 / len(STATS)
    for i, (value, label) in enumerate(STATS):
        x = 90 + i * tw
        body.append(f'<rect x="{x + 6:.1f}" y="{ty}" width="{tw - 12:.1f}" height="84" rx="10" fill="{LIGHT}" '
                    f'stroke="{GREY}" stroke-width="2"/>')
        body.append(text(x + tw / 2, ty + 40, value, 25, "bold", RED))
        body.append(text(x + tw / 2, ty + 68, label, 17, fill=MUTED))

    body += band_title(960, "The aftermath", DARK)
    body += chain(982, AFTERMATH, DARK)

    body.append(text(600, h - 140, "NYSE processed every order correctly. Nothing on Knight's own side stopped the",
                     19, fill=DARK))
    body.append(text(600, h - 112, "growing position: no firm-wide limit, no anomaly alarm, no kill switch anyone would pull.",
                     19, fill=DARK))
    return svg(w, h - 80, body), w, h - 80


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
        render(args.chrome, "risk-knight-timeline", timeline(), Path(tmp))


if __name__ == "__main__":
    main()
