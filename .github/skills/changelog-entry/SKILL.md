---
name: changelog-entry
description: "Write a new CHANGELOG.md entry for an edumatcher release. Use when: drafting release notes, updating the changelog before running mkrelease.sh, writing a new version section, summarising changes for a release, or preparing the changelog entry that mkrelease.sh will commit."
argument-hint: "Optional: version number (e.g. v0.8.0) and release type (patch/minor/major)"
---

# CHANGELOG Entry Writer

## Purpose

Generate a correctly formatted `CHANGELOG.md` entry for a new `edumatcher` release, matching the section layout that `scripts/mkrelease.sh` produces and that is established in the existing `CHANGELOG.md`.

---

## When to Use

- Before running `scripts/mkrelease.sh` to pre-fill release notes
- After a sprint or development cycle to summarise changes
- When `mkrelease.sh` creates the empty template and you want AI help filling it

---

## Required Format

Every entry **must** follow this exact structure. Omit sections that have no content — do **not** leave placeholder bullets.

```markdown
## [vX.Y.Z] - YYYY-MM-DD

Release Type: <patch | minor | major>

### 📋 Summary
One or two sentences describing the overall theme of the release.

### ⚠️ Breaking Changes
- <change> (omit section entirely if none)

### ✨ Additions
- <new feature or capability>

### 🚀 Improvements
- <improvement to existing behaviour>

### 🐛 Bug Fixes
- <fix> (omit section entirely if none)

### 📚 Documentation
- <doc change> (omit section entirely if none)

### 🛠 Internal
- <internal refactor, test, tooling, CI change>
```

### Rules

| Rule | Detail |
|------|--------|
| Version header | `## [vX.Y.Z] - YYYY-MM-DD` — brackets around tag, dash before date |
| Release Type line | Plain text `Release Type: patch` immediately after the header, no bullet |
| Section order | Summary → Breaking → Additions → Improvements → Bug Fixes → Documentation → Internal |
| Emoji | Each section uses the exact emoji prefix shown above — do not substitute |
| Bullet style | Standard Markdown `- ` bullet, one item per line |
| Omit empty sections | Drop the heading entirely rather than writing "None" or leaving placeholder text |
| Sentence style | Start each bullet with a capital letter; end without a period unless the sentence is complex |
| Present tense verbs | "Added", "Fixed", "Improved", "Updated" — past-tense action words |
| Trailing blank line | Leave one blank line after the last bullet before the next `##` version block |

---

## Procedure

1. **Gather context** — read the git log since the last tag:
   ```bash
   git log $(git describe --tags --abbrev=0)..HEAD --oneline
   ```
2. **Read recent CHANGELOG.md** — skim the last two entries to match tone and granularity.
3. **Determine release type**:
   - `patch` — bug fixes, docs, internal tooling only
   - `minor` — new features, improvements, no breaking API changes
   - `major` — breaking changes present
4. **Draft the entry** — follow the format above; group related commits into meaningful bullets rather than mirroring each commit verbatim.
5. **Prepend to CHANGELOG.md** — the new entry goes at the very top of the file, before all existing entries.
6. **Verify** — run a quick sanity check:
   ```bash
   grep "^## \[" CHANGELOG.md | head -5
   ```
   The new tag should appear first.

---

## Section Guidance

### 📋 Summary
Write 1–3 sentences. Cover the main theme ("This release adds sprint planning…"). Avoid listing every feature — that belongs in the sections below.

### ⚠️ Breaking Changes
Include **only** changes that require users to update their project files, config, CLI flags, or Python API calls. If none exist, omit this section entirely.

### ✨ Additions
New commands, new fields, new tools, new exporters, new CLI flags, new MCP tools.

### 🚀 Improvements
Changes to existing behaviour that are non-breaking: performance, error messages, UX polish, expanded options.

### 🐛 Bug Fixes
Each fix should reference the symptom, not the code change. Mention issue numbers where applicable (`Closes #N`).

### 📚 Documentation
Changes to `docs/`, `README.md`, `QUICKSTART.md`, example files, docstrings, or user-guide pages.

### 🛠 Internal
Test additions, CI changes, script/tooling updates, refactors with no user-visible effect, dependency bumps.

---

## Example Entry

```markdown
## [v0.8.0] - 2026-04-15

Release Type: minor

### 📋 Summary
This release adds PDF export for simulation results and improves CLI output
formatting for large projects.

### ✨ Additions
- Added `--export-pdf` flag to the `simulate` command for generating a PDF report
- Added configurable page size and font options for PDF output via `config.yaml`

### 🚀 Improvements
- Improved ASCII table output to truncate long task names with ellipsis instead of wrapping
- Improved HTML export template to include sprint burn-up charts when sprint data is present

### 🐛 Bug Fixes
- Fixed `--target-date` calculation ignoring calendar holidays on resource-constrained projects

### 📚 Documentation
- Added PDF export section to the User Guide
- Updated README quick-start example to show `--export-pdf`

### 🛠 Internal
- Added PDF export integration tests covering page count and section presence
- Bumped `reportlab` dependency to 4.1.0
```
