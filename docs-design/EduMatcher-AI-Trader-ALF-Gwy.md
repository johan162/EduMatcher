Version: 0.1.0

Date: 2026-08-11

Status: Design and Research Proposal


# EduMatcher — Routing `pm-ai-trader` through the ALF gateway

---

## Table of Contents

1. [Motivation](#1-motivation)
2. [Current state: how the AI trader connects today](#2-current-state-how-the-ai-trader-connects-today)
3. [The correction: the AI trader is not uniquely wrong](#3-the-correction-the-ai-trader-is-not-uniquely-wrong)
4. [What routing through ALF buys](#4-what-routing-through-alf-buys)
5. [What an ALF client must speak, and what already exists](#5-what-an-alf-client-must-speak-and-what-already-exists)
6. [Market data: the second connection](#6-market-data-the-second-connection)
7. [Scope of the change](#7-scope-of-the-change)
8. [Open decisions](#8-open-decisions)
9. [Recommendation and phased plan](#9-recommendation-and-phased-plan)
10. [Relationship to message-generator phase 6.3](#10-relationship-to-message-generator-phase-63)


## 1. Motivation

`pm-ai-trader` is a synthetic order-flow generator: it prices around
top-of-book and submits `LIMIT DAY` orders to drive activity for demos, load
tests and integration runs. Today it sends those orders **straight to the
matching engine's PULL socket**, the same wire the engine's own trusted
processes use. The proposal is to have it instead connect **through
`pm-alf-gwy`**, the ALF TCP order-entry gateway, exactly as an external trading
client would.

The argument for it is threefold:

1. **Standard order tracking.** An order that enters through a gateway carries
   that gateway's identity and flows through the standard acknowledgement and
   drop-copy path, so it is tracked in the same format as every real order.
2. **Inherited checks, now and future.** The gateway is where authentication,
   rate limiting, symbol/reference-data gating, risk controls and the
   display→ticks price conversion live. A client behind it inherits all of
   them automatically, including checks added later.
3. **One class of trader.** The AI trader would exercise the full production
   path — gateway included — rather than a privileged shortcut, which is both
   more realistic and a better integration test of the gateway itself.

The design doc for the bot (`EduMatcher-AI-trading-bot.md`, §1) already
*describes* it as one that "connects as a normal ALF gateway." That phrasing is
aspirational: the implementation registers a `gateway_id` **with** the engine
and speaks the engine's native ZMQ protocol directly — it *is* a gateway from
the engine's point of view, not a *client of* one. This proposal closes the gap
between that sentence and the wire.


## 2. Current state: how the AI trader connects today

`ai_trader/main.py` opens two ZeroMQ sockets against the engine directly:

| Socket | Address | Purpose |
|---|---|---|
| `PUSH` | `ENGINE_PULL_ADDR` (`tcp://…:5555`) | sends `gateway_connect`, `symbols_request`, `order.new` |
| `SUB` | `ENGINE_PUB_ADDR` | receives `book` snapshots, `trade.executed`, `order.ack.{id}` |

Its handshake is a **direct engine registration**: it publishes
`make_gateway_connect_msg(gateway_id)` and `make_symbols_request_msg(gateway_id)`
to the engine, then submits orders with `make_order_new_msg(order.to_dict())`.
After the phase-6.3 fix (§10) it builds a complete `Order` in **integer ticks**
and tags provenance in `client_tag`.

The engine therefore treats the AI trader as a first-class gateway: no auth, no
rate limit, no reference-data gate, no risk envelope — the very checks the real
gateways enforce.


## 3. The correction: the AI trader is not uniquely wrong

A grep for `make_pusher(ENGINE_PULL_ADDR)` is clarifying. The processes that
connect **straight to the engine** are:

`pm-ai-trader`, `pm-mm-bot`, `pm-alf-console`, `pm-scheduler`, `pm-stats`,
`pm-viewer`, and the `pm-command` CLI.

These are the **trusted internal processes**. The **gateways** —
`pm-alf-gwy` (ALF text/TCP), `pm-balf-gwy` (BALF binary), `pm-api-gwy` (REST) —
are the boundary for **external** clients speaking a different protocol, and
they are where the checks live.

So moving the AI trader behind ALF does **not** correct a lone anomaly; it moves
one process from the internal class to the external-client class. In particular
it makes the AI trader **inconsistent with `pm-mm-bot`**, which is also a bot and
also connects directly. That is a deliberate positioning — "the AI trader is a
*simulated external trader*, the market-maker is *internal infrastructure*" — and
should be chosen on purpose rather than by omission (see §8).


## 4. What routing through ALF buys

Concretely, once behind `pm-alf-gwy` the AI trader inherits, at zero further
cost, everything the gateway already does for real clients:

* **Authentication** — a LOGON handshake with a configured client identity,
  rather than an unauthenticated `gateway_connect`.
* **Rate limiting** — the gateway's token-bucket per session (a load bot is
  exactly the traffic this guards against, so this is a feature, not a
  hindrance — the bot's rate becomes a *tested* path).
* **Reference-data gating** — orders for unknown symbols are rejected
  (`SYMBOLS_NOT_READY` / unknown-symbol NACK) instead of reaching the book.
* **Risk controls and kill-switch** — whatever envelope the gateway enforces.
* **Price-unit conversion** — the gateway converts **display money → ticks**,
  which is the AI trader's *natural* unit; see §10.
* **Standard acknowledgement path** — ACK/NACK/FILL come back over the ALF
  session in the same shape a real client sees, so the bot's own success/reject
  accounting exercises the real reply format.

Future checks added to the gateway are inherited without touching the bot.


## 5. What an ALF client must speak, and what already exists

The ALF protocol is a simple pipe-delimited text line over TCP. Order entry is,
for example:

```
NEW|SYM=AAPL|SIDE=BUY|TYPE=LIMIT|QTY=10|PRICE=100.50|TIF=DAY
```

with `PRICE` in **display money** (the gateway converts). A client's lifecycle
is: open TCP, `LOGON` with its id, send `NEW`/`AMEND`/`CANCEL` lines, and read
`ACK`/`NACK`/`FILL`/event lines on the same socket.

**There is a working reference, but not a reusable library.**
`docs/examples/alf/python/alf_client.py` is an interactive external client, and
it leans on `docs/examples/alf/python/alf_parser.py`, which contains an
`AlfSession` (TCP + framing + parsing, no `edumatcher` import). That is the
shape to reuse — but it lives under `docs/examples/`, so a `src/` process should
**not** import it. The clean move is to add a small, tested
`edumatcher.alf_client.AlfClient` in `src/`, modelled on `AlfSession`: LOGON,
line construction for `NEW`, and response parsing. That library is useful beyond
the AI trader (integration tests, tools, a Python counterpart to the C example).


## 6. Market data: the second connection

Order entry is only half of the wire. The AI trader **prices** from
`best_bid`/`best_ask`/`last`, which it gets today from the engine's PUB feed
(`book` snapshots and `trade.executed`). ALF is an **order-entry** gateway; it
does not carry a market-data feed.

Two options:

* **Minimal** — keep the engine-PUB subscription for market data unchanged, and
  route only the *order* path through ALF. Half the bot is still "internal," but
  the order path — the one that matters for tracking and checks — is realistic.
* **Full realism** — take market data from `pm-md-gateway` / the CALF feed
  (there is already a reusable `edumatcher.calf_client`), so the bot is a fully
  external trader on both wires. Larger, and it means the bot no longer touches
  the engine at all.

The minimal option is recommended first; the CALF market-data switch is a clean
follow-up because `calf_client` already exists.


## 7. Scope of the change

Neither trivial nor large — a focused piece of work:

1. **New `src/edumatcher/alf_client/`** — a small `AlfClient` (TCP socket, LOGON
   handshake, `NEW` line construction from an `Order`-like input in display
   money, response parsing), with unit tests. Model on
   `docs/examples/alf/python/alf_parser.AlfSession`.
2. **Rewire `ai_trader/main.py`** — replace the `PUSH`-to-engine order path and
   the `gateway_connect`/`symbols_request` handshake with an `AlfClient` LOGON +
   `NEW`; keep the `SUB` market-data path (minimal option, §6). Drop the
   `to_ticks(...)` conversion (§10). Handle NACK and reconnect via the ALF
   session rather than the engine's ack topic.
3. **Configuration** — an ALF gateway host/port for the bot, replacing the
   engine PULL address for order entry.
4. **Tests** — the existing ai_trader tests mock `make_order_new_msg` and inspect
   the order payload; they would instead drive/inspect the `AlfClient` (a fake
   ALF endpoint). The `_make_order_payload` seam stays useful — it can produce
   the display-money order the client sends.

No change to the engine, the gateways, or the message generator.


## 8. Open decisions

1. **Does `pm-mm-bot` follow?** If "bots are simulated external traders" is the
   principle, the market-maker should eventually LOGON to a gateway too (it
   would use the quote path, not `NEW`). If instead the market-maker is
   "internal infrastructure," the two bots differ on purpose. Decide the
   principle; it governs both.
2. **Market data source (§6)** — engine-PUB now, `md_gateway`/CALF later, or
   CALF from the start.
3. **One client identity or many?** `pm-ai-swarm` launches many bots; each would
   LOGON as its own configured ALF client, which the gateway must be provisioned
   for (allowlist/credentials). This interacts with the gateway's client-config
   surface.


## 9. Recommendation and phased plan

Worth doing — for a simulation/load bot, realism and inherited checks are
exactly the point, and the pricing code gets *simpler*, not more complex (§10).

* **Phase 1 — reusable client.** Add `edumatcher.alf_client.AlfClient` in `src/`
  with its own tests, independent of the AI trader. Immediately useful for
  integration tests and as the Python counterpart to the C example client.
* **Phase 2 — rewire the AI trader.** Route orders through `AlfClient`, drop
  `to_ticks`, keep engine-PUB market data, update tests and config. Provision
  the bot's ALF identity (single bot first, then swarm).
* **Phase 3 (optional) — full external.** Move market data to `md_gateway`/CALF
  so the bot no longer touches the engine directly, and decide the `mm_bot`
  question (§8.1).


## 10. Relationship to message-generator phase 6.3

Phase 6.3 adopted `order.new` through its generated builder, which forced the
AI trader to build a **valid order in integer ticks** (`Order.create` +
`to_ticks`) and moved its `run_id`/`strategy` tags into the declared
`client_tag`. That fix is what makes the current direct-to-engine path correct.

This proposal would **simplify** that path rather than undo it: behind ALF the
bot submits **display-money** prices — its natural unit, the one its pricer
already computes in — and the gateway performs the `to_ticks` conversion. So the
tick conversion added in 6.3 moves out of the bot and into the gateway where
every other client's does, and `client_tag` provenance still rides through the
gateway to the engine unchanged. The 6.3 fix is the safe stepping stone; this is
the shape it points at.
