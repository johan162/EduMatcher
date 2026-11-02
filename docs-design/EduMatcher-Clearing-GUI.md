# EduMatcher — Clearing GUI, Margin Accounts and Client Accounts: Design Draft

Status: **DRAFT / investigation (2026-11-02)**. Nothing here is implemented.
Open decisions are marked **[Dn]** and collected in §9.

## 1. What we have today

| Piece | What it does | Gap for a clearing GUI |
|---|---|---|
| `pm-clearing` (`clearing/main.py`, `ledger.py`, `store.py`) | Subscribes to `trade.executed`, keeps `(gateway_id, symbol)` positions with VWAP `avg_cost`, cumulative `realized_pnl`, `unrealized_pnl`; writes `clearing.db` every 5 s / 100 trades; `position_close_snapshot` at each close | No margin, no equity, no intraday history (only the latest position row and daily rows) |
| `pm-eod` (`eod/`, `eod.db`, `roster.yaml`) | Daily mark-to-market settlement through a central pool; balance = `opening_balance` + Σ day amounts; statements per gateway | Effectively *variation margin* settlement, but no *requirement* side: a participant with $100 can hold any position (the §19.3 objection in `EduMatcher-Clearing.md`) |
| `pm-api-gwy` | REST/WS backend of `trader-gui`; already reads `clearing.db` read-only for `realized_pnl_session/mtd/ytd` on `GET /positions` | No clearing-wide endpoints |
| `trader-gui` | React/TS SPA, Vite, Zustand, TanStack Query, recharts/lightweight-charts, `serve.ts` static server proxying `/api` to `pm-api-gwy` | — template for the new app |
| Engine | Participant == gateway id (`participants[].id`); per-symbol `order_limits` only | No credit/margin check; no account concept anywhere |
| `EduMatcher-Clearing.md` §19 | **Proposed, not built**: full DVP cash+securities accounts, participant→many gateways, obligations | Superseded in practice by `pm-eod`'s P&L settlement; explicitly excludes margin **[D1]** |

## 2. Goals

1. A **clearing GUI** (`clearing-gui`, mirroring `trader-gui`) showing, per
   participant, a **margin account**: equity, requirement, excess/deficit,
   status, positions, and **history with graphs**.
2. **Client accounts**: a participant may act as a broker for retail clients
   who have no exchange access. Each order carries an **account id**;
   clearing tracks positions, P&L and margin **per account**.
3. Accounts are **opt-in per participant**.

Non-goals (for now): real collateral types/haircuts, interest, SPAN/VaR
models, default waterfall, multiple currencies, participant→many-gateway
grouping (§19.4) — participant stays == gateway id.

## 3. Terminology

- **Participant** — a gateway id in `participants[]` (unchanged).
- **Client account** (just *account*) — a sub-ledger under a participant,
  identified by a short string carried on orders. `""` = the participant's own
  **house** account.
- **Margin account** — the collateral view (equity vs requirement) kept by
  clearing for each participant *and* each client account.
- Naming collision: `eod.db.eod_settlement.account` today means "gateway id
  or EXCHANGE". It should become `gateway_id` + `account` when E-accounts land.

## 4. Margin model (recommended)

Keep `pm-eod`'s daily mark-to-market settlement and add a **requirement**
side — i.e. the futures-style model: variation margin moves cash daily,
initial/maintenance margin limits how large a position the equity supports.
It closes the §19.3 hole without building full DVP **[D1]**.

Per margin account (display currency, tick-normalised per symbol):

```
equity        = opening_balance + Σ_symbols (realized_pnl + unrealized_pnl)
gross_mv      = Σ_symbols |net_qty| × mark × multiplier
maint_req     = Σ_symbols |net_qty| × mark × maint_pct(symbol, side)
initial_req   = Σ_symbols |net_qty| × mark × initial_pct(symbol, side)
excess        = equity − maint_req
utilisation   = maint_req / equity
buying_power  = max(0, equity − initial_req) / initial_pct(default)
status        = OK | WARNING (utilisation ≥ warning_pct) | MARGIN_CALL (excess < 0)
```

`equity` is computed from `clearing.db` alone (cumulative realized +
unrealized since genesis equals opening + Σ settled day amounts + today's
change), so the GUI does not depend on `pm-eod` having run. `pm-eod`'s
settled balance is shown alongside as "settled cash" and the difference as
"unsettled P&L" — a teaching point in itself.

Configuration (new `clearing.margin` section in `engine_config.yaml`, so
`pm-config-gen`, `pm-cverifier` and `config-gui` see it):

```yaml
clearing:
  margin:
    initial_pct: 50
    maintenance_pct: 25
    short_maintenance_pct: 30
    warning_pct: 80
    snapshot_interval_sec: 60
    symbols:
      TSLA: { initial_pct: 60, maintenance_pct: 40 }
```

