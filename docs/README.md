# docs/ — Documentation Source

This folder holds the source of the EduMatcher documentation library: seven
books written here, plus the separately maintained *How an Exchange Works*
book (built from `../docs-exchange-intro/`, copied here as
`how-exchange-works.md`). Everything is built in two forms from the same
Markdown:

- **HTML site** — built by [MkDocs](https://www.mkdocs.org/) (Material theme)
  for GitHub Pages; configured in `../mkdocs.yml`.
- **PDF and EPUB books** — pandoc → XeLaTeX (A4 and B5, light and dark) and
  pandoc → EPUB3, plus one PDF per chapter.

---

## Folder structure

```text
docs/
├── Makefile                 build targets for every book, the site and the downloads (make help)
├── index.md                 site home page: the library map and "start here"
├── README.md                this file
├── how-exchange-works.md    GENERATED from ../docs-exchange-intro — do not edit here
├── books/                   one directory per book, each with a book.toml manifest
│   ├── quick-start/                    Quick Start Guide
│   ├── participant-guide/              Participant Guide
│   ├── operator-guide/                 Operator's Guide
│   ├── reference-manual/               Reference Manual
│   ├── protocols-and-clients/          Protocols and Clients
│   ├── architecture-and-development/   Architecture and Developer Guide
│   └── training-guide/                 Training Guide
├── build/                   shared build assets: book.mk, book_sources.py, gen_nav.py,
│                            epub_a11y.py, LaTeX templates, pandoc Lua filters
├── assets/                  images and the cover template/image of each book
├── examples/                runnable example clients and the bundled engine configurations
├── downloads/               EPUBs and example archives published with the site
├── javascripts/, stylesheets/, hooks/, presentations/
└── dist/, .build/           generated output
```

### How a book is put together

Each book directory contains a `book.toml` manifest: the title, subtitle and
the ordered list of parts and chapter files, plus optional `frontmatter`
(every book starts with `00-front/010-how-to-use-this-book.md`) and
`backmatter`. **Order comes from the manifest, never from file names** — the
three-digit prefixes only keep directory listings readable, and directory
names (`part-4-developing`, …) may keep an old part number; readers only see
the part titles from the manifest.

To add a chapter: write the file (start with `# Title` and a
`!!! note "Learning objectives"` box, end with "Where to go next"), add it to
the book's `book.toml`, and regenerate the site navigation with `make nav`
(it runs `build/gen_nav.py`, which rewrites the generated block in
`../mkdocs.yml`). Images live in `docs/assets/` and are linked relative to the
chapter (`../../../assets/x.png`); the PDF/EPUB build rewrites those paths.

Cross-book links are ordinary relative links. Before committing, run
`python scripts/checkdocs.py` from the repository root: it checks every link
and anchor, every `pm-*` command and flag shown in a code block, every engine
configuration snippet, and the `pm-help` documentation anchors.

---

## MkDocs

```bash
make docs     # build the static HTML site (also refreshes nav and downloads)
make serve    # serve locally with live reload
```

---

## PDF and EPUB books

Every book builds in four PDF variants, as an EPUB, and as one PDF per
chapter. `make help` lists all targets; the common ones are:

| Target | Builds |
|---|---|
| `make pdf-<book>` | the four PDFs of one book (A4/B5 × light/dark), e.g. `make pdf-quick-start` |
| `make epub-<book>` | the EPUB of one book |
| `make chapters-<book>` | one A4 PDF per chapter |
| `make book-<book>` | PDFs and EPUB of one book |
| `make pdf-docs` / `make epub-docs` | every book |
| `make docs-all` | everything, including *How an Exchange Works* |

Output is written to `dist/`.

### Build pipeline

```
book.toml → ordered Markdown sources
   │
   ▼ expand-shell-outputs.py, concatenate, normalise asset paths
   │
   ▼ pandoc (Lua filters: parts, pagebreaks, admonitions; Mermaid filter)
   │
   ▼ inject into the shared LaTeX template (a4, b5, dark_a4, dark_b5)
   │
   ▼ xelatex × 2  (TOC and cross-references)
   │
   ▼ dist/edumatcher_<book>_<variant>-<version>.pdf
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
filter** (`build/filters/pagebreaks.lua`) handles this transparently.

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
```text
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
