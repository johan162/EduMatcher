Version: 1.0.0

Date: 2026-08-20

Status: Design Proposal

# EduMatcher — Configuration Viewer (`pm-config-show`)



## Table of Contents

1. [Motivation](#1-motivation)
2. [Goals and Non-Goals](#2-goals-and-non-goals)
3. [CLI Surface](#3-cli-surface)
4. [What the File Actually Contains](#4-what-the-file-actually-contains)
5. [Panel Inventory](#5-panel-inventory)
6. [The Layout Algorithm](#6-the-layout-algorithm)
7. [Breakpoints and Density Tiers](#7-breakpoints-and-density-tiers)
8. [Colour, Glyphs and Copyability](#8-colour-glyphs-and-copyability)
9. [Worked Examples](#9-worked-examples)
10. [PDF Output](#10-pdf-output)
11. [Architecture and Module Design](#11-architecture-and-module-design)
12. [Implementation Plan](#12-implementation-plan)
13. [Testing Guide](#13-testing-guide)
14. [Acceptance Checklist](#14-acceptance-checklist)



## 1. Motivation

`engine_config.yaml` is the single source of truth for a running exchange, and
it has grown past the point where reading the file answers the questions people
actually ask of it. The deployed file in a nominal setup is 800–1500 lines, of
which perhaps 150 are data and the rest are explanatory comments. Answering
"which port does the market-data gateway bind?" or "what is TRADER02's API key?"
means scrolling, and answering "is anything colliding on a port?" means holding
six sections in your head at once.

`pm-cverifier` already answers *is this file correct*. Nothing answers *what
does this file say*. That is the gap `pm-config-show` fills: a read-only viewer
that prints the configuration as a dashboard and exits.

Three questions dominate day-to-day use and drive the whole design:

* **Which ports are in use, and what binds each one?** Six optional gateway
  sections, two named-mapping API gateways, three fixed engine sockets and two
  environment-overridable index sockets all bind listeners. No single place in
  the YAML shows them together, and several are defaults that appear nowhere in
  the file at all.
* **What are the API keys?** They are long opaque tokens that exist to be
  copied. A viewer that wraps or truncates one is worse than useless.
* **What instruments are configured?** This is the bulk of the data and the
  reason naive layouts fail: a thirty-symbol table is tall and narrow, and
  putting it beside anything strands a column of whitespace.

The difficulty of this tool is not gathering the data. It is spending the
available terminal — whatever size it happens to be — well.

### 1.1 The failure mode this design exists to avoid

The obvious implementation renders a fixed stack of tables. On a 200-column
terminal every table is 60 columns wide with 140 columns of dead space beside
it. Widening the tables instead produces prose columns 90 characters long. And
whichever choice is made, one table — symbols — is ten times taller than the
rest, so any side-by-side arrangement leaves a tall empty gutter next to it.

Three mechanisms in §6 attack exactly this: panels that state a width *range*
rather than a width, a packer that reaches forward to fill holes, and a
vertical gap-fill pass that stacks short panels beside tall ones.



## 2. Goals and Non-Goals

### 2.1 Goals

* Print a complete, digestible picture of one `engine_config.yaml` and exit.
  No TUI, no input loop, no refresh.
* Adapt to the terminal actually in use, from 60 columns to 250, without
  truncation, overflow or large voids.
* Make the full port inventory — including defaults and fixed engine sockets
  that never appear in the YAML — visible in one table, with collisions
  flagged.
* Render API keys unbroken and selectable, masked by default and revealed with
  `--all`.
* Group information logically so a reader can find a section by where it sits,
  not only by reading its title.
* Offer a multi-page A4-landscape PDF containing everything, for printing and
  for handing to a class.

### 2.2 Non-Goals

* **No validation.** Malformed input degrades to "not shown"; diagnosis belongs
  to `pm-cverifier`. The two tools are complementary and the viewer must never
  duplicate the verifier's judgement.
* **No writing.** The tool opens the file read-only and never writes to the
  data directory. `--output` writes only where the user points it.
* **No live state.** This is the *configuration*, not the running exchange.
  Nothing here connects to a socket.
* **No editing.** `pm-config-gen` and the config GUI own authoring.



## 3. CLI Surface

```
pm-config-show [-f FILE] [-m [1|2]] [-a] [--format {terminal,pdf}]
               [-o FILE] [--no-color] [--ascii] [--width N] [--version]
```

| Option | Meaning |
|---|---|
| `-f`, `--file YAML` | Config file to read. Default: `config.ENGINE_CONFIG_FILE`, i.e. `<DATA_DIR>/ref_data/engine_config.yaml` with `DATA_DIR` resolved by `config._resolve_data_dir()`. |
| `-m`, `--density [1\|2]` | Pack more in. Bare `-m` means 1. Default (no flag) is density 0, the essentials. |
| `-a`, `--all` | Everything: implies `-m 2`, reveals API keys in full, and adds the unrecognised-keys panel. |
| `--format` | `terminal` (default) or `pdf`. |
| `-o`, `--output FILE` | Destination for `--format pdf`. Defaults to `engine-config-<stem>.pdf` in the working directory. |
| `--no-color` | Suppress ANSI colour. Also implied when stdout is not a TTY or `NO_COLOR` is set. |
| `--ascii` | ASCII box drawing instead of Unicode. Auto-enabled when the terminal encoding is not UTF-8. |
| `--width N` | Force a render width. Used by tests and when piping to a file or a pager. |
| `--version` | Via `cli_version.add_version_argument`, as every other `pm-*` tool. |

Exit codes: `0` on success, `2` when the file does not exist or is not
readable, `3` when the YAML fails to parse. A parse failure prints the parser's
own message and points at `pm-cverifier`; it does not attempt partial recovery.

### 3.1 Interaction rules

* `--format pdf` ignores terminal width and defaults to density 2, because an
  A4 page has room the terminal does not. An explicit `-m` still wins.
* `-a` and `-m 2` differ in exactly two respects: `-a` reveals keys and shows
  unrecognised top-level keys. Density is a *layout* control; `--all` is a
  *disclosure* control. Keeping them separate means `-m 2` stays safe to run in
  front of a class.
* Piping is supported: `pm-config-show | less -R` works, `--width` overrides
  the 80-column fallback that applies when stdout is not a TTY.


## 4. What the File Actually Contains

The viewer reads the full documented schema, not just the sections the example
configs happen to use. Optional sections are simply absent from the render when
absent from the file — the layout has no fixed slots, so nothing leaves a hole.

| Top-level key | Shown as | Notes |
|---|---|---|
| `sessions_enabled`, `enforce_collars`, `enforce_circuit_breakers`, `country` | header chips | on/off/unset, colour-coded |
| `engine_tuning` | ENGINE TUNING | density 2 |
| `mm_obligation_defaults` (+ `.symbols`) | MARKET MAKING | overrides listed by symbol |
| `risk_controls.levels`, `.default_level` | PRICE COLLARS | symbol counts computed per level |
| `circuit_breaker_defaults` (+ `.reopening`) | CIRCUIT BREAKERS | reopening ladder at density 2 |
| `gateways.alf` | PARTICIPANTS | id, role, disconnect, quote policy |
| `alf_gateway`, `balf_gateway`, `post_trade_gateway`, `market_data_gateway`, `dc_gateway`, `log_server` | PORTS + GATEWAY TUNING | one listener row each; `log_server` contributes three |
| `api_gateways.<name>` | API GATEWAYS + PORTS + API KEYS | any number of named instances |
| `symbols` | SYMBOLS | the elastic panel |
| `market_maker_combos` | SEED COMBOS | legs summarised, expanded at density 2 |
| `indices` | INDICES | density 2 |
| `schedule` | SESSION SCHEDULE | rendered as a phase bar |
| anything else | UNRECOGNISED KEYS | `--all` only |

### 4.1 The port inventory

This is the part that cannot be read off the file, and it is the reason the
ports panel is the flagship. Three kinds of listener exist:

* **Fixed** — `ENGINE_PULL_ADDR` 5555, `ENGINE_PUB_ADDR` 5556 and
  `DROP_COPY_PUB_ADDR` 5557 are module constants in `config.py`. They appear
  nowhere in the YAML and cannot be changed without editing source.
* **Environment** — the index sockets, 5558 PUB and 5559 PULL, come from
  `EDUMATCHER_INDEX_PUB_PORT` / `EDUMATCHER_INDEX_PULL_PORT` with those
  defaults. Also absent from the YAML.
* **Configured** — the gateway sections. Crucially, *a section present with no
  `port:` key still binds*, on the runtime default. The viewer therefore shows
  the effective port and marks its origin, so a `default` row is visibly
  different from a `set` row.

The defaults mirror `cverifier/layer3_semantic._SINGLETON_GATEWAY_PORTS`, which
is where the collision checker already encodes them:

| Section | Process | Default | Protocol |
|---|---|---|---|
| `alf_gateway` | `pm-alf-gwy` | 5565 | TCP |
| `balf_gateway` | `pm-balf-gwy` | 5560 | TCP |
| `market_data_gateway` | `pm-md-gwy` | 5570 | TCP |
| `post_trade_gateway` | `pm-ralf-gwy` | 5580 | TCP |
| `dc_gateway` | `pm-dc-gwy` | 5590 | TCP |
| `log_server` | `pm-log-srv` | 5600 / 5601 pub / 5602 pull | TCP + ZMQ |
| `api_gateways.<name>` | `pm-api-gwy` | 8080 | HTTP |

> **Single source of truth.** These constants must not be re-typed. The
> implementation imports them from the cverifier module (or, better, both
> modules import a new `edumatcher/ports.py`) so that adding a gateway updates
> the viewer and the collision checker together. A duplicated table here is a
> guaranteed future drift bug.

Any port appearing twice is drawn in red and labelled `CLASH` in both rows —
the same condition `pm-cverifier` reports as M018, surfaced visually.



## 5. Panel Inventory

Every panel is an independent unit with a title, a width range and a build
function. Panels are grouped into **bands**, which is what produces the logical
grouping; the packer walks bands in order.

| Band | Panel | min | natural | max | Grows? | Notes |
|---|---|---:|---:|---:|---|---|
| `id` | ENGINE CONFIGURATION | — | full | full | — | path, size, mtime, flag chips, counts |
| `net` | PORTS & LISTENERS | 58 | 80 | 92 | yes | flagship; sheds PROTO/BIND columns when squeezed |
| `net` | API KEYS | *fixed* | *fixed* | *fixed* | no | width = longest key + labels; never negotiable |
| `access` | API GATEWAYS | 36 | 60 | 76 | yes | per-instance host:port, key count, swagger |
| `access` | SESSION SCHEDULE | 34 | 46 | 64 | no | phase bar, or a time list when narrow |
| `actors` | PARTICIPANTS | 38 | 74 | 100 | yes | drops DESCRIPTION below 54 inner columns |
| `actors` | MARKET MAKING | 32 | 44 | 56 | no | obligations, seed quotes, makers, overrides |
| `risk` | PRICE COLLARS | 34 | 46 | 54 | no | density ≥ 1 |
| `risk` | CIRCUIT BREAKERS | 30 | 40 | 56 | no | density ≥ 1 |
| `risk` | GATEWAY TUNING | 30 | 44 | 58 | no | density ≥ 1; heartbeat / idle / queue |
| `risk` | ENGINE TUNING | 34 | 48 | 60 | no | density 2 |
| `inst` | SYMBOLS | *elastic* | *elastic* | *elastic* | yes | see §6.4 |
| `inst` | SEED COMBOS | 40 | 72 | 100 | yes | density ≥ 1 |
| `misc` | UNRECOGNISED KEYS | — | full | full | — | `--all` only |

Two panels are special and deserve their own rules.

**API KEYS declares one width and refuses to move.** Its natural width is
`len(longest key) + 50`; its minimum and maximum are the same number. A panel
that cannot be squeezed simply does not join a row that has no room for it,
which is the correct behaviour for content whose value is destroyed by
truncation. Only when the *whole terminal* is narrower than that does the panel
switch to a stacked form — one label line, then the key alone on the next line,
still unbroken.

**SYMBOLS declares no width at all.** See §6.4.



## 6. The Layout Algorithm

Four mechanisms, applied in order.

### 6.1 Width ranges, not widths

A panel declares `min_w` (below this it is illegible), `nat_w` (comfortable),
`max_w` (beyond this it is stretched whitespace) and `wprio` (who is fed first
when width is scarce). Panels also declare `grow`: whether extra width buys
anything. A prose column — FUNCTION, DESCRIPTION — grows usefully; a table of
percentages does not.

This is the whole reason panels can be rearranged at all. A panel that reports
a single width can only be placed or not placed.

### 6.2 Shelf packing with lookahead

Panels are emitted in band order. A row is filled while the next panel's
`min_w` still fits beside the panels already on the row **at their natural
widths**. Packing on natural rather than minimum widths is what prevents three
panels being crammed into 80 columns and all three becoming unreadable.

When the next panel does not fit but a later, narrower one would, the packer
reaches forward up to four slots and pulls that one up — preferring a panel
from the same band, and crossing bands only when at least 30 columns are idle.
The hole gets filled without reordering the document.

### 6.3 Width distribution

Within a row: everyone starts at `min_w`; each is raised toward `nat_w` in
`wprio` order; the remainder goes to the growers, capped at `max_w`; any
residual widens the last panel so the right edge is never ragged. A row always
consumes the full terminal width.

`wprio` is what makes API KEYS win. It is fed before PORTS, because a truncated
key is worthless whereas a ports table without its BIND column is merely less
informative.

### 6.4 Vertical gap fill — the mechanism that kills dead space

Two panels side by side are almost never the same height. The short one leaves
a column of whitespace, which is precisely the "big table with nothing beside
it" failure this design exists to avoid.

So after widths are known, each cell measures its rendered height. Cells
shorter than the tallest one reach forward into the not-yet-placed queue and
**stack further panels inside themselves**, provided the candidate fits the
cell's width and the cell's remaining vertical gap (with a three-line
tolerance). Cells end up roughly level and the gutter disappears. In the
160-column example in §9.4, API GATEWAYS and SESSION SCHEDULE are stacked into
the cell beside the ports table for exactly this reason.

### 6.5 The symbols panel

Symbols are the one unbounded panel, and the design turns that liability into
the thing that guarantees a flush layout.

* **When the symbol list is long (> 14),** the panel takes a whole row and
  every column of it, then reflows *internally*: given width `W` it computes
  how many sub-tables of its natural width fit, chunks the alphabetical symbol
  list column-major across them, and sizes each sub-table so they exactly fill
  `W`. Sub-table width is capped at 1.3× natural; anything left over becomes
  inter-column spacing rather than stretched cells. The biggest table in the
  file is therefore the one table that can never strand space — it consumes
  whatever it is given.
* **When the list is short (≤ 14),** the panel behaves like any other: it
  declares a natural width of one sub-table and joins the packing, so a
  three-symbol config does not get a 200-column-wide table with three rows in
  it.

Column-major chunking matters: symbols read *down* each column in alphabetical
order, the way a printed index does, so scanning for a ticker works.

### 6.6 Fit-to-height

At the default density only, the render is measured against the terminal
height and trimmed in two stages:

1. Drop optional panels from the end until it fits, listing what was dropped in
   a footer with the flag that would bring it back.
2. If the mandatory panels still overflow, shorten the symbol list (16, then
   10, 6, 3 rows per column) and say so in the panel's own legend.

`-m` and `-a` skip this entirely: asking for more information is an explicit
statement that scrolling is acceptable.

> **Known cost.** Stage 1 re-packs after each drop and stage 2 re-renders per
> cap, so a worst-case default-density render measures the document a handful
> of times. At these sizes that is well under a millisecond of `rich`
> measurement and not worth optimising before it is shown to be a problem.



## 7. Breakpoints and Density Tiers

### 7.1 Size breakpoints

| Condition | Behaviour |
|---|---|
| width < 72 **or** height < 18 | **Tiny mode.** No boxes, no packing. Filename, counts, flag chips, and the enabled ports one per line — about 13 lines. Ends with a line saying the window is too small for the full view. |
| 72 ≤ width < 100 | Single column. Panels stack; the wide ones shed optional columns. |
| 100 ≤ width < 170 | Two columns typically, three where panels are narrow. |
| width ≥ 170 | Three columns; symbols reflows to 3–5 sub-tables. |

The breakpoints are consequences of the packer, not special cases in it: the
only hard-coded thresholds are the tiny-mode cutoff and the per-table column
thresholds inside individual panels.

### 7.2 Density tiers

| Tier | Flag | Adds |
|---|---|---|
| 0 | *(default)* | Header, ports, API keys (masked), API gateways, participants, market making, schedule, symbols (symbol, tick decimals, last price, quote count). Fit-to-height active. |
| 1 | `-m` | Price collars, circuit breakers, gateway tuning, seed combos, rate limits; symbols gains LEVEL and SHARES; participants gains QUOTE REFRESH. |
| 2 | `-m 2` | Engine tuning, indices, circuit-breaker reopening ladder, combo legs in full; symbols gains the per-symbol override marker. |
| all | `-a` | Density 2, plus unmasked API keys and the unrecognised-keys panel. |



## 8. Colour, Glyphs and Copyability

A small semantic palette, defined once in `theme.py`, used everywhere:

| Role | Style |
|---|---|
| Port number | bold bright yellow |
| Process name (`pm-*`) | bright green |
| API key (revealed) | bold bright magenta |
| Enabled / disabled | `●` bright green / `○` grey |
| Defaulted or fixed value | grey italic — visibly "not from this file" |
| Warning, override, collision | bright yellow / bold red |
| Role | TRADER blue, MARKET_MAKER magenta, ADMIN red, read-only grey |
| Panel chrome | grey, or cyan for the three panels that matter most |

Ordinary values use the terminal's default foreground rather than an explicit
white, so the coloured items carry the emphasis and the palette works on both
light and dark backgrounds.

Three rules about API keys, which exist to be copied:

1. A key is **never** wrapped and **never** truncated. If it does not fit
   one-per-row, the panel switches to a stacked form where the key occupies its
   own line.
2. No styling is applied *inside* a key, so a terminal double-click selects the
   whole token.
3. Masking preserves the prefix and the last four characters and pads the
   middle with `•` to the original length —
   `key-trader01-••••••••••••••••••••••••••••047r`. Same length masked or
   revealed, so `-a` never changes the layout, and the readable prefix still
   identifies which key you are looking at.

`--no-color` drops ANSI codes only; `--ascii` additionally swaps box drawing
for `+-|` and the on/off glyphs for `+`/`-`.


## 9. Worked Examples

Every block below is **real output** from a working prototype of this design,
rendered against files in this repository and captured with colour stripped.
Nothing here is hand-drawn, so the widths, wrapping and packing decisions are
the ones the algorithm actually makes.

Two configs are used: the deployed `engine_config.yaml` at the repository root
(3 symbols, 10 participants, 5 keys) and
`docs/examples/ref_data/thirty-books-complex-setup/engine_config.yaml`
(30 symbols, 8 participants, 9 keys, collars, breakers, combos, schedule).

### 9.1 Tiny — 60 × 14

Below the cutoff the tool abandons layout entirely and prints the one thing
someone on a small window almost always wants: the port map.

```
engine_config.yaml  3 sym · 10 gw · 5 keys
○ off sess ○ off collar ○ off cb 
PORTS
 5555 pm-engine   Order intake (CALF)
 5556 pm-engine   Event + book feed
 5557 pm-engine   Drop-copy feed
 5558 pm-index    Index value publish
 5559 pm-index    Index command intake
 5570 pm-md-gwy   Market data (MDLF)
 5580 pm-ralf-gwy Post-trade (RALF)
 8080 pm-api-gwy  REST API — desk
 8081 pm-api-gwy  REST API — dashboards
widen the terminal for the full view
```

### 9.2 Single column — 80 columns, default density

Note the API keys panel: 80 columns is narrower than the one-line form needs,
so it switches to the stacked form and each key still sits unbroken on its own
line. Note also the symbols panel: three symbols still reflow into two
sub-tables rather than leaving half the width empty.

```
╭─  ENGINE CONFIGURATION  ─────────────────────────────────────────────────────╮
│ /mnt/user-data/uploads/EduMatcher/engine_config.yaml                         │
│ 31.6 kB  ·  2026-08-20 23:15  ·  via --file                                  │
│ ○ off sessions   ○ off collars   ○ off breakers   ○ off mm-oblig             │
│ 3 symbols   10 participants   2 API gateways   5 keys   9 listeners          │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─  PORTS & LISTENERS  ────────────────────────────────────────────────────────╮
│  PORT   PROTO      PROCESS       FUNCTION                BIND                │
│ ──────────────────────────────────────────────────────────────────────────── │
│  5555   ZMQ PULL   pm-engine     Order intake (CALF)     127.0.0.1   fixed   │
│  5556   ZMQ PUB    pm-engine     Event + book feed       127.0.0.1   fixed   │
│  5557   ZMQ PUB    pm-engine     Drop-copy feed          127.0.0.1   fixed   │
│  5558   ZMQ PUB    pm-index      Index value publish     127.0.0.1   env     │
│  5559   ZMQ PULL   pm-index      Index command intake    127.0.0.1   env     │
│  5570   TCP        pm-md-gwy     Market data (MDLF)      127.0.0.1   set     │
│  5580   TCP        pm-ralf-gwy   Post-trade (RALF)       127.0.0.1   set     │
│  8080   HTTP       pm-api-gwy    REST API — desk         0.0.0.0     set     │
│  8081   HTTP       pm-api-gwy    REST API — dashboards   0.0.0.0     set     │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─  API KEYS  ─────────────────────────────────────────────────────────────────╮
│ TRADER01  TRADER       desk                                                  │
│   key-trader01-••••••••••••••••••••••••••••9ryr                              │
│ TRADER02  TRADER       desk                                                  │
│   key-trader02-••••••••••••••••••••••••••••5l2l                              │
│ OPS01     ADMIN        desk                                                  │
│   key-ops01-••••••••••••••••••••••••••••zf7f                                 │
│ MM01      MARKET_MAKER desk                                                  │
│   key-mm01-••••••••••••••••••••••••••••bj4s                                  │
│ —         READ-ONLY    dashboards                                            │
│   key-readonly-••••••••••••••••••••••••••••fnub                              │
│ masked — run with -a/--all to reveal                                         │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─  API GATEWAYS  ─────────────────────────────────────────────────────────────╮
│ GATEWAY                BIND            KEYS   SWAGGER                        │
│ ──────────────────────────────────────────────────────────────────────────── │
│ desk           ● on    0.0.0.0:8080       4   yes                            │
│ dashboards     ● on    0.0.0.0:8081       1   yes                            │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─  PARTICIPANTS  (gateways.alf)  ─────────────────────────────────────────────╮
│ ID          ROLE            ON DISCONNECT        DESCRIPTION                 │
│ ──────────────────────────────────────────────────────────────────────────── │
│ TRADER01    TRADER          CANCEL_ALL           Student                     │
│ DESK        TRADER          CANCEL_ALL           —                           │
│ 1           TRADER          CANCEL_ALL           —                           │
│ TRADER02    TRADER          CANCEL_ALL           Student                     │
│ DESK        TRADER          CANCEL_ALL           —                           │
│ 2           TRADER          CANCEL_ALL           —                           │
│ OPS01       ADMIN           LEAVE_ALL            Instructor                  │
│ CONSOLE     TRADER          CANCEL_ALL           —                           │
│ MM01        MARKET_MAKER    CANCEL_QUOTES_ONLY   Market                      │
│ MAKER       TRADER          CANCEL_ALL           —                           │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─  MARKET MAKING  ────────────────────────────────────────────────────────────╮
│ obligation         ○ off                                                     │
│ max spread         20 ticks                                                  │
│ min quantity       100                                                       │
│ seed quotes        3/3 symbols                                               │
│ makers             MM01                                                      │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─  SYMBOLS  ──────────────────────────────────────────────────────────────────╮
│ SYMBOL   DEC        LAST    Q          SYMBOL   DEC        LAST    Q         │
│ ─────────────────────────────────────  ───────────────────────────────────── │
│ AAPL       2      123.57    1          TSLA       2      169.84    1         │
│ MSFT       2      239.68    1                                                │
│ 3 symbols   DEC = tick decimals   Q = seeded MM quotes                       │
╰──────────────────────────────────────────────────────────────────────────────╯
```

### 9.3 Two columns — 120 columns, default density

The API GATEWAYS and MARKET MAKING panels are *stacked inside the cell* beside
the ports table (§6.4); without gap fill that cell would be six empty lines.
SYMBOLS joins PARTICIPANTS on the last row rather than claiming a row of its
own.

```
╭─  ENGINE CONFIGURATION  ─────────────────────────────────────────────────────────────────────────────────────────────╮
│ /mnt/user-data/uploads/EduMatcher/engine_config.yaml                     31.6 kB  ·  2026-08-20 23:15  ·  via --file │
│ ○ off sessions   ○ off collars   ○ off breakers   ○ off mm-oblig                                                     │
│ 3 symbols   10 participants   2 API gateways   5 keys   9 listeners                                                  │
╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─  PORTS & LISTENERS  ────────────────────────────────────────────────────────╮  ╭─  API GATEWAYS  ───────────────────╮
│  PORT   PROTO      PROCESS       FUNCTION                BIND                │  │ GATEWAY       BIND           KE…   │
│ ──────────────────────────────────────────────────────────────────────────── │  │ ────────────────────────────────── │
│  5555   ZMQ PULL   pm-engine     Order intake (CALF)     127.0.0.1   fixed   │  │ desk          0.0.0.0:8080     4   │
│  5556   ZMQ PUB    pm-engine     Event + book feed       127.0.0.1   fixed   │  │ dashboards    0.0.0.0:8081     1   │
│  5557   ZMQ PUB    pm-engine     Drop-copy feed          127.0.0.1   fixed   │  ╰────────────────────────────────────╯
│  5558   ZMQ PUB    pm-index      Index value publish     127.0.0.1   env     │  ╭─  MARKET MAKING  ──────────────────╮
│  5559   ZMQ PULL   pm-index      Index command intake    127.0.0.1   env     │  │ obligation         ○ off           │
│  5570   TCP        pm-md-gwy     Market data (MDLF)      127.0.0.1   set     │  │ max spread         20 ticks        │
│  5580   TCP        pm-ralf-gwy   Post-trade (RALF)       127.0.0.1   set     │  │ min quantity       100             │
│  8080   HTTP       pm-api-gwy    REST API — desk         0.0.0.0     set     │  │ seed quotes        3/3 symbols     │
│  8081   HTTP       pm-api-gwy    REST API — dashboards   0.0.0.0     set     │  │ makers             MM01            │
╰──────────────────────────────────────────────────────────────────────────────╯  ╰────────────────────────────────────╯
╭─  API KEYS  ─────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ GATEWAY ID        API GW           ROLE                 API KEY                                                      │
│ ──────────────────────────────────────────────────────────────────────────────────────────────────────────────────── │
│ TRADER01          desk             TRADER               key-trader01-••••••••••••••••••••••••••••9ryr                │
│ TRADER02          desk             TRADER               key-trader02-••••••••••••••••••••••••••••5l2l                │
│ OPS01             desk             ADMIN                key-ops01-••••••••••••••••••••••••••••zf7f                   │
│ MM01              desk             MARKET_MAKER         key-mm01-••••••••••••••••••••••••••••bj4s                    │
│ —                 dashboards       READ-ONLY            key-readonly-••••••••••••••••••••••••••••fnub                │
│ masked — run with -a/--all to reveal                                                                                 │
╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─  PARTICIPANTS  (gateways.alf)  ───────────────────────────────────────────╮  ╭─  SYMBOLS  ──────────────────────────╮
│ ID          ROLE            ON DISCONNECT        DESCRIPTION               │  │ SYMBOL   DEC        LAST    Q        │
│ ────────────────────────────────────────────────────────────────────────── │  │ ──────────────────────────────────── │
│ TRADER01    TRADER          CANCEL_ALL           Student                   │  │ AAPL       2      123.57    1        │
│ DESK        TRADER          CANCEL_ALL           —                         │  │ MSFT       2      239.68    1        │
│ 1           TRADER          CANCEL_ALL           —                         │  │ TSLA       2      169.84    1        │
│ TRADER02    TRADER          CANCEL_ALL           Student                   │  │ 3 symbols   DEC = tick decimals   Q  │
│ DESK        TRADER          CANCEL_ALL           —                         │  │ = seeded MM quotes                   │
│ 2           TRADER          CANCEL_ALL           —                         │  ╰──────────────────────────────────────╯
│ OPS01       ADMIN           LEAVE_ALL            Instructor                │                                          
│ CONSOLE     TRADER          CANCEL_ALL           —                         │                                          
│ MM01        MARKET_MAKER    CANCEL_QUOTES_ONLY   Market                    │                                          
│ MAKER       TRADER          CANCEL_ALL           —                         │                                          
╰────────────────────────────────────────────────────────────────────────────╯                                          
```

### 9.4 Three columns — 160 columns, density 1, thirty symbols

Density 1 brings in collars, breakers, gateway tuning and combos. The symbol
list is now long enough to claim its own full-width row and reflows into three
sub-tables that exactly fill 160 columns. The schedule renders as a phase bar;
the API keys panel is fed before the ports table, so ports is the one that
gives up width.

```
╭─  ENGINE CONFIGURATION  ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ /mnt/user-data/uploads/EduMatcher/docs/examples/ref_data/thirty-books-complex-setup/engine_config.yaml           48.9 kB  ·  2026-08-20 23:15  ·  via --file │
│ ● on sessions   ● on collars   ● on breakers   ● on mm-oblig                                                                                                 │
│ 30 symbols   8 participants   2 API gateways   9 keys   9 listeners                                                                                          │
╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─  PORTS & LISTENERS  ─────────────────────────────────────────────────────────────────╮  ╭─  API GATEWAYS  ──────────────────────────────────────────────────╮
│  PORT   PROTO      PROCESS       FUNCTION                         BIND                │  │ GATEWAY                BIND            KEYS   SWAGGER             │
│ ───────────────────────────────────────────────────────────────────────────────────── │  │ ───────────────────────────────────────────────────────────────── │
│  5555   ZMQ PULL   pm-engine     Order intake (CALF)              127.0.0.1   fixed   │  │ desk           ● on    0.0.0.0:8080       8   yes                 │
│  5556   ZMQ PUB    pm-engine     Event + book feed                127.0.0.1   fixed   │  │ dashboards     ● on    0.0.0.0:8081       1   yes                 │
│  5557   ZMQ PUB    pm-engine     Drop-copy feed                   127.0.0.1   fixed   │  ╰───────────────────────────────────────────────────────────────────╯
│  5558   ZMQ PUB    pm-index      Index value publish              127.0.0.1   env     │  ╭─  SESSION SCHEDULE  ──────────────────────────────────────────────╮
│  5559   ZMQ PULL   pm-index      Index command intake             127.0.0.1   env     │  │ 08:45         08:55         09:00         16:00         16:10     │
│  5570   TCP        pm-md-gwy     Market data (MDLF)               127.0.0.1   set     │  │ ├─────────────┼─────────────┼─────────────┼─────────────┤         │
│  5580   TCP        pm-ralf-gwy   Post-trade (RALF)                127.0.0.1   set     │  │    Pre-open    Opening-auc       cont      Closing-auc            │
│  8080   HTTP       pm-api-gwy    REST API — desk                  0.0.0.0     set     │  ╰───────────────────────────────────────────────────────────────────╯
│  8081   HTTP       pm-api-gwy    REST API — dashboards            0.0.0.0     set     │                                                                       
╰───────────────────────────────────────────────────────────────────────────────────────╯                                                                       
╭─  API KEYS  ────────────────────────────────────────────────────────────────────────────────╮  ╭─  PARTICIPANTS  (gateways.alf)  ────────────────────────────╮
│ GATEWAY ID     API GW        ROLE             API KEY                                       │  │ ID          ROLE            ON DISCONNECT        DESCR…     │
│ ─────────────────────────────────────────────────────────────────────────────────────────── │  │ ─────────────────────────────────────────────────────────── │
│ TRADER01       desk          TRADER           key-trader01-••••••••••••••••••••••••••••047r │  │ TRADER01    TRADER          CANCEL_ALL           Stude…     │
│ TRADER02       desk          TRADER           key-trader02-••••••••••••••••••••••••••••26oo │  │ TRADER02    TRADER          CANCEL_ALL           Stude…     │
│ TRADER03       desk          TRADER           key-trader03-••••••••••••••••••••••••••••psd8 │  │ TRADER03    TRADER          CANCEL_ALL           Stude…     │
│ TRADER04       desk          TRADER           key-trader04-••••••••••••••••••••••••••••2ri3 │  │ TRADER04    TRADER          CANCEL_ALL           Stude…     │
│ TRADER05       desk          TRADER           key-trader05-••••••••••••••••••••••••••••7vb0 │  │ TRADER05    TRADER          CANCEL_ALL           Stude…     │
│ OPS01          desk          ADMIN            key-ops01-••••••••••••••••••••••••••••xeeo    │  │ OPS01       ADMIN           LEAVE_ALL            Instr…     │
│ MM01           desk          MARKET_MAKER     key-mm01-••••••••••••••••••••••••••••zdpf     │  │ MM01        MARKET_MAKER    CANCEL_QUOTES_ONLY   Prima…     │
│ MM02           desk          MARKET_MAKER     key-mm02-••••••••••••••••••••••••••••cjzu     │  │ MM02        MARKET_MAKER    CANCEL_QUOTES_ONLY   Backu…     │
│ —              dashboards    READ-ONLY        key-readonly-••••••••••••••••••••••••••••erqk │  ╰─────────────────────────────────────────────────────────────╯
│ masked — run with -a/--all to reveal                                                        │                                                                 
╰─────────────────────────────────────────────────────────────────────────────────────────────╯                                                                 
╭─  MARKET MAKING  ──────────────────────────────────╮  ╭─  PRICE COLLARS  ──────────────────────────────────╮  ╭─  CIRCUIT BREAKERS  ─────────────────────────╮
│ obligation         ● on                            │  │ LEVEL                    STATIC    DYNAMIC    SYMS │  │ LVL                       SHIFT         HALT │
│ max spread         12 ticks                        │  │ ────────────────────────────────────────────────── │  │ ──────────────────────────────────────────── │
│ min quantity       200                             │  │ DEFAULT  ◂default         20.0%       2.0%      28 │  │ L1                         7.0%           5m │
│ seed quotes        30/30 symbols                   │  │ CORE                      18.0%       2.0%       1 │  │ L2                        13.0%          15m │
│ makers             MM01, MM02                      │  │ HIGH_BETA                 12.0%       4.0%       1 │  │ L3                        20.0%   till close │
│ seed combos        1                               │  │ enforced: ● on                                     │  │ enforced: ● on   window: 5m                  │
│ overrides: AAPL                                    │  ╰────────────────────────────────────────────────────╯  ╰──────────────────────────────────────────────╯
╰────────────────────────────────────────────────────╯                                                                                                          
╭─  GATEWAY TUNING  ─────────────────────────────────────╮  ╭─  SEED COMBOS  ──────────────────────────────────────────────────────────────────────────────────╮
│ PROCESS          HB    IDLE     QUEUE                  │  │ COMBO                                     TYPE    TIF    LEGS                                    │
│ ────────────────────────────────────────────────────── │  │ ──────────────────────────────────────────────────────────────────────────────────────────────── │
│ pm-md-gwy         1       5       20k                  │  │ SEED-PAIR-AAPL-MSFT                       AON     DAY    B100 AAPL / S100 MSFT                   │
│ pm-ralf-gwy       1      10        8k                  │  ╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╰────────────────────────────────────────────────────────╯                                                                                                      
╭─  SYMBOLS  ──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ SYMBOL   DEC        LAST   LEVEL        Q   SHARES                                        SYMBOL   DEC        LAST   LEVEL        Q   SHARES                 │
│ ──────────────────────────────────────────────────────────────────                        ────────────────────────────────────────────────────────────────── │
│ AAPL       2      210.24   CORE         2    15.4B                                        MU         2      255.95   DEFAULT      2     1.1B                 │
│ ADBE       2      152.65   DEFAULT      2     460M                                        NFLX       2      180.75   DEFAULT      2     430M                 │
│ AMD        2      160.73   DEFAULT      2    1.62B                                        NOW        2      166.83   DEFAULT      2     205M                 │
│ AMZN       2       22.88   DEFAULT      2    10.6B                                        NVDA       2       46.22   DEFAULT      2    24.6B                 │
│ ASML       2      199.48   DEFAULT      2     415M                                        ORCL       2      185.45   DEFAULT      2     2.8B                 │
│ AVGO       2       71.14   DEFAULT      2     4.7B                                        PYPL       2      157.04   DEFAULT      2    1.08B                 │
│ BABA       2      206.32   DEFAULT      2     2.2B                                        QCOM       2       35.98   DEFAULT      2    1.69B                 │
│ BKNG       2      183.87   DEFAULT      2      44M                                        SAP        2       70.56   DEFAULT      2    1.15B                 │
│ CRM        2       66.04   DEFAULT      2     970M                                        SHOP       2       55.63   DEFAULT      2    1.32B                 │
│ CSCO       2      284.87   DEFAULT      2    4.06B                                        SONY       2      230.33   DEFAULT      2    1.24B                 │
│ GOOGL      2      169.87   DEFAULT      2    12.2B                                        SQ         2      233.91   DEFAULT      2     600M                 │
│ IBM        2      166.03   DEFAULT      2     910M                                        TSLA       2      130.43   HIGH_BETA    2     3.2B                 │
│ INTC       2       82.05   DEFAULT      2     4.3B                                        TSM        2      172.87   DEFAULT      2    5.18B                 │
│ META       2      226.19   DEFAULT      2    2.56B                                        TXN        2      230.59   DEFAULT      2     910M                 │
│ MSFT       2      276.61   DEFAULT      2    7.43B                                        UBER       2      180.69   DEFAULT      2    2.13B                 │
│ 30 symbols   DEC = tick decimals   Q = seeded MM quotes                                                                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### 9.5 Wide and complete — 200 columns, `--all`

Keys revealed, engine tuning shown, three panel columns throughout. The masked
and revealed forms are the same width, so `-a` changes what you can read, never
where anything sits.

```
╭─  ENGINE CONFIGURATION  ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ /mnt/user-data/uploads/EduMatcher/docs/examples/ref_data/thirty-books-complex-setup/engine_config.yaml                                                   48.9 kB  ·  2026-08-20 23:15  ·  via --file │
│ ● on sessions   ● on collars   ● on breakers   ● on mm-oblig                                                                                                                                         │
│ 30 symbols   8 participants   2 API gateways   9 keys   9 listeners                                                                                                                                  │
╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─  PORTS & LISTENERS  ────────────────────────────────────────────────────────────────────╮  ╭─  API KEYS  ───────────────────────────────────────────────────────────────────────────────────────────╮
│  PORT   PROTO      PROCESS       FUNCTION                            BIND                │  │ GATEWAY ID      API GW         ROLE               API KEY                                              │
│ ──────────────────────────────────────────────────────────────────────────────────────── │  │ ────────────────────────────────────────────────────────────────────────────────────────────────────── │
│  5555   ZMQ PULL   pm-engine     Order intake (CALF)                 127.0.0.1   fixed   │  │ TRADER01        desk           TRADER             key-trader01-zkljn6052yfv1wn8gcmggr8pyosj047r        │
│  5556   ZMQ PUB    pm-engine     Event + book feed                   127.0.0.1   fixed   │  │ TRADER02        desk           TRADER             key-trader02-2mc1ja1emoc4tlod6o9nocapch6126oo        │
│  5557   ZMQ PUB    pm-engine     Drop-copy feed                      127.0.0.1   fixed   │  │ TRADER03        desk           TRADER             key-trader03-pphwuy1mvlk8rx5v5irhfoi7c7ispsd8        │
│  5558   ZMQ PUB    pm-index      Index value publish                 127.0.0.1   env     │  │ TRADER04        desk           TRADER             key-trader04-pmg96gcrwkcu0brhdbkhxymkbsr62ri3        │
│  5559   ZMQ PULL   pm-index      Index command intake                127.0.0.1   env     │  │ TRADER05        desk           TRADER             key-trader05-f86xmkaelr3v0zv1a8h2x8m5jhbv7vb0        │
│  5570   TCP        pm-md-gwy     Market data (MDLF)                  127.0.0.1   set     │  │ OPS01           desk           ADMIN              key-ops01-nnog5fcg4w53ta78ednzz8rt2gvuxeeo           │
│  5580   TCP        pm-ralf-gwy   Post-trade (RALF)                   127.0.0.1   set     │  │ MM01            desk           MARKET_MAKER       key-mm01-dwd2z71uucq7gfizyh203qtps30hzdpf            │
│  8080   HTTP       pm-api-gwy    REST API — desk                     0.0.0.0     set     │  │ MM02            desk           MARKET_MAKER       key-mm02-rsdafv374y73j30gctmyscijtplgcjzu            │
│  8081   HTTP       pm-api-gwy    REST API — dashboards               0.0.0.0     set     │  │ —               dashboards     READ-ONLY          key-readonly-rffwde8s2u48nhnr9hu46k1ktayyerqk        │
╰──────────────────────────────────────────────────────────────────────────────────────────╯  ╰────────────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─  API GATEWAYS  ─────────────────────────────────────────────────╮  ╭─  SESSION SCHEDULE  ───────────────────────╮  ╭─  PARTICIPANTS  (gateways.alf)  ───────────────────────────────────────────────╮
│ GATEWAY                BIND            KEYS   SWAGGER            │  │ 08:45 Pre-open                             │  │ ID          ROLE            ON DISCONNECT        DESCRIPTION                   │
│ ──────────────────────────────────────────────────────────────── │  │ 08:55 Opening auction                      │  │ ────────────────────────────────────────────────────────────────────────────── │
│ desk           ● on    0.0.0.0:8080       8   yes                │  │ 09:00 Continuous                           │  │ TRADER01    TRADER          CANCEL_ALL           Student desk 1                │
│ dashboards     ● on    0.0.0.0:8081       1   yes                │  │ 16:00 Closing auction                      │  │ TRADER02    TRADER          CANCEL_ALL           Student desk 2                │
╰──────────────────────────────────────────────────────────────────╯  │ 16:10 Close                                │  │ TRADER03    TRADER          CANCEL_ALL           Student desk 3                │
╭─  PRICE COLLARS  ────────────────────────────────────────────────╮  ╰────────────────────────────────────────────╯  │ TRADER04    TRADER          CANCEL_ALL           Student desk 4                │
│ LEVEL                                  STATIC    DYNAMIC    SYMS │  ╭─  GATEWAY TUNING  ─────────────────────────╮  │ TRADER05    TRADER          CANCEL_ALL           Student desk 5                │
│ ──────────────────────────────────────────────────────────────── │  │ PROCESS          HB    IDLE     QUEUE      │  │ OPS01       ADMIN           LEAVE_ALL            Instructor console            │
│ DEFAULT  ◂default                       20.0%       2.0%      28 │  │ ────────────────────────────────────────── │  │ MM01        MARKET_MAKER    CANCEL_QUOTES_ONLY   Primary market maker          │
│ CORE                                    18.0%       2.0%       1 │  │ pm-md-gwy         1       5       20k      │  │ MM02        MARKET_MAKER    CANCEL_QUOTES_ONLY   Backup market maker           │
│ HIGH_BETA                               12.0%       4.0%       1 │  │ pm-ralf-gwy       1      10        8k      │  ╰────────────────────────────────────────────────────────────────────────────────╯
│ enforced: ● on                                                   │  ╰────────────────────────────────────────────╯                                                                                    
╰──────────────────────────────────────────────────────────────────╯                                                                                                                                    
╭─  MARKET MAKING  ────────────────────────────────────╮  ╭─  CIRCUIT BREAKERS  ─────────────────────────────────╮  ╭─  ENGINE TUNING  ────────────────────────────────────────────────────────────────╮
│ obligation         ● on                              │  │ LVL                               SHIFT         HALT │  │ snapshot_interval_sec          0.25                                              │
│ max spread         12 ticks                          │  │ ──────────────────────────────────────────────────── │  │ quote_history_maxlen           30                                                │
│ min quantity       200                               │  │ L1                                 7.0%           5m │  │ drop_copy_buffer_size          10000                                             │
│ seed quotes        30/30 symbols                     │  │ L2                                13.0%          15m │  │ recent_trades_maxlen           20                                                │
│ makers             MM01, MM02                        │  │ L3                                20.0%   till close │  │ depth_snapshot_tolerance_ticks 100                                               │
│ seed combos        1                                 │  │ enforced: ● on   window: 5m                          │  ╰──────────────────────────────────────────────────────────────────────────────────╯
│ overrides: AAPL                                      │  │ reopen on · band 10% · +10%/2m → +20%/5m             │                                                                                      
╰──────────────────────────────────────────────────────╯  ╰──────────────────────────────────────────────────────╯                                                                                      
╭─  SYMBOLS  ──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ SYMBOL   DEC        LAST   LEVEL        Q   SHARES   OVR          SYMBOL   DEC        LAST   LEVEL        Q   SHARES   OVR          SYMBOL   DEC        LAST   LEVEL        Q   SHARES   OVR         │
│ ────────────────────────────────────────────────────────────────  ────────────────────────────────────────────────────────────────  ──────────────────────────────────────────────────────────────── │
│ AAPL       2      210.24   CORE         2    15.4B   ··M          GOOGL      2      169.87   DEFAULT      2    12.2B   ···          PYPL       2      157.04   DEFAULT      2    1.08B   ···         │
│ ADBE       2      152.65   DEFAULT      2     460M   ···          IBM        2      166.03   DEFAULT      2     910M   ···          QCOM       2       35.98   DEFAULT      2    1.69B   ···         │
│ AMD        2      160.73   DEFAULT      2    1.62B   ···          INTC       2       82.05   DEFAULT      2     4.3B   ···          SAP        2       70.56   DEFAULT      2    1.15B   ···         │
│ AMZN       2       22.88   DEFAULT      2    10.6B   ···          META       2      226.19   DEFAULT      2    2.56B   ···          SHOP       2       55.63   DEFAULT      2    1.32B   ···         │
│ ASML       2      199.48   DEFAULT      2     415M   ···          MSFT       2      276.61   DEFAULT      2    7.43B   ···          SONY       2      230.33   DEFAULT      2    1.24B   ···         │
│ AVGO       2       71.14   DEFAULT      2     4.7B   ···          MU         2      255.95   DEFAULT      2     1.1B   ···          SQ         2      233.91   DEFAULT      2     600M   ···         │
│ BABA       2      206.32   DEFAULT      2     2.2B   ···          NFLX       2      180.75   DEFAULT      2     430M   ···          TSLA       2      130.43   HIGH_BETA    2     3.2B   CB·         │
│ BKNG       2      183.87   DEFAULT      2      44M   ···          NOW        2      166.83   DEFAULT      2     205M   ···          TSM        2      172.87   DEFAULT      2    5.18B   ···         │
│ CRM        2       66.04   DEFAULT      2     970M   ···          NVDA       2       46.22   DEFAULT      2    24.6B   ···          TXN        2      230.59   DEFAULT      2     910M   ···         │
│ CSCO       2      284.87   DEFAULT      2    4.06B   ···          ORCL       2      185.45   DEFAULT      2     2.8B   ···          UBER       2      180.69   DEFAULT      2    2.13B   ···         │
│ 30 symbols   DEC = tick decimals   Q = seeded MM quotes   OVR = Collar/Breaker/Mm-obligation override                                                                                                │
╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─  SEED COMBOS  ──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ COMBO                                                                                       TYPE    TIF    LEGS                                                                                      │
│ ──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────── │
│ SEED-PAIR-AAPL-MSFT                                                                         AON     DAY    B100 AAPL / S100 MSFT                                                                     │
╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### 9.6 Fit-to-height — 120 × 34, a config that does not fit

Thirty symbols, nine keys and ten port rows cannot fit 34 lines. Stage 1 drops
MARKET MAKING, SESSION SCHEDULE and API GATEWAYS; stage 2 caps the symbol list
at three rows per column. Both trims announce themselves and name the flag that
undoes them.

```
╭─  ENGINE CONFIGURATION  ─────────────────────────────────────────────────────────────────────────────────────────────╮
│ /mnt/user-data/uploads/EduMatcher/docs/examples/ref_data/thirty-books-complex-setup/engine_config.yaml               │
│ 48.9 kB  ·  2026-08-20 23:15  ·  via --file                                                                          │
│ ● on sessions   ● on collars   ● on breakers   ● on mm-oblig                                                         │
│ 30 symbols   8 participants   2 API gateways   9 keys   9 listeners                                                  │
╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─  PORTS & LISTENERS  ────────────────────────────────────────────────────────╮  ╭─  PARTICIPANTS  (gateways.alf)  ───╮
│  PORT   PROTO      PROCESS       FUNCTION                BIND                │  │ ID      ROLE        ON DISCONNECT  │
│ ──────────────────────────────────────────────────────────────────────────── │  │ ────────────────────────────────── │
│  5555   ZMQ PULL   pm-engine     Order intake (CALF)     127.0.0.1   fixed   │  │ TRAD…   TRADER      CANCEL_ALL     │
│  5556   ZMQ PUB    pm-engine     Event + book feed       127.0.0.1   fixed   │  │ TRAD…   TRADER      CANCEL_ALL     │
│  5557   ZMQ PUB    pm-engine     Drop-copy feed          127.0.0.1   fixed   │  │ TRAD…   TRADER      CANCEL_ALL     │
│  5558   ZMQ PUB    pm-index      Index value publish     127.0.0.1   env     │  │ TRAD…   TRADER      CANCEL_ALL     │
│  5559   ZMQ PULL   pm-index      Index command intake    127.0.0.1   env     │  │ TRAD…   TRADER      CANCEL_ALL     │
│  5570   TCP        pm-md-gwy     Market data (MDLF)      127.0.0.1   set     │  │ OPS01   ADMIN       LEAVE_ALL      │
│  5580   TCP        pm-ralf-gwy   Post-trade (RALF)       127.0.0.1   set     │  │ MM01    MARKET_M…   CANCEL_QUOTES… │
│  8080   HTTP       pm-api-gwy    REST API — desk         0.0.0.0     set     │  │ MM02    MARKET_M…   CANCEL_QUOTES… │
│  8081   HTTP       pm-api-gwy    REST API — dashboards   0.0.0.0     set     │  ╰────────────────────────────────────╯
╰──────────────────────────────────────────────────────────────────────────────╯                                        
╭─  API KEYS  ─────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ GATEWAY ID        API GW           ROLE                 API KEY                                                      │
│ ──────────────────────────────────────────────────────────────────────────────────────────────────────────────────── │
│ TRADER01          desk             TRADER               key-trader01-••••••••••••••••••••••••••••047r                │
│ TRADER02          desk             TRADER               key-trader02-••••••••••••••••••••••••••••26oo                │
│ TRADER03          desk             TRADER               key-trader03-••••••••••••••••••••••••••••psd8                │
│ TRADER04          desk             TRADER               key-trader04-••••••••••••••••••••••••••••2ri3                │
│ TRADER05          desk             TRADER               key-trader05-••••••••••••••••••••••••••••7vb0                │
│ OPS01             desk             ADMIN                key-ops01-••••••••••••••••••••••••••••xeeo                   │
│ MM01              desk             MARKET_MAKER         key-mm01-••••••••••••••••••••••••••••zdpf                    │
│ MM02              desk             MARKET_MAKER         key-mm02-••••••••••••••••••••••••••••cjzu                    │
│ —                 dashboards       READ-ONLY            key-readonly-••••••••••••••••••••••••••••erqk                │
│ masked — run with -a/--all to reveal                                                                                 │
╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─  SYMBOLS  ──────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ SYMBOL   DEC        LAST    Q          SYMBOL   DEC        LAST    Q          SYMBOL   DEC        LAST    Q          │
│ ─────────────────────────────────────  ─────────────────────────────────────  ─────────────────────────────────────  │
│ AAPL       2      210.24    2          AMZN       2       22.88    2          BABA       2      206.32    2          │
│ ADBE       2      152.65    2          ASML       2      199.48    2          BKNG       2      183.87    2          │
│ AMD        2      160.73    2          AVGO       2       71.14    2          CRM        2       66.04    2          │
│ showing 9 of 30 symbols — 21 more, use -m or a taller window                                                         │
╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯
not shown at this size: mm, schedule, apigw   —  use -m / -m 2 / -a
```


## 10. PDF Output

`--format pdf` renders the same view model through ReportLab (Platypus) to
**A4 landscape**, 297 × 210 mm, 12 mm margins, giving a 273 × 186 mm text area.
Landscape because the content is tabular and wide; A4 because the audience is
European and the alternative is a hand-tuned Letter variant nobody checks.

ReportLab is the one new dependency this tool introduces. It is a pure-Python
wheel with no system libraries, which matters for a package installed with
`pipx` on student machines.

### 10.1 Page plan

| Page | Contents |
|---|---|
| 1 — Overview | Title block (path, size, mtime, SHA-256 of the file), flag chips, counts, the full ports table including fixed and defaulted rows, and the session schedule as a phase bar. |
| 2 — Access | Participants, API gateways with rate limits and timeouts, and the credentials table. Keys masked unless `--all`. |
| 3 — Risk & market making | Collar levels with symbol counts, circuit-breaker levels, the reopening ladder, MM obligations with per-symbol overrides, seed combos with legs. |
| 4+ — Symbols | Three-column flow with a repeating header, breaking across as many pages as needed. |
| last — Appendix | Engine tuning, gateway tuning, indices, and (with `--all`) unrecognised keys. |

Every page carries a running header (tool and version left, config file name
centre, generation timestamp right) and a footer with `page N of M`. The header
also repeats the four global flags, so a page torn out of the middle still says
whether collars were on.

### 10.2 Shared structure

The PDF renderer consumes `ConfigView` — the same read-only model the terminal
renderer uses. It does **not** reuse the packer: a page has a fixed size, so
the layout is a static frame plan and the only dynamic decision is how many
symbol pages are needed. Sharing the model rather than the layout keeps both
renderers simple and guarantees the two outputs never disagree about content.

Colour is reused semantically but muted for print: the port column stays
emphasised, disabled rows go grey, collisions stay red. Zebra striping replaces
the terminal's rule lines. Fonts are Helvetica throughout with a monospace face
(Courier) for keys, paths and ports.



## 11. Architecture and Module Design

All under `src/edumatcher/config_show/`. Note the underscore: `config-show`
is not a legal Python package name, and every other tool in the tree uses the
underscore form (`config_gen`, `log_srv`, `md_gateway`).

```
src/edumatcher/config_show/
    __init__.py
    cli.py            argparse surface, file resolution, dispatch, exit codes
    model.py          frozen dataclasses: Listener, Participant, Credential,
                      ApiGateway, Symbol, RiskLevel, CBLevel, Combo, Index,
                      Schedule, Source, ConfigView
    extract.py        raw YAML mapping -> ConfigView.  All schema knowledge
                      lives here, and every accessor is defensive
    theme.py          the entire palette, glyph set and box styles
    panels.py         one build function per panel; each takes a width and
                      returns a rich renderable
    layout.py         Panel descriptor, shelf packer, width distribution,
                      gap fill, fit-to-height
    render_term.py    panel selection per density, breakpoints, tiny mode
    render_pdf.py     ReportLab document, page templates, flowables
```

Dependency direction is strictly one-way: `cli → render_* → panels → layout,
theme, model` and `cli → extract → model`. `model.py` imports nothing from the
package; `layout.py` knows nothing about configuration.

`pyproject.toml` gains one script entry, alongside the existing `pm-*` block:

```toml
pm-config-show = "edumatcher.config_show.cli:main"
```

and one dependency:

```toml
reportlab = ">=4.2"
```

### 11.1 Why the view model is a separate layer

Three renderers will eventually exist (terminal, PDF, and the tiny fallback
which is really a third). Each of them needs "the effective port of the
market-data gateway, and whether that came from the file or a default" — a
computation with real logic in it. Doing that once, into frozen dataclasses,
is what stops the three renderers drifting. It also makes the whole thing
testable without a terminal: assert on `ConfigView`, not on ANSI output.

### 11.2 Defensiveness

`extract.py` treats every value as untrusted. A section that is `None`, a
string where a mapping was expected, a `symbols` entry with no `tick_decimals`
— all degrade to "not shown" or `—`. The viewer must render *something* for
any file that `yaml.safe_load` accepts, because the most likely moment someone
reaches for it is when the config is broken and they want to see what is in it.
Errors are `pm-cverifier`'s job; a viewer that crashes on a bad file has failed
at the exact moment it was needed.



## 12. Implementation Plan

| Step | Deliverable |
|---|---|
| 1 | `model.py` + `extract.py` with the full schema and the port inventory imported from a shared constant table. Unit-tested against all twelve `docs/examples/ref_data/*` configs plus the sample. |
| 2 | `theme.py` + `panels.py`: every panel rendering standalone at a fixed width. |
| 3 | `layout.py`: packer, distribution, gap fill. Property tests on synthetic panel sets. |
| 4 | `render_term.py`: density selection, breakpoints, tiny mode, fit-to-height. |
| 5 | `cli.py` + the `pyproject.toml` script entry. Tool usable end to end. |
| 6 | `render_pdf.py` and the `reportlab` dependency. |
| 7 | `docs/user-guide/` page and a `README.md` mention next to `pm-cverifier`. |

Steps 1–5 are the tool; 6 is separable and can land in a second commit without
holding up the terminal view.

### 12.1 Shared port constants

Step 1 should extract the gateway/port table out of
`cverifier/layer3_semantic.py` into a new `edumatcher/gateway_ports.py` and
have both modules import it. This is a small refactor that pays for itself the
first time a gateway is added, and it is much cheaper to do now than after the
constants have been duplicated.



## 13. Testing Guide

Layout code is notoriously untested because "does it look right" is not an
assertion. These four are:

* **No overflow, ever.** For every example config × every width in
  `{60, 72, 80, 100, 120, 160, 200, 250}` × every density, assert that no
  rendered line exceeds the target width. This is the single highest-value
  test in the suite and it catches almost every layout regression.
* **No truncated keys.** For every config at every width ≥ 72, assert that each
  `api_key` string appears verbatim and unbroken in the `--all` output.
* **Port inventory completeness.** For each config, assert the set of ports in
  the render equals the set computed by `_collect_gateway_ports` plus the fixed
  and environment sockets. Assert a synthetic colliding config marks both rows.
* **Density is monotone.** Every field visible at density *n* is visible at
  density *n+1*.

Plus: golden-file tests on `--width 120 --no-color` output for two
representative configs, a read-only check asserting the config file's mtime is
unchanged after a run, and a malformed-YAML fixture asserting a clean exit 3
rather than a traceback.

Rendering to a fixed width is done by constructing `Console(width=…,
height=…)`, so no pty is needed and the tests run in CI.



## 14. Acceptance Checklist

- [ ] `pm-config-show` with no arguments renders the deployed config from `<DATA_DIR>/ref_data/`.
- [ ] Every port that any process binds appears exactly once, labelled with process, function, bind address and origin.
- [ ] A port collision is visible in red on both rows.
- [ ] API keys are never wrapped or truncated at any width ≥ 72, and are copyable with one double-click.
- [ ] Keys are masked by default and full under `-a`, with identical layout either way.
- [ ] No rendered line exceeds the terminal width at any tested width or density.
- [ ] No row leaves a vertical gutter taller than four lines beside a panel.
- [ ] A 30-symbol config at 200 columns uses 4–5 symbol sub-columns and fills the width.
- [ ] A 3-symbol config does not stretch its symbol table across the terminal.
- [ ] Below 72 columns or 18 rows, the tiny summary appears and fits.
- [ ] Optional sections absent from the YAML leave no hole in the layout.
- [ ] `--format pdf` produces a multi-page A4-landscape PDF with page numbers and repeating headers.
- [ ] The config file is not modified; no file is written outside `--output`.
- [ ] A malformed YAML file exits 3 with a readable message and no traceback.