Opening balances stay in `roster.yaml` (already used by `pm-eod`).

**Enforcement [D2].** Recommended phase 1 is *monitor only*: status in the
GUI, a `MARGIN_CALL` event row, a line on the EOD statement. Pre-trade
enforcement would require the engine (or the gateways) to know clearing
state — a cross-process dependency on the hot path — and is left as an
optional later WP (e.g. clearing triggers `risk.kill_switch_gateway` and an
"opening orders blocked" flag).

## 5. Client accounts

### 5.1 Configuration [D3]

```yaml
participants:
- id: BROKER01
  role: TRADER
  disconnect_behaviour: CANCEL_ALL
  accounts:
    enabled: true
    house_trading: true        # may also trade with no account [D5]
    ids: [C1001, C1002, C1003]
```

`roster.yaml` gains per-account name and `opening_balance` under the
participant. Recommended: the **engine config owns the list** (the engine
has to validate it); the roster only annotates it.

### 5.2 Order semantics

- New optional field `account` on `order.new` (string, `max_len: 16`,
  `^[A-Z0-9_-]+$`).
- Engine validation, new reject codes:
  - accounts disabled and `account` present → `ACCOUNT_NOT_ALLOWED`
  - accounts enabled, `account` absent and `house_trading: false` → `ACCOUNT_REQUIRED`
  - not in `ids` → `UNKNOWN_ACCOUNT`
- `account` is **immutable on amend**; cancel needs no account.
- Echoed on `order.ack / fill / cancelled / expired` and drop copy (same
  path as `client_tag`).
- Combo/OCO: legs inherit the parent's account. MM quotes: house only.
- `trade.executed` grows `buy_account` / `sell_account` (nullable). Like the
  gateway ids, they must be **stripped from the public CALF projection**
  (`project_trade_executed_calf`).
- **Self-match prevention [D6]:** today keyed on gateway. A cross between two
  clients of the same broker is a legitimate trade; a match within one
  account is a wash. Recommended: SMP keyed on `(gateway_id, account)`.

### 5.3 Ingress protocols that need the field

| Path | Change | Effort |
|---|---|---|
| REST `POST /orders` (`pm-api-gwy`) | JSON field + schema | S |
| ALF text (`alf_gwy`, `alf_console`) | optional token | S |
| BALF binary (`balf_gwy/codec.py`, NEW_ORDER 0x10, fixed 60-byte frame) | new frame size, codec + spec + size tests | M |
| Internal producers (`ai_trader`, `mm_bot`, `market_sim`) | none required; optional "broker" persona later | — |

### 5.4 Margin at two levels [D4]

Each client account is its own margin account. The participant's
requirement at the CCP is recommended to be **gross** — the sum of its
accounts' requirements (plus house) — rather than **omnibus net**, where
client A long 100 and client B short 100 net to zero margin while the broker
still carries both risks. The GUI can show the "net would have been" figure
as a teaching aid.

## 6. Clearing data model changes

No migration (pre-1.0 policy): a new schema means a fresh `clearing.db`.

- `trade_events`: `+ buy_account TEXT NOT NULL DEFAULT ''`, `+ sell_account …`
- `gateway_symbol_positions`, `gateway_daily_summary`,
  `position_close_snapshot`: key becomes `(…, gateway_id, account, symbol)`;
  the existing `gateway_pnl_totals` view sums over `account`.
- `Ledger._positions` key → `(gateway_id, account, symbol)`.
- New, the history behind the graphs:

```sql
CREATE TABLE margin_snapshots (
  ts_ns          INTEGER NOT NULL,
  trade_date     TEXT    NOT NULL,
  gateway_id     TEXT    NOT NULL,
  account        TEXT    NOT NULL DEFAULT '',   -- '' = house; '*' = participant total
  equity         REAL    NOT NULL,
  realized_pnl   REAL    NOT NULL,
  unrealized_pnl REAL    NOT NULL,
  gross_mv       REAL    NOT NULL,
  maint_req      REAL    NOT NULL,
  initial_req    REAL    NOT NULL,
  status         TEXT    NOT NULL,
  PRIMARY KEY (gateway_id, account, ts_ns)
);
CREATE TABLE margin_events (            -- status transitions only
  ts_ns INTEGER NOT NULL, trade_date TEXT NOT NULL, gateway_id TEXT NOT NULL,
  account TEXT NOT NULL DEFAULT '', old_status TEXT, new_status TEXT NOT NULL,
  equity REAL NOT NULL, maint_req REAL NOT NULL
);
```

