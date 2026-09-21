# EduMatcher → Tirnex rename: findings and plan

Scan performed directly against the repo at `~/Devel/EduMatcher` (896 tracked
files match "edumatcher" case-insensitively). No renaming has been done —
this is the plan plus a dry-run-first helper script.

**Name status:** `Tirnex` is an invented word (no
dictionary meaning found in any language checked) that passed PyPI, npm, and
general web-search screening — no prominent company, product, or trademark
turned up. That is not the same as a real trademark/company-registry
clearance: web search reliably catches well-known/well-indexed names but has
repeatedly missed smaller registered companies during this naming search
(three earlier candidates — Bellex, Kaupex, Kaupra — all passed the same
screening and then turned out to be real registered businesses). Before
committing engineering time to this rename, run `Tirnex` through USPTO TESS
(uspto.gov/trademarks/search), EUIPO eSearch (euipo.europa.eu/eSearch), and
your target jurisdictions' company registries (e.g. UK Companies House).
Treat every "Tirnex" below as a working placeholder until that check clears.

## 1. What's actually there (verified, not assumed)

Casing conventions in use — only three, cleanly separated, nothing stray:

| Pattern      | Occurrences | Used for                                    |
|--------------|-------------|----------------------------------------------|
| `EduMatcher` | 1152        | Prose, doc titles, PascalCase identifiers     |
| `edumatcher` | 4696        | Python package/module path, snake_case, image/file names |
| `EDUMATCHER` | 503         | Env vars, C header guards, shell constants    |


Breakdown by area (files touched):

```
tests            248
src              195   <- entire importable package tree
web-apps         189
docs             137
docs-design       67   <- 62 files literally named EduMatcher-*.md
deployment        24
scripts           10
[root]             7   (README, pyproject.toml, mkdocs.yml, CHANGELOG.md, TODO.md, ...)
tools              6
.github            5   (workflows)
spec               4
docs-exchange-intro 4
```

## 2. Category breakdown and what each needs

### A. Python package (highest risk — this is not a text edit, it's a package rename)
- `pyproject.toml`: `name = "edumatcher"`, `packages = [{include = "edumatcher", from = "src"}]`,
  every `pm-*` console-script entry point points at `edumatcher.<module>:main` (33 entries).
- `src/edumatcher/` — the actual package directory, ~280 files, with
  `import edumatcher...` / `from edumatcher...` statements throughout `src/`
  and `tests/`.
- This must become `src/tirnex/` (or whatever slug you pick) with every
  import statement rewritten. Renaming this wrong breaks every entry point,
  every test, and the built wheel.
- Also touches: `src/edumatcher/py.typed`, `src/edumatcher/completion/pm-completion.{bash,zsh}`
  (these reference the module for completion, check contents not just filename).

### B. PyPI / TestPyPI publishing
- There is **no separate PyPI project-name config** — the published name is
  whatever `pyproject.toml`'s `name =` says, for both targets. TestPyPI vs
  PyPI is selected in `.github/workflows/publish-to-pypi.yml` purely by tag
  format (`vX.Y.Z` = production PyPI, anything else = TestPyPI); neither
  target hardcodes "edumatcher" anywhere else in that workflow.
- Consequence: once you rename `pyproject.toml`'s `name`, the *next* publish
  goes to PyPI/TestPyPI under the new name as a **brand-new project**, not a
  rename of the existing one. PyPI has no rename feature.
  - You will want to keep a final release under the old name (e.g. a
    `0.x.y` "final" version) whose README says "renamed to tirnex, see
    <link>", then either yank later releases or just stop publishing to the
    old name.
  - Decide before you touch anything: do you want to reserve the `tirnex`
    name on PyPI/TestPyPI immediately (register it even before the code
    catches up) so nobody else can grab it in the interim? This is worth
    doing early and separately from the code change.
  - `pipx install edumatcher` in README (line 54) and `./edumatcher.sh shell`
    instructions all need updating to match whatever install path you choose.

