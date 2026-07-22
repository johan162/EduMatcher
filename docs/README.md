# docs/ — Documentation Source

This folder contains all documentation source files for `mcprojsim`.
The documentation is built in two independent forms:

- **HTML site** — built by [MkDocs](https://www.mkdocs.org/) for the web / GitHub Pages.
- **PDF User Guide** — built via pandoc → XeLaTeX from the same Markdown sources, in four variants (see below).

---

## Folder structure

```text
docs/
├── Makefile                                     — build targets for all documentation outputs
├── index.md                                     — site home page
├── README.md                                    - this file, explaining the structure
├── faq.md                                       - FAQ for the EduMatcher
├── glossary.md                                  - Extensive glossary
├── how-exchange-works.md                        - Introduction to how a modern exchange works
├── architecture                                 - Architecture folder
│   ├── 01-architecture.md                       - A high level architecture overview
│   └── 02-architecture-guide.md                 - A deep dive into the architecture
├── assets                                       - Primarily image asssets for documentation
├── concepts                                     - Explanation of exchange concepts
│   ├── 01-concepts-order-book.md                - High level explanation of the order-book
│   ├── 02-concepts-order-book-deep-dive.md      - A deep dive into explaining the code of the order book
│   ├── 03-concepts-mm-quotes.md                 - Explanation of Market-Maker quotes
│   ├── 04-concepts-first-trade.md               - How to get started doing a trade
│   └── 05-concepts-trading-day.md               - Explanation of exchange sessions
├── developer                                    - Developer information
│   ├── 01-dev-practice.md                       - Developer on-boarding
│   ├── 02-ai-bot.md                             - Explanation on the use of trading-bots
│   ├── 03-experiments.md                        - Suggested experiments and exchange additions
│   └── 04-verification.md                       - How to set-up test-framework and run tests
├── javascripts                                  - Javascripts for documentation rendering
│   ├── mathjax.js                               - Typeset of LaTeX equations
│   └── mermaid-init.js                          - Render mermaid graphs
└── user-guide                                   - The main user-guide
    ├── 010-configuration.md
    ├── 160-commands.md
    ├── 040-running-the-engine.md
    ├── 060-order-types.md
    ├── 070-combos.md
    ├── 080-auctions-scheduling.md
    ├── 130-pnl-clearing.md
    ├── 050-gateway.md
    ├── 270-messages.md
    ├── 170-processes.md
    ├── 180-persistence.md
    ├── 120-risk-controls.md
    ├── 200-drop-copy.md
    ├── 900-app-alf-protocol.md
    ├── pagebreaks.lua                             - LUA filter for adding custom page-breaks
    ├── template_a4.tex                            - Light A4 LaTeX template
    ├── template_b5.tex                            - Light B5 LaTeX template
    ├── template_dark_a4.tex                       - Dark A4 LaTeX template 
    └── template_dark_b5.tex                       - Dark B5 LaTeX template
```

---

## MkDocs

The HTML site is configured in `mkdocs.yml` at the project root.

```bash
# Build the static HTML site
make docs

# Serve locally with live reload (http://localhost:8100)
make docs-serve

# Deploy to GitHub Pages
make docs-deploy
```

The site uses the [Material for MkDocs](https://squidfunk.github.io/mkdocs-material/) theme.
API documentation is generated automatically from docstrings via `mkdocstrings[python]`.

`docs/examples.md` is generated — do not edit it by hand.
Edit `docs/examples_template.md` and run `make gen-examples` instead.

---

## PDF User Guide

The User Guide is produced in **four variants** from the same Markdown source files:

| Variant | Paper | Theme | Intended use |
|---------|-------|-------|-------------|
| `mcprojsim_user_guide-<ver>.pdf` | A4 | Light | Print |
| `mcprojsim_user_guide-dark-<ver>.pdf` | A4 | Dark | Screen / tablet |
| `mcprojsim_user_guide-b5-<ver>.pdf` | B5 | Light | Print (book trim) |
| `mcprojsim_user_guide-dark-b5-<ver>.pdf` | B5 | Dark | Tablet (recommended) |

```bash
# Build all four PDF variants in parallel
make pdf-docs

# Build a single variant (example)
make ../dist/mcprojsim_user_guide-dark-b5-0.11.2.pdf
```

Output is written to `../dist/`.

### Build pipeline

```
Markdown sources
   │
   ▼ cat (concatenate)
   │
   ▼ pandoc --lua-filter pagebreaks.lua --metadata paper_format=<a4|b5>
   │         (converts Markdown → LaTeX body)
   │
   ▼ awk (inject body into LaTeX template at %%__USER_GUIDE_CONTENT__%%)
   │
   ▼ xelatex × 2  (two passes for TOC and cross-references)
   │
   ▼ dist/mcprojsim_user_guide-<variant>-<version>.pdf
```

### Why dark theme and B5?

**Dark theme:** a dark-background PDF is significantly easier on the eyes for
extended screen reading — lower brightness contrast reduces eye strain, making
it the natural choice whenever the guide is read on a tablet or laptop rather
than printed on paper.  The light variants remain available for anyone who
prefers to print the guide.

**B5 paper (176 × 250 mm):** B5 matches the aspect ratio of a 10–11 inch
tablet screen much more closely than A4 (210 × 297 mm).  The dark B5 template
also uses very narrow left and right margins so that the text fills the screen
with minimal wasted space — a layout that would look cramped on paper but is
ideal on a tablet where the reader holds the device rather than a book.

The light A4 template uses wider margins and normal line spacing, which is
better suited for printed output.

### Conditional page breaks — `pagebreaks.lua`

Because the same Markdown source is compiled into both A4 and B5 PDFs, page
breaks that look right in one format often land in the wrong place in the
other.  Rather than maintaining two copies of the source, a **pandoc Lua
filter** (`user_guide/pagebreaks.lua`) handles this transparently.

The filter is activated via `--metadata paper_format=a4` or `=b5` at pandoc
invocation time (set automatically by the Makefile). Two marker syntaxes are
available in the Markdown source:

**Between blocks** — HTML comments, safe for both MkDocs and Pandoc:

```markdown
<!-- pagebreak:any -->
<!-- pagebreak:b5 -->
<!-- pagebreak:a4 -->
```

**Inside a verbatim/code block** — inline marker line:

````markdown
```yaml
key: value
!!! yaml-cbreak-b5
key2: value2
```
````

The prefix before `-cbreak-` (e.g. `yaml`, `text`) sets the syntax-highlighting
language class of the code block that follows the break.  Markers for the
inactive format are always stripped without emitting a page break, so the same
source reads cleanly in both formats.

In the MkDocs HTML output all markers are silently removed — the filter has no
effect on the web build.

---

## Containerised documentation server

A pre-built static site can be served via a containerised nginx server.
The container is defined in `../Dockerfile.docs`.

```bash
# Build the container image
make docs-container-build

# Start the server  (http://localhost:8100)
make docs-container-start

# Stop / restart / status / logs
make docs-container-stop
make docs-container-restart
make docs-container-status
make docs-container-logs
```
