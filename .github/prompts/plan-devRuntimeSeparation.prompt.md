# Plan: Dev / Runtime Separation via pipx + Environment Variables

**TL;DR**: Keep poetry for development (unchanged). For end users, add two environment variables (`EDUMATCHER_DATA_DIR`, `EDUMATCHER_CONFIG`) to `config.py` for runtime configurability, bundle a sample config as a package resource, add a `pm-setup` command to bootstrap a new session, and publish to PyPI so students install with `pipx install edumatcher`.

---

## Phase 1 — `config.py`: environment variable overrides

Modify `src/edumatcher/config.py` to resolve `DATA_DIR` and `ENGINE_CONFIG_FILE` in priority order:

**DATA_DIR** (new logic):
1. `EDUMATCHER_DATA_DIR` env var — always wins
2. Source-tree detection: `Path(__file__).parent.parent.name == "src"` → use current `src/data/` (dev unchanged)
3. Installed (pipx/pip): fall back to `~/.local/share/edumatcher`

**ENGINE_CONFIG_FILE** (new logic):
1. `EDUMATCHER_CONFIG` env var — always wins
2. Source-tree: use current `project_root/engine_config.yaml` (dev unchanged)
3. Installed: `Path.cwd() / "engine_config.yaml"` (user runs from their session dir)

All derived constants (`GTC_ORDERS_FILE`, `STATS_DB_FILE`, etc.) continue to derive from `DATA_DIR` — no other files touched.

---

## Phase 2 — Bundle a sample config as a package resource

Copy `engine_config.yaml` → `src/edumatcher/engine_config.sample.yaml` and declare it as package data in `pyproject.toml`. The `pm-setup` command in Phase 3 uses `importlib.resources` to extract it. This means every pipx installation includes a working sample config out of the box.

---

## Phase 3 — New `pm-setup` entry point  *(depends on Phase 1 & 2)*

New file `src/edumatcher/setup_cmd.py` registered as:

```toml
pm-setup = "edumatcher.setup_cmd:main"
```

What it does:
- Creates the data directory (`EDUMATCHER_DATA_DIR` or `~/.local/share/edumatcher`)
- Copies the bundled `engine_config.sample.yaml` to `./engine_config.yaml` in CWD (unless one already exists or `--force` is given)
- Prints a shell snippet to paste into `.zshrc` / `.bashrc`

Options: `--data-dir PATH`, `--config-dest PATH`, `--force`

---

## Phase 4 — Update `tools/launch_all.sh`  *(depends on Phase 3)*

Strip all `poetry run` prefixes — bare `pm-engine`, `pm-gateway`, etc. work once pipx-installed or in an activated venv. Add a preflight check: if `pm-engine` is not on PATH, print instructions to install via pipx. Optionally export `EDUMATCHER_DATA_DIR` before launching.

---

## Phase 5 — New `scripts/install-runtime.sh`

One-shot instructor script:
1. Checks `pipx` is available (installs it via `brew`/`apt` if missing)
2. Runs `pipx install edumatcher` (or `pipx install --force` for upgrades)
3. Runs `pm-setup` to initialise data dir and copy sample config
4. Prints a final checklist

---

## Phase 6 — Documentation  *(parallel with 1–5)*

- `docs/user-guide/03-running-the-engine.md`: add a **Developer mode vs Installed mode** comparison table at the top (poetry vs pipx, `src/data` vs `~/.local/share/edumatcher`, etc.)
- `docs/user-guide/10-processes.md`: replace all `poetry run pm-xxx` examples with bare `pm-xxx`; add env var reference table

---

## Relevant files

| File | What changes |
|---|---|
| `src/edumatcher/config.py` | Add env var resolution for `DATA_DIR` and `ENGINE_CONFIG_FILE` |
| `src/edumatcher/setup_cmd.py` | New — `pm-setup` bootstrap command |
| `src/edumatcher/engine_config.sample.yaml` | New — bundled sample extracted by `pm-setup` |
| `pyproject.toml` | Add `pm-setup` entry point; add package data include |
| `tools/launch_all.sh` | Strip `poetry run`, add PATH preflight |
| `scripts/install-runtime.sh` | New — pipx install + setup one-liner for students |
| `docs/user-guide/03-running-the-engine.md` | Dev vs runtime section |
| `docs/user-guide/10-processes.md` | Update command examples |

---

## Verification

1. `poetry build && pipx install dist/edumatcher-*.whl --force` — all 15 `pm-*` commands appear in PATH
2. `pm-setup` — data dir created, config copied, shell snippet printed correctly
3. `EDUMATCHER_DATA_DIR=/tmp/test pm-engine --verbose` — engine uses `/tmp/test` for all data files
4. `pm-engine --config /tmp/test/engine_config.yaml` — config loaded from specified path
5. `poetry run pytest -n auto tests/ --cov-fail-under=85` — existing tests still pass (dev mode unchanged)

---

## Decisions made

- Default runtime data dir: `~/.local/share/edumatcher` (XDG; one store per machine)
- `pm-setup` creates it; users can override per-session with `EDUMATCHER_DATA_DIR`
- Distribution: PyPI (`pipx install edumatcher`); dev uses poetry as today
- Dev experience is **entirely unchanged** — the source-tree detection in `config.py` keeps `src/data` as the dev default with no env var needed

---

## Open questions / deferred

- Multi-session isolation: should `pm-setup` support a `--session NAME` flag to create `~/.local/share/edumatcher/sessions/<name>` instead of a flat store? Useful for running multiple independent classroom sessions on one machine.
- Should `pm-setup` also generate a `launch.sh` helper in the session dir that exports `EDUMATCHER_DATA_DIR` and starts all processes?
- Windows support: `~/.local/share` does not exist on Windows. Use `%APPDATA%\edumatcher` via `platformdirs` package?