### C. Environment variables
24 unique `EDUMATCHER_*` names across 100 files. Confirmed by grep, this
list is exhaustive:
```
EDUMATCHER_API_KEY             EDUMATCHER_ENGINE_PULL_PORT
EDUMATCHER_API_URL             EDUMATCHER_GATEWAY_BIND_HOST
EDUMATCHER_CONFIG              EDUMATCHER_GHCR_OWNER
EDUMATCHER_DATA_DIR            EDUMATCHER_INDEX_BIND_HOST
EDUMATCHER_DOCS_IMAGE          EDUMATCHER_INDEX_PUB_PORT
EDUMATCHER_DOCS_PORT           EDUMATCHER_INDEX_PULL_PORT
EDUMATCHER_DROP_COPY_PUB_PORT  EDUMATCHER_TEST_CLOCK
EDUMATCHER_ENGINE_BIND_HOST    EDUMATCHER_USE_PROXY_CA
EDUMATCHER_ENGINE_HOST         EDUMATCHER_VERSION
EDUMATCHER_ENGINE_PUB_PORT     EDUMATCHER_API_GW_CONFIG
```
Plus three that are **not env vars** — they're C header include-guards,
generated by msgen (`docs/examples/generated/*.h`):
```
EDUMATCHER_MSG_H  EDUMATCHER_ORDER_H  EDUMATCHER_TRADE_H  EDUMATCHER_API_GATEWAY_CLIENT_H
```
These can rename fine with the same text substitution.

**Breaking-change consideration:** renaming env vars is a hard break for
anyone with `EDUMATCHER_DATA_DIR` etc. already set in their shell profile,
systemd units, docker `.env` files, or CI secrets. Two options:
1. Clean break — rename everywhere, document in CHANGELOG/migration notes.
2. Back-compat shim — read new name, fall back to old with a deprecation
   warning, for one release cycle. Given the project's stated "no backward
   compatibility for its own sake" simplicity preference, (1) is probably
   the right call, but flagging it since it's a real behavior change for
   anyone with an existing `.env` or deployed config, not just a rename.
   **Your call — I'd ask before assuming.**

Also note `deployment/docker/.env` and `deployment/docker/.env.example`
are real files with live env var assignments (not just documentation) —
these need the values renamed, not just mentioned.

### D. File and directory names
- 62 files: `docs-design/EduMatcher-*.md` and `docs-design/reviews/EduMatcher-*.md`
  — straightforward `git mv` to `Tirnex-*.md`, preserving suffix exactly
  (e.g. `EduMatcher-Clearing.md` → `Tirnex-Clearing.md`).
- `deployment/curl/edumatcher.sh` → `deployment/curl/tirnex.sh`
- `deployment/vm/install_edumatcher.sh` → `deployment/vm/install_tirnex.sh`
- `docs/examples/generated/edumatcher_{msg,order,trade}.{c,h}` — these are
  **generated** by `pm-msgen`/`src/edumatcher/msgen/`. Don't hand-rename;
  regenerate after the code rename so content and filename stay consistent
  with whatever the generator emits.
- `docs/presentations/introduction-to-edumatcher.{pdf,pptx}`,
  `docs/presentations/training/edumatcher-training.{pdf,pptx}` — binary
  files; renaming the filename is a `git mv`, but the *content* (title
  slide, etc.) won't be touched by any text-replace. Decide if these need
  manual re-export or if the filename-only rename is enough for now.
- Entire `src/edumatcher/` directory tree → `src/tirnex/` (see section A).

### E. Container / GHCR image names
Confirmed image name references (5 images, matches your earlier note about
GHCR publishing):
```
ghcr.io/johan162/edumatcher                (main engine image)
ghcr.io/johan162/edumatcher-terminal-gui
ghcr.io/johan162/edumatcher-log-gui
ghcr.io/johan162/edumatcher-config-gui
ghcr.io/johan162/edumatcher-trader-gui
```
Referenced in: `deployment/curl/compose.yaml`, `deployment/curl/README.md`,
`deployment/docker/compose*.yaml` (local build names, no ghcr.io prefix),
`web-apps/*/docker-compose.yml`, `.github/workflows/publish-images.yml`.

**Same problem as PyPI**: GHCR packages don't rename in place either (or if
they technically can via GitHub package settings, existing pulls/tags under
the old name stay where they are). A rename here means: new images publish
under `ghcr.io/johan162/tirnex*` from the next release; old
`ghcr.io/johan162/edumatcher*` images remain pullable as historical
artifacts unless you explicitly delete them. Same "reserve the name early,
plan a final tagged release under the old name" logic as PyPI applies.

`EDUMATCHER_GHCR_OWNER` env var (section C) is unrelated to the image
*name* — it's the owner/org prefix — but gets renamed for consistency
regardless.

