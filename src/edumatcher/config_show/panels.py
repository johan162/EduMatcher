"""Panel builders.  Each takes a width and returns a ``rich`` renderable.

Every builder is responsible for degrading gracefully as its width shrinks:
shedding optional columns, switching to a stacked form, or falling back to a
plain list.  Nothing here may overflow the width it was handed -- that is the
single invariant the test suite checks hardest.
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any, Literal, Sequence

from rich.console import Group, RenderableType
from rich.panel import Panel as RichPanel
from rich.table import Table
from rich.text import Text

from edumatcher.gateway_ports import SINGLETON_GATEWAYS

from edumatcher.config_show import theme as T
from edumatcher.config_show.layout import GAP
from edumatcher.config_show.model import ConfigView, Symbol

#: yaml section key -> the pm-* process that reads it, for the tuning panel.
SECTION_PROCESS: dict[str, str] = {
    spec.key: spec.process for spec in SINGLETON_GATEWAYS
}

#: Panel chrome costs two border columns and two padding columns.
CHROME = 4


# ---------------------------------------------------------------------------
# small shared helpers
# ---------------------------------------------------------------------------
def boxed(title: str, body: RenderableType, width: int, hot: bool = False) -> RichPanel:
    """Wrap ``body`` in the standard panel chrome."""
    return RichPanel(
        body,
        title=Text(f" {title} ", style=T.S_TITLE_HOT if hot else T.S_TITLE),
        title_align="left",
        border_style=T.S_BORDER_HOT if hot else T.S_BORDER,
        box=T.THEME.panel_box,
        width=width,
        padding=(0, 1),
    )


def label_grid(*widths: int) -> Table:
    """A borderless label/value grid."""
    grid = Table.grid(padding=(0, 1))
    for width in widths:
        grid.add_column(width=width or None)
    return grid


def data_table(width: int) -> Table:
    """A ruled table that fills exactly ``width`` columns."""
    return Table(
        box=T.THEME.table_box,
        expand=True,
        width=width,
        pad_edge=False,
        show_edge=False,
        header_style=T.S_LABEL,
        padding=(0, 1),
    )


def onoff(value: Any) -> Text:
    if value is True:
        return Text(f"{T.THEME.on_glyph} on", style=T.S_ON)
    if value is False:
        return Text(f"{T.THEME.off_glyph} off", style=T.S_OFF)
    return Text(f"{T.THEME.off_glyph} unset", style=T.S_DEFAULTED)


def human_ns(nanoseconds: Any) -> str:
    """Nanoseconds as something a human can compare at a glance."""
    if not isinstance(nanoseconds, (int, float)) or isinstance(nanoseconds, bool):
        return "—"
    seconds = nanoseconds / 1e9
    if seconds < 60:
        return f"{seconds:g}s"
    if seconds < 3600:
        return f"{seconds / 60:g}m"
    return f"{seconds / 3600:g}h"


def human_count(value: Any) -> str:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return "—"
    for divisor, suffix in ((1e9, "B"), (1e6, "M"), (1e3, "k")):
        if value >= divisor:
            return f"{value / divisor:.2f}".rstrip("0").rstrip(".") + suffix
    return str(value)


def human_bytes(size: int) -> str:
    return f"{size / 1024:.1f} kB" if size < 1024 * 1024 else f"{size / 1048576:.1f} MB"


def human_pct(value: float | None) -> str:
    return f"{value:.1%}" if value is not None else "—"


def mask_key(key: str) -> str:
    """Hide the secret, keep the identifying prefix and a four-char tail.

    Padded to the original length so ``--all`` reveals keys without moving
    anything: the masked and unmasked forms occupy identical space.
    """
    head, sep, tail = key.rpartition("-")
    if not sep:
        return key[:4] + "•" * max(0, len(key) - 8) + key[-4:]
    return f"{head}-" + "•" * max(0, len(tail) - 4) + tail[-4:]


# ---------------------------------------------------------------------------
# 1. identity and global flags
# ---------------------------------------------------------------------------
FLAG_CHIPS: tuple[tuple[str, str], ...] = (
    ("sessions", "sessions_enabled"),
    ("collars", "enforce_collars"),
    ("breakers", "enforce_circuit_breakers"),
    ("mm-oblig", "enforce_mm_obligation"),
)


def build_header(view: ConfigView, width: int) -> RenderableType:
    source = view.source
    when = (
        datetime.fromtimestamp(source.mtime).strftime("%Y-%m-%d %H:%M")
        if source.exists
        else "—"
    )
    meta = Text(
        f"{human_bytes(source.size)}  ·  {when}  ·  via " f"{source.resolved_via}",
        style=T.S_LABEL,
    )
    path = str(source.path)
    inner = width - CHROME

    if inner >= len(path) + len(meta.plain) + 4:
        header = Table.grid(expand=True)
        header.add_column(ratio=1, no_wrap=True)
        header.add_column(justify="right", no_wrap=True)
        header.add_row(Text(path, style="bold white"), meta)
        line: RenderableType = header
    else:
        # Narrow: keep the *tail* of the path -- the filename and the ref_data
        # directory identify it, the leading directories do not.
        shown = path if len(path) <= inner else "…" + path[-(inner - 1) :]
        line = Group(Text(shown, style="bold white", no_wrap=True), meta)

    chips = Text()
    for label, key in FLAG_CHIPS:
        chips.append_text(onoff(view.flags.get(key)).append(f" {label}   "))
    if view.flags.get("country"):
        chips.append(f"{T.THEME.on_glyph} {view.flags['country']}", style=T.S_ON)

    counts = Text(
        f"{len(view.symbols)} symbols   {len(view.participants)} participants   "
        f"{len(view.api_gateways)} API gateways   {len(view.credentials)} keys   "
        f"{len(view.listeners)} listeners",
        style=T.S_LABEL,
    )

    return boxed("ENGINE CONFIGURATION", Group(line, chips, counts), width, hot=True)


# ---------------------------------------------------------------------------
# 2. ports -- the flagship panel
# ---------------------------------------------------------------------------
def build_ports(view: ConfigView, width: int) -> RenderableType:
    inner = width - CHROME
    wide, mid = inner >= 70, inner >= 52

    table = data_table(inner)
    table.add_column("PORT", justify="right", width=5, no_wrap=True)
    if wide:
        table.add_column("PROTO", width=8, no_wrap=True)
    table.add_column("PROCESS", width=11, no_wrap=True)
    table.add_column("FUNCTION", ratio=1, overflow="ellipsis")
    if wide:
        table.add_column("BIND", width=9, no_wrap=True)
    if mid:
        table.add_column("", width=7, no_wrap=True)

    collisions = view.port_collisions
    for listener in view.listeners:
        clash = listener.port in collisions
        row: list[Any] = [
            Text(str(listener.port), style=T.S_BAD if clash else T.S_PORT)
        ]
        if wide:
            row.append(Text(listener.proto, style=T.S_LABEL))
        row.append(
            Text(listener.process, style=T.S_PROC if listener.enabled else T.S_OFF)
        )
        row.append(
            Text(listener.function, style=T.S_VALUE if listener.enabled else T.S_OFF)
        )
        if wide:
            row.append(Text(listener.bind, style=T.S_LABEL))
        if mid:
            if clash:
                state = Text("CLASH", style=T.S_BAD)
            elif not listener.enabled:
                state = Text("off", style=T.S_OFF)
            else:
                label, style = T.ORIGIN_STYLE.get(listener.origin, ("?", T.S_LABEL))
                state = Text(label, style=style)
            row.append(state)
        table.add_row(*row)

    return boxed("PORTS & LISTENERS", table, width, hot=True)


# ---------------------------------------------------------------------------
# 3. session schedule
# ---------------------------------------------------------------------------
#: Below this many columns per phase the bar cannot carry a legible label.
MIN_SEGMENT = 10


def build_schedule(view: ConfigView, width: int) -> RenderableType:
    """Equal-width phase segments.

    A *proportional* time axis is useless here: pre-open, both auctions and
    the close cluster into two or three columns while the continuous session
    eats the rest.  Equal segments show the sequence and the clock times,
    which is what a reader actually needs.
    """
    phases = view.schedule.phases
    inner = width - CHROME

    if not phases:
        return boxed(
            "SESSION SCHEDULE",
            Text("no schedule: section — continuous trading only", style=T.S_DEFAULTED),
            width,
        )

    nseg = max(1, len(phases) - 1)
    if inner < 30 or len(phases) < 2 or (inner - 6) // nseg < MIN_SEGMENT:
        grid = label_grid(0, 0)
        for label, hhmm in phases:
            grid.add_row(Text(hhmm, style=T.S_PORT), Text(label, style=T.S_VALUE))
        return boxed("SESSION SCHEDULE", grid, width)

    seg = (inner - 6) // nseg

    def blit(buffer: list[str], at: int, text: str) -> None:
        at = max(0, min(len(buffer) - len(text), at))
        for offset, char in enumerate(text):
            buffer[at + offset] = char

    times = [" "] * inner
    written_to = -1
    for i, (_, hhmm) in enumerate(phases):
        at = max(0, min(inner - len(hhmm), i * seg))
        if at <= written_to:  # never let two clock times collide
            continue
        blit(times, at, hhmm)
        written_to = at + len(hhmm)

    bar = Text()
    palette = (T.S_LABEL, T.S_WARN, T.S_ON, T.S_WARN, T.S_LABEL)
    for i in range(nseg):
        bar.append(T.THEME.bar_start if i == 0 else T.THEME.bar_mid, style=T.S_RULE)
        bar.append(T.THEME.bar_fill * (seg - 1), style=palette[i % len(palette)])
    bar.append(T.THEME.bar_end, style=T.S_RULE)

    names = [" "] * inner
    for i in range(nseg):
        label = phases[i][0].replace(" auction", "-auc").replace("Continuous", "cont")
        label = label[: seg - 1]
        blit(names, i * seg + (seg - len(label)) // 2, label)

    return boxed(
        "SESSION SCHEDULE",
        Group(
            Text("".join(times), style=T.S_PORT, no_wrap=True),
            bar,
            Text("".join(names), style=T.S_LABEL, no_wrap=True),
        ),
        width,
    )


# ---------------------------------------------------------------------------
# 4. API gateways
# ---------------------------------------------------------------------------
def build_apigw(view: ConfigView, width: int, density: int) -> RenderableType:
    inner = width - CHROME
    show_state, show_swagger = inner >= 44, inner >= 58
    show_rate = density >= 1 and inner >= 72

    table = data_table(inner)
    table.add_column("GATEWAY", width=12, no_wrap=True, overflow="ellipsis")
    if show_state:
        table.add_column("", width=5, no_wrap=True)
    table.add_column("BIND", width=13, no_wrap=True)
    table.add_column("KEYS", justify="right", width=5)
    if show_swagger:
        table.add_column("SWAGGER", width=7, no_wrap=True)
    if show_rate:
        table.add_column("RATE w/s", justify="right", width=8)
    # Spacer soaks up slack so the named columns keep their declared widths --
    # but only when there is slack to soak; below that it would compete with
    # them for space and truncate a header.
    spacer = inner >= 40
    if spacer:
        table.add_column("", ratio=1)

    for gateway in view.api_gateways:
        row: list[Any] = [
            Text(gateway.name, style=T.S_PROC if gateway.enabled else T.S_OFF)
        ]
        if show_state:
            row.append(onoff(gateway.enabled))
        row.append(Text(f"{gateway.host}:{gateway.port}", style=T.S_PORT))
        row.append(Text(str(len(gateway.credentials)), style=T.S_VALUE))
        if show_swagger:
            row.append(
                Text(
                    "yes" if gateway.swagger else "no",
                    style=T.S_WARN if gateway.swagger else T.S_OFF,
                )
            )
        if show_rate:
            limit = gateway.rate_limit
            row.append(
                Text(
                    f"{limit.get('writes_per_second', '—')}"
                    f"/{limit.get('burst', '—')}",
                    style=T.S_LABEL,
                )
            )
        if spacer:
            row.append(Text(""))
        table.add_row(*row)

    return boxed("API GATEWAYS", table, width)


# ---------------------------------------------------------------------------
# 5. API keys -- copy-safe by construction
# ---------------------------------------------------------------------------
#: Width the one-line form needs on top of the key itself: three label
#: columns plus their padding.
KEY_LABEL_WIDTH = 11 + 10 + 13 + 10


def build_keys(view: ConfigView, width: int, reveal: bool) -> RenderableType:
    credentials = view.credentials
    inner = width - CHROME
    if not credentials:
        return boxed("API KEYS", Text("none configured", style=T.S_DEFAULTED), width)

    shown = [c.api_key if reveal else mask_key(c.api_key) for c in credentials]
    key_width = max(len(s) for s in shown)

    if inner >= key_width + KEY_LABEL_WIDTH:
        table = data_table(inner)
        table.add_column("GATEWAY ID", width=11, no_wrap=True)
        table.add_column("API GW", width=10, no_wrap=True)
        table.add_column("ROLE", width=13, no_wrap=True)
        table.add_column("API KEY", width=key_width, no_wrap=True)
        for cred, text in zip(credentials, shown):
            table.add_row(
                Text(str(cred.gateway_id or "—"), style=T.S_VALUE),
                Text(cred.owner_gateway, style=T.S_LABEL),
                Text(cred.role, style=T.ROLE_STYLE.get(cred.role, T.S_LABEL)),
                # No styling *inside* the key: a terminal double-click must
                # select the whole token.
                Text(text, style=T.S_KEY if reveal else T.S_LABEL),
            )
        body: RenderableType = table
    else:
        # Too narrow for one line per key -- but a key is never wrapped, so
        # give it its own line under a label line.
        lines: list[RenderableType] = []
        for cred, text in zip(credentials, shown):
            lines.append(
                Text.assemble(
                    (f"{cred.gateway_id or '—':<10}", T.S_VALUE),
                    (f"{cred.role:<13}", T.ROLE_STYLE.get(cred.role, T.S_LABEL)),
                    (cred.owner_gateway, T.S_LABEL),
                )
            )
            lines.append(
                Text("  " + text, style=T.S_KEY if reveal else T.S_LABEL, no_wrap=True)
            )
        body = Group(*lines)

    if not reveal:
        body = Group(
            body, Text("masked — run with -a/--all to reveal", style=T.S_DEFAULTED)
        )
    return boxed("API KEYS", body, width, hot=True)


def keys_panel_width(view: ConfigView) -> int:
    """The one width the key panel accepts; see ``render_term``."""
    longest = max((len(c.api_key) for c in view.credentials), default=40)
    return longest + KEY_LABEL_WIDTH + CHROME


# ---------------------------------------------------------------------------
# 6. participants
# ---------------------------------------------------------------------------
def build_participants(view: ConfigView, width: int, density: int) -> RenderableType:
    inner = width - CHROME
    show_desc = inner >= 54
    show_policy = density >= 1 and inner >= 84

    table = data_table(inner)
    table.add_column("ID", width=9, no_wrap=True)
    table.add_column("ROLE", width=13, no_wrap=True)
    table.add_column("ON DISCONNECT", width=18, no_wrap=True)
    if show_desc:
        table.add_column("DESCRIPTION", ratio=1, no_wrap=True, overflow="ellipsis")
    if show_policy:
        table.add_column("QUOTE REFRESH", width=22, no_wrap=True)
    else:
        table.add_column("", width=1)

    for participant in view.participants:
        row: list[Any] = [
            Text(participant.gid, style=T.S_SYMBOL),
            Text(participant.role, style=T.ROLE_STYLE.get(participant.role, T.S_VALUE)),
            Text(participant.disconnect, style=T.S_LABEL),
        ]
        if show_desc:
            row.append(
                Text(
                    participant.description or "—",
                    style=T.S_VALUE if participant.description else T.S_DEFAULTED,
                )
            )
        row.append(
            Text(participant.quote_policy or "—", style=T.S_DEFAULTED)
            if show_policy
            else Text("")
        )
        table.add_row(*row)

    return boxed("PARTICIPANTS  (gateways.alf)", table, width)


# ---------------------------------------------------------------------------
# 7. risk, circuit breakers, market making
# ---------------------------------------------------------------------------
def build_collars(view: ConfigView, width: int) -> RenderableType:
    table = data_table(width - CHROME)
    table.add_column("LEVEL", ratio=1, no_wrap=True, overflow="ellipsis")
    table.add_column("STATIC", justify="right", width=7)
    table.add_column("DYNAMIC", justify="right", width=8)
    table.add_column("SYMS", justify="right", width=5)

    for level in view.risk_levels:
        name = Text(level.name, style=T.S_SYMBOL)
        if level.is_default:
            name.append(f"  {T.THEME.default_marker}", style=T.S_DEFAULTED)
        table.add_row(
            name,
            Text(human_pct(level.static_band_pct), style=T.S_VALUE),
            Text(human_pct(level.dynamic_band_pct), style=T.S_VALUE),
            Text(str(level.n_symbols), style=T.S_LABEL),
        )

    footer = Text.assemble(
        ("enforced: ", T.S_LABEL), onoff(view.flags.get("enforce_collars"))
    )
    return boxed("PRICE COLLARS", Group(table, footer), width)


def build_breakers(view: ConfigView, width: int, density: int) -> RenderableType:
    table = data_table(width - CHROME)
    table.add_column("LVL", width=4, no_wrap=True)
    table.add_column("SHIFT", justify="right", ratio=1)
    table.add_column("HALT", justify="right", width=10)

    for level in view.cb_levels:
        halted = level.halt_duration_ns
        table.add_row(
            Text(level.name, style=T.S_SYMBOL),
            Text(human_pct(level.price_shift_pct), style=T.S_VALUE),
            Text(
                human_ns(halted) if halted else "till close",
                style=T.S_VALUE if halted else T.S_WARN,
            ),
        )

    extras: list[RenderableType] = [
        Text.assemble(
            ("enforced: ", T.S_LABEL),
            onoff(view.flags.get("enforce_circuit_breakers")),
            ("   window: ", T.S_LABEL),
            (human_ns(view.cb_reference_window_ns), T.S_VALUE),
        )
    ]
    if density >= 2 and view.cb_reopening:
        reopening = view.cb_reopening
        ladder = " → ".join(
            f"+{float(step.get('widen_pct', 0)):.0%}"
            f"/{human_ns(step.get('min_duration_ns'))}"
            for step in reopening.get("expansions", [])
            if isinstance(step, dict)
        )
        extras.append(
            Text(
                f"reopen {'on' if reopening.get('enabled') else 'off'} · band "
                f"{float(reopening.get('initial_band_pct', 0)):.0%}"
                + (f" · {ladder}" if ladder else ""),
                style=T.S_LABEL,
                overflow="ellipsis",
                no_wrap=True,
            )
        )

    return boxed("CIRCUIT BREAKERS", Group(table, *extras), width)


def build_market_making(view: ConfigView, width: int) -> RenderableType:
    defaults = view.mm_defaults
    quoted = sum(1 for s in view.symbols if s.n_quotes)
    makers = sorted({m for s in view.symbols for m in s.quote_makers})

    grid = label_grid(18, 0)
    grid.add_row(
        Text("obligation", style=T.S_LABEL),
        onoff(defaults.get("enforce_mm_obligation")),
    )
    grid.add_row(
        Text("max spread", style=T.S_LABEL),
        Text(f"{defaults.get('mm_max_spread_ticks', '—')} ticks", style=T.S_VALUE),
    )
    grid.add_row(
        Text("min quantity", style=T.S_LABEL),
        Text(str(defaults.get("mm_min_qty", "—")), style=T.S_VALUE),
    )
    grid.add_row(
        Text("seed quotes", style=T.S_LABEL),
        Text(f"{quoted}/{len(view.symbols)} symbols", style=T.S_VALUE),
    )
    grid.add_row(
        Text("makers", style=T.S_LABEL),
        Text(
            ", ".join(makers) or "—", style=T.S_PROC, overflow="ellipsis", no_wrap=True
        ),
    )
    if view.combos:
        grid.add_row(
            Text("seed combos", style=T.S_LABEL),
            Text(str(len(view.combos)), style=T.S_VALUE),
        )

    body: list[RenderableType] = [grid]
    if view.mm_symbol_overrides:
        body.append(
            Text(
                "overrides: " + ", ".join(view.mm_symbol_overrides),
                style=T.S_WARN,
                overflow="ellipsis",
                no_wrap=True,
            )
        )
    return boxed("MARKET MAKING", Group(*body), width)


# ---------------------------------------------------------------------------
# 8. symbols -- the elastic panel
# ---------------------------------------------------------------------------
Justify = Literal["default", "left", "center", "right", "full"]


#: Symbol sub-table columns, keyed by the lowest density that shows them.
#: Spelled as one annotated table rather than built up with ``+=``: appending
#: bare literals re-infers the element type as ``tuple[str, int, str]``, which
#: an invariant ``list`` will not accept back.
_SYMBOL_COLUMNS: tuple[tuple[int, str, int, Justify], ...] = (
    (0, "SYMBOL", 6, "left"),
    (0, "DEC", 3, "right"),
    (0, "LAST", 9, "right"),
    (1, "LEVEL", 9, "left"),
    (0, "Q", 2, "right"),
    (1, "SHARES", 6, "right"),
    (2, "OVR", 4, "left"),
)


def _symbol_columns(density: int) -> tuple[tuple[str, int, Justify], ...]:
    """The columns shown at ``density``, in display order."""
    return tuple(
        (name, width, justify)
        for needed, name, width, justify in _SYMBOL_COLUMNS
        if density >= needed
    )


def symbols_natural_width(density: int) -> int:
    """Width of one symbol sub-table: columns, padding and a spacer."""
    columns = _symbol_columns(density)
    return sum(w for _, w, _ in columns) + 2 * len(columns) + 4


def _symbol_sub_table(
    chunk: Sequence[Symbol], width: int, density: int, default_level: str | None
) -> Table:
    table = data_table(width)
    for name, column_width, justify in _symbol_columns(density):
        table.add_column(name, width=column_width, justify=justify, no_wrap=True)
    table.add_column("", ratio=1)  # spacer soaks up the row's slack

    for symbol in chunk:
        price = symbol.price
        decimals = symbol.tick_decimals if symbol.tick_decimals is not None else 2
        row: list[Any] = [
            Text(symbol.name, style=T.S_SYMBOL),
            Text(
                str(symbol.tick_decimals) if symbol.tick_decimals is not None else "—",
                style=T.S_LABEL,
            ),
            Text(
                f"{price:,.{decimals}f}" if price is not None else "—", style=T.S_VALUE
            ),
        ]
        if density >= 1:
            level = symbol.level or default_level or "—"
            row.append(Text(level, style=T.S_VALUE if symbol.level else T.S_DEFAULTED))
        row.append(
            Text(
                str(symbol.n_quotes) if symbol.n_quotes else "·",
                style=T.S_PROC if symbol.n_quotes else T.S_OFF,
            )
        )
        if density >= 1:
            row.append(Text(human_count(symbol.outstanding), style=T.S_LABEL))
        if density >= 2:
            row.append(Text(symbol.override_flags, style=T.S_WARN))
        row.append(Text(""))
        table.add_row(*row)
    return table


def build_symbols(
    view: ConfigView, width: int, density: int, row_cap: int | None = None
) -> RenderableType:
    """Reflow the symbol list into as many sub-tables as ``width`` allows.

    Chunking is column-major so that symbols read *down* each column in
    alphabetical order, the way a printed index does.
    """
    if not view.symbols:
        return boxed("SYMBOLS", Text("none configured", style=T.S_DEFAULTED), width)

    inner = width - CHROME
    natural = symbols_natural_width(density)
    columns = max(1, (inner + GAP) // (natural + GAP))
    columns = min(columns, len(view.symbols))
    rows_per_column = math.ceil(len(view.symbols) / columns)
    columns = math.ceil(len(view.symbols) / rows_per_column)  # drop empty tails

    ordered = sorted(view.symbols, key=lambda s: s.name)
    hidden = 0
    if row_cap is not None and rows_per_column > row_cap:
        rows_per_column = row_cap
        hidden = len(ordered) - rows_per_column * columns
        ordered = ordered[: rows_per_column * columns]

    # Cap how far a sub-table stretches; the rest becomes column spacing, so a
    # short list does not turn into a few rows of very airy cells.
    sub_width = min((inner - GAP * (columns - 1)) // columns, int(natural * 1.3))
    spill = inner - columns * sub_width - GAP * (columns - 1)
    padding = GAP + (spill // (columns - 1) if columns > 1 else 0)

    chunks = [
        ordered[i * rows_per_column : (i + 1) * rows_per_column] for i in range(columns)
    ]
    grid = Table.grid(padding=(0, padding))
    for _ in range(columns):
        grid.add_column(width=sub_width)
    grid.add_row(
        *[
            _symbol_sub_table(chunk, sub_width, density, view.default_risk_level)
            for chunk in chunks
        ]
    )

    if hidden > 0:
        legend = Text(
            f"showing {len(ordered)} of {len(view.symbols)} symbols — "
            f"{hidden} more, use -m or a taller window",
            style=T.S_WARN,
        )
    else:
        legend = Text(
            f"{len(view.symbols)} symbols   DEC = tick decimals   "
            f"Q = seeded MM quotes"
            + ("   OVR = Collar/Breaker/Mm override" if density >= 2 else ""),
            style=T.S_DEFAULTED,
            overflow="ellipsis",
            no_wrap=True,
        )

    return boxed("SYMBOLS", Group(grid, legend), width, hot=True)


# ---------------------------------------------------------------------------
# 9. secondary panels
# ---------------------------------------------------------------------------
def build_gateway_tuning(view: ConfigView, width: int) -> RenderableType:
    table = data_table(width - CHROME)
    table.add_column("PROCESS", width=12, no_wrap=True)
    table.add_column("HB", justify="right", width=4)
    table.add_column("IDLE", justify="right", width=5)
    table.add_column("QUEUE", justify="right", width=7)
    table.add_column("", ratio=1)

    for key, section in view.gateway_sections.items():
        table.add_row(
            Text(SECTION_PROCESS.get(key, key), style=T.S_PROC),
            Text(str(section.get("heartbeat_interval_sec", "—")), style=T.S_VALUE),
            Text(str(section.get("idle_timeout_sec", "—")), style=T.S_VALUE),
            Text(human_count(section.get("max_client_queue")), style=T.S_VALUE),
            Text(""),
        )
    return boxed("GATEWAY TUNING", table, width)


def build_engine_tuning(view: ConfigView, width: int) -> RenderableType:
    grid = label_grid(30, 0)
    if not view.tuning:
        grid.add_row(Text("engine defaults", style=T.S_DEFAULTED), Text(""))
    for key, value in view.tuning.items():
        grid.add_row(Text(key, style=T.S_LABEL), Text(str(value), style=T.S_VALUE))
    return boxed("ENGINE TUNING", grid, width)


def build_combos(view: ConfigView, width: int, density: int) -> RenderableType:
    table = data_table(width - CHROME)
    table.add_column("COMBO", ratio=1, no_wrap=True, overflow="ellipsis")
    table.add_column("TYPE", width=5)
    table.add_column("TIF", width=4)
    table.add_column("LEGS", ratio=2, overflow="ellipsis", no_wrap=density < 2)

    for combo in view.combos:
        legs = " / ".join(
            f"{str(leg.get('side', '?'))[:1]}{leg.get('quantity', '?')} "
            f"{leg.get('symbol', '?')}"
            + (
                f" @{leg.get('price')}"
                if density >= 2 and leg.get("price") is not None
                else ""
            )
            for leg in combo.legs
        )
        table.add_row(
            Text(combo.combo_id, style=T.S_SYMBOL),
            Text(combo.combo_type, style=T.S_VALUE),
            Text(combo.tif, style=T.S_LABEL),
            Text(legs, style=T.S_VALUE),
        )
    return boxed("SEED COMBOS", table, width)


def build_indices(view: ConfigView, width: int) -> RenderableType:
    table = data_table(width - CHROME)
    table.add_column("INDEX", width=12, no_wrap=True)
    table.add_column("BASE", justify="right", width=8)
    table.add_column("EVERY", justify="right", width=6)
    table.add_column("CONSTITUENTS", ratio=1, overflow="ellipsis", no_wrap=True)

    for index in view.indices:
        table.add_row(
            Text(index.idx_id, style=T.S_SYMBOL),
            Text(
                str(index.base_value if index.base_value is not None else "—"),
                style=T.S_VALUE,
            ),
            Text(
                (
                    f"{index.publish_interval_sec}s"
                    if index.publish_interval_sec is not None
                    else "—"
                ),
                style=T.S_LABEL,
            ),
            Text(
                f"{len(index.constituents)}: " + ", ".join(index.constituents),
                style=T.S_VALUE,
            ),
        )
    return boxed("INDICES", table, width)


def build_unknown(view: ConfigView, width: int) -> RenderableType:
    body = Text(", ".join(view.unknown_keys) or "none", style=T.S_WARN)
    return boxed("UNRECOGNISED TOP-LEVEL KEYS", body, width)
