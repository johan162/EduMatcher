# EduMatcher web site

A static, multi-page site (light and dark theme) that presents EduMatcher, embeds the
complete documentation built from `docs/`, and offers the system and the books for
download. No framework and no runtime dependencies: plain HTML, CSS and a little JavaScript.

```bash
make web-site            # build everything (pages + docs + downloads), then open web_site/index.html
make web-site-serve      # fast pages-only build and a local server on http://localhost:8000
# or directly:
python web_site/build.py --help
```

## What is in the folder

| Path | What | Committed? |
|---|---|---|
| `src/pages/*.html` | Page sources (`index`, `platform`, `apps`, `learn`, `docs`, `download`, `404`) | yes |
| `src/partials/` | Shared head, header, footer and the **SVG illustrations** | yes |
| `assets/` | CSS, JS, screenshots, book covers | yes |
| `data/books.json` | The book list: title, audience, cover, entry page, file stem | yes |
| `data/facts.json` | Benchmark figures that cannot be derived from the repo | yes |
| `*.html` (site root) | **Generated** from `src/` by `build.py` — open `index.html` to preview | yes |
| `mkdocs-site.yml`, `docs_hooks.py`, `docs_theme/` | Embeds `docs/` in the site's look (see below) | yes |
| `docs/` | **Generated** documentation site (mkdocs, about 120 MB) | no |
| `downloads/` | **Generated** self-hosted books, wheel and `SHA256SUMS.txt` | no |

## Releasing: what you do for a new version

Bump the version as usual (`pyproject.toml`) and publish the release. That is all:

1. CI (`.github/workflows/website.yml`) runs `python web_site/build.py --downloads release`
   on every published release (and on demand), and deploys to GitHub Pages.
2. Locally, `make web-site` does the same and additionally self-hosts whatever it finds in
   `docs/dist/` (PDF/EPUB for this version) and `dist/` (wheel and sdist, built with
   `poetry build` when missing).

Everything that changes per release is derived, nothing is typed into the pages:

| Shown on the site | Comes from |
|---|---|
| Version everywhere, install pin, release/notes links | `pyproject.toml` |
| Command count, test count, lines of code (home page stats) | `pyproject.toml`, `tests/`, `src/` |
| Documentation (`/docs/`) | `docs/` + `mkdocs.yml`, rebuilt each time |
| Book download table (A4, B5, A4 dark, B5 dark, EPUB) | `data/books.json` × version → release asset URLs, or local `docs/dist/` copies |
| Wheel, sdist, source archive | `edumatcher-<version>…` in `dist/`, else the GitHub release / tag |
| Slide-deck list | PDFs found in `docs/presentations/` |
| Checksums | `downloads/SHA256SUMS.txt` for every self-hosted file |

Download links never dangle: for each file the build uses a local copy if it exists and
otherwise the GitHub release asset `…/releases/download/v<version>/<name>`, so the
release must contain the artifacts named by `docs/Makefile` (`edumatcher_<stem>_a4-<ver>.pdf`, …).
The build fails loudly if `data/books.json` points at a documentation page that no longer exists.

### Things you may still edit by hand

* **New book** — add an entry to `data/books.json` and a cover to `assets/img/covers/`.
* **New benchmark numbers** — `data/facts.json`.
* **New screenshots** — drop them in `assets/img/shots/` and reference them from `src/pages/apps.html`.
* **Copy and design** — `src/pages/*.html`, `assets/css/site.css`. Run `python web_site/build.py --no-docs`
  after changing `src/`; the generated `*.html` files in this folder are overwritten.

## How the documentation is embedded

`mkdocs-site.yml` inherits the repository's `mkdocs.yml` (same content, navigation and
markdown extensions) and only changes the output folder (`web_site/docs/`) and the theme
palette. `docs_hooks.py` injects `docs_theme/assets/docs-site.{css,js}` into every page, which

* restyles Material to match the site (navy/cyan, Bebas Neue headings),
* adds the EduMatcher home link and site menu to the docs header, and
* shares the light/dark choice with the rest of the site (`localStorage["em-theme"]`).

`docs/` itself and the project's normal `mkdocs build` are untouched.

## Hosting

Any static host works: serve the folder (or the `_site` tree CI assembles). Links are relative,
so it also works under a sub-path such as `https://<user>.github.io/EduMatcher/`.
The CI workflow publishes through GitHub Pages ("GitHub Actions" source); note this replaces the
`gh-pages` branch deployment of `docs.yml` — the same documentation is available under `/docs/`.

## Notes

* Decorative tickers, the live order-book widget, the price-discovery chart and the AI-swarm grid are
  illustrations (generated in the browser), and are labelled as such.
* The Training Guide cover in `assets/img/covers/` was rendered from the Quick Start cover template
  so that all eight covers share the look of the print books.
* Fonts (Bebas Neue, Barlow, DM Mono, Playfair Display) load from Google Fonts with system fallbacks.