### F. GitHub repo itself
- `git remote -v` confirms: `origin → https://github.com/johan162/EduMatcher.git`
- GitHub repo rename gives an automatic redirect for git clone/fetch/push
  and web URLs — but does **not** rewrite:
  - Badges/links baked into README, mkdocs.yml (`repo_url`, `site_url`),
    CI badge URLs — all reference `johan162/EduMatcher` explicitly and
    should be updated to the literal new path even though the redirect
    would technically still work (cleaner, avoids a permanent redirect
    dependency).
  - Any GitHub Pages URL (`https://johan162.github.io/EduMatcher/` appears
    9+ times in README alone, plus `mkdocs.yml site_url`) — renaming the
    repo changes the Pages URL too, which changes every one of those links.
  - Local clones on other machines keep their old `origin` URL working via
    redirect, but won't auto-update.

### G. Things that should NOT be hand-edited
- `dist/*.whl`, `dist/*.tar.gz` — build output, currently
  `edumatcher-0.40.5-py3-none-any.whl`. Delete and rebuild after the
  package rename; don't try to rename these in place.
- `site/` — mkdocs build output, regenerate via `mkdocs build` after
  `mkdocs.yml` is updated.
- `.venv/`, `.mypy_cache/`, `.pytest_cache/`, `.build/`, `htmlcov/`,
  `coverage.xml`, `.coverage` — all derived/cache, will self-correct on
  next clean build/test run. Safe to `rm -rf` and regenerate rather than
  edit.
- `build-tools/node_modules/**` — vendored third-party JS deps, not part
  of the rename surface at all (checked: no genuine project-name hits in
  there, only coincidental substring noise from unrelated packages).
- `CHANGELOG.md` (37 mentions) and `TODO.md` (3 mentions) — these are
  **historical record**. Recommend leaving past entries referencing
  "EduMatcher" as-is (that's what the project was called when those
  entries were written) and only using the new name in entries going
  forward, starting with a CHANGELOG entry announcing the rename itself.
  Rewriting history here is a judgment call, not a mechanical one —
  flagging rather than deciding for you.

## 3. Suggested execution order

This is not a single global replace. Doing it in the wrong order breaks
things in between commits (e.g. renaming imports before the directory
exists). Order that keeps the tree working at each step:

