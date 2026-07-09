# EduMatcher Config Builder (`config-gui`)

A browser-based builder for EduMatcher's `engine_config.yaml` — a human-friendly
companion to the `pm-config-gen` CLI. It offers live cross-field validation,
progressive disclosure by experience level (*Beginner* / *Intermediate* /
*Expert*), import of existing configs, light and dark themes, and export that is
guaranteed parseable by the engine.

> **User & operator documentation** — installation, running in development,
> production and container deployment, environment variables, and a full
> troubleshooting guide — lives in the user guide:
> **[Configuration GUI chapter](../docs/user-guide/27-config-GUI.md)**.
>
> This README is the **developer** reference: architecture, project layout,
> testing, and how to keep the GUI in sync with `pm-config-gen`.

### Makefile quick reference

This directory includes a `Makefile` covering the full local and container
lifecycle. Run `make help` at any time to see all available targets.

**Initial setup after a fresh checkout:**

```bash
make install      # install npm workspaces (npm ci when lockfile exists)
make build        # type-check + build all workspaces
```

**Day-to-day development:**

```bash
make dev          # start both the API and the web dev server together
make dev-server   # start only the Fastify backend (port 5175)
make dev-web      # start only the Vite frontend  (port 5174)
make test         # run the unit test suite
make typecheck    # TypeScript type-check across all workspaces
make format       # Prettier format pass
```

**Container workflow:**

```bash
make up           # build image and start the stack in detached mode
                  # (auto-detects podman or docker, starts podman machine
                  # if needed on macOS)
make down         # stop and remove the container stack
make logs         # follow container logs
make ps           # show container status
```

**Restore a pristine checkout state:**

```bash
make down         # stop any running containers first
make clean        # remove all build artifacts (dist/, *.tsbuildinfo)
rm -rf node_modules  # remove installed packages
make install      # reinstall from lockfile
```


## Quick start (development)

For a manual setup do the following:

```bash
cd config-gui
npm install

# two terminals:
npm run dev:server   # API  → http://127.0.0.1:5175
npm run dev:web      # web  → http://127.0.0.1:5174
```

Open http://127.0.0.1:5174. See the
[user-guide chapter](../docs/user-guide/27-config-GUI.md) for production and
single-container deployment.


## Architecture

The app is a small npm-workspaces monorepo:

```
config-gui/
  apps/
    web/                 React + Vite frontend (UI, personas, theming, tabs)
    server/              Fastify backend (import / validate / generate / verify)
  packages/
    schema/              Types, Zod schemas, default constants (mirrors defaults.py)
    yaml-codec/          Draft <-> engine_config.yaml (serialize + parse)
    diagnostics/         Cross-field validation rule engine (pure functions)
  scripts/
    generate-fixtures.ts Emits representative configs from drafts
    verify-python.sh     Pipes generated configs through the Python engine loader
  Dockerfile / docker-compose.yml   Single-container production image
```

Data flow: the UI edits an in-memory `EngineConfigDraft` (Zustand store) →
`packages/diagnostics` recomputes issues live → export serializes the draft via
`packages/yaml-codec` → the backend can optionally hand the YAML to
`pm-cverifier`.

## Developer commands

```bash
npm test              # unit tests: schema, yaml-codec, diagnostics (Vitest)
npm run typecheck     # type-check every workspace
npm run build         # type-check + build the production frontend bundle
npm run verify:python # golden-file check: generate configs and validate each
                      # with the REAL Python load_engine_config() (needs Poetry)
npm run format        # Prettier
```

`verify:python` is the authoritative correctness gate — keep it green.

## Maintenance — keeping the GUI and `pm-config-gen` in sync

**The most important thing to know when maintaining this app.** The GUI
re-implements the `engine_config.yaml` format in TypeScript (it needs a full
structural editor and a YAML→model importer, which the CLI does not provide), so
the format has **two owners**: Python `pm-config-gen` and this codec. **When you
add or change an engine-config field, update both.**

When you add a new `engine_config.yaml` field:

1. **Python** (`src/edumatcher/config_gen/`): `defaults.py`, `builder.py`,
   `renderer.py`, `warnings.py`, `cli_comments.py` as usual.
2. **GUI schema** (`packages/schema/`): `types.ts`, `zod.ts`, `defaults.ts`, and
   `createBlankDraft()` in `factory.ts`.
3. **GUI codec** (`packages/yaml-codec/`): `build.ts` (draft → document, mirrors
   `builder.py`), `parse.ts` (YAML → draft, so imports keep it), and any hint in
   `renderer.ts` / `defaultFieldComments.ts`.
4. **GUI diagnostics** (`packages/diagnostics/`): add/adjust the rule; mirror the
   `id` and message of the equivalent `warnings.py` rule.
5. **GUI UI** (`apps/web/src/tabs/`): add the editor with the correct persona
   tag, mandatory/optional treatment, and help text.
6. **Verify**: `npm test`, `npm run typecheck`, and — crucially —
   `npm run verify:python`.

Files that mirror a Python source carry a `MAINTENANCE:` comment naming their
counterpart. Grep before shipping a format change:

```bash
grep -rn "MAINTENANCE" packages
```

> Design note: shelling out to `pm-config-gen` so Python owns the format outright
> was considered and rejected for v1 — the CLI has no YAML-import path and its
> flag surface cannot express every value the GUI must let users edit (explicit
> market-maker quote prices, imported passthrough YAML). The dual-ownership above
> is the trade-off; the golden-file test keeps the two honest.

## Design reference

Full design and rationale:
[`docs-design/EduMatcher-Config-GUI.md`](../docs-design/EduMatcher-Config-GUI.md).
