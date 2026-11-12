#!/usr/bin/env python3
"""Generate the figures for the market maker chapter.

Writes to assets/:
  mm-quote-lifecycle.png   the full lifecycle of a market maker quote, drawn as a loop

Used in src/02-orders-and-matching/09-market-makers-the-providers-of-liquidity.md.
Builds SVGs and renders them to PNG with headless Google Chrome.

Usage: python3 scripts/gen_market_maker_figures.py [--chrome PATH]
"""
from __future__ import annotations

import argparse
import subprocess
import tempfile
from pathlib import Path

DEFAULT_CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
ASSETS = Path(__file__).resolve().parent.parent / "assets"

BLUE, ORANGE, RED, GREEN, DARK, MUTED, GREY = "#2b6cb0", "#dd6b20", "#c53030", "#2f855a", "#1a202c", "#4a5568", "#a0aec0"
FONT = 'font-family="Helvetica, Arial, sans-serif"'
BW, BH = 250, 110


def text(x: float, y: float, s: str, size: int = 20, weight: str = "normal",
         fill: str = DARK, anchor: str = "middle", style: str = "normal") -> str:
    return (f'<text x="{x:.1f}" y="{y:.1f}" {FONT} font-size="{size}" font-weight="{weight}" '
            f'font-style="{style}" fill="{fill}" text-anchor="{anchor}">{s}</text>')


def box(cx: float, cy: float, title: str, lines: list[str], colour: str = BLUE) -> list[str]:
    out = [f'<rect x="{cx - BW / 2}" y="{cy - BH / 2}" width="{BW}" height="{BH}" rx="12" '
           f'fill="{colour}" fill-opacity="0.08" stroke="{colour}" stroke-width="2.5"/>',
           text(cx, cy - 18, title, 21, "bold", colour)]
    out += [text(cx, cy + 12 + 24 * i, s, 17, fill=MUTED) for i, s in enumerate(lines)]
    return out


def path(d: str, colour: str = DARK, label: str = "", lx: float = 0, ly: float = 0) -> list[str]:
    mid = {DARK: "a-dark", RED: "a-red", GREEN: "a-green"}[colour]
    out = [f'<path d="{d}" fill="none" stroke="{colour}" stroke-width="3" marker-end="url(#{mid})"/>']
    if label:
        out.append(text(lx, ly, label, 18, "bold", colour))
    return out


def svg(w: int, h: int, body: list[str]) -> str:
    markers = "".join(
        f'<marker id="{i}" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" '
        f'orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="{c}"/></marker>'
        for i, c in [("a-dark", DARK), ("a-red", RED), ("a-green", GREEN)])
    return "\n".join([f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">',
                      f"<defs>{markers}</defs>", f'<rect width="{w}" height="{h}" fill="white"/>', *body, "</svg>"])


def quote_lifecycle() -> tuple[str, int, int]:
    w, h = 1240, 720
    top, mid, low = 110, 380, 610
    x1, x2, x3, x4 = 150, 460, 770, 1080
    half = BW / 2
    body: list[str] = []
    body += box(x1, top, "1. Submit quote", ["Two-sided: bid and ask", "resting in the book"], GREEN)
    body += box(x2, top, "2. Quote rests", ["Anyone may trade", "against either side"])
    body += box(x3, top, "3. Fill event", ["One side is hit by", "an aggressive order"])
    body += box(x4, top, "4. Refresh policy", ["Surviving side is", "cancelled or left active"])
    body += box(x3, mid, "6. Re-quoting window", ["Exchange tracks the", "deadline for a fresh quote"])
    body += box(x2, mid, "7. Fresh quote", ["New bid and ask", "at updated prices"], GREEN)
    body += box(x4, low, "MMP fires", ["All quotes cancelled;", "protection period starts"], RED)

    dw, dh = 135, 75
    body.append(f'<polygon points="{x4},{mid - dh} {x4 + dw},{mid} {x4},{mid + dh} {x4 - dw},{mid}" '
                f'fill="{ORANGE}" fill-opacity="0.08" stroke="{ORANGE}" stroke-width="2.5"/>')
    body.append(text(x4, mid - 8, "5. MMP check", 20, "bold", ORANGE))
    body.append(text(x4, mid + 18, "Nth fill in the", 16, fill=MUTED))
    body.append(text(x4, mid + 38, "rolling window?", 16, fill=MUTED))

    body += path(f"M {x1 + half} {top} L {x2 - half - 4} {top}")
    body += path(f"M {x2 + half} {top} L {x3 - half - 4} {top}")
    body += path(f"M {x3 + half} {top} L {x4 - half - 4} {top}")
    body += path(f"M {x4} {top + BH / 2} L {x4} {mid - dh - 4}")
    body += path(f"M {x4 - dw} {mid} L {x3 + half + 4} {mid}", GREEN, "No", (x4 - dw + x3 + half) / 2, mid - 12)
    body += path(f"M {x4} {mid + dh} L {x4} {low - BH / 2 - 4}", RED, "Yes", x4 + 26, (mid + dh + low - BH / 2) / 2 + 6)
    body += path(f"M {x4 - half} {low} L {x3} {low} L {x3} {mid + BH / 2 + 4}")
    body += path(f"M {x3 - half} {mid} L {x2 + half + 4} {mid}")
    body += path(f"M {x2} {mid - BH / 2} L {x2} {top + BH / 2 + 4}")

    body.append(text((x2 + x3) / 2, (top + mid) / 2 - 2, "↻ repeats dozens of", 18, "bold", MUTED, style="italic"))
    body.append(text((x2 + x3) / 2, (top + mid) / 2 + 22, "times per minute per symbol", 18, "bold", MUTED, style="italic"))
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
        render(args.chrome, "mm-quote-lifecycle", quote_lifecycle(), Path(tmp))


if __name__ == "__main__":
    main()
