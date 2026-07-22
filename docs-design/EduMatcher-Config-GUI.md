Version: 1.0.0

Date: 2026-07-09

Status: Design Proposal

# EduMatcher — Configuration GUI (`config-gui`) Design Proposal



## Table of Contents

- [EduMatcher — Configuration GUI (`config-gui`) Design Proposal](#edumatcher--configuration-gui-config-gui-design-proposal)
  - [Table of Contents](#table-of-contents)
  - [1. Overview](#1-overview)
  - [2. Problem Statement](#2-problem-statement)
  - [3. Goals and Non-Goals](#3-goals-and-non-goals)
    - [3.1 Goals](#31-goals)
    - [3.2 Non-Goals](#32-non-goals)
  - [4. Personas and Complexity Tiers](#4-personas-and-complexity-tiers)
  - [5. Information Architecture](#5-information-architecture)
    - [5.1 Top-level layout](#51-top-level-layout)
    - [5.2 Tab list (in navigation order)](#52-tab-list-in-navigation-order)
    - [5.3 Master–detail pattern (Symbols tab example)](#53-masterdetail-pattern-symbols-tab-example)
  - [6. Visual Design System](#6-visual-design-system)
  - [7. Field Catalogue](#7-field-catalogue)
    - [7.1 Basics — Symbols \& Gateways (mandatory section)](#71-basics--symbols--gateways-mandatory-section)
    - [7.2 Sessions \& Schedule](#72-sessions--schedule)
    - [7.3 Risk Controls \& Collars](#73-risk-controls--collars)
    - [7.4 Circuit Breakers](#74-circuit-breakers)
    - [7.5 Market-Maker Obligations \& Seeding](#75-market-maker-obligations--seeding)
    - [7.6 Symbols Tab — Consolidated Per-Symbol Panel](#76-symbols-tab--consolidated-per-symbol-panel)
    - [7.7 Indices](#77-indices)
    - [7.8 Combos (Seed Orders)](#78-combos-seed-orders)
    - [7.9 Auxiliary Gateways — Common Fields](#79-auxiliary-gateways--common-fields)
      - [7.9.1 Post-Trade Gateway (Intermediate+)](#791-post-trade-gateway-intermediate)
      - [7.9.2 Market-Data Gateway (Intermediate+)](#792-market-data-gateway-intermediate)
      - [7.9.3 BALF Gateway (Expert only)](#793-balf-gateway-expert-only)
      - [7.9.4 API Gateway (Expert only)](#794-api-gateway-expert-only)
    - [7.10 Output \& Generation Controls (Review tab)](#710-output--generation-controls-review-tab)
  - [8. Cross-Field Validation and Consistency Engine](#8-cross-field-validation-and-consistency-engine)
    - [8.1 Rule catalogue (baseline, inherited from `pm-config-gen`/`warnings.py`)](#81-rule-catalogue-baseline-inherited-from-pm-config-genwarningspy)
    - [8.2 New rules required by the fuller GUI schema (not present in the current CLI's `warnings.py`)](#82-new-rules-required-by-the-fuller-gui-schema-not-present-in-the-current-clis-warningspy)
    - [8.3 Presentation](#83-presentation)
  - [9. Importing an Existing Configuration](#9-importing-an-existing-configuration)
  - [10. Guided Help System](#10-guided-help-system)
  - [11. Review, Diagnostics and Export](#11-review-diagnostics-and-export)
  - [12. Technical Architecture](#12-technical-architecture)
    - [12.1 Stack](#121-stack)
    - [12.2 Monorepo layout](#122-monorepo-layout)
    - [12.3 Data flow](#123-data-flow)
    - [12.4 Keeping CLI and GUI in sync](#124-keeping-cli-and-gui-in-sync)
  - [13. Data Model](#13-data-model)
  - [14. API Reference](#14-api-reference)
  - [15. Security Considerations](#15-security-considerations)
  - [16. Accessibility Requirements](#16-accessibility-requirements)
  - [17. State Management and Persistence](#17-state-management-and-persistence)
  - [18. Testing Strategy](#18-testing-strategy)
  - [19. Implementation Plan](#19-implementation-plan)
  - [20. Recommended Enhancements Beyond the Stated Requirements](#20-recommended-enhancements-beyond-the-stated-requirements)
  - [21. Open Questions and Future Work](#21-open-questions-and-future-work)
  - [22. Acceptance Checklist](#22-acceptance-checklist)



## 1. Overview

`pm-config-gen` (see [EduMatcher-config-generator.md](EduMatcher-config-generator.md))
turns high-level operator intent into a valid `engine_config.yaml`, but it is
still a command-line tool with **over 100 flags**, several compound
mini-languages (`GW_SPEC`, `CB_SPEC`, `LEVEL_SPEC`, `--symbol-opts
SYM:k=v,...`, combo leg strings, API gateway instance strings), and validation
feedback that only appears after the whole command is typed and run.

This document specifies **`config-gui`**, a browser-based, Node.js/TypeScript
web application that lets an operator build, import, edit, validate, and export
`engine_config.yaml` interactively — with live validation, progressive
disclosure by experience level, and guided help — without needing to memorize
any CLI syntax.

`config-gui` is a companion to, not a replacement for, `pm-config-gen` and
`pm-cverifier` ([EduMatcher-Config-Verifier.md](EduMatcher-Config-Verifier.md)).
It targets the same output format and reuses the same validation vocabulary so
the three tools stay consistent.

## 2. Problem Statement

Current pain points building `engine_config.yaml` by hand or via
`pm-config-gen`:

- **Syntax overload.** Compound spec strings (e.g.
  `MM01:MARKET_MAKER:CANCEL_QUOTES_ONLY`, `L1:0.07:5:AUCTION`,
  `AAPL:tick_decimals=2,static_band=0.15`) are easy to mistype and hard to
  proofread by eye.
- **Delayed feedback.** Validation only happens after the full command runs;
  there is no partial/incremental feedback while composing a large invocation.
- **Hidden interdependencies.** A symbol's `level=` must match a
  `--risk-level` name; a `MARKET_MAKER` gateway implies mandatory quote
  seeding; enabling `--sessions-enabled` implies a schedule and a running
  `pm-scheduler`. These relationships are documented but not enforced visually.
- **One-size-fits-all complexity.** A first-time student setting up a
  two-trader classroom exchange sees exactly the same flag surface as an
  instructor wiring up API gateways, BALF, and multi-leg combo seeds.
- **No round trip.** There is no supported way to load an existing
  `engine_config.yaml` back into a form for incremental editing; today,
  edits happen by hand in a text editor.

## 3. Goals and Non-Goals

### 3.1 Goals

- Support **every field reachable through `pm-config-gen`'s CLI surface**
  (see [Section 7](#7-field-catalogue)), plus a small number of well-justified
  additions ([Section 20](#20-recommended-enhancements-beyond-the-stated-requirements)).
- Provide three **personas** — `BEGINNER`, `INTERMEDIATE`, `EXPERT` — that
  control how much of the field surface is visible at once, switchable at any
  time without losing data.
- Organize the UI as **tabs and panels**, each showing only the fields
  relevant to the current persona and section.
- Visually and unambiguously distinguish **mandatory** vs **optional**
  fields, and show default values for anything left unset.
- Run **live cross-field validation** that highlights correlated fields
  (e.g. a symbol's risk level and the level's definition) and flags
  inconsistent combinations before export.
- Support **importing an existing `engine_config.yaml`** as the starting
  point for a new editing session, preserving anything the GUI does not
  model as read-only "passthrough" data.
- Provide **contextual guides and built-in help** (tooltips, glossary,
  onboarding tour, deep links to `docs/user-guide/`) so the tool is
  self-teaching.
- Produce output that is byte-for-byte parseable by
  `load_engine_config()` — i.e., the GUI is held to the same correctness bar
  as `pm-config-gen`.

### 3.2 Non-Goals

- `config-gui` does not run or manage the engine, scheduler, or any gateway
  process. It only produces (and optionally verifies) a config file.
- It does not replace `pm-config-gen` as a scriptable/CI-friendly tool — the
  CLI remains the automation-friendly path; the GUI is the human-friendly
  path. Both should stay behaviourally aligned (see [Section 12.4](#124-keeping-cli-and-gui-in-sync)).
  the GUI is the human-friendly path.
- It does not provide multi-user real-time collaborative editing (e.g. two
  people editing the same draft simultaneously) in v1.
- It does not manage secrets storage/rotation for generated API keys beyond
  one-time display and export (see [Section 15](#15-security-considerations)).
- It does not validate that seeded prices are "realistic" relative to any
  real market data feed.

## 4. Personas and Complexity Tiers

The persona is a single global setting (top bar, always visible, switchable
at any time) that controls **field visibility**, not permissions — nothing
is ever truly hidden data-loss-style; switching to a higher persona simply
reveals more panels/fields for values that may already be set (e.g. via
import). Switching to a lower persona **never clears** higher-tier values;
it just stops showing their editors, with a small "N advanced settings
hidden" indicator per panel so nothing is lost silently.

| Persona | Target user | Philosophy |
|---|---|---|
| `BEGINNER` | First-time student running a classroom exchange | Show only what's needed for a working, safe minimal exchange: symbols, gateways, one collar band, one circuit-breaker toggle, sessions on/off. Every field has a safe, pre-filled default. |
| `INTERMEDIATE` | TA / instructor tuning a specific scenario | Adds named risk levels, editable circuit-breaker ladder, per-symbol overrides, market-maker obligation tuning, indices, and the two most common auxiliary gateways (post-trade, market-data). |
| `EXPERT` | Course author / power user building the full teaching environment | Adds BALF gateway, API gateway (including multi-instance + explicit credentials), combo seed orders, per-symbol circuit-breaker overrides, deterministic seeding (`--seed`), and raw-YAML passthrough editing. |

Each field in [Section 7](#7-field-catalogue) is tagged with a **minimum
persona** (`B`, `I`, or `E`) — the lowest tier at which it becomes visible.
`B` fields are visible in all three tiers, `I` fields in `INTERMEDIATE` and
`EXPERT`, `E` fields only in `EXPERT`.

Design rule for implementers: persona is a **view filter**, not a validation
gate. If an imported config sets an `EXPERT`-only field while the user is in
`BEGINNER` mode, that value stays in the data model, is still exported
correctly, and is surfaced via the "N advanced settings hidden here" banner
described above — never silently dropped.

## 5. Information Architecture

### 5.1 Top-level layout

```
┌─────────────────────────────────────────────────────────────────────────┐
│ EduMatcher Config Builder      [Beginner ▾]  [Import] [New] [⌘K]  [Save]│
├───────────────┬───────────────────────────────────────────┬─────────────┤
│  Navigation    │              Active Panel                 │ Diagnostics │
│  (tabs)        │                                             │   Drawer    │
│                │                                             │             │
│ ● Basics    ✓  │   <form fields for the selected tab>       │  2 warnings │
│ ○ Sessions  ✓  │                                             │  0 errors   │
│ ○ Risk      !  │                                             │             │
│ ○ Circuit…  ✓  │                                             │  ⚠ Symbol   │
│ ○ Market Mk ✓  │                                             │  TSLA has   │
│ ○ Symbols   ✓  │                                             │  no risk    │
│ ○ Indices   —  │                                             │  level match│
│ ○ Combos    —  │                                             │  [Jump→]    │
│ ○ Gateways  —  │                                             │             │
│ ○ Review       │                                             │             │
└───────────────┴───────────────────────────────────────────┴─────────────┘
```

- **Navigation** is a vertical tab list. Each tab shows a status glyph:
  `✓` complete/valid, `!` has warnings, `✗` has errors, `—` not configured
  (optional section, untouched). Tabs hidden by the current persona are
  omitted entirely from this list (not disabled — omitted — to avoid clutter).
- **Active Panel** renders the selected tab's form. Large tabs (Symbols,
  Indices, Combos, API Gateway) use a **master–detail** sub-layout: a list
  on the left, an editor for the selected item on the right.
- **Diagnostics Drawer** is persistent and global — it always lists every
  current warning/error across the *entire* config, not just the active
  tab, each with a "Jump →" action that switches tabs/scrolls to and
  briefly highlights the offending field(s). It can be collapsed to a badge
  showing counts.
- **Top bar** actions: persona switcher, Import (upload YAML), New
  (blank draft, confirms discard), a command palette (`⌘K`/`Ctrl K`,
  Expert-oriented but available to all) to jump to any field by name, and
  Save (persists the draft — see [Section 17](#17-state-management-and-persistence)).

### 5.2 Tab list (in navigation order)

| # | Tab | Min persona to see tab at all | Notes |
|---|---|---|---|
| 1 | **Basics** (symbols + gateways) | B | Always first; mandatory section |
| 2 | **Sessions & Schedule** | B | Toggle-only in Beginner; full schedule editor from Intermediate |
| 3 | **Risk & Collars** | B | Single global band in Beginner; named levels from Intermediate |
| 4 | **Circuit Breakers** | B | On/off toggle with built-in ladder in Beginner; editable ladder from Intermediate |
| 5 | **Market Maker** | B (only rendered if ≥1 `MARKET_MAKER` gateway exists) | Mid-range seeding always shown once relevant; obligations tuning from Intermediate |
| 6 | **Symbols** (per-symbol overrides) | I | Master–detail grid; in Beginner, per-symbol overrides are not offered (global values apply to all) |
| 7 | **Indices** | I | Up to 5 indices |
| 8 | **Combos** | E | Multi-leg seed order builder |
| 9 | **Auxiliary Gateways** (Post-Trade / Market-Data / BALF / API) | I for Post-Trade & Market-Data; E for BALF & API | Sub-tabbed within this tab |
| 10 | **Review & Export** | B | Always last; diagnostics summary + YAML preview + download |

### 5.3 Master–detail pattern (Symbols tab example)

```
┌───────────────┬───────────────────────────────────────────────────────┐
│ Symbols   [+]  │  AAPL                                    [Delete]     │
│               │  ┌ General ┬ Collar ┬ Circuit Breaker ┬ Market Maker ┐│
│ ▸ AAPL    ✓   │  │ Tick decimals:        [2      ] (default: 2)     ││
│   MSFT    ✓   │  │ Outstanding shares:   [       ] optional          ││
│   TSLA    !   │  │ Risk level:           [DEFAULT ▾] (Intermediate+)││
│               │  │ Last buy/sell price:  [   ]/[   ] optional        ││
│               │  └───────────────────────────────────────────────────┘│
└───────────────┴───────────────────────────────────────────────────────┘
```

Symbols are added/removed from the list; removing a symbol that is
referenced elsewhere (index constituent, combo leg, `--symbol-opts`
overrides, `--api-gateway-instance` via a gateway that trades it) triggers a
confirmation dialog listing every dependent reference so nothing breaks
silently.

## 6. Visual Design System

Implementers should use an existing accessible component library (see
[Section 12](#12-technical-architecture)) rather than building primitives
from scratch. The following are the **semantic design tokens** the app
needs; exact hex values are left to the project's design system, but the
roles below must exist and be used consistently:

| Token role | Usage |
|---|---|
| `--color-required` (accent, e.g. a warm red/orange) | Left border + label asterisk on every mandatory field |
| `--color-optional-set` | Border/background for an optional field the user has explicitly set (distinguish "set" from "default") |
| `--color-optional-default` (muted/grey) | Optional fields still at their default — rendered with ghost placeholder text `Default: <value>` |
| `--color-warning` (amber) | Field-level and panel-level warning state, tab glyph `!` |
| `--color-error` (red) | Field-level and panel-level error state, tab glyph `✗` |
| `--color-linked` (blue/teal) | Highlight ring used to show two or more cross-validated fields are correlated (see [Section 8](#8-cross-field-validation-and-consistency-engine)) |
| `--color-success` (green) | Tab glyph `✓`, inline "valid" check |

Typography/layout baseline: a 12-column responsive grid, minimum supported
viewport 1280px wide for the 3-pane layout (Navigation / Panel /
Diagnostics), collapsing to a 2-pane layout with the Diagnostics Drawer as a
slide-over below 1024px, and a single-column stacked layout with tabs as an
accordion below 768px (tablet, not primary target but must remain usable —
see [Section 16](#16-accessibility-requirements)).

**Mandatory vs optional convention (applies everywhere):**

- Mandatory field: red asterisk after the label, red left border on the
  input, cannot be left empty, tab cannot reach `✓` until satisfied.
- Optional field with a default: label has no asterisk; the input shows a
  greyed-out placeholder `Default: 0.5` when empty; once the user types a
  value, the border switches to `--color-optional-set` and a small "reset to
  default" (↺) icon appears.
- Optional field with no default (must be filled in manually after
  generation, e.g. MM quote `bid_price`): rendered with an explicit amber
  "Required before starting the engine" chip instead of a default ghost
  value, so it's visually distinct from "optional-with-safe-default".

## 7. Field Catalogue

This is the authoritative mapping from every `pm-config-gen` CLI
concept to a GUI field. Columns: **Mandatory** (Yes/No), **Default**
(pre-filled value), **Persona** (minimum tier at which the field is shown),
**Widget** (control type), **Notes**.

### 7.1 Basics — Symbols & Gateways (mandatory section)

| Field | CLI source | Mandatory | Default | Persona | Widget | Notes |
|---|---|---|---|---|---|---|
| Symbols | `--symbols` | Yes | — | B | Tag input w/ autocomplete, uppercases on blur | At least 1 required; duplicates rejected inline |
| Gateways table | `--gateways` | Yes | — | B | Editable table, add/remove rows | At least 1 required; IDs unique, uppercased on blur |
| Gateway → ID | part of `GW_SPEC` | Yes | — | B | Text cell | |
| Gateway → Role | part of `GW_SPEC` | No | `TRADER` | B | Dropdown: `TRADER` / `MARKET_MAKER` / `ADMIN` | |
| Gateway → Disconnect behavior | part of `GW_SPEC` | No | Role-derived (`CANCEL_ALL` / `CANCEL_QUOTES_ONLY` / `LEAVE_ALL`) | I | Dropdown, auto-set then editable | Beginner: hidden, always uses role default |
| Gateway → Description | part of `GW_SPEC` | No | `""` | I | Text cell | |

### 7.2 Sessions & Schedule

| Field | CLI source | Mandatory | Default | Persona | Widget | Notes |
|---|---|---|---|---|---|---|
| Sessions enabled | `--sessions-enabled` / `--no-sessions-enabled` | No | `false` | B | Switch | Info banner explains `pm-scheduler` must run when enabled |
| Emit schedule | `--schedule` / `--no-schedule` | No | mirrors "Sessions enabled" | I | Switch (Intermediate+; Beginner always emits default schedule when sessions enabled) | |
| Pre-open | `--pre-open` | No | `09:00` | I | Time picker | Must be < Opening auction; enforced fatally by `pm-config-gen` itself ([§8.1](#81-rule-catalogue-baseline-inherited-from-pm-config-genwarningspy)) |
| Opening auction | `--opening-auction` | No | `09:25` | I | Time picker | Must be < Continuous |
| Continuous | `--continuous` | No | `09:30` | I | Time picker | Must be < Closing auction |
| Closing auction | `--closing-auction` | No | `16:00` | I | Time picker | Must be < Closing end |
| Closing end | `--closing-end` | No | `16:05` | I | Time picker | |

### 7.3 Risk Controls & Collars

| Field | CLI source | Mandatory | Default | Persona | Widget | Notes |
|---|---|---|---|---|---|---|
| Global static band | `--static-band` | No | none (no collar unless set) | B | Slider + numeric (%), range (0,100) exclusive | Simplified single control in Beginner; creates `DEFAULT` level |
| Global dynamic band | `--dynamic-band` | No | `0.02` if static band set | B | Slider + numeric (%) | |
| Named risk levels | `--risk-level` (repeatable) | No | `[]` | I | Repeatable card list: Name, Static %, Dynamic % | Name uppercased, unique; referenced by symbols |
| Per-symbol static band override | `--symbol-static-band` / `--symbol-opts static_band` | No | inherits global/level | I | Numeric field inside Symbols → Collar tab | |
| Per-symbol dynamic band override | `--symbol-dynamic-band` / `--symbol-opts dynamic_band` | No | inherits global/level | I | Numeric field inside Symbols → Collar tab | |
| Per-symbol risk level assignment | `--symbol-risk-level` / `--symbol-opts level` | No | none | I | Dropdown populated from defined levels (incl. `DEFAULT`) | Cross-validated against level catalogue |
| Outstanding shares | `--outstanding-shares` | No | none | I | Numeric field inside Symbols → General tab | Used for index weighting |

### 7.4 Circuit Breakers

| Field | CLI source | Mandatory | Default | Persona | Widget | Notes |
|---|---|---|---|---|---|---|
| Enforce circuit breakers | `--no-circuit-breakers` (inverted) | No | `true` | B | Switch | Turning off shows a persistent amber "tests only" banner |
| CB ladder | `--cb-levels` | No | `L1:0.07:5`, `L2:0.13:15`, `L3:0.20` (all `AUCTION`) | B (read-only preview) / I (editable) | Table: Level, Shift %, Halt (minutes or "rest of day" toggle), Resumption mode | Beginner sees the 3 built-in rows read-only with a "customize in Intermediate mode" hint |
| Add custom level | `--cb-levels` (extra entries) | No | — | E | "+ Add level" row | Beginner/Intermediate capped at L1–L3 |
| CB reference window | `--cb-window-ns` | No | `300000000000` (5 min) | I | Duration input (minutes, converted to ns) | |
| Per-symbol CB shift override | `--symbol-opts cb_shift_LN` | No | inherits ladder | E | Numeric field, Symbols → Circuit Breaker tab | |
| Per-symbol CB halt override | `--symbol-opts cb_halt_LN` | No | inherits ladder | E | Minutes input, 0 = rest of day | |
| Per-symbol CB resumption override | `--symbol-opts cb_resumption_LN` | No | inherits ladder | E | Dropdown `AUCTION`/`CONTINUOUS` | |

### 7.5 Market-Maker Obligations & Seeding

Rendered only once at least one gateway has role `MARKET_MAKER`.

| Field | CLI source | Mandatory | Default | Persona | Widget | Notes |
|---|---|---|---|---|---|---|
| Enforce MM obligations | `--enforce-mm-obligations` | No | `false` | B | Switch | |
| Max spread (ticks) | `--mm-spread-ticks` | No | `20` | B | Numeric | |
| Min quantity | `--mm-min-qty` | No | `100` | B | Numeric | |
| Per-symbol spread/qty override | `--symbol-opts mm_spread_ticks` / `mm_min_qty` | No | inherits global | I | Numeric fields, Symbols → Market Maker tab | |
| Per-symbol enforcement override | `--symbol-opts enforce_mm_obligation` | No | inherits global | I | Switch, Symbols → Market Maker tab | |
| Seed MM mid-range | `--seed-mm-mid-range` | No | none | B | Min/Max price range slider, tick-grid aware | Required before Beginner can leave `null` MM quote stubs; strongly recommended inline |
| Seed last prices from MM | `--seed-last-prices-from-mm` | No | `false` | I | Switch, disabled until mid-range set | Disabled-state tooltip explains the dependency |
| Seed last prices (placeholder) | `--seed-last-prices` | No | `false` | I | Switch | Mutually informative with the above — see [§8](#8-cross-field-validation-and-consistency-engine) |
| Deterministic seed | `--seed` | No | none (random) | E | Numeric | For reproducible classroom runs |
| MM quote stub review | n/a (generated) | — | `bid/ask = null`, `qty = 1000`, `tif = DAY`, `seed_once = true` | B | Read-only checklist per symbol × MM gateway, each row flagged "fill in before starting the engine" unless mid-range seeding supplies real values | |

### 7.6 Symbols Tab — Consolidated Per-Symbol Panel

The Symbols tab (master–detail, [§5.3](#53-masterdetail-pattern-symbols-tab-example))
hosts all per-symbol fields from 7.3–7.5 organized into four sub-tabs per
symbol: **General** (tick decimals, outstanding shares, last prices),
**Collar** (static/dynamic band, risk level), **Circuit Breaker** (per-level
overrides), **Market Maker** (spread/qty/enforcement overrides, quote stub
status). Sub-tabs beyond General are hidden entirely in `BEGINNER`.

| Field | CLI source | Mandatory | Default | Persona | Widget |
|---|---|---|---|---|---|
| Tick decimals (global default) | `--tick-decimals` | No | `2` | B | Numeric, `0..8`, applies to symbols without an override |
| Tick decimals (per-symbol) | `--symbol-opts tick_decimals` | No | inherits global | I | Numeric, `0..8` |

### 7.7 Indices

| Field | CLI source | Mandatory (if index defined) | Default | Persona | Widget | Notes |
|---|---|---|---|---|---|---|
| Index ID | `--index` | Yes | — | I | Text, alphanumeric + `-`/`_`, uppercased | Max 5 indices |
| Description | `--index` (suffix) | No | `Index <ID>` | I | Text | |
| Constituents | `--index-constituents` | Yes | — | I | Multi-select from defined symbols | Every index must have ≥ 1 constituent |
| Base value | `--index-base-value` | No | `1000.0` | I | Numeric | |
| Publish interval (sec) | `--index-interval` | No | `1.0` | I | Numeric | |
| History file | `--index-history-file` | No | `data/indexes/<id>_history.*` (derived) | E | Text/path | Advanced; shown read-only until Expert |
| State file | `--index-state-file` | No | `data/indexes/<id>_state.*` (derived) | E | Text/path | |

### 7.8 Combos (Seed Orders)

Expert-only tab; a multi-leg order builder.

| Field | CLI source | Mandatory (if combo defined) | Default | Persona | Widget | Notes |
|---|---|---|---|---|---|---|
| Combo ID | `--combo` | Yes | — | E | Text, unique | |
| Combo type | `--combo` | Yes | — | E | Dropdown (`ComboType` enum) | |
| TIF | `--combo` | Yes | — | E | Dropdown (`TIF` enum) | |
| Legs | `--combo` | Yes, ≥ 2, ≤ 10 | — | E | Repeatable leg row: Symbol, Side, Order type, Qty, Price, Stop, SMP action | Prices/stops entered as **decimal** display values honoring the symbol's `tick_decimals` and converted to the integer tick representation internally (see [§20](#20-recommended-enhancements-beyond-the-stated-requirements)) |
| Leg → Symbol | leg field | Yes | — | E | Dropdown from defined symbols | No duplicate symbols within one combo |
| Leg → Side | leg field | Yes | — | E | Dropdown `BUY`/`SELL` | |
| Leg → Order type | leg field | Yes | — | E | Dropdown (`OrderType` enum) | |
| Leg → Quantity | leg field | Yes | — | E | Numeric, > 0 | |
| Leg → Price | leg field | No | none | E | Decimal input | Omit for market legs; `pm-config-gen` itself now accepts decimal prices for `--combo` legs and converts to ticks (see [§20](#20-recommended-enhancements-beyond-the-stated-requirements)) |
| Leg → Stop price | leg field | No | none | E | Decimal input | |
| Leg → SMP action | leg field | No | `NONE` | E | Dropdown (`SmpAction` enum) | |

### 7.9 Auxiliary Gateways — Common Fields

Post-Trade, Market-Data, and BALF gateways share a common shape. Rather than
three near-duplicate tables, the shared pattern is described once, followed
by each gateway's distinguishing fields.

**Common network-service fields** (each rendered under its own gateway
sub-tab, each with its own default constants):

| Field pattern | Applies to | Widget | Notes |
|---|---|---|---|
| Enable this gateway | all three (+ API gateway) | Switch | Turning on reveals the rest of the sub-tab; turning off keeps values but excludes the section from output |
| Name | all three | Text | |
| Bind address | all three | Text (IP) | |
| Port | all three | Numeric | **Cross-validated for collisions across every configured gateway** — `pm-config-gen` itself now warns on this ([§8.1](#81-rule-catalogue-baseline-inherited-from-pm-config-genwarningspy), [§20](#20-recommended-enhancements-beyond-the-stated-requirements)) |
| Heartbeat interval (sec) | all three | Numeric | |
| Idle timeout (sec) | all three | Numeric | |
| Max client queue | all three | Numeric | |

#### 7.9.1 Post-Trade Gateway (Intermediate+)

| Field | CLI source | Default | Persona |
|---|---|---|---|
| Enable / Name / Bind / Port / Heartbeat / Idle / Max queue | `--post-trade-*` | `ralf-gwy01`, `0.0.0.0`, `5580`, `1`, `5`, `10000` | I |
| Replay retention (sec) | `--post-trade-replay-retention-sec` | `86400` | I |
| Allowed roles | `--post-trade-allowed-roles` | `CLEARING`, `DROP_COPY`, `AUDIT` | I — multi-select |

#### 7.9.2 Market-Data Gateway (Intermediate+)

| Field | CLI source | Default | Persona |
|---|---|---|---|
| Enable / Name / Bind / Port / Heartbeat / Idle / Max queue | `--market-data-*` | `md-gwy01`, `0.0.0.0`, `5570`, `1`, `5`, `10000` | I |
| Replay window (sec) | `--market-data-replay-window-sec` | `30` | I |
| Max symbols per client | `--market-data-max-symbols-per-client` | `200` | I |

#### 7.9.3 BALF Gateway (Expert only)

| Field | CLI source | Default | Persona |
|---|---|---|---|
| Enable / Name / Bind / Port / Heartbeat interval / Idle / Max queue | `--balf-*` | `balf-gwy01`, `0.0.0.0`, `5560`, `1`, `30`, `10000` | E |
| Heartbeat timeout (sec) | `--balf-heartbeat-timeout-sec` | `5` | E |
| Auth timeout (sec) | `--balf-auth-timeout-sec` | `10` | E |
| Max connections | `--balf-max-connections` | `64` | E |
| Max messages/sec | `--balf-max-messages-per-second` | `100` | E |
| Max errors before disconnect | `--balf-max-errors-before-disconnect` | `10` | E |
| Error window (sec) | `--balf-error-window-sec` | `60` | E |
| Duplicate session policy | `--balf-duplicate-session-policy` | `REJECT_NEW` | E — dropdown `REJECT_NEW` / `EVICT_OLD` |

#### 7.9.4 API Gateway (Expert only)

| Field | CLI source | Default | Persona | Widget |
|---|---|---|---|---|
| Enable | `--api-gateway` (implied by any field) | off | E | Switch |
| Deployment mode | derived | Single instance | E | Toggle: **Single instance** vs **Multi-instance** |
| Instance name (single mode) | `--api-gateway-name` | `default` | E | Text |
| Instances table (multi mode) | `--api-gateway-instance` | `[]` | E | Table: Name, Gateway IDs (multi-select), Port (optional, auto-assigned `base + index` if blank) |
| Host | `--api-gateway-host` | `127.0.0.1` | E | Text |
| Port (single mode / base port) | `--api-gateway-port` | `8080` | E | Numeric — collision-checked |
| Swagger UI enabled | `--api-gateway-swagger-enabled` | `true` | E | Switch |
| Log level | `--api-gateway-log-level` | `info` | E | Dropdown `debug`/`info`/`warning`/`error` |
| Stats DB path | `--api-gateway-stats-db` | `data/stats.db` | E | Text/path |
| Rate limit — writes/sec | `--api-gateway-rate-limit-writes-per-second` | `10` | E | Numeric |
| Rate limit — burst | `--api-gateway-rate-limit-burst` | `20` | E | Numeric |
| Engine auth timeout (sec) | `--api-gateway-engine-auth-sec` | `3.0` | E | Numeric |
| Engine reply timeout (sec) | `--api-gateway-engine-reply-sec` | `3.0` | E | Numeric |
| Wait-ack timeout (sec) | `--api-gateway-wait-ack-sec` | `3.0` | E | Numeric |
| Auto-generate keys | `--api-gateway-generate-keys` | `true` | E | Switch |
| Generate read-only key | `--api-gateway-readonly-key` | `false` | E | Switch |
| Explicit credentials (single mode only) | `--api-key` | `[]` | E | Table: Key (masked, "generate" button available), Gateway (dropdown incl. "read-only"), Description |

### 7.10 Output & Generation Controls (Review tab)

| Field | CLI source | Default | Persona | Widget |
|---|---|---|---|---|
| Comment default fields in output | `--comment-default-config-fields` | `false` | E | Switch |
| Download filename | `--output` | `engine_config.yaml` | B | Text |
| Overwrite confirmation | `--force` | n/a (GUI always confirms before replacing an in-progress import) | B | Dialog, not a persistent field |
| Dry-run / preview | `--dry-run` | n/a — GUI always previews before download | B | The YAML preview pane *is* the dry-run view |

## 8. Cross-Field Validation and Consistency Engine

Every rule below runs **live**, on every relevant field change, client-side
(see [§12](#12-technical-architecture)), and is also re-checked before
export. Each rule produces a diagnostic object:

```ts
interface Diagnostic {
  id: string;                 // stable rule id, e.g. "undefined-risk-level"
  severity: "info" | "warning" | "error";
  message: string;
  fieldPaths: string[];       // one or more fields this diagnostic links
  tab: string;                // which tab to jump to
}
```

When a diagnostic has 2+ `fieldPaths`, both fields render a
`--color-linked` outline simultaneously while either is focused/hovered, and
the Diagnostics Drawer entry's "Jump →" cycles focus between them.

### 8.1 Rule catalogue (baseline, inherited from `pm-config-gen`/`warnings.py`)

| Rule | Trigger | Severity | Fields linked |
|---|---|---|---|
| Undefined risk level | Symbol's `level` doesn't match any defined level name | Error | Symbol.level ↔ Risk Levels list |
| MM gateway needs quote seeds | ≥1 `MARKET_MAKER` gateway and any symbol still has a `null` bid/ask stub | Warning | Gateway ↔ affected symbols' MM quote rows |
| Collars/CB disabled | `enforce_collars=false` or `enforce_circuit_breakers=false` | Warning | Basics toggle |
| Tick decimals = 0 | Global or per-symbol `tick_decimals == 0` | Warning | Field itself |
| Single gateway | Exactly 1 gateway configured | Warning | Gateway table |
| No ADMIN gateway | No gateway has role `ADMIN` | Info | Gateway table |
| Sessions enabled, default schedule | `sessions_enabled=true`, schedule untouched | Info | Sessions toggle |
| `--seed-last-prices-from-mm` without mid-range | Switch on but no `seed_mm_mid_range` | Error (GUI disables the switch, see 7.5) | MM seeding fields |
| Lowercase symbol/gateway ID | Any ID typed in lowercase | Auto-fixed, no diagnostic needed (see [§20](#20-recommended-enhancements-beyond-the-stated-requirements)) | — |
| Port collision | Two or more of {Post-Trade, Market-Data, BALF, API Gateway instance(s)} resolve to the same `(bind_address, port)`, treating `0.0.0.0`/`::` as matching any address | Warning | All colliding gateway Port fields |
| Schedule out of order | Any schedule time is malformed, or `pre_open < opening_auction < continuous < closing_auction < closing_end` is violated | Error | All 5 schedule time fields |

**Note:** Port collision and Schedule-out-of-order were originally proposed
as GUI-only additions ([§20](#20-recommended-enhancements-beyond-the-stated-requirements))
but have since been implemented directly in `pm-config-gen`
(`_port_collision_warnings` in `warnings.py`, `_validate_schedule_order` in
`cli.py`), so they are listed here as baseline rules the GUI must match
exactly rather than rules the GUI introduces on its own.

### 8.2 New rules required by the fuller GUI schema (not present in the current CLI's `warnings.py`)

| Rule | Trigger | Severity | Fields linked |
|---|---|---|---|
| Index missing constituents | Index defined with 0 constituents | Error | Index card ↔ Constituents field |
| Index constituent not in symbol universe | Constituent symbol not present in Basics → Symbols | Error | Index constituent ↔ Symbols list |
| Combo leg symbol unknown | Leg references a symbol not in Basics → Symbols | Error | Combo leg ↔ Symbols list |
| Combo duplicate leg symbol | Same symbol appears twice in one combo | Error | Both leg rows |
| API gateway ID overlap | Same ALF gateway ID assigned to two `--api-gateway-instance` entries | Error | Both instance rows |
| API instance/credentials mode conflict | Both multi-instance table and explicit `--api-key` rows populated | Error | Deployment mode toggle |
| Outstanding shares missing for index constituent | Symbol used in an index has no `outstanding_shares` set | Warning | Symbol.outstandingShares ↔ Index card |
| Large symbol universe | > 10 symbols | Info | Symbols tag input |

These remain GUI-only because they cover schema areas (`indices`, `combos`,
`api_gateways` instance mode) that `pm-config-gen`'s own `warnings.py`
doesn't yet cross-check; implementing them there too would be a reasonable
follow-up but is out of scope for this document.

### 8.3 Presentation

- **Panel-level banner**: when a panel has ≥1 error, a red banner appears at
  the top of the panel summarizing the count with jump links; warnings use
  an amber banner.
- **Field-level markers**: red/amber left border + inline icon + tooltip
  with the diagnostic message directly under the field.
- **Tab glyphs**: aggregate worst severity within the tab (`✗` > `!` > `✓`
  > `—`).
- **Export gate**: the Review tab's "Download" action is disabled while any
  `error`-severity diagnostic exists anywhere in the config; warnings do not
  block export but require a one-time acknowledgement checkbox ("I
  understand N warnings will be included") the first time a user tries to
  export with outstanding warnings.

## 9. Importing an Existing Configuration

1. User clicks **Import** → file picker (or drag-and-drop) accepting
   `.yaml`/`.yml`, max size guarded (see [§15](#15-security-considerations)).
2. Backend parses the YAML into the canonical `EngineConfigDraft` model
   ([§13](#13-data-model)) using a strict schema (Zod), **not** by trying to
   re-derive CLI flags — the GUI's internal state models the full
   `engine_config.yaml` schema directly, so import is a direct
   YAML → object mapping.
3. Any YAML keys/sections the GUI does not have a dedicated editor for
   (e.g., a hand-added `gateways.alf[*].mm_obligations` override, or a
   `market_maker_combos` entry the Combos tab doesn't yet cover) are kept in
   a per-section `unmappedYaml` bucket and displayed in a read-only "Advanced
   / Unmapped YAML" panel at the bottom of the relevant tab, with a clear
   callout: *"This data is preserved but not editable here — edit and
   re-import, or use the raw YAML pane."* An Expert-only **raw YAML
   passthrough editor** (CodeMirror, YAML-aware) lets power users hand-edit
   these blocks without leaving the app; edits there are re-parsed into the
   same buckets on save.
4. Import always runs full validation immediately and opens the Review tab
   first, showing "Imported: 3 warnings, 0 errors — review before
   continuing" so users see the health of what they just loaded before
   touching anything.
5. Re-exporting a config that was imported preserves comments **only** for
   the header metadata block (regenerated fresh, matching
   `pm-config-gen`'s convention); inline field comments are not
   round-tripped since the GUI is a structural editor, not a text editor —
   this is called out explicitly in the UI ("Comments in the original file
   are not preserved on export") to set expectations.

## 10. Guided Help System

- **Inline field help**: every field has an `(i)` affordance opening a short
  popover with a one-paragraph explanation, its CLI equivalent flag (for
  users who also use the terminal), and, where relevant, a worked example
  value.
- **Section intros**: each tab opens with a 2–3 sentence explainer, e.g. the
  Circuit Breakers tab explains "shift %" and "halt duration" in plain
  language before showing the ladder editor (mirrors the "Financial Concepts
  Primer" style used in [EduMatcher-Index.md](EduMatcher-Index.md)).
- **Glossary drawer**: a persistent, searchable glossary (collar, static vs
  dynamic band, circuit breaker ladder resumption mode, MM obligation,
  combo, disconnect behaviour, session phase) reachable from the top bar.
- **Onboarding tour**: first-run only, a 5-step guided tour (Basics → pick a
  persona → Sessions → Market Maker if applicable → Review/Export),
  dismissible and re-launchable from a "?" menu.
- **Deep links to docs**: every help popover that maps to a documented
  concept links out to the relevant page under `docs/user-guide/` (e.g. the
  schedule/session explainer links to `docs/user-guide/01-configuration.md`
  session-control section).
- **Persona nudges**: if a `BEGINNER` user's config would benefit from a
  hidden field (e.g., they have a `MARKET_MAKER` gateway but no way to tune
  per-symbol spread because that's Intermediate+), show a small "Switch to
  Intermediate to customize this" hint instead of just omitting the
  capability silently.

## 11. Review, Diagnostics and Export

The Review tab has three stacked sections:

1. **Diagnostics summary** — the same list as the Diagnostics Drawer, but
   full-width and grouped by tab, so a user can do a final top-to-bottom
   pass.
2. **YAML preview** — read-only, syntax-highlighted (CodeMirror/Monaco),
   generated by the same renderer used for export, with a "Copy to
   clipboard" button. Includes the standard header/comment block matching
   `pm-config-gen`'s convention (generation date, equivalent CLI invocation
   summary text for reference, validate-with hint).
3. **Export actions**:
   - **Download** `engine_config.yaml` (disabled while errors exist).
   - **Optional: Verify with `pm-cverifier`** — if the deployment has a
     server-side Python environment available, this button POSTs the
     generated YAML to a backend endpoint that shells out to
     `pm-cverifier --format json` (read-only tool, safe to invoke) and
     renders its authoritative report inline, underneath the GUI's own
     diagnostics, clearly labeled as "additional server-side checks." This
     is optional/pluggable — the GUI must fully function without it
     ([§12.4](#124-keeping-cli-and-gui-in-sync)).

## 12. Technical Architecture

### 12.1 Stack

| Layer | Choice | Rationale |
|---|---|---|
| Frontend framework | React 18 + TypeScript, bundled with Vite | Fast dev loop, huge ecosystem, matches "average UI dev" familiarity |
| Styling | Tailwind CSS + a headless accessible component kit (Radix UI primitives / shadcn/ui) | Accessible-by-default dropdowns, dialogs, switches, tooltips without hand-rolling ARIA |
| Forms & validation | React Hook Form + Zod resolvers | Schema-driven validation shared with the backend (see 12.2) |
| Tables/grids | TanStack Table | Gateways, CB ladder, indices, combo legs, credentials tables |
| Code/YAML preview | CodeMirror 6 (YAML mode) | Lighter weight than Monaco; sufficient for read-only preview + Expert passthrough editing |
| Client state | Zustand (or React Context + `useReducer` for smaller teams) | Holds persona, active draft, diagnostics cache |
| Routing | React Router, one route per tab (`/basics`, `/risk`, `/review`, …) | Deep-linkable/bookmarkable sections, supports the "?" help deep links |
| Backend runtime | Node.js + TypeScript | Matches stated requirement |
| Backend framework | Fastify | Lightweight, first-class TypeScript + JSON schema support, good for a small focused API |
| Shared schema package | `packages/schema` (Zod schemas + inferred TS types + default constants) imported by both frontend and backend | Single source of truth for validation, avoids client/server drift |
| YAML codec | `js-yaml` (parse) + a small custom serializer matching `pm-config-gen`'s comment style (write) | Full control over generated comments/formatting |

### 12.2 Monorepo layout

```
config-gui/
  apps/
    web/                  React frontend (Vite)
    server/               Fastify backend
  packages/
    schema/                Zod schemas, TS types, default constants (mirrors defaults.py)
    yaml-codec/             engine_config.yaml <-> EngineConfigDraft (parse + serialize)
    diagnostics/            Cross-field rule engine (Section 8), pure functions, unit-tested in isolation
  package.json              npm/pnpm workspaces root
```

### 12.3 Data flow

```mermaid
flowchart LR
    U[User in browser] -->|edits form| S[Zustand store: EngineConfigDraft]
    S -->|on change| D[diagnostics package\nrule engine]
    D -->|Diagnostic[]| U
    U -->|Import YAML| API1[POST /api/config/import]
    API1 -->|yaml-codec parse| S
    U -->|Download| API2[POST /api/config/generate]
    API2 -->|yaml-codec serialize| U
    U -->|optional Verify| API3[POST /api/config/verify]
    API3 -->|execFile pm-cverifier --format json| PY[Python pm-cverifier]
    PY --> API3 --> U
```

### 12.4 Keeping CLI and GUI in sync

Two sources of drift risk: (a) default values, (b) validation rules. To
mitigate:

- **Defaults**: add a small Python export script,
  `scripts/export-config-gen-defaults.py`, that imports
  `edumatcher.config_gen.defaults` and writes a JSON file (e.g.
  `packages/schema/generated/defaults.json`) consumed at build time by the
  TS `schema` package. Run this script in CI whenever `defaults.py` changes
  (a CI check fails if the JSON is stale — compare against a checked-in
  copy).
- **Validation rules**: the GUI's `diagnostics` package re-implements the
  rules in TypeScript (necessary since the GUI validates a full schema
  model, not CLI flags) but each rule's `id` and message text should mirror
  `warnings.py` where an equivalent exists, and a code comment should
  reference the Python source function, so the two stay conceptually
  aligned during future changes to either tool.
- **Golden-file integration test**: a CI job generates several representative
  configs through the GUI's backend `generate` endpoint and pipes each
  through the real `load_engine_config()` (Python) to guarantee GUI output
  always stays parser-valid, exactly mirroring how `pm-config-gen` is
  tested today.

## 13. Data Model

The canonical client/server state, `EngineConfigDraft`, mirrors
`engine_config.yaml`'s structure directly (not the CLI flags — the CLI
mini-languages are strictly an input-encoding concern that the GUI avoids by
editing structured fields directly). Abbreviated TypeScript sketch:

```ts
interface EngineConfigDraft {
  sessionsEnabled: boolean;
  snapshotIntervalSec: number;
  enforceCollars: boolean;
  enforceCircuitBreakers: boolean;
  schedule?: Schedule;

  symbols: Record<string, SymbolConfig>;   // key = uppercased symbol
  gateways: GatewayConfig[];

  riskControls?: {
    defaultLevel?: string;
    levels: Record<string, { staticBandPct: number; dynamicBandPct: number }>;
  };
  circuitBreakerDefaults?: {
    windowNs: number;
    levels: Record<string, CbLevel>;
  };
  mmObligationDefaults?: {
    enforceMmObligation: boolean;
    mmMaxSpreadTicks: number;
    mmMinQty: number;
    symbols?: Record<string, Partial<{ mmMaxSpreadTicks: number; mmMinQty: number; enforceMmObligation: boolean }>>;
  };

  indices: IndexConfig[];
  combos: ComboConfig[];

  postTradeGateway?: PostTradeGatewayConfig;
  marketDataGateway?: MarketDataGatewayConfig;
  balfGateway?: BalfGatewayConfig;
  apiGateways: ApiGatewayConfig[];

  // Preserves any YAML this GUI version doesn't model yet; keyed by
  // section/path so it can be re-attached on export without loss.
  unmappedYaml: Record<string, unknown>;
}

interface SymbolConfig {
  tickDecimals: number;
  level?: string;
  outstandingShares?: number;
  lastBuyPrice?: number | null;
  lastSellPrice?: number | null;
  collar?: { staticBandPct?: number; dynamicBandPct?: number };
  circuitBreaker?: { levels: Record<string, Partial<CbLevel>> };
  marketMakerQuotes?: MmQuoteStub[];
}

interface GatewayConfig {
  id: string;
  role: "TRADER" | "MARKET_MAKER" | "ADMIN";
  disconnectBehaviour: "CANCEL_ALL" | "CANCEL_QUOTES_ONLY" | "LEAVE_ALL";
  description?: string;
}

interface CbLevel {
  priceShiftPct: number;
  haltDurationNs: number | null;   // null = rest of day
  resumptionMode: "AUCTION" | "CONTINUOUS";
}
```

`packages/schema` exports Zod schemas that mirror every interface above,
plus the imported `defaults.json` constants, so `React Hook Form`'s
`zodResolver` and the backend's request validation use the exact same
rules.

## 14. API Reference

All endpoints are stateless with respect to persistence (no server-side
draft storage by default — see [§17](#17-state-management-and-persistence));
each call receives/returns a complete `EngineConfigDraft` (or a fragment for
targeted validation).

| Method & path | Body | Response | Purpose |
|---|---|---|---|
| `POST /api/config/import` | `{ yaml: string }` | `{ draft: EngineConfigDraft, unmapped: string[] }` | Parse uploaded YAML into a draft |
| `POST /api/config/validate` | `{ draft: EngineConfigDraft }` | `{ diagnostics: Diagnostic[] }` | Full server-side re-check (mirrors client-side rule engine; used as the authoritative gate before generate) |
| `POST /api/config/generate` | `{ draft: EngineConfigDraft, filename?: string }` | `{ yaml: string, filename: string }` | Serialize a draft to `engine_config.yaml` text |
| `POST /api/config/verify` (optional feature) | `{ yaml: string }` | `{ report: PmCverifierReport }` | Shells out to `pm-cverifier --format json` if available server-side; returns `503` with a clear message if the Python toolchain isn't installed on this deployment |
| `GET /api/defaults` | — | `{ defaults: DefaultsJson }` | Serves the generated `defaults.json` (see [§12.4](#124-keeping-cli-and-gui-in-sync)) so the frontend can bootstrap without bundling it if desired |
| `GET /api/healthz` | — | `{ ok: true }` | Liveness probe |

All endpoints validate request bodies against the shared Zod schemas before
doing any work and return `400` with a structured error list on failure.

## 15. Security Considerations

- **No shell string concatenation.** The `verify` endpoint (and any future
  subprocess integration) must invoke Python tools via `child_process.execFile`
  with an argument array (never `exec`/`shell: true`), and must not
  interpolate any user-controlled string into a shell command. Only a
  fixed, hardcoded argv (`["pm-cverifier", "--format", "json", tmpFilePath]`)
  is allowed; the YAML content itself is written to a securely-created
  temporary file, never passed as a CLI argument.
- **Upload limits.** YAML import is capped (e.g. 1 MB) and parsed with
  `js-yaml`'s safe (default) schema; reject before parsing if the file
  exceeds the limit or fails a quick structural sanity check, to avoid
  resource-exhaustion via deeply nested or excessively large YAML ("YAML
  bomb" style anchors/aliases — `js-yaml` disables custom tag execution by
  default, but explicitly disable anchors/alias expansion limits are still
  worth capping via `json: true`/size checks).
- **No server-side persistence of secrets by default.** Generated API
  gateway keys are plaintext credentials embedded in the output YAML. The
  server must not log request/response bodies containing `apiGateways[].credentials`,
  and drafts are not stored server-side unless an explicit, authenticated
  "save to account" feature is added later (out of scope for v1 — see
  [§21](#21-open-questions-and-future-work)). Client-side draft storage
  (`localStorage`/IndexedDB) is acceptable for a single-user local tool but
  must be called out in the UI ("this draft, including any generated API
  keys, is stored only in this browser").
- **One-time key display pattern.** Generated/explicit API keys are shown
  in full in the Review/Export preview (they must be, since they're part of
  the output file), but the Auxiliary Gateways → API Gateway credentials
  table masks keys by default with a "reveal" toggle per row, matching
  common secrets-UI conventions and reducing shoulder-surfing risk during
  classroom demos.
- **Path fields are opaque strings, not filesystem operations.** Fields like
  `stats_db`, `history_file`, `state_file` are free-text paths written into
  YAML for the *engine* process to use later — the GUI/backend never reads
  or writes to those paths itself, so path traversal isn't a GUI-side file
  I/O risk; still, strip control characters and reject values containing
  YAML-breaking sequences before embedding them.
- **CORS/auth for hosted deployments.** If deployed beyond a single local
  user (e.g., a shared classroom server), the backend must sit behind
  authentication and per-user rate limiting on `/api/config/verify` (the
  only endpoint that spawns a subprocess) to prevent abuse/DoS via repeated
  subprocess invocation.
- **Dependency hygiene.** Standard Node.js OWASP-Top-10-relevant practices:
  pin dependencies, run `npm audit`/`osv-scanner` in CI, keep Fastify and
  its plugins current, set standard security headers (Helmet) on the
  backend even though this is primarily an internal tool.

## 16. Accessibility Requirements

- All interactive controls (switches, dropdowns, sliders, table cells) must
  be keyboard-operable and screen-reader labeled — use Radix UI/shadcn
  primitives, which provide this out of the box; do not build custom
  unlabeled `div`-based controls.
- Color must never be the only signal: mandatory/optional/error/warning
  states each pair a color with an icon and/or text (asterisk, `!`, `✗`,
  "Default:" ghost text) so the app is usable by colorblind users and meets
  WCAG 2.1 AA contrast ratios.
- The Diagnostics Drawer and inline field errors must be announced via
  `aria-live="polite"` regions so screen reader users learn about new
  validation issues without losing focus.
- Full keyboard navigation between tabs (arrow keys within the nav list,
  `Tab`/`Shift+Tab` through form fields), and the command palette (`⌘K`)
  must be reachable and dismissible via keyboard alone.
- Target WCAG 2.1 AA as the baseline compliance bar for this app.

## 17. State Management and Persistence

- **Autosave draft** to `localStorage` (or IndexedDB, if draft size warrants
  it — combos/indices can grow large) on every change, debounced (~500ms),
  so a browser crash/refresh doesn't lose work. A "Restore previous draft?"
  prompt appears on next visit if an autosaved draft exists and differs from
  a blank state.
- **Explicit "Save" in the top bar** is a lightweight affordance that just
  forces an immediate autosave flush and shows a confirmation toast — v1 has
  no server-side accounts/multi-device sync; that's future work.
- **New draft** requires confirmation if the current draft has unsaved
  meaningful content (more than just defaults).
- **Undo/redo** is not required for v1 but the Zustand store should be
  structured (e.g. via a command/patch log) so it can be added later without
  a rewrite — noted as a forward-compatibility consideration, not a v1
  requirement.

## 18. Testing Strategy

| Layer | Tooling | Coverage focus |
|---|---|---|
| Unit — schema & diagnostics | Vitest | Every Zod schema, every rule in `packages/diagnostics` (table-driven tests mirroring [§8](#8-cross-field-validation-and-consistency-engine)) |
| Unit — yaml-codec | Vitest | Round-trip: draft → YAML → draft equality for every field in [Section 7](#7-field-catalogue); unmapped-YAML preservation |
| Component | React Testing Library | Persona visibility (a field tagged `E` never renders in `BEGINNER`/`INTERMEDIATE` DOM), mandatory/optional visual states, cross-field highlight behavior |
| E2E | Playwright | Full happy paths: (1) new config from scratch as Beginner → export; (2) import a sample `engine_config.yaml` → edit → export; (3) trigger each Section 8 rule and confirm it blocks/warns appropriately; (4) persona switch preserves data |
| Integration (CI, cross-language) | Node test invoking `generate` endpoint, then shelling to Python `load_engine_config()` | Guarantees GUI output is always parser-valid, matching the bar set by `pm-config-gen`'s own test suite |
| Accessibility | `axe-core` via Playwright or `jest-axe` | No critical/serious violations on each tab in each persona |

## 19. Implementation Plan

1. **Foundation** — monorepo scaffold, `packages/schema` with Zod types +
   generated `defaults.json`, `packages/yaml-codec` round-trip for the
   mandatory Basics section only, blank React app shell with tab navigation
   and persona switcher (no real fields yet). *Verify: unit tests green,
   empty app renders all tabs per persona.*
2. **Basics + Review + Export** — Symbols, Gateways, YAML preview, download.
   *Verify: can produce the CLI's "minimal two-trader exchange" example
   ([EduMatcher-config-generator.md §10.2](EduMatcher-config-generator.md#102-minimal-two-trader-exchange)) and it validates via `load_engine_config()`.*
3. **Sessions, Risk & Collars, Circuit Breakers** — including the new
   schedule-ordering and CB-ladder editors. *Verify: reproduce
   [EduMatcher-config-generator.md §10.3](EduMatcher-config-generator.md#103-three-symbol-classroom-session-with-schedule).*
4. **Market Maker + Symbols master-detail tab** — mid-range seeding,
   per-symbol overrides. *Verify: reproduce the per-symbol override example
   in [EduMatcher-config-generator.md §10.1](EduMatcher-config-generator.md#101-per-symbol-override-example).*
5. **Import pipeline + unmapped-YAML passthrough + raw YAML editor.**
   *Verify: import each example config used in steps 2–4, edit one field,
   re-export, confirm no data loss.*
6. **Indices + Auxiliary Gateways (Post-Trade, Market-Data).**
7. **Expert tier: Combos, BALF, API Gateway (incl. multi-instance +
   credentials), deterministic seeding, comment-default-fields toggle.**
8. **Cross-validation completeness pass** — implement every rule in
   [§8.2](#82-new-rules-required-by-the-fuller-gui-schema-not-present-in-the-current-clis-warningspy),
   full Playwright rule-trigger suite.
9. **Polish** — guided help content, onboarding tour, accessibility audit
   fixes, `pm-cverifier` optional integration.

## 20. Recommended Enhancements Beyond the Stated Requirements

The following were not explicitly requested but were identified as
valuable based on the field inventory and common failure modes observed in
`EduMatcher-config-generator.md`'s own warning catalogue. All six have now
been actioned — three landed directly in `pm-config-gen` (so the CLI and
GUI share the same corrected behaviour instead of drifting), and three are
GUI-only concerns that remain fully specified in this document.

- **Cross-gateway port collision detection** — ✅ **Implemented in
  `pm-config-gen`.** `warnings.py` now computes every enabled network
  endpoint (post-trade, market-data, BALF, each API gateway instance) and
  emits a `[WARN] Port collision: ...` diagnostic when two resolve to the
  same `bind_address:port` (treating `0.0.0.0`/`::` as matching any
  address). See `_network_endpoints`/`_port_collision_warnings` in
  [warnings.py](../src/edumatcher/config_gen/warnings.py) and the baseline
  rule table in [§8.1](#81-rule-catalogue-baseline-inherited-from-pm-config-genwarningspy).
  The GUI's `diagnostics` package should mirror this exact rule so CLI and
  GUI users see identical warnings for identical inputs.
- **Schedule chronological-order validation** — ✅ **Implemented in
  `pm-config-gen`.** `cli.py`'s `_validate_schedule_order` now parses and
  bounds-checks all five `HH:MM` schedule flags and raises a fatal
  `ValueError` (`Schedule times must be strictly increasing: ...`) if
  `pre_open < opening_auction < continuous < closing_auction < closing_end`
  is violated, or if any value isn't a valid `HH:MM` time. This is a hard
  error (exit code 2), unlike the advisory port-collision warning, because
  an out-of-order schedule can never produce a usable session sequence.
  The GUI's time pickers ([§7.2](#72-sessions--schedule)) must enforce the
  same ordering live, not just at export time.
- **Silent auto-uppercasing** of symbol/gateway IDs — already the
  behaviour of `pm-config-gen` today (`parse_gateway_spec` and the
  `--symbols` parsing both `.upper()` the value before use); the CLI also
  keeps its post-hoc `[INFO]` note so terminal users aren't surprised by a
  silent rewrite. The GUI should go one step further per
  [§7.1](#71-basics--symbols--gateways-mandatory-section): transform on
  blur with no separate warning needed, since the change is visible
  immediately in the field itself.
- **Tick-aware decimal price entry** for combo leg prices/stops — ✅
  **Implemented in `pm-config-gen`.** `--combo` leg `PRICE`/`STOP` values
  may now be given as a decimal display price (e.g. `209.50`), converted
  to the integer tick representation using the leg symbol's effective
  `tick_decimals` (global `--tick-decimals` or a per-symbol
  `--symbol-opts tick_decimals=` override). Plain integers (e.g. `20950`)
  keep meaning a raw tick count exactly as before, so every existing
  invocation keeps working unchanged — see `_parse_leg_price` in
  [cli.py](../src/edumatcher/config_gen/cli.py). The GUI's combo leg editor
  ([§7.8](#78-combos-seed-orders)) should always display/accept decimal
  prices and can rely on the same conversion rule being authoritative.
- **One-time-reveal masking for generated API keys** — GUI-only; already
  fully specified in [§7.9.4](#794-api-gateway-expert-only) and
  [§15](#15-security-considerations). No `pm-config-gen` change applies
  since the CLI has no interactive display surface to mask.
- **Persona nudges** rather than silent field hiding — GUI-only; already
  fully specified in [§10](#10-guided-help-system). No `pm-config-gen`
  change applies.
- **Golden-file CI integration** piping generated YAML through the real
  Python `load_engine_config()` — partially pre-existing:
  `pm-config-gen` already self-validates at generation time via
  `_validate_generated_when_possible` in `cli.py`, and its own test suite
  (`tests/test_config_gen_integration.py`) round-trips example configs
  through `load_engine_config()`. What remains GUI-side work is wiring the
  equivalent CI job described in [§12.4](#124-keeping-cli-and-gui-in-sync)
  and [§18](#18-testing-strategy) once the GUI's `generate` endpoint
  exists; this is tracked, not yet actionable until implementation begins.

## 21. Open Questions and Future Work

- Should generated configs be saveable server-side against a user account
  (multi-device continuity), and if so, what auth provider fits the
  classroom deployment model (course LMS SSO? simple email/password?).
- Should the GUI support multiple simultaneous drafts/tabs (e.g., one per
  course section) with a draft picker, or is one active draft per browser
  sufficient for v1?
- Is a config **diff view** (imported vs. current edits, or draft A vs.
  draft B) valuable enough for instructors auditing student submissions to
  prioritize in a v2?
- Should `pm-cverifier` integration ([§11](#11-review-diagnostics-and-export))
  be a hard dependency (bundle a Python runtime with the server, e.g. via a
  container image) rather than an optional best-effort feature, to make the
  "authoritative check" always available?
- Internationalization is out of scope for v1 — flag if the target audience
  needs non-English UI text.

## 22. Acceptance Checklist

- [ ] Every field in [Section 7](#7-field-catalogue) has a working editor,
      correct default, correct persona visibility, and correct
      mandatory/optional visual treatment.
- [ ] Every rule in [Section 8](#8-cross-field-validation-and-consistency-engine)
      is implemented, unit-tested, and reachable via the Playwright E2E
      suite.
- [ ] Import → edit → export round-trips without data loss for every
      example config referenced in
      [EduMatcher-config-generator.md §10](EduMatcher-config-generator.md#10-example-invocations).
- [ ] All three personas render distinct, correct field sets from the same
      underlying draft, and switching between them never discards data.
- [ ] The Review tab's Download action is blocked while any error-severity
      diagnostic is outstanding, and requires acknowledgement for
      outstanding warnings.
- [ ] Every generated config passes `load_engine_config()` in the golden-file
      CI job.
- [ ] `axe-core` reports no critical/serious accessibility violations on any
      tab in any persona.
- [ ] The `verify` endpoint uses `execFile` with a fixed argv and a
      temp-file-based YAML payload — no shell string interpolation.
- [ ] `packages/schema/generated/defaults.json` is regenerated and checked
      by CI whenever `defaults.py` changes.
