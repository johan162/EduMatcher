#!/usr/bin/env python3
"""Generate the figures for the Architecture and Developer Guide.

Writes to docs/assets/architecture/:
  arch-system-overview.png    every process, the buses they bind or connect, and the two planes
  arch-message-frames.png     the three frames of a PUSH and a PUB message, and who adds each
  arch-order-flow.png         one NEW order from keystroke to fan-out, with its causal ids
  arch-buffers-hwm.png        every queue a message waits in, its size, and where it can be lost
  arch-gap-detection.png      per-topic seq and socket-wide eseq, and why a tail drop is seen late
  arch-shutdown-waves.png     pm-opctl stop: the four SIGTERM waves and what each process flushes
  arch-engine-loop.png        one iteration of the engine's run loop

Used in docs/books/architecture-and-development/part-1-architecture/.
Builds SVGs and renders them to PNG with headless Google Chrome, as the figure
scripts of the exchange-intro book do.

Usage: python3 scripts/gen_architecture_figures.py [--chrome PATH] [--only NAME]
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Callable

DEFAULT_CHROME = (
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    if sys.platform == "darwin"
    else "/usr/bin/google-chrome"
)
ASSETS = Path(__file__).resolve().parent.parent / "docs" / "assets" / "architecture"

BLUE, ORANGE, RED, GREEN, PURPLE = "#2b6cb0", "#dd6b20", "#c53030", "#2f855a", "#6b46c1"
DARK, MUTED, GREY, LIGHT, TEAL = "#1a202c", "#4a5568", "#cbd5e0", "#f7fafc", "#2c7a7b"
FONT = 'font-family="Helvetica, Arial, sans-serif"'
MONO = 'font-family="Menlo, Consolas, monospace"'


def esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def text(
    x: float,
    y: float,
    s: str,
    size: int = 18,
    weight: str = "normal",
    fill: str = DARK,
    anchor: str = "middle",
    mono: bool = False,
    style: str = "normal",
) -> str:
    face = MONO if mono else FONT
    return (
        f'<text x="{x:.1f}" y="{y:.1f}" {face} font-size="{size}" font-weight="{weight}" '
        f'font-style="{style}" fill="{fill}" text-anchor="{anchor}">{esc(s)}</text>'
    )


def label(x: float, y: float, s: str, colour: str, size: int = 15) -> list[str]:
    """A short label on a white backing, so it stays legible on top of a line."""
    wd = len(s) * size * 0.62 + 12
    return [
        f'<rect x="{x - wd / 2:.1f}" y="{y - size - 2:.1f}" width="{wd:.1f}" height="{size + 10}" rx="4" fill="white"/>',
        text(x, y, s, size, "bold", colour),
    ]


def lines(
    x: float, y: float, rows: list[str], size: int = 16, gap: int = 22, **kw: object
) -> list[str]:
    return [text(x, y + i * gap, r, size, **kw) for i, r in enumerate(rows)]  # type: ignore[arg-type]


def box(
    x: float,
    y: float,
    w: float,
    h: float,
    colour: str,
    fill_opacity: float = 0.08,
    rx: int = 10,
    dash: str = "",
    stroke_width: float = 2.5,
) -> str:
    d = f' stroke-dasharray="{dash}"' if dash else ""
    return (
        f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" rx="{rx}" fill="{colour}" '
        f'fill-opacity="{fill_opacity}" stroke="{colour}" stroke-width="{stroke_width}"{d}/>'
    )


def solid(x: float, y: float, w: float, h: float, colour: str, rx: int = 10) -> str:
    return f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" rx="{rx}" fill="{colour}"/>'


def arrow(
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    colour: str = DARK,
    both: bool = False,
    dash: str = "",
    width: float = 3,
) -> str:
    mid = colour.lstrip("#")
    start = f' marker-start="url(#a{mid})"' if both else ""
    d = f' stroke-dasharray="{dash}"' if dash else ""
    return (
        f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="{colour}" '
        f'stroke-width="{width}" marker-end="url(#a{mid})"{start}{d}/>'
    )


def path_arrow(d: str, colour: str = DARK, dash: str = "", width: float = 3) -> str:
    mid = colour.lstrip("#")
    da = f' stroke-dasharray="{dash}"' if dash else ""
    return (
        f'<path d="{d}" fill="none" stroke="{colour}" stroke-width="{width}" '
        f'marker-end="url(#a{mid})"{da}/>'
    )


def cross(x: float, y: float, r: float = 11) -> str:
    return (
        f'<circle cx="{x}" cy="{y}" r="{r + 4}" fill="white" stroke="{RED}" stroke-width="2.5"/>'
        f'<path d="M{x - r * 0.6},{y - r * 0.6} L{x + r * 0.6},{y + r * 0.6} '
        f'M{x + r * 0.6},{y - r * 0.6} L{x - r * 0.6},{y + r * 0.6}" stroke="{RED}" stroke-width="3.5"/>'
    )


def defs() -> str:
    markers = "".join(
        f'<marker id="a{c.lstrip("#")}" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="5" '
        f'markerHeight="5" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="{c}"/></marker>'
        for c in (DARK, BLUE, ORANGE, RED, GREEN, PURPLE, MUTED, TEAL)
    )
    return f"<defs>{markers}</defs>"


def svg(w: int, h: int, body: list[str]) -> str:
    return "\n".join(
        [
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">',
            f'<rect width="{w}" height="{h}" fill="white"/>',
            defs(),
            *body,
            "</svg>",
        ]
    )


def title(w: int, main: str, sub: str) -> list[str]:
    return [text(w / 2, 44, main, 28, "bold"), text(w / 2, 76, sub, 18, fill=MUTED)]


# ---------------------------------------------------------------------------
# 1. System overview
# ---------------------------------------------------------------------------


def system_overview() -> tuple[str, int, int]:
    w, h = 1400, 1130
    b = title(
        w,
        "EduMatcher at a glance",
        "One engine binds the core bus; every other process connects to it. Remote clients reach only the gateways.",
    )

    # The trusted host and the network edge.
    b.append(box(300, 110, 1080, 960, MUTED, 0.03, 16, "10 6", 2))
    b.append(
        text(
            320,
            140,
            "Trusted host — core plane binds 127.0.0.1",
            17,
            "bold",
            MUTED,
            "start",
        )
    )
    b.append(box(20, 110, 260, 960, BLUE, 0.03, 16, "10 6", 2))
    b.append(text(150, 140, "Network", 17, "bold", BLUE))

    # External clients.
    clients = [
        ("Trader clients", "ALF text · BALF binary", 210),
        ("Browsers, scripts", "REST · WebSocket", 350),
        ("Market-data clients", "CALF", 490),
        ("Post-trade parties", "RALF · DC1 drop copy", 630),
        ("Any process", "LALF log records", 960),
    ]
    for name, proto, y in clients:
        b.append(box(40, y - 34, 220, 72, BLUE))
        b.append(text(150, y - 6, name, 17, "bold", BLUE))
        b.append(text(150, y + 20, proto, 15, fill=MUTED))

    # Service layer (gateways).
    gws = [
        ("pm-alf-gwy :5565", "pm-balf-gwy :5560", 210),
        ("pm-api-gwy", ":8080 desk · :8081 dashboards", 350),
        ("pm-md-gwy :5570", "CALF feed + replay", 490),
        ("pm-ralf-gwy :5580", "pm-dc-gwy :5590", 630),
    ]
    b.append(text(450, 165, "Service layer — binds 0.0.0.0", 16, "bold", TEAL))
    for top, bottom, y in gws:
        b.append(box(340, y - 38, 220, 80, TEAL, 0.1))
        b.append(text(450, y - 8, top, 16, "bold", TEAL))
        b.append(text(450, y + 18, bottom, 14, fill=DARK))
    for _, _, y in clients[:4]:
        b.append(arrow(262, y, 336, y, BLUE, both=True))

    # The engine.
    ex, ey, ew, eh = 660, 300, 300, 250
    b.append(solid(ex, ey, ew, eh, DARK, 14))
    b.append(text(ex + ew / 2, ey + 40, "pm-engine", 26, "bold", "white"))
    b.append(
        text(ex + ew / 2, ey + 68, "single thread · one book per symbol", 15, fill=GREY)
    )
    for i, (port, what) in enumerate(
        [
            ("PULL :5555", "commands"),
            ("PUB :5556", "events"),
            ("PUB :5557", "drop copy"),
        ]
    ):
        y = ey + 104 + i * 46
        b.append(
            f'<rect x="{ex + 20}" y="{y}" width="{ew - 40}" height="36" rx="18" fill="white" fill-opacity="0.16"/>'
        )
        b.append(text(ex + 36, y + 24, port, 16, "bold", "white", "start", mono=True))
        b.append(text(ex + ew - 36, y + 24, what, 15, fill="white", anchor="end"))

    # Gateways to engine (PUSH) and back (SUB).
    b.append(path_arrow("M562,190 C610,190 610,410 652,410", BLUE))
    b.append(path_arrow("M562,330 C600,330 610,414 652,414", BLUE))
    b.append(path_arrow("M656,456 C610,456 600,500 564,500", ORANGE))
    b.append(path_arrow("M656,460 C610,470 600,630 564,630", ORANGE))
    b.append(path_arrow("M656,452 C610,452 590,360 564,360", ORANGE))
    b += label(610, 262, "PUSH", BLUE)
    b += label(612, 580, "SUB", ORANGE)

    # Second-tier publishers.
    b.append(box(1010, 180, 340, 100, PURPLE, 0.08))
    b.append(text(1180, 212, "pm-index", 18, "bold", PURPLE))
    b.append(text(1180, 238, "PUB :5558 · PULL :5559", 15, mono=True))
    b.append(text(1180, 262, "index levels, corporate actions", 14, fill=MUTED))
    b.append(box(1010, 310, 340, 100, PURPLE, 0.08))
    b.append(text(1180, 342, "pm-market-sim", 18, "bold", PURPLE))
    b.append(text(1180, 368, "PUB :5553 · PULL :5554", 15, mono=True))
    b.append(text(1180, 392, "true values, news", 14, fill=MUTED))
    b.append(arrow(964, 420, 1006, 250, ORANGE))
    b.append(arrow(964, 425, 1006, 370, ORANGE))
    b.append(box(1010, 440, 340, 110, MUTED, 0.04, 8))
    b += lines(
        1180,
        468,
        [
            "Each binds a bus of its own and",
            "follows the engine's :5556; clients",
            "connect to both",
        ],
        14,
        22,
        fill=MUTED,
    )

    # Command senders.
    b.append(box(660, 170, 300, 90, BLUE, 0.06))
    b.append(text(810, 200, "Other command senders", 17, "bold", BLUE))
    b.append(text(810, 226, "pm-scheduler · pm-admin · pm-mm-bot", 14))
    b.append(text(810, 248, "consoles · pm-stats · pm-market-sim", 14))
    b.append(arrow(810, 262, 810, 296, BLUE))

    # Recorders and viewers on the event bus.
    recs = [
        ("pm-audit", "every topic → audit.log"),
        ("pm-clearing", "trades → clearing.db"),
        ("pm-stats", "trades, books → stats.db"),
        ("Viewers, bots", "board · ticker · AI traders"),
    ]
    for i, (name, what) in enumerate(recs):
        x = 336 + i * 260
        b.append(box(x, 770, 236, 76, GREEN))
        b.append(text(x + 118, 802, name, 17, "bold", GREEN))
        b.append(text(x + 118, 828, what, 14, fill=MUTED))
        b.append(arrow(810, 556, x + 118, 766, ORANGE))
    b += label(810, 700, "Event subscribers on :5556", ORANGE, 16)

    # Log and health buses.
    b.append(box(336, 905, 500, 110, MUTED, 0.06))
    b.append(text(586, 937, "pm-log-srv  LALF :5600", 17, "bold", MUTED))
    b.append(text(586, 963, "every process ships its log records here", 14))
    b.append(text(586, 985, "LALF-PS :5601 / :5602 for the log GUI", 14))
    b.append(arrow(262, 960, 332, 960, MUTED, dash="8 6"))
    b.append(box(870, 905, 480, 110, RED, 0.05))
    b.append(text(1110, 937, "pm-monitor  PULL :5610 · PUB :5611", 17, "bold", RED))
    b.append(text(1110, 963, "every long-running process PUSHes a", 14))
    b.append(text(1110, 985, "health beacon every 2 s from its own thread", 14))

    b.append(
        text(
            w / 2,
            h - 22,
            "Arrows point from sender to receiver. Blue: commands (PUSH → PULL). Orange: events (PUB → SUB).",
            17,
            fill=DARK,
        )
    )
    return svg(w, h, b), w, h


# ---------------------------------------------------------------------------
# 2. Message frames
# ---------------------------------------------------------------------------


def _frame_row(
    y: float, label: str, colour: str, frames: list[tuple[str, str, float, str]]
) -> list[str]:
    out = [text(60, y - 14, label, 20, "bold", colour, "start")]
    x = 60.0
    for name, content, width, fill in frames:
        out.append(box(x, y, width, 70, fill, 0.12))
        out.append(text(x + width / 2, y + 28, name, 15, "bold", fill))
        out.append(text(x + width / 2, y + 54, content, 15, mono=True))
        x += width + 14
    return out


def message_frames() -> tuple[str, int, int]:
    w, h = 1400, 820
    b = title(
        w,
        "Anatomy of a bus message",
        "Two frames of content and one frame about the content. decode() reads only frames 0 and 1.",
    )
    b += _frame_row(
        150,
        "PUSH  gateway → engine",
        BLUE,
        [
            ("frame 0 · topic", "order.new", 240, BLUE),
            ("frame 1 · JSON payload", '{"symbol":"AAPL","side":"BUY",…}', 420, BLUE),
            ("frame 2 · envelope", "msg_id|causation_id|correlation_id", 520, PURPLE),
        ],
    )
    b += _frame_row(
        290,
        "PUB  engine → subscribers",
        ORANGE,
        [
            ("frame 0 · topic", "order.ack.TRADER01", 240, ORANGE),
            (
                "frame 1 · JSON payload",
                '{"order_id":"9f2c…","accepted":true}',
                420,
                ORANGE,
            ),
            (
                "frame 2 · trailer",
                "seq|eseq|msg_id|causation_id|correlation_id",
                520,
                PURPLE,
            ),
        ],
    )

    # Who writes what.
    y0 = 420
    b.append(text(60, y0, "Who adds each part", 20, "bold", anchor="start"))
    rows = [
        (
            BLUE,
            "make_*() builders",
            "builds frames 0 and 1 from the spec in spec/messages/ (coerced, validated)",
        ),
        (
            PURPLE,
            "CausalPusher",
            "appends a root envelope: a fresh ULID, no cause, chain = itself",
        ),
        (
            PURPLE,
            "CausalPublisher",
            "stamps msg_id; cites the command being handled as causation_id; inherits its chain",
        ),
        (
            PURPLE,
            "SequencedPublisher",
            "puts seq (per topic) and eseq (per socket) in front of the envelope",
        ),
        (
            DARK,
            "BusSocket",
            "sends the three frames with plain-int flag arithmetic (1.6 µs instead of 4.2 µs)",
        ),
    ]
    for i, (colour, who, what) in enumerate(rows):
        y = y0 + 44 + i * 46
        b.append(solid(60, y - 22, 12, 30, colour, 3))
        b.append(text(88, y, who, 17, "bold", colour, "start", mono=True))
        b.append(text(470, y, what, 17, anchor="start"))

    b.append(box(60, 690, 1280, 96, GREEN, 0.06))
    b += lines(
        700,
        724,
        [
            "Why a frame and not more JSON keys: stamping never decodes and re-encodes the payload, the same fields",
            "need not be declared on 136 message types, and a consumer that does not care is unaffected.",
            "Why one frame and not five: ZeroMQ charges per frame — packing them cut a publish from 8.2 to 5.5 µs.",
        ],
        16,
        24,
    )
    return svg(w, h, b), w, h


# ---------------------------------------------------------------------------
# 3. One order end to end
# ---------------------------------------------------------------------------


def order_flow() -> tuple[str, int, int]:
    w, h = 1400, 1000
    b = title(
        w,
        "One NEW order, end to end",
        "Every message the engine publishes while handling the order cites it as the cause (A) and carries its chain.",
    )
    lanes = [
        ("Trader client", 130),
        ("pm-alf-gwy", 400),
        ("pm-engine", 760),
        ("Subscribers", 1150),
    ]
    for name, x in lanes:
        b.append(
            solid(x - 110, 110, 220, 46, DARK if name == "pm-engine" else MUTED, 10)
        )
        b.append(text(x, 140, name, 18, "bold", "white"))
        b.append(
            f'<line x1="{x}" y1="160" x2="{x}" y2="{h - 70}" stroke="{GREY}" stroke-width="2" stroke-dasharray="6 6"/>'
        )

    def step(
        y: float, x1: float, x2: float, colour: str, label: str, sub: str = ""
    ) -> None:
        b.append(arrow(x1, y, x2, y, colour))
        mx = (x1 + x2) / 2
        b.append(text(mx, y - 10, label, 15, "bold", colour))
        if sub:
            b.append(text(mx, y + 20, sub, 14, fill=MUTED))

    def note(
        x: float, y: float, rows: list[str], colour: str = DARK, width: float = 300
    ) -> None:
        b.append(solid(x - width / 2, y - 22, width, 24 * len(rows) + 16, "white", 8))
        b.append(
            box(x - width / 2, y - 22, width, 24 * len(rows) + 16, colour, 0.07, 8)
        )
        b.extend(lines(x, y, rows, 14, 24, fill=DARK))

    step(205, 130, 400, BLUE, "NEW|SYM=AAPL|SIDE=BUY|QTY=100|PRICE=150.00")
    note(400, 250, ["parse · price → ticks", "gateway_id from the session"], TEAL, 280)
    step(330, 400, 760, BLUE, "PUSH order.new", "envelope msg=A · cause=— · chain=A")
    note(
        760,
        380,
        [
            "echo the command to PUB (audit)",
            "set_cause(A)",
            "gates 1–10: gateway, symbol, fields,",
            "session, ATO/ATC, halt, collar, …",
        ],
        DARK,
        320,
    )
    step(510, 760, 400, ORANGE, "order.ack.TRADER01", "msg=B · cause=A · chain=A")
    step(545, 400, 130, ORANGE, "ACK|ACCEPTED=TRUE")
    note(760, 600, ["book.process(order)", "match → trades, events"], DARK, 280)
    step(680, 760, 1150, ORANGE, "trade.executed", "msg=C · cause=A · chain=A")
    step(740, 760, 1150, ORANGE, "order.fill.TRADER01 / .MM01", "msg=D, E · cause=A")
    step(800, 760, 1150, RED, "drop_copy.event.* on :5557", "sequenced per fill")
    note(760, 850, ["clear_cause()  (in a finally)"], DARK, 280)
    step(
        920, 760, 1150, MUTED, "book.AAPL / depth.AAPL", "next throttle tick · no cause"
    )
    b.append(
        text(
            1150, h - 40, "clearing · stats · audit · md-gwy · viewers", 15, fill=MUTED
        )
    )
    return svg(w, h, b), w, h


# ---------------------------------------------------------------------------
# 4. Buffers and high-water marks
# ---------------------------------------------------------------------------


def buffers_hwm() -> tuple[str, int, int]:
    w, h = 1400, 900
    b = title(
        w,
        "Where a message waits, and where it can be lost",
        "High-water marks count messages, not bytes, and apply per connected peer (one pipe per peer).",
    )

    # Command path.
    b.append(text(60, 140, "Command path", 21, "bold", BLUE, "start"))
    cmd = [
        ("Gateway", "PUSH pipe", "SNDHWM 1000 · IMMEDIATE", BLUE),
        ("Kernel", "TCP buffers", "loopback socket", MUTED),
        ("Engine", "PULL pipe", "RCVHWM 1000 per pusher", DARK),
        ("Engine", "run loop", "one message at a time", DARK),
    ]
    for i, (who, what, size, colour) in enumerate(cmd):
        x = 60 + i * 330
        b.append(box(x, 165, 270, 100, colour, 0.08))
        b.append(text(x + 135, 196, f"{who} — {what}", 17, "bold", colour))
        b.append(text(x + 135, 226, size, 15, mono=True))
        if i < 3:
            b.append(arrow(x + 274, 215, x + 326, 215, BLUE))
    b.append(box(60, 285, 600, 74, RED, 0.05, 8))
    b += lines(
        360,
        314,
        [
            "Engine away or pipe full: send fails at once (SNDTIMEO 0)",
            "→ the client gets ENGINE_UNAVAILABLE. Never blocks, never queues.",
        ],
        15,
        24,
    )

    # Event path.
    b.append(
        text(60, 420, "Event path (one subscriber shown)", 21, "bold", ORANGE, "start")
    )
    ev = [
        ("Engine", "PUB pipe", "SNDHWM 1000 per sub", ORANGE, True),
        ("Kernel", "TCP buffers", "send + receive", MUTED, False),
        ("Subscriber", "SUB pipe", "RCVHWM 1000 … 200 000", GREEN, True),
        ("Subscriber", "application", "drains ≤ 1000 per wake", GREEN, False),
    ]
    for i, (who, what, size, colour, drops) in enumerate(ev):
        x = 60 + i * 330
        b.append(box(x, 445, 270, 100, colour, 0.08))
        b.append(text(x + 135, 476, f"{who} — {what}", 17, "bold", colour))
        b.append(text(x + 135, 506, size, 15, mono=True))
        if i < 3:
            b.append(arrow(x + 274, 495, x + 326, 495, ORANGE))
        if drops:
            b.append(cross(x + 252, 450))
    b.append(box(60, 565, 1260, 74, RED, 0.05, 8))
    b += lines(
        690,
        594,
        [
            "When the next pipe is full, PUB drops the message for that subscriber only — silently. The publisher never waits,",
            "so one slow subscriber can never slow the engine. The subscriber learns of the loss from a jump in seq.",
        ],
        15,
        24,
    )

    # Measured.
    b.append(
        text(
            60,
            690,
            "Measured: a 100 000-message burst to a subscriber that is not reading",
            19,
            "bold",
            anchor="start",
        )
    )
    bars = [
        ("RCVHWM 1000 (default)", 14_000, RED),
        ("RCVHWM 200 000 (recorders)", 100_000, GREEN),
    ]
    for i, (label, n, colour) in enumerate(bars):
        y = 720 + i * 62
        b.append(text(60, y + 30, label, 16, "bold", colour, "start"))
        b.append(
            f'<rect x="360" y="{y + 8}" width="{900 * n / 100_000:.0f}" height="34" rx="6" fill="{colour}" fill-opacity="0.8"/>'
        )
        b.append(
            f'<rect x="360" y="{y + 8}" width="900" height="34" rx="6" fill="none" stroke="{GREY}" stroke-width="2"/>'
        )
        inside = n > 60_000
        b.append(
            text(
                350 + 900 * n / 100_000 if inside else 370 + 900 * n / 100_000,
                y + 32,
                f"{n:,} delivered".replace(",", " "),
                15,
                "bold",
                "white" if inside else DARK,
                "end" if inside else "start",
            )
        )
    return svg(w, h, b), w, h


# ---------------------------------------------------------------------------
# 5. Gap detection
# ---------------------------------------------------------------------------


def gap_detection() -> tuple[str, int, int]:
    w, h = 1400, 860
    b = title(
        w,
        "Seeing a loss that ZeroMQ does not report",
        "seq counts per topic, so a filtering subscriber sees no phantom gaps; eseq counts everything the socket sent.",
    )
    msgs = [
        ("trade", 1, 1),
        ("depth", 1, 2),
        ("trade", 2, 3),
        ("book", 1, 4),
        ("trade", 3, 5),
        ("depth", 2, 6),
        ("trade", 4, 7),
    ]
    colours = {"trade": ORANGE, "depth": TEAL, "book": PURPLE}
    b.append(text(60, 140, "Published by the engine", 19, "bold", anchor="start"))
    for i, (t, seq, eseq) in enumerate(msgs):
        x = 60 + i * 180
        c = colours[t]
        b.append(box(x, 160, 160, 96, c, 0.12))
        b.append(text(x + 80, 190, f"{t}.*", 17, "bold", c, mono=True))
        b.append(text(x + 80, 216, f"seq {seq}", 15, mono=True))
        b.append(text(x + 80, 240, f"eseq {eseq}", 15, fill=MUTED, mono=True))

    for j, i in enumerate([0, 2, 4, 6]):
        x = 60 + i * 180
        b.append(arrow(x + 80, 260, x + 80, 330, ORANGE))
        b.append(box(x, 334, 160, 50, ORANGE, 0.12))
        b.append(text(x + 80, 366, f"seq {j + 1}  ✓", 16, "bold", ORANGE))
    b.append(
        text(
            60,
            416,
            'A subscriber to "trade." receives seq 1, 2, 3, 4 — contiguous, although it filtered out three messages',
            18,
            "bold",
            ORANGE,
            "start",
        )
    )

    b.append(
        text(
            60,
            470,
            "pm-audit takes every topic — it checks eseq, the socket-wide count",
            19,
            "bold",
            DARK,
            "start",
        )
    )
    b += lines(
        60,
        502,
        [
            "Had it checked seq of one topic only, it could not have proved the whole stream complete.",
            "A subscriber that filters must use seq: its eseq would jump on every message it filtered out.",
        ],
        16,
        24,
        anchor="start",
    )

    # Tail drop.
    b.append(
        text(
            60,
            586,
            "A loss is seen only when the next message arrives",
            19,
            "bold",
            RED,
            "start",
        )
    )
    cells = [
        ("1 … 14 000", GREEN, "received"),
        ("14 001 … 100 000", RED, "dropped at the HWM"),
        ("100 001", GREEN, "next publish"),
    ]
    x = 60
    for label, c, note in cells:
        width = 560 if c == RED else 300
        b.append(box(x, 604, width, 70, c, 0.12, 8, "8 6" if c == RED else ""))
        b.append(text(x + width / 2, 634, label, 17, "bold", c, mono=True))
        b.append(text(x + width / 2, 660, note, 15, fill=MUTED))
        x += width + 20
    b += lines(
        60,
        716,
        [
            "Measured (RCVHWM 1000, subscriber not reading during a 100 000-message burst): the last message received had",
            "seq 14 000 and nothing looked wrong. Only when seq 100 001 arrived did the hole of 86 000 become visible.",
            "A seq that goes DOWN is not a gap: the publisher restarted and its counters began again at 1.",
        ],
        16,
        26,
        anchor="start",
    )
    return svg(w, h, b), w, h


# ---------------------------------------------------------------------------
# 6. Shutdown waves
# ---------------------------------------------------------------------------


def shutdown_waves() -> tuple[str, int, int]:
    w, h = 1400, 940
    b = title(
        w,
        "pm-opctl-cli stop: four waves of SIGTERM",
        "Each wave is waited out (up to 15 s) before the next. Nothing is ever sent SIGKILL.",
    )
    waves = [
        (
            "Wave 1 — everything else",
            BLUE,
            ["gateways · bots · GUIs", "scheduler · viewers"],
            [
                "drain the engine events already published, so fills reach their owners",
                "send each client ERR CODE=GATEWAY_SHUTDOWN, flush for up to 2 s",
                "log each session off at the engine (system.gateway_disconnect)",
            ],
        ),
        (
            "Wave 2 — pm-engine",
            DARK,
            ["the single writer"],
            [
                "handler sets _running = False; the current message finishes",
                "save resting orders, combos, book stats (atomic, fsync)",
                "publish system.book_checkpoint per symbol, then system.eod",
                "close PULL, PUB, drop copy; stop the health reporter",
            ],
        ),
        (
            "Wave 3 — the recorders",
            GREEN,
            ["pm-audit · pm-clearing", "pm-stats · pm-index", "pm-monitor"],
            [
                "still running in wave 2, so they received system.eod",
                "on SIGTERM each drains what is already queued: pm-audit until system.eod (≤ 5 s),",
                "pm-stats for 0.5 s, pm-clearing until a 250 ms poll comes back empty",
                "then commit, fsync and close",
            ],
        ),
        (
            "Wave 4 — pm-log-srv",
            MUTED,
            ["the central log"],
            [
                "last, so it records every other process's farewell",
                "commits its batch, closes log.db",
            ],
        ),
    ]
    y = 110
    for i, (name, colour, who, rows) in enumerate(waves):
        hgt = 40 + 26 * len(rows) + 20
        b.append(solid(60, y, 300, hgt, colour, 10))
        b.append(text(210, y + 36, name, 18, "bold", "white"))
        b += lines(210, y + 64, who, 14, 20, fill="white")
        b.append(box(380, y, 960, hgt, colour, 0.06))
        b += [
            text(410, y + 36 + k * 26, "•  " + r, 16, anchor="start")
            for k, r in enumerate(rows)
        ]
        if i < 3:
            b.append(arrow(210, y + hgt + 4, 210, y + hgt + 34, colour))
        y += hgt + 40
    b.append(box(60, y - 10, 1280, 88, RED, 0.05, 8))
    b += lines(
        700,
        y + 20,
        [
            "Why this order: the recorders must still be listening when the engine says its last word, and the",
            "engine must stop before them so that nothing new is published after they have drained.",
        ],
        16,
        26,
    )
    return svg(w, h, b), w, h


# ---------------------------------------------------------------------------
# 7. Engine loop
# ---------------------------------------------------------------------------


def engine_loop() -> tuple[str, int, int]:
    w, h = 1400, 820
    b = title(
        w,
        "One turn of the engine's run loop",
        "A message is handled to completion before the next is looked at. Maintenance runs between messages.",
    )
    steps = [
        ("poll PULL, ≤ 200 ms", "wakes on a message or the timeout", BLUE),
        ("recv + decode", "guarded: a bad message is counted, not fatal", BLUE),
        ("echo the command", "re-published so the audit trail has it first", PURPLE),
        ("set_cause(envelope)", "everything published now cites it", PURPLE),
        ("dispatch → handler", "gates, book.process, publish results", DARK),
        ("clear_cause()", "in a finally — never leaks to the next", PURPLE),
    ]
    for i, (head, sub, colour) in enumerate(steps):
        y = 120 + i * 82
        b.append(box(140, y, 470, 64, colour, 0.1))
        b.append(text(375, y + 28, head, 18, "bold", colour, mono=head[0].islower()))
        b.append(text(375, y + 52, sub, 14, fill=MUTED))
        if i < len(steps) - 1:
            b.append(arrow(375, y + 66, 375, y + 80, colour))
    # Maintenance block.
    b.append(box(700, 160, 620, 380, GREEN, 0.06))
    b.append(text(1010, 196, "_run_maintenance()", 20, "bold", GREEN, mono=True))
    b.append(
        text(
            1010,
            224,
            "on every idle poll, and every 10 ms while busy · each step guarded",
            15,
            fill=MUTED,
        )
    )
    items = [
        "book.<SYM> / depth.<SYM> snapshots, throttled per symbol",
        "auction indicatives during a call phase",
        "circuit-breaker reopen timers",
        "silent gateways: 3 missed heartbeats → disconnect",
        "checkpoint the resting book to disk every 5 s",
        "debug-count summary every 5 s",
        "hand the health beacon its samples",
    ]
    b += [
        text(730, 264 + k * 38, "•  " + t, 16, anchor="start")
        for k, t in enumerate(items)
    ]
    b.append(path_arrow("M612,580 C660,580 660,500 696,500", GREEN))
    b.append(box(700, 580, 620, 90, ORANGE, 0.06))
    b.append(text(1010, 614, "GcPolicy.tick(idle)", 18, "bold", ORANGE, mono=True))
    b.append(
        text(
            1010,
            642,
            "collect while idle; freeze long-lived objects after the open",
            15,
        )
    )
    b.append(path_arrow("M140,600 C60,600 60,140 136,140", MUTED, "8 6"))
    b.append(text(52, 380, "next", 15, "bold", MUTED, style="italic"))
    b.append(text(52, 400, "turn", 15, "bold", MUTED, style="italic"))
    b.append(
        text(
            w / 2,
            h - 40,
            "SIGTERM only clears _running: the loop ends after the current turn, then _shutdown() runs.",
            17,
        )
    )
    return svg(w, h, b), w, h


FIGURES: dict[str, Callable[[], tuple[str, int, int]]] = {
    "arch-system-overview": system_overview,
    "arch-message-frames": message_frames,
    "arch-order-flow": order_flow,
    "arch-buffers-hwm": buffers_hwm,
    "arch-gap-detection": gap_detection,
    "arch-shutdown-waves": shutdown_waves,
    "arch-engine-loop": engine_loop,
}


def render(chrome: str, name: str, built: tuple[str, int, int], tmp: Path) -> None:
    content, w, h = built
    src = tmp / f"{name}.svg"
    src.write_text(content, encoding="utf-8")
    out = ASSETS / f"{name}.png"
    subprocess.run(
        [
            chrome,
            "--headless=new",
            "--disable-gpu",
            "--hide-scrollbars",
            "--force-device-scale-factor=2",
            f"--window-size={w},{h}",
            f"--screenshot={out}",
            src.as_uri(),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    print(f"Wrote {out}")


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "--chrome", default=DEFAULT_CHROME, help="Chrome/Chromium executable"
    )
    ap.add_argument("--only", choices=sorted(FIGURES), help="render one figure")
    args = ap.parse_args()
    ASSETS.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        for name, fn in FIGURES.items():
            if args.only in (None, name):
                render(args.chrome, name, fn(), Path(tmp))


if __name__ == "__main__":
    main()
