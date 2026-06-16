# docs-exchange-intro

This directory contains the source and build pipeline for the Exchange Intro book PDF.

## Structure

The book is organized by a top-level manifest and a chapter-per-file source tree.

- `book.toml`: single source of truth for document order
- `src/00-frontmatter/`: title page/preface/introduction content
- `src/01-foundation/`: Part I chapters
- `src/02-orders-and-matching/`: Part II chapters
- `src/03-risk-and-compliance/`: Part III chapters
- `src/04-technology-and-infrastructure/`: Part IV chapters
- `src/90-backmatter/`: glossary and references

Each part directory uses:

- `00-part.md` for the part opener
- one file per chapter (numbered, e.g. `01-...md`, `02-...md`)

## Manifest (`book.toml`)

`book.toml` defines exact build order and keeps the four-part book structure explicit.

Sections:

- `[frontmatter]`: ordered list of frontmatter files
- `[[parts]]`: repeated part blocks with:
  - `title`
  - `dir`
  - ordered `files` list
- `[backmatter]`: ordered list of closing files

Build order is taken from this manifest, not from filesystem sorting.

## Build flow

The Makefile resolves sources from `book.toml` via:

- `scripts/book_sources.py`

Then it runs the existing pipeline:

1. expand `{{!cmd...}}` placeholders
2. concatenate ordered markdown
3. convert to LaTeX with Pandoc + Lua filters
4. inject into LaTeX templates
5. compile the four PDF variants with XeLaTeX

## Commands

From this directory:

```bash
make pdf-docs
make clean
```

## Editing guidelines

When adding a chapter:

1. Add a new chapter markdown file in the correct part directory.
2. Insert that filename in the correct position in `book.toml` under that part's `files` list.
3. Rebuild with `make pdf-docs`.

When adding a new part-level intro paragraph, update the part's `00-part.md`.

Do not rely on filename sorting to control chapter order. Always update `book.toml`.

## Example: Add one chapter in Part II

Suppose you add this file:

`src/02-orders-and-matching/12-order-amendments.md`

Then update the Part II `files` list in `book.toml`:

```toml
[[parts]]
title = 'Part II: Orders, Matching, and the Trading Day'
dir = 'src/02-orders-and-matching'
files = [
  '00-part.md',
  '01-the-order-the-fundamental-unit.md',
  '02-order-types-the-vocabulary-of-intent.md',
  '03-time-in-force-how-long-should-the-order-live.md',
  '04-the-order-book-the-exchange-s-memory.md',
  '05-price-time-priority-the-fairness-rule.md',
  '06-the-matching-engine-the-heart-of-the-exchange.md',
  '07-the-life-of-a-trade.md',
  '08-market-makers-the-providers-of-liquidity.md',
  '09-the-opening-and-closing-auction.md',
  '10-trading-sessions-the-day-in-the-life-of-a-market.md',
  '11-putting-it-all-together.md',
  '12-order-amendments.md',
]
```

Rebuild to verify ordering and rendering:

```bash
make pdf-docs
```
