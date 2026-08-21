"""Terminal renderer: pick panels for the density, pack them, print, exit."""

from __future__ import annotations

from rich.console import Console
from rich.table import Table
from rich.text import Text

from edumatcher.config_show import panels as P
from edumatcher.config_show import theme as T
from edumatcher.config_show.layout import (
    GAP,
    Panel,
    Row,
    fit_to_height,
    flow,
    render_cell,
    total_height,
)
from edumatcher.config_show.model import ConfigView

#: Below either of these the tool abandons layout and prints a plain summary.
TINY_WIDTH = 72
TINY_HEIGHT = 18

#: A symbol list shorter than this does not need the whole terminal width, so
#: it becomes an ordinary packable panel instead of a full-width band.
SMALL_SYMBOL_SET = 14

#: Successive symbol row caps tried when the mandatory panels alone overflow.
SYMBOL_ROW_CAPS: tuple[int | None, ...] = (None, 16, 10, 6, 3)


def build_panels(
    view: ConfigView, density: int, reveal: bool, symbol_row_cap: int | None = None
) -> list[Panel]:
    """Assemble the panel list for one density, in band order."""
    panels: list[Panel] = [
        Panel(
            "header",
            40,
            999,
            lambda w: P.build_header(view, w),
            band="id",
            hard_break=True,
            optional=False,
        ),
        Panel(
            "ports",
            58,
            80,
            lambda w: P.build_ports(view, w),
            band="net",
            max_w=92,
            wprio=1,
            grow=True,
            optional=False,
        ),
    ]

    if view.credentials:
        # The one panel with a hard content width: a truncated key is
        # worthless, so it declares a single width and never shares a squeezed
        # row.  Below that width the builder falls back to a stacked form that
        # still prints every key unbroken.
        key_width = P.keys_panel_width(view)
        panels.append(
            Panel(
                "keys",
                key_width,
                key_width,
                lambda w: P.build_keys(view, w, reveal),
                band="net",
                max_w=key_width,
                wprio=0,
                optional=False,
            )
        )

    if view.api_gateways:
        panels.append(
            Panel(
                "apigw",
                36,
                60,
                lambda w: P.build_apigw(view, w, density),
                band="access",
                max_w=76,
                grow=True,
            )
        )
    if view.schedule.phases:
        panels.append(
            Panel(
                "schedule",
                34,
                46,
                lambda w: P.build_schedule(view, w),
                band="access",
                max_w=64,
            )
        )

    panels.append(
        Panel(
            "participants",
            38,
            74,
            lambda w: P.build_participants(view, w, density),
            band="actors",
            max_w=100,
            wprio=1,
            grow=True,
            optional=False,
        )
    )
    panels.append(
        Panel(
            "mm",
            32,
            44,
            lambda w: P.build_market_making(view, w),
            band="actors",
            max_w=56,
        )
    )

    if density >= 1:
        if view.risk_levels:
            panels.append(
                Panel(
                    "collars",
                    34,
                    46,
                    lambda w: P.build_collars(view, w),
                    band="risk",
                    max_w=54,
                )
            )
        if view.cb_levels:
            panels.append(
                Panel(
                    "breakers",
                    30,
                    40,
                    lambda w: P.build_breakers(view, w, density),
                    band="risk",
                    max_w=56,
                )
            )
        if view.gateway_sections:
            panels.append(
                Panel(
                    "gwtuning",
                    30,
                    44,
                    lambda w: P.build_gateway_tuning(view, w),
                    band="risk",
                    max_w=58,
                )
            )
    if density >= 2 and view.tuning:
        panels.append(
            Panel(
                "tuning",
                34,
                48,
                lambda w: P.build_engine_tuning(view, w),
                band="risk",
                max_w=60,
            )
        )

    natural = P.symbols_natural_width(density)
    if len(view.symbols) <= SMALL_SYMBOL_SET:
        panels.append(
            Panel(
                "symbols",
                natural + 4,
                natural + 4,
                lambda w: P.build_symbols(view, w, density, symbol_row_cap),
                band="inst",
                max_w=3 * natural + 8,
                wprio=1,
                grow=True,
                optional=False,
            )
        )
    else:
        panels.append(
            Panel(
                "symbols",
                30,
                999,
                lambda w: P.build_symbols(view, w, density, symbol_row_cap),
                band="inst",
                hard_break=True,
                optional=False,
            )
        )

    if density >= 1 and view.combos:
        panels.append(
            Panel(
                "combos",
                40,
                72,
                lambda w: P.build_combos(view, w, density),
                band="inst",
                grow=True,
            )
        )
    if density >= 2 and view.indices:
        panels.append(
            Panel(
                "indices",
                40,
                80,
                lambda w: P.build_indices(view, w),
                band="inst",
                grow=True,
            )
        )
    if reveal and view.unknown_keys:
        panels.append(
            Panel(
                "unknown",
                30,
                999,
                lambda w: P.build_unknown(view, w),
                band="misc",
                hard_break=True,
            )
        )

    return panels


def render_tiny(view: ConfigView, console: Console) -> None:
    """The one thing somebody on a small window almost always wants."""
    console.print(Text(view.source.path.name, style="bold white"), end="  ")
    console.print(
        Text(
            f"{len(view.symbols)} sym · {len(view.participants)} gw "
            f"· {len(view.credentials)} keys",
            style=T.S_LABEL,
        )
    )

    chips = Text()
    for label, key in (
        ("sess", "sessions_enabled"),
        ("collar", "enforce_collars"),
        ("cb", "enforce_circuit_breakers"),
    ):
        chips.append_text(P.onoff(view.flags.get(key)).append(f" {label} "))
    console.print(chips)

    console.print(Text("PORTS", style=T.S_TITLE))
    for listener in view.listeners:
        if not listener.enabled:
            continue
        console.print(
            Text.assemble(
                (f"{listener.port:>5} ", T.S_PORT),
                (f"{listener.process:<12}", T.S_PROC),
                (listener.function, T.S_LABEL),
            )
        )
    console.print(Text("widen the terminal for the full view", style=T.S_DEFAULTED))


def render(view: ConfigView, console: Console, density: int, reveal: bool) -> None:
    width, height = console.width, console.height
    if width < TINY_WIDTH or height < TINY_HEIGHT:
        render_tiny(view, console)
        return

    if density == 0:
        # Trim in two stages: drop optional panels first, then -- if the
        # mandatory panels still overflow -- shorten the symbol list, which is
        # the only panel whose height is unbounded.
        rows: list[Row] = []
        dropped: list[str] = []
        for cap in SYMBOL_ROW_CAPS:
            rows, dropped = fit_to_height(
                console, build_panels(view, density, reveal, cap), width, height - 2
            )
            if total_height(console, rows) <= height - 2:
                break
    else:
        rows = flow(console, build_panels(view, density, reveal), width)
        dropped = []

    for row in rows:
        if len(row) == 1:
            console.print(render_cell(row[0][0], row[0][1]))
            continue
        grid = Table.grid(padding=(0, GAP))
        for _, cell_width in row:
            grid.add_column(width=cell_width)
        grid.add_row(*[render_cell(cell, cell_width) for cell, cell_width in row])
        console.print(grid)

    if dropped:
        console.print(
            Text(
                "not shown at this size: "
                + ", ".join(dropped)
                + "   —  use -m / -m 2 / -a",
                style=T.S_DEFAULTED,
            )
        )
