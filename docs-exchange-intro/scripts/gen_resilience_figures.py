#!/usr/bin/env python3
"""Generate the figures for the primary and secondary sites chapter.

Writes to assets/:
  resilience-active-passive.png   active-passive replication through a WAL, heartbeat monitoring and failover

Used in src/04-technology-and-infrastructure/04-primary-and-secondary-sites-resilience-architecture.md.
Builds SVGs and renders them to PNG with headless Google Chrome.

Usage: python3 scripts/gen_resilience_figures.py [--chrome PATH]
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
BW, BH = 300, 150


def text(x: float, y: float, s: str, size: int = 20, weight: str = "normal",
         fill: str = DARK, anchor: str = "middle", style: str = "normal") -> str:
    return (f'<text x="{x:.1f}" y="{y:.1f}" {FONT} font-size="{size}" font-weight="{weight}" '
            f'font-style="{style}" fill="{fill}" text-anchor="{anchor}">{s}</text>')


def box(cx: float, cy: float, colour: str, title: str, lines: list[str], filled: bool = True) -> list[str]:
    fill, ink, sub = (colour, "white", "white") if filled else ("white", colour, MUTED)
    out = [f'<rect x="{cx - BW / 2:.1f}" y="{cy - BH / 2:.1f}" width="{BW}" height="{BH}" rx="14" fill="{fill}" '
           f'stroke="{colour}" stroke-width="3"/>',
           text(cx, cy - BH / 2 + 36, title, 23, "bold", ink)]
    for i, line in enumerate(lines):
        out.append(text(cx, cy - BH / 2 + 68 + 25 * i, line, 17, fill=sub))
    return out


def arrow(x1: float, y1: float, x2: float, y2: float, colour: str = DARK, dash: bool = False) -> str:
    d = ' stroke-dasharray="9 7"' if dash else ""
    return (f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="{colour}" stroke-width="3.5" '
            f'marker-end="url(#a-dark)"{d}/>')


def svg(w: int, h: int, body: list[str]) -> str:
    marker = (f'<marker id="a-dark" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="5" markerHeight="5" '
              f'orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="{DARK}"/></marker>')
    return "\n".join([f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">',
                      f"<defs>{marker}</defs>", f'<rect width="{w}" height="{h}" fill="white"/>', *body, "</svg>"])


def active_passive() -> tuple[str, int, int]:
    w, h = 1200, 760
    xs = [200, 600, 1000]
    top, bot = 215, 545
    body = [text(600, 44, "Active-passive replication and failover", 28, "bold"),
            text(600, 80, "Normal operation on the top row; what happens when the primary stops on the bottom row", 20, fill=MUTED)]

    body.append(f'<rect x="30" y="{top - BH / 2 - 30}" width="1140" height="{BH + 60}" rx="16" fill="{LIGHT}" stroke="{GREY}"/>')
    body.append(text(48, top - BH / 2 - 8, "Normal operation", 18, "bold", MUTED, "start"))
    body.append(f'<rect x="30" y="{bot - BH / 2 - 30}" width="1140" height="{BH + 60}" rx="16" fill="#fff5f5" stroke="{GREY}"/>')
    body.append(text(48, bot - BH / 2 - 8, "Primary fails", 18, "bold", RED, "start"))

    body += box(xs[0], top, BLUE, "Primary site", ["ACTIVE", "accepts orders", "publishes events"])
    body += box(xs[1], top, DARK, "Write-ahead log", ["every event written", "before it is processed"], filled=False)
    body += box(xs[2], top, MUTED, "Secondary site", ["PASSIVE (shadow)", "follows the log silently", "does not publish"])
    body.append(arrow(xs[0] + BW / 2 + 4, top, xs[1] - BW / 2 - 8, top))
    body.append(text((xs[0] + xs[1]) / 2, top - 14, "log first", 17, "bold", MUTED))
    body.append(arrow(xs[1] + BW / 2 + 4, top, xs[2] - BW / 2 - 8, top))
    body.append(text((xs[1] + xs[2]) / 2, top - 14, "streamed", 17, "bold", MUTED))
    body.append(text((xs[1] + xs[2]) / 2, top + 26, "in real time", 17, "bold", MUTED))

    body += box(xs[0], bot, ORANGE, "Heartbeat monitor", ["expects a heartbeat", "from the primary", "every N ms"])
    body += box(xs[1], bot, RED, "Failover decision", ["heartbeat missed (timeout)", "fence the old primary", "manual or automatic"])
    body += box(xs[2], bot, GREEN, "Secondary promoted", ["now ACTIVE", "resumes from the log's tail", "begins publishing"])
    body.append(arrow(xs[0], top + BH / 2 + 4, xs[0], bot - BH / 2 - 8, ORANGE, dash=True))
    body.append(text(xs[0] + 14, (top + bot) / 2 + 6, "heartbeats", 17, "bold", ORANGE, "start"))
    body.append(arrow(xs[0] + BW / 2 + 4, bot, xs[1] - BW / 2 - 8, bot))
    body.append(text((xs[0] + xs[1]) / 2, bot - 14, "missed", 17, "bold", MUTED))
    body.append(arrow(xs[1] + BW / 2 + 4, bot, xs[2] - BW / 2 - 8, bot))
    body.append(text((xs[1] + xs[2]) / 2, bot - 14, "promote", 17, "bold", MUTED))
    body.append(arrow(xs[2], top + BH / 2 + 4, xs[2], bot - BH / 2 - 8, GREEN, dash=True))
    body.append(text(xs[2] + 14, (top + bot) / 2 + 6, "same machine,", 17, "bold", GREEN, "start"))
    body.append(text(xs[2] + 14, (top + bot) / 2 + 28, "new role", 17, "bold", GREEN, "start"))

    body.append(text(600, h - 50, "The promoted secondary continues the same sequence numbers, so participants see no gap.", 19, fill=DARK))
    body.append(text(600, h - 20, "Fencing the old primary first prevents split brain: two engines both accepting orders.", 18, fill=MUTED, style="italic"))
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
        render(args.chrome, "resilience-active-passive", active_passive(), Path(tmp))


if __name__ == "__main__":
    main()
