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
> This README is the **developer** reference: project layout, getting started,
> and how to keep the GUI in sync with `pm-config-gen`.


## Project layout

```
config-gui/
  apps/
    web/                           React + Vite frontend (UI, personas, theming, tabs)
    server/                        Fastify backend (import / validate / generate / verify)
  packages/    
    schema/                        Types, Zod schemas, default constants (mirrors defaults.py)
    yaml-codec/                    Draft <-> engine_config.yaml (serialize + parse)
    diagnostics/                   Cross-field validation rule engine (pure functions)
  scripts/    
    generate-fixtures.ts           Emits representative configs from drafts
    verify-python.sh               Pipes generated configs through the Python engine loader
  Dockerfile / docker-compose.yml  Single-container production image
  Makefile                         Full local and container lifecycle targets
```

Data flow: the UI edits an in-memory `EngineConfigDraft` (Zustand store) →
`packages/diagnostics` recomputes issues live → export serializes the draft via
`packages/yaml-codec` → the backend optionally hands the YAML to `pm-cverifier`.


## Getting started

**Fastest path — container:**

```bash
make up     # detects podman or docker, builds image, starts on http://localhost:8080
make down   # stop and remove
```

**Local development:**

```bash
make install   # npm ci from lockfile
make dev       # starts API (port 5175) + web dev server (port 5174) together
```

Open **http://127.0.0.1:5174**. Run `make help` for a full list of targets.


## Developer commands

```bash
npm test              # unit tests: schema, yaml-codec, diagnostics (Vitest)
npm run typecheck     # type-check every workspace
npm run build         # type-check + build the production frontend bundle
npm run verify:python # golden-file check: generate configs and validate each
                      # with the real Python load_engine_config() (needs Poetry)
```

`verify:python` is the authoritative correctness gate — keep it green.


## Maintenance — keeping the GUI and `pm-config-gen` in sync

The GUI re-implements the `engine_config.yaml` format in TypeScript, so the
format has **two owners**: Python `pm-config-gen` and this codec. **When you
add or change an engine-config field, update both.**

When you add a new field:

1. **Python** (`src/edumatcher/config_gen/`): `defaults.py`, `builder.py`,
   `renderer.py`, `warnings.py`, `cli_comments.py` as usual.
2. **GUI schema** (`packages/schema/`): `types.ts`, `zod.ts`, `defaults.ts`, and
   `createBlankDraft()` in `factory.ts`.
3. **GUI codec** (`packages/yaml-codec/`): `build.ts` (draft → document),
   `parse.ts` (YAML → draft), and any hints in `renderer.ts` /
   `defaultFieldComments.ts`.
4. **GUI diagnostics** (`packages/diagnostics/`): add/adjust the rule; mirror
   the `id` and message of the equivalent `warnings.py` rule.
5. **GUI UI** (`apps/web/src/tabs/`): add the editor with the correct persona
   tag, mandatory/optional treatment, and help text.
6. **Verify**: `npm test`, `npm run typecheck`, and `npm run verify:python`.

Files that mirror a Python source carry a `MAINTENANCE:` comment naming their
counterpart. Grep before shipping a format change:

```bash
grep -rn "MAINTENANCE" packages
```
