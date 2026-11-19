# Deploying the Trading GUI (`pm-trading-ui`)

!!! note "Learning objectives"
    After reading this page you will understand:

    - Which services the Trading GUI needs
    - How to start it with the whole stack, on its own in a container, as a
      development server, or as a production build without a container
    - Which build-time and server settings configure it

The **Trading GUI** is the browser trading terminal for traders, market makers
and the ADMIN. How to use it is described in the Participant Guide chapter
[Trading GUI](../../participant-guide/part-6-front-ends/020-trading-platform-gui.md); this chapter covers running
and configuring it. Its source code lives in `web-apps/trader-gui/` and its full
specification is `docs-design/EduMatcher-Trading-GUI.md`; it is served on port
**8093**.

## Prerequisites

| Requirement | Notes |
|---|---|
| **`pm-api-gwy`** ([API Gateway](../../operator-guide/part-5-gateways/050-api-gateway.md)) | Required — this is the only upstream service the Trading GUI talks to. It must be reachable on `localhost:8080` (or wherever `VITE_API_BASE`/`API_PROXY_TARGET` points). |
| **`pm-engine`** | Required indirectly — `pm-api-gwy` authenticates your gateway against it at login, so a running gateway with a stopped engine still fails login. |
| An API key bound to a `TRADER`, `MARKET_MAKER`, or `ADMIN` gateway identity | Defined under `api_gateways.<name>.credentials` in `engine_config.yaml`. See [Logging in](../../participant-guide/part-6-front-ends/020-trading-platform-gui.md#logging-in) below. |
| **Podman ≥ 4** or **Docker ≥ 24** with a Compose plugin | Needed for the container run path. |
| **Node.js ≥ 22 (LTS)** and npm | Needed only for local development or serving the production bundle without a container. |
| `pm-stats` (optional) | Powers Trade History, the daily rollup, the chart's history and the Order Detail timeline. Without it those degrade to an explanatory notice; live trading is unaffected. |
| `pm-audit` (optional) | Powers the ADMIN cross-gateway order drill-down only. |

## Running the application

There are three ways to run it, and which one you want depends on what you are
doing. If you are not sure, use the first.

| | What it is | Open | Use it when |
|---|---|---|---|
| **The whole stack** | The exchange and the six web applications started by default (`terminal-gui`, `log-gui`, `trader-gui`, `book-gui`, `dash-gui`, `clearing-gui`) — a seventh, `config-gui`, is opt-in (`CONFIG_GUI=1`) since it talks to no exchange — together as containers | <http://localhost:8093> | You want a working system. This is almost always the right answer |
| **This app alone, in a container** | Just the Trading GUI, pointed at an exchange you started some other way | <http://localhost:8093> | The exchange runs elsewhere — another machine, a VM, a host install |
| **Local dev server** | Vite with hot reload, on your machine | <http://localhost:8193> | You are changing this application's code |

### The whole stack (recommended)

This starts the exchange *and* the Trading GUI together, on one private
network, with no addresses to configure:

**A released install:**

```bash
cd ~/.edumatcher
./edumatcher.sh start
```

**From a source checkout:**

```bash
cd deployment/docker
make up-all
```

Then open **<http://localhost:8093>**. The exchange's REST API is reachable at
`edumatcher:8080` from inside the network, which the compose file sets for you
— there is nothing to point anywhere.

The other applications come up at the same time: the trader terminal on
[8090](../../participant-guide/part-6-front-ends/010-trading-info-terminal.md), the log console on
[8091](../../operator-guide/part-6-observe-and-recover/050-log-console.md), the order book viewer on 8094, the
[operator dashboard](../../operator-guide/part-6-observe-and-recover/070-operator-dashboard.md) on 8095 and the
[Clearing GUI](../../participant-guide/part-6-front-ends/040-clearing-gui.md) on 8096.

Everyday commands, from `deployment/docker` (or with `./edumatcher.sh` in a
released install):

```bash
make status      # is every exchange process up?
make logs        # the backend's own output
make down-all    # stop everything
```

Full detail — including how to change which configuration the exchange trades
— is in [Installation](../../operator-guide/part-1-install-and-deploy/010-installation.md).

### This app alone, in a container

Use this when the exchange is already running somewhere else. From
`web-apps/trader-gui/`:

```bash
make up
```

Then open **<http://localhost:8093>**.

This path has one thing to configure, because the application is no longer on
the same network as the exchange: where `pm-api-gwy` is. The compose file
defaults to `host.docker.internal`, which resolves on Docker Desktop but not
on Podman or Linux Docker, so set it explicitly:

```bash
# Podman
API_PROXY_TARGET=http://host.containers.internal:8080 make up

# Linux Docker, or a gateway on another machine
API_PROXY_TARGET=http://192.168.1.50:8080 make up
```

If port 8093 is taken on your machine, move the *host* side of it:

```bash
TRADER_GUI_PORT=8193 make up
```

`make logs` follows the server log, `make down` stops it, `make ps` shows the
stack.

!!! note "`CALF_*` and `LOG_SRV_*` in this compose file"
    The file sets them for parity with TapeDeck, but `apps/serve/serve.ts`
    does not read them: the Trading GUI has no CALF uplink and no bridge
    process of its own, only the REST/WebSocket proxy. Leave them alone.

### Local dev server

```bash
make install    # once, and after any dependency change
make dev        # Vite with hot reload
```

Open **<http://localhost:8193>**, enter an API key, and click **Connect**.

`vite.config.ts` proxies every `/api/*` request — REST *and* the WebSocket
upgrades under `/api/v1/ws/` (`private`, `market-data`, `admin/monitor`) — to
`http://localhost:8080`. So as long as `pm-api-gwy`'s `desk` instance is
reachable on port 8080 of your own machine, this needs no configuration:
`VITE_API_BASE` and `VITE_WS_BASE` stay empty and the browser only ever talks
to one origin, which sidesteps CORS entirely.

Starting the exchange with `make up-all` publishes 8080 on `127.0.0.1`, so the
container stack and this dev server work together with nothing further to set.
See [The Development Loop](../../architecture-and-development/part-4-developing/020-development-workflow.md) for the full
inner-loop workflow.

### Production build and serve (without a container)

```bash
make build      # typecheck + vite build → apps/web/dist/
make serve      # serve apps/web/dist/ via pm-trading-ui-serve, :8093
```

`pm-trading-ui-serve` (`apps/serve/serve.ts`) is a small dependency-free Node
`http` server: it serves the built SPA with `Cache-Control: immutable` on
hashed asset bundles and `no-cache` on `index.html`, falls back every unknown
`GET` path to `index.html` so React Router can handle client-side navigation,
and optionally proxies `/api/*` to `pm-api-gwy` when `API_PROXY_TARGET` is
set. With `API_PROXY_TARGET` unset, `/api/*` returns an explanatory `503`
rather than silently 404-ing.

```bash
# Custom port, proxy API to a remote gateway
PORT=8088 API_PROXY_TARGET=http://my-exchange:8080 npm run serve
```

In production you have two options for `/api/*`: put a reverse proxy (nginx,
Caddy, Traefik) in front that routes `/api/*` to `pm-api-gwy` and `/` to
`pm-trading-ui-serve` (recommended, `API_PROXY_TARGET` left unset), or set
`API_PROXY_TARGET` and let `pm-trading-ui-serve` forward `/api/*` itself,
which needs no extra infrastructure for a single-machine setup.

### Make targets

| Target | What it does |
|---|---|
| `make install` | `npm ci` from the lockfile across all workspaces (`npm install` when there is no lockfile yet) |
| `make dev` | Vite dev server on `:8193` with hot reload |
| `make build` | Typecheck + production build into `apps/web/dist/` |
| `make build-debug` | Build with source maps, skipping the typecheck |
| `make typecheck` / `make lint` | TypeScript type-check (TypeScript *is* the linter here) |
| `make test` | Vitest suite |
| `make format` | Prettier over the whole tree |
| `make serve` | Serve the built SPA via `pm-trading-ui-serve` on `:8093` |
| `make up` / `make down` / `make restart` | Start / stop / restart this app's own container |
| `make cbuild` | Build the container image without starting it |
| `make logs` / `make ps` | Follow container logs / show stack status |
| `make cdist` | Build a distributable image tarball under `dist/` |
| `make clean` | Remove build artefacts and `dist/` |
| `make distclean` | Also remove `node_modules` and the lockfile, for a pristine `make install` |
| `make imageclean` | Remove this project's local container images |
| `make ghcr-login` / `cpush` / `ghcr-logout` / `ghcr-clean` | Log in to the GitHub Container Registry, push the image, log out, and log out plus remove the local images |

Run `make help` for the authoritative list, `npm run serve -- --help` for the
static server's own flag reference, and see `web-apps/trader-gui/README.md` for the
implementation's own notes.

## Configuration reference

The app reads its configuration from Vite environment variables at build
time. Copy `web-apps/trader-gui/.env.example` to `.env` and adjust.

| Variable | Default | Purpose |
|---|---|---|
| `VITE_API_BASE` | *(empty)* | Base URL for the `pm-api-gwy` REST API. Empty relies on the dev proxy / same-origin reverse proxy. |
| `VITE_WS_BASE` | *(empty)* | Base URL for WebSocket connections. Empty resolves against the page origin (`http`→`ws`, `https`→`wss`). |
| `VITE_APP_TITLE` | `EduMatcher Trading` | Title on the login screen, shown as `<title> · pm-trading-ui`. The browser tab title is fixed in `apps/web/index.html`, and the top bar always shows `EduMatcher pm-trader`. |
| `VITE_MAX_OVERVIEW_SYMBOLS` | `250` | Cap on the broad book/trades subscription (Market Overview). |
| `VITE_MAX_FOCUS_SYMBOLS` | `25` | Cap on the focused per-symbol depth/auction subscription set (active symbol + watchlist). |
| `VITE_CHART_HISTORY_TICKS` | `1000` | Historical prints fetched for an intraday chart. |
| `VITE_FLASH_DURATION_MS` | `500` | Price flash-cell animation duration. |
| `VITE_MARKET_THROTTLE_MS` | `250` | How often Market Overview re-derives its rows from the book store — bounds re-render work independently of symbol count. |
| `VITE_WS_RECONNECT_MAX_DELAY` | `30000` | WebSocket reconnect backoff cap, in milliseconds. |
| `VITE_NOTIFICATION_BUFFER` | `500` | Maximum entries retained in the Event Center. |

A mistyped integer value falls back to its default rather than becoming `NaN`
and silently disabling the cap it was meant to set.

For the production static server (`pm-trading-ui-serve`), the relevant
variables are plain environment variables rather than `VITE_*` build-time
values:

| Variable | Default | Purpose |
|---|---|---|
| `HOST` | `0.0.0.0` | Bind address. |
| `PORT` | `8093` | Listen port. |
| `STATIC_DIR` | `apps/web/dist/` | Path to the built SPA. |
| `API_PROXY_TARGET` | *(unset — `/api/*` returns 503)* | Forward `/api/*` to this URL, e.g. `http://localhost:8080`. |

This table is generated from the same declaration the server reads at startup,
so `npm run serve -- --help` prints exactly these four options and their real
defaults — including the absolute `STATIC_DIR` path resolved for your checkout.
Treat that output as authoritative if it ever disagrees with this page.

Both container paths set the same `pm-trading-ui-serve` variables, plus a
host-side port mapping — but they differ in exactly one place, which is the
thing worth knowing:

| Variable | In the whole stack (`compose.guis.yaml`) | In this app alone (`web-apps/trader-gui/docker-compose.yml`) |
|---|---|---|
| `TRADER_GUI_PORT` | `8093` — host port; change it if 8093 is taken | `8093` — same |
| `HOST` / `PORT` | `0.0.0.0` / `8093` — bind inside the container | `0.0.0.0` / `8093` — same |
| `API_PROXY_TARGET` | `http://edumatcher:8080` — the backend's service name on the shared network; nothing to configure | `http://host.docker.internal:8080` — reaches back out to your host; **set it explicitly on Podman or Linux Docker** |

That single row is why the whole-stack path needs no addresses: both
containers are on one Compose network, so the exchange has a name
(`edumatcher`) that simply resolves. Running this app on its own puts it
outside that network, and it has to be told how to get back in.


## See also

- [Trading GUI](../../participant-guide/part-6-front-ends/020-trading-platform-gui.md) — logging in, the screens and every role's actions
- [API Gateway](../part-5-gateways/050-api-gateway.md) — the REST and WebSocket surface the app is built on, and its credentials
- [Installation](010-installation.md) — the container stack and `.env`
