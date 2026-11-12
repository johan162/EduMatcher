#!/usr/bin/env python3
"""Generate the figures for the participants chapter.

Writes to assets/:
  participants-map.png   who is in the room: investors, brokers, market makers, the exchange, clearing and regulators

Used in src/01-foundation/04-the-participants.md.
Builds SVGs and renders them to PNG with headless Google Chrome.

Usage: python3 scripts/gen_participants_figures.py [--chrome PATH]
"""
from __future__ import annotations

import argparse
import subprocess
import tempfile
from pathlib import Path

DEFAULT_CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
ASSETS = Path(__file__).resolve().parent.parent / "assets"

BLUE, ORANGE, RED, GREEN, DARK, MUTED, GREY = "#2b6cb0", "#dd6b20", "#c53030", "#2f855a", "#1a202c", "#4a5568", "#cbd5e0"
PURPLE, TEAL = "#6b46c1", "#2c7a7b"
FONT = 'font-family="Helvetica, Arial, sans-serif"'


def text(x: float, y: float, s: str, size: int = 20, weight: str = "normal",
         fill: str = DARK, anchor: str = "middle", style: str = "normal") -> str:
    return (f'<text x="{x:.1f}" y="{y:.1f}" {FONT} font-size="{size}" font-weight="{weight}" '
            f'font-style="{style}" fill="{fill}" text-anchor="{anchor}">{s}</text>')


def box(cx: float, cy: float, w: float, h: float, colour: str, title: str, lines: list[str]) -> list[str]:
    out = [f'<rect x="{cx - w / 2:.1f}" y="{cy - h / 2:.1f}" width="{w}" height="{h}" rx="14" fill="{colour}"/>',
           text(cx, cy - h / 2 + 34, title, 23, "bold", "white")]
    for i, line in enumerate(lines):
        out.append(text(cx, cy - h / 2 + 64 + 25 * i, line, 17, fill="white"))
    return out


def arrow(x1: float, y1: float, x2: float, y2: float, label: str, colour: str = DARK,
          lx: float | None = None, ly: float | None = None, dash: bool = False, both: bool = False) -> list[str]:
    d = ' stroke-dasharray="9 7"' if dash else ""
    start = ' marker-start="url(#a-dark)"' if both else ""
    out = [f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="{colour}" stroke-width="3.5"'
           f' marker-end="url(#a-dark)"{start}{d}/>']
    if label:
        out.append(text(lx if lx is not None else (x1 + x2) / 2, ly if ly is not None else (y1 + y2) / 2 - 10,
                        label, 17, "bold", MUTED))
    return out


def svg(w: int, h: int, body: list[str]) -> str:
    marker = (f'<marker id="a-dark" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="5" markerHeight="5" '
              f'orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="{DARK}"/></marker>')
    return "\n".join([f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">',
                      f"<defs>{marker}</defs>", f'<rect width="{w}" height="{h}" fill="white"/>', *body, "</svg>"])


def participants_map() -> tuple[str, int, int]:
    w, h = 1200, 820
    body = [text(600, 44, "Who is in the room", 30, "bold"),
            text(600, 80, "The participants of this chapter and how orders, trades and oversight flow between them", 20, fill=MUTED)]
    body += box(170, 250, 260, 150, BLUE, "Investors", ["retail (individuals)", "institutional (funds,", "pensions, insurers)"])
    body += box(170, 520, 260, 130, TEAL, "Brokers", ["execute orders for", "clients; broker-dealers"])
    body += box(600, 385, 280, 170, DARK, "The exchange", ["gateways, order books,", "matching engine,", "market data"])
    body += box(1030, 200, 280, 150, PURPLE, "Market makers", ["and HFT / prop firms:", "trade for their own", "account, quote both sides"])
    body += box(1030, 560, 280, 160, ORANGE, "Clearing house (CCP)", ["guarantees trades via", "clearing members;", "CSD records ownership"])
    body += box(600, 690, 360, 96, RED, "Regulators", ["SEC, CFTC, FINRA, FCA, ESMA, ..."])

    body += arrow(170, 326, 170, 452, "", BLUE)
    body.append(text(186, 395, "orders", 17, "bold", MUTED, "start"))
    body += arrow(302, 500, 458, 425, "orders", lx=372, ly=446)
    body += arrow(888, 245, 742, 340, "quotes and orders", lx=868, ly=318, both=True)
    body += arrow(742, 430, 888, 530, "trades", lx=835, ly=462)
    body.append(text(614, 262, "market data out to everyone", 17, "bold", GREEN, "start"))
    body.append(f'<line x1="600" y1="298" x2="600" y2="225" stroke="{GREEN}" stroke-width="3.5" stroke-dasharray="6 5"/>')
    for x, y in [(420, 690), (780, 690)]:
        tx, ty = (170, 590) if x < 600 else (1030, 645)
        body += arrow(x, y, tx + (40 if x < 600 else -40), ty, "", RED, dash=True)
    body += arrow(600, 640, 600, 474, "", RED, dash=True)
    body.append(text(616, 600, "oversight", 17, "bold", RED, "start"))
    body.append(text(600, h - 22, "Investors reach the exchange through brokers; market makers connect directly as members.",
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
        render(args.chrome, "participants-map", participants_map(), Path(tmp))


if __name__ == "__main__":
    main()