1. **Clear the name, then lock the exact slug(s)** — this blocks everything
   else:
   - Display name: `Tirnex` — **pending your own USPTO/EUIPO/company-registry
     check** (see the status note at the top of this document). Confirmed
     so far only as: free on PyPI (`pypi.org/pypi/tirnex/json` → HTTP 404)
     and npm (`registry.npmjs.org/tirnex` → HTTP 404) as of this writing,
     and nothing prominent found in general web search.
   - Package/import name (PEP 8, must be valid Python identifier,
     conventionally lowercase): `tirnex`
   - Env var prefix: `TIRNEX_`
   - PyPI project name: `tirnex` — free as of this writing; re-check
     immediately before you actually publish, since availability can change
     — and separately check test.pypi.org yourself (not reachable from this
     session's network egress).
   - GHCR image basename: `tirnex` — free by construction once you own the
     `johan162` GHCR namespace (GHCR packages are namespaced per-owner, so
     nobody else can hold `ghcr.io/johan162/tirnex*` out from under you).
   - Repo name: `Tirnex`
   - Install dir convention: `~/.tirnex`
   **Treat this as provisional until the registry/trademark check clears**
   — the script below takes these as parameters rather than hardcoding
   guesses, precisely so the slug can change with a one-line edit if
   `Tirnex` doesn't clear.

2. **Reserve external names early** (can happen in parallel with dev work,
   before code changes land, and ideally only after the trademark/registry
   check clears): register `tirnex` on PyPI + TestPyPI with a
   placeholder/first release; confirm `ghcr.io/johan162/tirnex*` are free.

3. On a branch (not main): run the package rename first in isolation —
   `git mv src/edumatcher src/tirnex`, rewrite all `import edumatcher` /
   `from edumatcher` in `src/` and `tests/`, update `pyproject.toml`
   (`name`, `packages`, all 33 entry points). Run the full test suite +
   `black`/`flake8`/`mypy`/`pyright` per your project standards before
   proceeding — this is the step most likely to break silently (a missed
   import doesn't always fail loudly).

4. Rename the 62 `docs-design/EduMatcher-*.md` files and fix any internal
   cross-links between them (a doc that links to another doc by its old
   filename).

5. Text-substitute the three casing variants across everything else
   (docs, web-apps, deployment configs, scripts, tools, spec, root files),
   excluding CHANGELOG.md/TODO.md history per section G.

6. Rename env vars (`EDUMATCHER_*` → `TIRNEX_*`) — separate step from (5)
   since you may want the deprecation-shim discussion resolved first.

7. Update GHCR image names in compose files and `publish-images.yml`.

8. Regenerate `docs/examples/generated/*` via `pm-msgen` rather than
   hand-editing, to keep generator and output in sync.

9. Rebuild `dist/`, `site/`, clear caches — don't hand-edit these.

10. Rename the GitHub repo itself (last, since local dev doesn't depend on
    the remote name, and doing it last means you're not fighting a
    redirect during steps 1-9). Update README/mkdocs badge URLs
    immediately after, since GitHub Pages URL changes the moment the repo
    is renamed.

11. Verification pass (see §4).

## 4. Verification checklist (final step, before you consider this done)
- `git grep -ilI edumatcher` returns only CHANGELOG.md/TODO.md history
  (and possibly `dist/`/`site/` if not yet rebuilt — should be empty/
  regenerated).
- `poetry check` and `poetry build` succeed with the new package name.
- Full test suite green; `black`, `flake8`, `mypy`, `pyright` clean (per
  your project's standing "after implementation" rule).
- Every `pm-*` console script still resolves (`poetry run pm-engine --help`
  etc. for a sample of entry points).
- `mkdocs build` succeeds, spot-check a few rendered pages for broken
  internal links to the renamed `docs-design/Tirnex-*.md` files.
- Grep specifically for the old GHCR/PyPI URLs in docs to make sure none
  point at the old, soon-to-be-stale package/image locations without a
  clear "legacy" label.

## 5. Helper script dry run — verified against the real repo

The accompanying `rename_edumatcher.sh` was actually executed in dry-run
mode against this repo (no `--apply`, so nothing was changed) to confirm it
works before handing it to you. That test run used the script's defaults at
the time (`EduEx`/`eduex`/`EDUEX`) — the script's defaults are now `Tirnex`/
`tirnex`/`TIRNEX` (see the script header), but the detection logic itself is
identical, so every result below transfers unchanged: only the new-name
strings in the "would rewrite to" output differ. Re-run the dry run
yourself once you've cloned/pulled the updated script, before doing
anything with `--apply`, as a final sanity check. Results from the verified
run:
- Detected the `src/edumatcher/` → `src/tirnex/` directory rename correctly.
- Detected all 62 `docs-design/EduMatcher-*.md` renames correctly, including
  files with underscores/mixed case in the suffix (e.g.
  `EduMatcher-BALF_Proposal.md` → `Tirnex-BALF_Proposal.md`).
- Detected `deployment/curl/edumatcher.sh`, `deployment/vm/install_edumatcher.sh`,
  and the 4 presentation files.
- Content-rewrite pass correctly listed 888 files, correctly excluding
  CHANGELOG.md, TODO.md, dist/, site/, build-tools/node_modules/,
  docs/examples/generated/, and poetry.lock.
- Env-var report correctly listed all 24 `EDUMATCHER_*` names plus the 3 C
  header guards, and confirmed they're left untouched unless `--rename-env`
  is passed.
- No errors, no files touched (git status was clean before and after).

Additionally, with the `Tirnex` defaults now in place, both `--dry-run` and
`--apply` were re-verified end-to-end against a small synthetic git repo
(a `src/edumatcher/__init__.py` with an `import edumatcher` line, a
`docs-design/EduMatcher-Clearing.md`, and a README mixing all three casings
plus an `EDUMATCHER_DATA_DIR` reference). Confirmed:
- `src/edumatcher/` → `src/tirnex/`, `docs-design/EduMatcher-Clearing.md` →
  `docs-design/Tirnex-Clearing.md`, both via real `git mv`.
- File content rewritten with each casing mapped correctly in a single
  file (`EduMatcher is edumatcher, EDUMATCHER_DATA_DIR=/x` correctly became
  `Tirnex is tirnex, EDUMATCHER_DATA_DIR=/x` — note the env var reference
  was correctly left alone since `--rename-env` wasn't passed).
- `import edumatcher` correctly became `import tirnex` inside the moved
  package directory.
- This confirms the script's substitution logic is name-agnostic and the
  swap from the `EduEx` defaults to `Tirnex` didn't introduce any bugs.
