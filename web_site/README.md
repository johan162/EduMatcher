# EduMatcher web site

A static, multi-page site (light and dark theme) that presents EduMatcher, embeds the complete
documentation built from `docs/`, and offers the system and the books for download. No framework and
no runtime dependencies: plain HTML, CSS and a little JavaScript.

The site is **built locally and uploaded to the external web host with `scripts/mkweb.sh`**. The
project's own documentation site stays where it is, on `gh-pages` (published by `docs.yml`); the
site simply contains a second, restyled copy of the same documentation under `/docs/`.

```bash
make web-site            # full build: pages + embedded docs + downloads (about 30 s)
make web-site-serve      # fast pages-only build, served on http://localhost:8000
make web-site-upload     # upload the built site (same as ./scripts/mkweb.sh)
python web_site/build.py --help
```

## Releasing: step by step

The site is part of the normal release; **`scripts/mkghrelease.sh` builds and uploads it as its
last real step (PHASE 6C)**, so after the usual steps there is nothing extra to remember.

### One-time set-up

| Need | How |
|---|---|
| Python tooling incl. mkdocs | `poetry install --with dev,docs` |
| GitHub CLI, logged in | `gh auth login`; `export GITHUB_USER=<your user>` |
| Upload credentials for `mkweb.sh` | `export TIRNEX_ADITUS_FTP_SITE=… TIRNEX_ADITUS_FTP_USER=… TIRNEX_ADITUS_FTP_PWD=…` |
| `expect` (used by `mkweb.sh` for the sftp password) | `brew install expect` |

### For each release

This is `release_checklist.md` with the web-site consequences spelled out.

1. **Bump the version** — `poetry version <NEW VERSION>`.
   *Web site:* this is the only place the version is typed. The hero badge, footer, install pin,
   download file names and release links all follow it.
2. **Write the changelog entry** (`/changelog` skill) in `CHANGELOG.md`. *Web site:* nothing.
3. **Run `scripts/mkbld.sh`** until it is clean. It rebuilds `dist/` (wheel and sdist) and
   `docs/dist/` (every book as A4, B5, A4-dark, B5-dark PDF and EPUB, plus the `_all` ZIPs) for the
   new version after wiping the old ones. *Web site:* these are exactly the files the site
   self-hosts, so they must exist for this version — step 6 refuses to continue without them.
4. **Commit everything** on `develop` (generated site files are git-ignored, so the tree stays clean).
5. **Run `scripts/mkrelease.sh <version> [major|minor|patch]`** — merges to `main`, tags, pushes.
   CI publishes the docs to `gh-pages`, the package to PyPI and the container images.
   *Web site:* nothing yet.
6. **When CI is green, run `scripts/mkghrelease.sh`** (try `--dry-run` first). It
   1. checks up front that the upload credentials, `expect` and mkdocs are available, so a missing
      variable cannot fail *after* the release is published;
   2. creates the GitHub release with the wheel, sdist and all-formats ZIPs;
   3. waits for the container-image workflow;
   4. **PHASE 6C — builds and uploads the web site:**
      * checks `pyproject.toml` matches the release tag,
      * `python web_site/build.py --downloads local --strict` — rebuilds the docs with mkdocs,
        copies the PDFs/EPUBs from `docs/dist/` and the wheel/sdist from `dist/` into
        `web_site/downloads/` (with `SHA256SUMS.txt`), and fails if any of them is missing,
      * `scripts/mkweb.sh` — uploads `*.html`, `assets/`, `docs/` and `downloads/` via sftp.
7. **Check the live site:** the version badge, `/docs/`, and the Download page (click a PDF, the
   wheel and a ZIP).

