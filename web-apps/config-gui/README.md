# EduMatcher Config Builder (`pm-config-ui`)

A browser-based builder for EduMatcher's authored `engine_config.yaml` — a
human-friendly companion to the `pm-config-gen` CLI. It offers live
cross-field validation, progressive disclosure by experience level
(*Beginner* / *Intermediate* / *Expert*), import of existing configs, light
and dark themes, and export that is guaranteed parseable by the engine.

**Dependencies:** none required at runtime. The optional "Verify with
`pm-cverifier`" button shells out to the Python engine (`pm-cverifier` on
`PATH`, or override with `CVERIFIER_COMMAND`) purely to double-check exported
YAML; without it, that one endpoint returns a friendly 503 and everything
else works.

## Project layout

```
config-gui/
  apps/
    web/                           React + Vite frontend (UI, personas, theming, tabs)
    server/                        Fastify backend (import / validate / generate / verify)
  packages/
    schema/                        Types, Zod schemas, default constants
    yaml-codec/                    Draft <-> engine_config.yaml (serialize + parse)
    diagnostics/                   Cross-field validation rule engine (pure functions)
  scripts/
    generate-fixtures.ts           Emits representative configs from drafts
    verify-python.sh               Pipes generated configs through the Python engine loader
  Dockerfile                       Single-container production image
  Dockerfile.proxy                 Same, plus corporate proxy/CA support
  docker-compose.yml               Compose wrapper around Dockerfile
  Makefile                         Full local and container lifecycle targets
```

## Quick start

### Container

```bash
make up     # detects podman or docker, builds image, starts on http://localhost:8092
make down   # stop and remove
```


If you are behind a proxy (or firewall), export `http_proxy` in your shell before `make up` (or `make cbuild` / `make cdist`). The Makefile passes it into the image build as `HTTP_PROXY` and `HTTPS_PROXY`, rewriting a `localhost` proxy host to `host.containers.internal` so the build container can reach it, and defaulting the port to `9000` when the URL has none. With `http_proxy` unset the build uses no proxy. `make print-proxy` shows the values the build will get.



### Development server

```bash
make install   # npm ci from lockfile
make dev       # starts API (port 5192) + web dev server (port 8192) together
```

Open **http://127.0.0.1:8192** — the Vite dev server proxies `/api` to the
Fastify backend on port 5192. Run `make help` for the full target list.

## Environment variables

| Variable            | Default            | Applies to      | Description                                              |
| -------------------- | ------------------- | --------------- | ---------------------------------------------------------- |
| `HOST`               | `127.0.0.1`         | server          | Bind address                                                |
| `PORT`                | `5192` (dev), `8092` (container) | server | Listen port                                       |
| `MAX_IMPORT_BYTES`    | `1000000`           | server          | Max accepted import payload, in bytes                       |
| `CVERIFIER_COMMAND`   | `pm-cverifier`       | server          | Command used to invoke `pm-cverifier` for `/verify` (space-separated, e.g. `poetry run pm-cverifier`) |
| `CORS_ORIGIN`         | `*`                  | server          | Allowed CORS origin; restrict to your site origin in production |
| `STATIC_DIR`          | _(unset)_            | server          | When set, the built frontend is served from this directory (single-container mode) |

Container-only build args (`docker-compose.yml`, for corporate proxies):
`HTTP_PROXY`, `HTTPS_PROXY`, `NO_PROXY`, `NPM_STRICT_SSL`, `CA_CERT_FILE`,
`USE_PROXY_CA` — see the comments in `Dockerfile` / `Dockerfile.proxy`.

## Startup sequence

1. No other EduMatcher process needs to be running first — this GUI reads
   and writes YAML files, it does not connect to any live process.
2. Start the GUI: `make up` (container) or `make dev` (development).
3. Author or import a config, and export it once cross-field validation is
   clean.
4. Run `pm-config-deploy <file>` (outside this GUI) to validate and compile
   the exported YAML into the artifact every `pm-*` process reads.

## Other Makefile targets

| Target          | Description                                                          |
| ---------------- | ---------------------------------------------------------------------- |
| `build`           | Type-check + production build of all workspaces                        |
| `build-debug`     | Frontend build with sourcemaps, unminified                             |
| `typecheck`       | Type-check every workspace                                             |
| `test`            | Run unit tests (Vitest) for schema, yaml-codec, diagnostics             |
| `lint`            | Alias for `typecheck`                                                  |
| `format`          | Format source with Prettier                                            |
| `dev-web`         | Only the web dev server (Vite)                                         |
| `dev-server`      | Only the backend dev server (Fastify)                                  |
| `cbuild`          | Build the container image via compose without starting it              |
| `restart`         | Restart the container stack                                            |
| `logs`            | Follow container logs                                                  |
| `ps`              | Show container stack status                                            |
| `cdist`           | Build a distributable: container image + exported OCI tarball in `dist/` |
| `clean`           | Remove local build artifacts and `dist/`                               |

`npm run verify:python` (outside `make`) runs the golden-file check that
validates generated configs with the real Python `load_engine_config()`;
it needs Poetry and is the authoritative correctness gate for the YAML
codec.

## Other relevant information

Data flow: the UI edits an in-memory `EngineConfigDraft` (Zustand store) →
`packages/diagnostics` recomputes issues live → export serializes the draft
via `packages/yaml-codec` → the backend optionally hands the YAML to
`pm-cverifier`.

The GUI re-implements the `engine_config.yaml` format in TypeScript, so the
format has two owners: Python `pm-config-gen` and this codec. When you add
or change an engine-config field, update both sides — grep for
`MAINTENANCE:` comments across `packages/` to find every file that mirrors
a Python source before shipping a format change.
