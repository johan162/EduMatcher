#!/usr/bin/env python3
"""Generate the figures for the technology architecture chapter.

Writes to assets/:
  tech-architecture-overview.png   participants, gateway, matching engine, message bus and subscribers
  tech-md-gap-recovery.png         UDP multicast live feed with a TCP replay channel for a lost packet

Used in src/04-technology-and-infrastructure/02-the-technology-architecture.md.
Builds SVGs and renders them to PNG with headless Google Chrome.

Usage: python3 scripts/gen_architecture_figures.py [--chrome PATH]
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

PARTICIPANTS = [("Participant A", "GW01"), ("Participant B", "GW02"), ("Participant C", "GW03")]
SUBSCRIBERS = [("Clearing", "process"), ("Audit", "log"), ("Market data", "feed"), ("Stats", "recorder"),
               ("Drop copy", "feed")]


def text(x: float, y: float, s: str, size: int = 20, weight: str = "normal",
         fill: str = DARK, anchor: str = "middle", style: str = "normal") -> str:
    return (f'<text x="{x:.1f}" y="{y:.1f}" {FONT} font-size="{size}" font-weight="{weight}" '
            f'font-style="{style}" fill="{fill}" text-anchor="{anchor}">{s}</text>')


def arrow(x1: float, y1: float, x2: float, y2: float, colour: str = DARK, both: bool = False) -> str:
    start = ' marker-start="url(#a-dark)"' if both else ""
    return (f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="{colour}" stroke-width="3.5" '
            f'marker-end="url(#a-dark)"{start}/>')


def box(x: float, y: float, w: float, h: float, colour: str, fill_opacity: float = 0.08) -> str:
    return (f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" rx="10" fill="{colour}" '
            f'fill-opacity="{fill_opacity}" stroke="{colour}" stroke-width="2.5"/>')


def svg(w: int, h: int, body: list[str]) -> str:
    return "\n".join([f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">',
                      f'<rect width="{w}" height="{h}" fill="white"/>', *body, "</svg>"])


def overview() -> tuple[str, int, int]:
    w, h = 1200, 1080
    body = [f'<defs><marker id="a-dark" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="5" markerHeight="5" '
            f'orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="{DARK}"/></marker></defs>',
            text(600, 44, "The exchange technology stack", 28, "bold"),
            text(600, 78, "Commands flow down through one serialised path; events fan out to every subscriber",
                 20, fill=MUTED)]

    # Participants and load balancer.
    py0, ph, pw = 120, 80, 260
    lb_y, lb_h = 262, 56
    for i, (name, gw) in enumerate(PARTICIPANTS):
        cx = 300 + 300 * i
        body.append(box(cx - pw / 2, py0, pw, ph, BLUE))
        body.append(text(cx, py0 + 34, name, 21, "bold", BLUE))
        body.append(text(cx, py0 + 62, gw, 18, fill=MUTED))
        body.append(arrow(cx, py0 + ph + 6, 600 + (cx - 600) * 0.3, lb_y - 6, both=True))
    body.append(box(450, lb_y, 300, lb_h, MUTED, 0.10))
    body.append(text(600, lb_y + 36, "Load balancer", 21, "bold"))

    # Gateway layer.
    gw_y, gw_h = 380, 84
    body.append(arrow(600, lb_y + lb_h + 6, 600, gw_y - 6, both=True))
    body.append(text(780, 268, "orders in ↓", 18, "bold", BLUE, "start"))
    body.append(text(780, 292, "ACKs and fill", 18, "bold", GREEN, "start"))
    body.append(text(780, 316, "notifications out ↑", 18, "bold", GREEN, "start"))
    body.append(box(250, gw_y, 700, gw_h, BLUE, 0.12))
    body.append(text(600, gw_y + 36, "Gateway layer", 23, "bold", BLUE))
    body.append(text(600, gw_y + 66, "authentication · validation · FIX translation", 19, fill=DARK))

    # Matching engine, with the PUSH / PULL pair to the gateway.
    me_y, me_h = 580, 120
    body.append(arrow(500, gw_y + gw_h + 6, 500, me_y - 6))
    body.append(text(484, 512, "validated orders", 18, "bold", BLUE, "end"))
    body.append(text(484, 536, "(PUSH)", 18, fill=MUTED, anchor="end"))
    body.append(arrow(700, me_y - 6, 700, gw_y + gw_h + 6))
    body.append(text(716, 512, "ACKs and fills", 18, "bold", GREEN, "start"))
    body.append(text(716, 536, "(PULL)", 18, fill=MUTED, anchor="start"))
    body.append(f'<rect x="250" y="{me_y}" width="700" height="{me_h}" rx="12" fill="{DARK}"/>')
    body.append(text(600, me_y + 42, "Matching engine", 25, "bold", "white"))
    for k, chip in enumerate(["single-threaded", "one book per symbol", "deterministic"]):
        cx = 380 + 220 * k
        body.append(f'<rect x="{cx - 100}" y="{me_y + 64}" width="200" height="38" rx="19" fill="white" '
                    f'fill-opacity="0.15"/>')
        body.append(text(cx, me_y + 90, chip, 18, "bold", "white"))

    # Message bus and subscribers.
    bus_y, bus_h = 790, 60
    body.append(arrow(600, me_y + me_h + 6, 600, bus_y - 6))
    body.append(text(616, 744, "trades, fills, book updates", 18, "bold", ORANGE, "start"))
    body.append(f'<rect x="60" y="{bus_y}" width="1080" height="{bus_h}" rx="10" fill="{ORANGE}"/>')
    body.append(text(600, bus_y + 39, "PUB socket · message bus", 23, "bold", "white"))

    sy, sh, sw, gap = 920, 84, 200, 20
    for i, (name, kind) in enumerate(SUBSCRIBERS):
        x = 60 + i * (sw + gap)
        body.append(arrow(x + sw / 2, bus_y + bus_h + 6, x + sw / 2, sy - 6))
        body.append(box(x, sy, sw, sh, GREEN))
        body.append(text(x + sw / 2, sy + 36, name, 21, "bold", GREEN))
        body.append(text(x + sw / 2, sy + 64, kind, 18, fill=MUTED))

    body.append(text(600, h - 24, "Every subscriber receives the same stream of events and takes what its job needs.",
                     19, fill=DARK))
    return svg(w, h, body), w, h


def seq_strip(cx: float, y: float, missing: int | None) -> list[str]:
    """Sequence numbers 44-48 as received; a lost one is drawn as an empty dashed slot."""
    out = []
    for k, n in enumerate(range(44, 49)):
        x = cx - 2.5 * 52 + k * 52
        if n == missing:
            out.append(f'<rect x="{x + 2}" y="{y}" width="46" height="40" rx="5" fill="white" stroke="{RED}" '
                       f'stroke-width="2.5" stroke-dasharray="6 4"/>')
            out.append(text(x + 25, y + 27, "?", 20, "bold", RED))
        else:
            out.append(f'<rect x="{x + 2}" y="{y}" width="46" height="40" rx="5" fill="{BLUE}"/>')
            out.append(text(x + 25, y + 27, str(n), 18, "bold", "white"))
    return out


def gap_recovery() -> tuple[str, int, int]:
    w, h = 1200, 850
    body = [f'<defs><marker id="a-dark" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="5" markerHeight="5" '
            f'orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="{DARK}"/></marker>'
            f'<marker id="a-red" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="5" markerHeight="5" '
            f'orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="{RED}"/></marker>'
            f'<marker id="a-green" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="5" markerHeight="5" '
            f'orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="{GREEN}"/></marker></defs>',
            text(600, 44, "Market data: UDP multicast with TCP recovery", 28, "bold"),
            text(600, 78, "One live feed for everyone; a separate replay channel for whoever missed a packet",
                 20, fill=MUTED)]

    me_y = 120
    body.append(f'<rect x="420" y="{me_y}" width="360" height="70" rx="12" fill="{DARK}"/>')
    body.append(text(600, me_y + 44, "Matching engine", 24, "bold", "white"))

    bus_y = 270
    body.append(arrow(600, me_y + 76, 600, bus_y - 6))
    body.append(text(616, 228, "seq 1, 2, 3 …", 18, "bold", ORANGE, "start"))
    body.append(text(616, 251, "each packet sent once", 18, fill=MUTED, anchor="start"))
    body.append(f'<rect x="60" y="{bus_y}" width="1080" height="60" rx="10" fill="{ORANGE}"/>')
    body.append(text(600, bus_y + 39, "UDP multicast · live feed", 23, "bold", "white"))

    sy, sw, sh = 410, 340, 150
    for i, name in enumerate(["Subscriber A", "Subscriber B", "Subscriber C"]):
        cx = 220 + 380 * i
        gap = i == 2
        body.append(arrow(cx, bus_y + 66, cx, sy - 6))
        colour = RED if gap else GREEN
        body.append(box(cx - sw / 2, sy, sw, sh, colour))
        body.append(text(cx, sy + 36, name, 21, "bold", colour))
        body += seq_strip(cx, sy + 56, 47 if gap else None)
        body.append(text(cx, sy + 128, "gap detected after 46" if gap else "complete, in order", 18,
                         "bold" if gap else "normal", RED if gap else MUTED))
    body.append(text(410, 380, "no ACKs, no retransmission", 17, fill=MUTED, style="italic"))

    # Replay channel under subscriber C, with the request and the answer.
    tx, ty, tw, th = 980, 670, 340, 84
    body.append(box(tx - tw / 2, ty, tw, th, BLUE, 0.12))
    body.append(text(tx, ty + 36, "TCP unicast", 22, "bold", BLUE))
    body.append(text(tx, ty + 64, "replay channel", 18, fill=MUTED))
    body.append(arrow(tx - 60, sy + sh + 6, tx - 60, ty - 6, RED).replace("a-dark", "a-red"))
    body.append(text(tx - 76, 604, "resend", 18, "bold", RED, "end"))
    body.append(text(tx - 76, 628, "seq 47", 18, "bold", RED, "end"))
    body.append(arrow(tx + 60, ty - 6, tx + 60, sy + sh + 6, GREEN).replace("a-dark", "a-green"))
    body.append(text(tx + 76, 604, "seq 47", 18, "bold", GREEN, "start"))
    body.append(text(tx + 76, 628, "retransmitted", 18, "bold", GREEN, "start"))

    body.append(text(80, 650, "Every message carries a sequence number.", 19, anchor="start"))
    body.append(text(80, 678, "A subscriber that sees 46 followed by 48", 19, anchor="start"))
    body.append(text(80, 706, "knows 47 was lost, and asks for that one", 19, anchor="start"))
    body.append(text(80, 734, "message alone over a reliable TCP channel.", 19, anchor="start"))
    body.append(text(600, h - 24, "The live feed never waits: subscribers A and B are unaffected by C's recovery.",
                     19, fill=DARK))
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
        for name, fn in [("tech-architecture-overview", overview), ("tech-md-gap-recovery", gap_recovery)]:
            render(args.chrome, name, fn(), Path(tmp))


if __name__ == "__main__":
    main()