Options for step 6: `--skip-web` (leave the site alone), `--no-web-upload` (build, don't upload),
`--skip-images`, `--dry-run`.

### If the web-site phase fails

The GitHub release is already out; only the site needs redoing. Fix the cause, then:

```bash
make web-site && ./scripts/mkweb.sh        # same as PHASE 6C, minus the strict check
python web_site/build.py --downloads local --strict && ./scripts/mkweb.sh   # with the strict check
```

| Symptom | Cause / fix |
|---|---|
| `--strict: not found locally: …` | `docs/dist/`, `dist/` or `docs-exchange-intro/dist/` lacks files — re-run `scripts/mkbld.sh` (add `--intro` for the intro book) |
| `books.json points at docs pages that do not exist` | a chapter was renamed — fix `entry` in `data/books.json` |
| `mkdocs not found` | `poetry install --with docs` |
| pyproject/tag mismatch | you are not on the tagged `main` commit |
| upload hangs or asks for a password | check the three `TIRNEX_ADITUS_FTP_*` variables |
| clean step reports `could not remove …` | the sftp user lacks delete rights on that path; fix on the server, then re-run `mkweb.sh` (the site is already partly removed, so do not leave it) |

### Updating the site between releases

Edit a page, a screenshot or a book entry, then `make web-site-serve` to look at it, and
`make web-site && make web-site-upload` to publish. A docs-only fix works the same way. (The
`gh-pages` documentation is updated by its own workflow, independent of the site.)

## What the build derives (never typed into a page)

| Shown on the site | Comes from |
|---|---|
| Version everywhere, install pin, release and tag links | `pyproject.toml` |
| Command count, test count, lines of code (home-page stats) | `pyproject.toml`, `tests/`, `src/` |
| Documentation (`/docs/`) | `docs/` + `mkdocs.yml`, rebuilt every time |
| Guide-book PDFs (A4, B5, dark) and EPUBs | `docs/dist/edumatcher_<stem>_…-<version>.*`, self-hosted |
| Per-book all-formats ZIP | link to the GitHub release asset `edumatcher_<stem>_all-<version>.zip` |
| **Exchange Concepts** (the separate intro book): edition number, chapter count | `docs-exchange-intro/version.toml` (its own version scheme), `docs-exchange-intro/book.toml` |
| Exchange Concepts PDFs (A4, B5, dark), EPUB, Part I–IV PDFs, quiz bundle | `docs-exchange-intro/dist/exchange_intro_*-<edition>.*` (the part PDFs are unpacked from the parts bundle ZIP), self-hosted |
| Wheel, sdist | `dist/edumatcher-<version>…`, self-hosted; source archives link to the tag on GitHub |
| Slide-deck list | PDFs found in `docs/presentations/` |
| Checksums | `downloads/SHA256SUMS.txt` for every self-hosted file |

Without `--strict` (a plain `make web-site`) a missing file is greyed out on the page instead of
failing the build, so you can preview the site before the artifacts exist. A link is never left
pointing at a file that is not there.

### Things you still edit by hand

* **New guide book** — add an entry to `data/books.json` and a cover to `assets/img/covers/`
  (the book list, Learn page, Documentation page and Download table all follow).
* **New benchmark numbers** — `data/facts.json`.
* **New screenshots** — put them in `assets/img/shots/` and reference them from `src/pages/apps.html`.
* **Copy and design** — `src/pages/*.html`, `src/partials/`, `assets/css/site.css`.

### The introduction book is separate

*Exchange Concepts: An Introduction* (`docs-exchange-intro/`) is **not** one of the guide books: it is a
general introduction to financial exchanges and does not document EduMatcher. It therefore has its own
section on the home, Learn and Download pages, is not counted in "N guide books", and carries its own
edition number (`docs-exchange-intro/version.toml`), which is shown as "Edition x.y.z" and never mixed with
the EduMatcher version. It is configured by the `intro` block in `data/books.json`; its downloads are
resolved from `docs-exchange-intro/dist/` for whatever edition `version.toml` says, so after rebuilding the
book (`mkbld.sh --intro`) the next site build picks up the new edition by itself. Its cover is
`assets/img/covers/exchange-intro.jpg` (a copy of `docs-exchange-intro/assets/cover-exchange-intro.png`,
including its PRE-RELEASE watermark — replace the image when the book is no longer a pre-release).
`--strict` also requires the intro files to exist locally.

## Folder layout

| Path | What | In git? |
|---|---|---|
| `src/pages/*.html` | Page sources (`index`, `platform`, `apps`, `learn`, `docs`, `download`, `404`) | yes |
| `src/partials/` | Shared head, header, footer and the SVG illustrations | yes |
| `assets/` | CSS, JS, screenshots, book covers | yes |
| `data/books.json`, `data/facts.json` | Book list; benchmark figures | yes |
| `build.py` | The build | yes |
| `mkdocs-site.yml`, `docs_hooks.py`, `docs_theme/` | Embeds `docs/` in the site's look (below) | yes |
| `*.html` in this folder | **Generated** pages | no |
| `docs/` | **Generated** documentation (mkdocs, about 120 MB) | no |
| `downloads/` | **Generated** books, wheel, sdist, `SHA256SUMS.txt` | no |

## How the documentation is embedded

`mkdocs-site.yml` inherits the repository's `mkdocs.yml` (same content, navigation and extensions)
and only changes the output folder (`web_site/docs/`) and the palette. `docs_hooks.py` injects
`docs_theme/assets/docs-site.{css,js}` into every page, which restyles Material to match the site,
adds the EduMatcher home link and site menu to the header, and shares the light/dark choice with the
rest of the site (`localStorage["em-theme"]`). `docs/` itself and the normal `mkdocs build` are untouched.

## Hosting notes

* Links are relative, so the site also works under a sub-path.
* `mkweb.sh` first **removes the previous site from the server** (root `*.html` and the `assets/`, `docs/`
  and `downloads/` directories — nothing else in the login directory), then uploads the new one. Old-version
  downloads and deleted pages therefore disappear, but the site is incomplete for the duration of the upload.
  `./scripts/mkweb.sh --dry-run` lists what would be removed; `--no-clean` uploads without removing anything.
* The decorative ticker, the live order book, the price-discovery chart and the AI-swarm grid are
  illustrations generated in the browser, and are labelled as such. The order-book debugger on the
  Learn page (`#obd` in `site.js`) is a scripted replay of the worked example in *The Order Book:
  Deep Dive*; if that example changes, update its `STEPS` to match.
* The Training Guide cover in `assets/img/covers/` was rendered from the Quick Start cover template
  so that all eight covers share the look of the print books.
* Fonts (Bebas Neue, Barlow, DM Mono, Playfair Display) load from Google Fonts with system fallbacks.
