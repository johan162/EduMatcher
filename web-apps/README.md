# EduMatcher web apps

Four independent browser applications for the EduMatcher exchange. Each is
its own npm workspace with its own `package.json`, `Dockerfile`,
`docker-compose.yml`, and `Makefile` — nothing here is shared between them,
and none of the Python `pm-*` processes depend on this directory existing.
It exists purely to keep four self-contained frontend projects out of the
repository root.

| App | System name | Role | Dev port(s) |
| --- | --- | --- | --- |
| [`log-gui/`](log-gui/) | `pm-log-ui` | Operator console over `pm-log-srv`'s logs — live tail, search, alerts, acks | bridge `8091`, web `5178` |
| [`trader-gui/`](trader-gui/) | `pm-trading-ui` | Trading terminal (TRADER / MARKET_MAKER / ADMIN personas) against `pm-api-gwy` | web `5173`, prod serve `4173` |
| [`terminal-gui/`](terminal-gui/) | `pm-terminal` | Read-only, credential-free market display ("TapeDeck") | bridge `8090`, web `5179` |
| [`config-gui/`](config-gui/) | n/a | Browser builder for authored `engine_config.yaml`, companion to `pm-config-gen` | server `5175`, web `5174` |

Each app's own `README.md` is the developer reference (project layout,
getting started, environment variables). The `docs/user-guide/` chapters are
the user/operator reference; each app README links to its chapter.

## Common shape

Every app follows the same layout:

```
<app>/
  apps/            One or more npm workspace packages (web frontend, and
                    usually a small Node/Fastify backend)
  packages/         Shared TypeScript (types, protocol codecs, query builders)
  Dockerfile
  docker-compose.yml   Single-container production image, build context is
                        the app's own directory
  Makefile          install / dev / test / build / up — the same target
                     names across all four apps
```

`log-gui`, `trader-gui`, and `terminal-gui` each ship a small first-party
Node backend that talks to the Python side directly (LALF-PS, CALF TCP, or
the REST/WebSocket API gateway). `config-gui` is the odd one out: it has no
required runtime dependency on any `pm-*` process — its optional
`verify:python` check is the only place it shells out to the Python engine,
purely to keep exported YAML honest.

## Running one

From the app's own directory:

```bash
cd web-apps/<app>
make up        # container stack, or:
make dev       # local Node processes
```

See the app's own `README.md` and the matching `docs/user-guide/` chapter
for prerequisites, environment variables, and troubleshooting.
