# Design Ideas

This directory is a lightweight workspace for design ideas across **EduMatcher**: both project-level concepts and supporting infrastructure ideas.

## Design Document Index

- `EduMatcher-Requirements.md`
- `EduMatcher-Feature_Implementation_Plan.md`
- `EduMatcher-BALF_Proposal.md`
- `EduMatcher-Market_Data_Protocol.md`
- `EduMatcher-MM_Quotes_Implementation_Plan.md`
- `EduMatcher-Tick_Migration_Plan.md`
- `EduMatcher-Session-gwy-command.md`
- `EduMatcher-Index.md`
- `EduMatcher-index-cb.md`
- `EduMatcher-Config-Verifier.md`
- `EduMatcher-Cleaaring.md`
- `EduMatcher-Stat-commands.md`
- `EduMatcher-Cross-host-connection.md`
- `EduMatcher-Post-Trade-Dissemination-Gateway.md`

### Build PDF Documents

PDFs can be built in both light and dark themes. From this directory, run:

```bash
make
```

To build PDFs in dark theme, run:

```bash
make dark
```

This builds PDF versions of the design markdown documents in light or dark theme and stores them in `dist/` using versioned filenames and theme-specific suffixes.

### Clean up temporary build artifacts

```bash
make clean
```

### Remove all built files including generated PDFs

```bash
make really-clean
```

> [!NOTE]
> All PDFs are generated through the shared LaTeX template: `design_template.tex` (light theme) and `design_template_dark.tex` (dark theme).
