# EduMatcher Audit GUI (`pm-audit-ui`)

A read-only, ADMIN-only web client for reviewing retained audit evidence:
it pins an evidence collection as a snapshot and reads everything through
pm-api-gwy's `/api/v1/audit` routes (design:
`docs-design/EduMatcher-Audit-GUI.md`; plan:
`docs-design/EduMatcher-Audit-GUI-Workplan.md`).

The browser talks only to its own origin. The static server (`apps/serve`)
serves the SPA and forwards `/api/*` to pm-api-gwy, which reads the audit
trail itself (its `audit_collections`). The browser never sees a path,
database or another service's address.

## What this release has

- Login with an **ADMIN** key (kept in memory for the tab only). TRADER,
  MARKET_MAKER and read-only keys are refused with a message.
- The collection picker: choosing a collection pins it as a snapshot, and
  the top bar labels the view **historical snapshot** with its id and how
  far its records reach.
- The evidence banner above every workspace: extent (receipt clock, UTC),
  records and engine runs, recorder gaps (the replay's `ESEQ_GAP` findings),
  manifest state (`checked, unanchored` / `failed` / `no manifest`), the
  attached `pm-sim-forensics` result, a torn active file, and what the
  evidence cannot support. It cannot be folded while a check has failed.
- Seven workspaces in four groups (Triage, Investigate, Trust, Conclude).
  Those not built yet say "Not in this release".

## Run it

```bash
make install          # npm workspace
make dev              # Vite on http://localhost:8197, /api -> localhost:8080
make build test typecheck
make serve            # production build on :8097 (set API_PROXY_TARGET)
make up               # container on :8097 (podman or docker)
```

`API_PROXY_TARGET` is pm-api-gwy's HTTP address as the container sees it
(`.env.example`). Unset, `/api/*` answers 503 with an explanation.

## Tests

Vitest and Testing Library. `apps/web/test/contract.test.ts` holds the Zod
schemas (`apps/web/src/api/schemas.ts`) to `spec/rest/openapi.json`:
every route the GUI reads must parse the contract's example and declare
exactly its fields.
