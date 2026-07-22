# MkDocs Hooks

This directory contains custom MkDocs hooks that extend the build process.

## section_numbering.py

Automatically adds chapter and section numbers to the user-guide documentation during HTML generation.

### How it works

1. **Chapter numbering**: Files are numbered based on their filename prefix:
   - `000-getting-started.md` → Chapter 1
   - `010-configuration.md` → Chapter 2
   - `160-commands.md` → Chapter 3
   - etc.

2. **Section numbering**: Headers within each chapter are numbered hierarchically:
   - `#` headers get chapter numbers (e.g., "1. Getting Started")
   - `##` headers get section numbers (e.g., "1.1. What is EduMatcher?")
   - `###` headers get subsection numbers (e.g., "1.2.1. End-user mode")
   - `####` headers get subsubsection numbers (e.g., "1.2.1.1. Requirements")

3. **Non-destructive**: The hook processes markdown during the build phase only. Source files remain unchanged, preserving compatibility with LaTeX PDF generation.

### Scope

- Only applies to files in the `docs/user-guide/` directory
- Other sections (concepts, architecture, developer, etc.) are unaffected
- Only processes files that start with a number prefix (e.g., `00-`, `01-`, etc.)

### Testing

Build the documentation to see the numbering in action:

```bash
poetry run mkdocs build
```

Then check the generated HTML files in `site/user-guide/`:

```bash
# View the numbered headings
grep "<h[1-4]" site/user-guide/00-getting-started/index.html | head -10
```

### Configuration

The hook is registered in `mkdocs.yml`:

```yaml
hooks:
  - docs/hooks/section_numbering.py
```

To disable numbering, simply comment out or remove this line from the configuration.