Sampled by `pm-clearing` every `snapshot_interval_sec` and at every close
(≈ 500 rows/day per margin account at 60 s; intraday rows can be thinned to
one per day after `--retention-days`). Daily graphs read
`position_close_snapshot` + the close-time `margin_snapshots` row.

`pm-eod`: settle and print statements per `(gateway_id, account)`; a broker
receives one statement with a section per client.

## 7. Backend: `pm-api-gwy` clearing routes

Mirrors how `trader-gui` uses `pm-api-gwy`: a new `api_gateways.clearing`
instance (e.g. port 8082) and `routers/clearing.py`, **read-only** over
`clearing.db` (+ `eod.db`). Visibility: ADMIN sees everything; TRADER/MM see
their own participant and its accounts (a broker sees its clients) **[D7]**.

```
GET /clearing/summary                          exchange totals, invariant check (Σ VM = 0), counts by status
GET /clearing/participants                     one row per participant: equity, req, excess, utilisation, status
GET /clearing/participants/{gw}                detail + accounts list
GET /clearing/positions?gateway=&account=&symbol=
GET /clearing/margin/history?gateway=&account=&from=&to=&resolution=intraday|daily
GET /clearing/pnl/daily?gateway=&account=&from=&to=
GET /clearing/trades?gateway=&account=&date=
GET /clearing/symbols/{symbol}/open-interest   long/short per participant (concentration)
GET /clearing/margin-events?status=&date=
GET /clearing/statements/{date}/{gw}           pm-eod output
```

Live refresh: poll every 5 s (= the clearing flush interval). A
`clearing.*` bus message + WS push is a later optimisation, not needed for v1.

## 8. `clearing-gui`

Same stack and layout as `trader-gui` (`apps/web`, `apps/serve`,
Dockerfile, Makefile, `make up`), ports **8096** (container) / **8196** (dev).

Screens:

1. **Overview (CCP view)** — participants table: equity, maint req, excess,
   utilisation bar, status badge, intraday equity sparkline; tiles for total
   open interest, Σ equity, # in WARNING / MARGIN_CALL; the zero-sum check.
2. **Participant** — margin tiles (equity, settled cash, unsettled P&L,
   requirement, excess, buying power); positions table; charts: equity vs
   maintenance requirement (intraday + daily), cumulative realized/unrealized
   P&L, gross exposure by symbol; trades; statements; **Accounts** tab when
   enabled.
3. **Account** — the same as Participant, scoped to one client account; on
   the participant page, a gross-vs-net requirement comparison.
4. **Symbol** — open interest and long/short concentration by participant.
5. **Margin events** — status transitions, filterable; deep links to 2/3.

## 9. Open decisions

| # | Question | Recommendation |
|---|---|---|
| D1 | Settlement model: keep `pm-eod` mark-to-market + margin requirement, or build §19 full DVP cash/securities | Keep MTM + add requirement; mark §19 superseded |
| D2 | Margin enforcement | Monitor only first; enforcement as a later optional WP |
| D3 | Account registry: pre-registered list in engine config, or free-form ids | Pre-registered (engine can reject, GUI can show idle clients) |
| D4 | Participant requirement over accounts: gross or omnibus net | Gross |
| D5 | May an accounts-enabled participant also trade house (no account)? | Yes, via `house_trading` flag, default true |
| D6 | SMP scope with accounts | `(gateway_id, account)` |
| D7 | GUI audience: clearing operator only, or also each participant for itself | Both, enforced by API key role |

## 10. Work packages (proposed order)

Margin first: it gives the GUI value without touching the engine or any
wire protocol; accounts then ride on an already-working view.

| WP | Content | Verify |
|---|---|---|
| CG1 | Margin config + computation + `margin_snapshots`/`margin_events` in `pm-clearing`; `pm-clearing-cli margin` | unit tests for the formulas; Σ VM = 0 property test |
| CG2 | `routers/clearing.py` + `api_gateways.clearing` | API tests incl. role scoping |
| CG3 | `clearing-gui` skeleton, Overview, Participant, charts | vitest; run against a live sim |
| CA1 | `account` in spec, `Order`, engine validation, config (`participants[].accounts`), cverifier, config-gen | engine tests per reject code |
| CA2 | Echo on lifecycle + drop copy; `trade.executed` buy/sell_account; CALF strip; REST/ALF/BALF ingress | protocol round-trip tests; BALF frame-size test |
| CA3 | Clearing keyed by account; `pm-eod` per account | ledger tests with mixed house/client fills |
| CA4 | GUI Accounts tab + Account page + gross-vs-net view | vitest |
| CA5 | Optional: `ai_trader` "broker" persona trading for N clients | sim run |
| CE1 | Optional: enforcement (D2) | — |
