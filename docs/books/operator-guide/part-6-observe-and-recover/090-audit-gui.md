# Audit GUI (`pm-audit-ui`)

!!! note "Learning objectives"
    After reading this page you will understand:

    - What the Audit GUI is for, and how it reaches the audit trail
    - What must be configured and running, and how to start it
    - How a snapshot pins the evidence, and what the evidence banner says
    - How to read the Market canvas and the order drawer
    - How to diagnose an error it shows, what load it puts on the gateway,
      and what this release leaves out


## Overview

The **Audit GUI** (`pm-audit-ui`, `web-apps/audit-gui/`, port **8097**) is
a read-only browser client for reviewing what the exchange recorded: the
retained audit trail that `pm-audit` writes (`audit.log` and its archived
days), reconstructed with `pm-audit-replay`'s own rules. Only an **ADMIN**
key may use it; trading, market-maker and read-only keys are refused at the
login.

The browser talks to one service only: `pm-api-gwy`, through its
`/api/v1/audit` routes (and `/api/v1/status` for the login). The gateway
reads the trail itself, read-only, from the directories its configuration
names; the browser never sees a path. Nothing in the application can trade,
change the exchange or edit the evidence.

This release (R0 of the design, `docs-design/EduMatcher-Audit-GUI.md`) has
the evidence banner and the **Market** workspace. Findings, Participants,
Explorer, Integrity & Coverage and Investigations are listed and say "Not in
this release".


## What must be running

| Needs | Why |
|---|---|
| `pm-api-gwy` (the `desk` instance in the shipped stack) | It serves `/api/v1/audit` and reads the trail |
| `pm-engine` | It confirms each key and its role at the login |
| An ADMIN gateway key (`OPS01` in the bundled configurations) | Every audit route is ADMIN-only |
| `audit_collections` in the gateway's `api_gateways` block | Which trails may be read, each by an id. Omitted: one collection, `default`, the data directory (`audit.log` there and its `audit/` parts and archives) |

The gateway keeps its derivative files (pinned copies, the replay index of
each snapshot) under `data/audit-gui/`. They can be deleted at any time;
they are rebuilt on the next read. See [API Gateway](../part-5-gateways/050-api-gateway.md)
for `audit_collections` and the routes.

`pm-audit` need not be stopped: a snapshot copies the active file's complete
lines when it is pinned, so records written afterwards never change what it
shows.


## Starting it

**With the stack.** The source-built and released compose stacks run it
beside the other GUIs (`edumatcher-audit-gui`, published on `AUDIT_GUI_PORT`,
default 8097), proxying to the `desk` gateway. `./edumatcher.sh urls` and
`make up-all` list it.

**On its own, in a container.**

```bash
cd web-apps/audit-gui
API_PROXY_TARGET=http://host.containers.internal:8080 make up   # Podman
make up                                                          # Docker Desktop
```

**Without a container.**

```bash
cd web-apps/audit-gui
make install && make build
API_PROXY_TARGET=http://localhost:8080 make serve    # production build on :8097
make dev                                             # Vite on :8197, /api → localhost:8080
```

| Variable | Default | Meaning |
|---|---|---|
| `API_PROXY_TARGET` | unset (compose: `http://host.docker.internal:8080`) | Where `/api/*` goes. Unset: `/api/*` answers 503 with an explanation |
| `HOST` / `PORT` | `0.0.0.0` / `8097` | The static server's listener |
| `STATIC_DIR` | `apps/web/dist` | The built application |
| `AUDIT_GUI_PORT` | `8097` | Host port the container is published on |


## Pinning a snapshot

Log in with the ADMIN key, then choose an **evidence collection** in the top
bar. The gateway pins it as a **snapshot**: every audit file's size and
SHA-256, the active file's complete lines, the engine runs and what the
evidence can support. Every view reads that snapshot, so pages, stories and
charts never drift onto records written later, and the top bar labels the
view **Historical snapshot** with its id, how far its records reach, and
when it was pinned. Choosing the same unchanged collection again gives the
same snapshot.

A snapshot also pins two optional sources:

- the evidence **manifest** (`audit/manifest.jsonl`), checked as
  `pm-audit-cli verify` checks it;
- a **`pm-sim-forensics` report** in `forensics/` beside the collection
  directory (the tool's default `--out` for the installed data directory;
  for another collection, pass `--out <collection>/../forensics`). Its
  `findings.json` lists the audit files it read, and the report is used only
  if they are exactly the snapshot's.

The first read of a snapshot reconstructs its session (`pm-audit-replay`'s
pipeline and episode index) inside the gateway: about 6,400 records a
second, so seconds for a class session and minutes for a very large trail.
Later reads are fast. One snapshot is kept in memory at a time.


## The evidence banner

Above every workspace. Read it before anything else.

| Line | Meaning |
|---|---|
| Extent | First and last record on the receipt clock (UTC), records, engine runs |
| Gaps | Recorder gaps: the replay's `ESEQ_GAP` findings, records the engine published that `pm-audit` never received. "no recorder gap" is a measured zero |
| Manifest | **checked, unanchored**: the hash chain and every archive match, but no copy of the head hash is kept off this host, so a rewritten chain would not show. **failed**: each problem by day. **no manifest**: no day has been archived yet |
| Forensics | The report's checks per status. SKIPPED (its data was absent) and ERROR (the check broke) are never a pass |
| Active file | A partial last line of `audit.log` left out of the snapshot |
| Not available | Each analysis the evidence cannot support, with its reason code |

The banner can be folded to one line, except while a check has failed (a
failed manifest, or a FAIL or ERROR in a matching forensics report).


## The Market canvas

Open **Market** and choose a symbol. The canvas shows one symbol on one time
axis (receipt clock):

- **Depth heatmap**: the displayed quantity per price level from the recorded
  `book.<symbol>` observations only, bids blue, asks amber. An observation
  is valid until the next one, a phase change, an uncross, lost records or
  the engine stopping; nothing is interpolated. The cadence line says how
  often books were recorded; bins are never finer than its median.
- **Masks**, hatched: a **gap** (records lost: no cells) and a **halt** (the
  book observed while halted is kept). The list under the chart names each,
  with its reason.
- **Order lifelines**: each order or quote leg as a bar at its price from
  admission to its end, thicker for more displayed quantity, dashed while a
  stop is held. The end glyph says how it ended: ● filled, × owner cancel,
  ⊗ system cancel, ◌ expired, ▸ still resting, … cut by the window.
- **Trades**: ▲ buyer-initiated, ▼ seller-initiated, ◆ auction prints; and
  the **flow strip** of signed aggressive volume underneath.

Drag across the chart to zoom to an interval; **Whole session** undoes it.
Click a lifeline, or select it in the list under the chart (arrow keys,
Enter), to open the **order drawer**:

- **Story**: `pm-audit-replay`'s narration of the order, fact by fact, with
  the confidence of each link;
- **Checks**: the replay's findings on the order's episodes;
- **Raw evidence**: every record naming the order, with its payload and
  `file:line`.

The symbol, the interval and the open drawer are in the address bar: Back and
Forward step through them, and a copied link reopens the same view of the
same snapshot. The **Help** button explains every mark.


## Diagnosing what it shows

| It says | Meaning | What to do |
|---|---|---|
| "This is a TRADER key…" / "read-only key" at the login | Only ADMIN keys may read audit evidence | Log in with an ADMIN gateway's key |
| A collection listed as unavailable (`SOURCE_MISSING`) | Its directory does not exist on the gateway's host | Fix `audit_collections` or mount the directory |
| `AUDIT_SOURCE_UNAVAILABLE (SOURCE_CHANGED)` | A retained file changed after the snapshot was pinned | Pin the collection again; find out why an archived file changed |
| `CAPABILITY_UNAVAILABLE (NO_BOOK_OBSERVATIONS)` on the canvas | No `book.<symbol>` record was retained | The lifelines and the drawer still work |
| Forensics `DIFFERENT_INPUTS` | The report beside the collection read other audit files | Re-run `pm-sim-forensics` on the stopped run |
| "Gaps: counting…" for a long time | The first read is reconstructing a large session | Wait; later reads are fast |


## Load on the exchange

None on the engine beyond the login check: the gateway reads files. A first
read of a snapshot costs the gateway one reconstruction (see above); the
market model of a symbol is built once per snapshot (about 120,000 records a
second) and its queries take milliseconds for a class session. The browser
loads its chart library only when Market opens.


## What it leaves out

This release is the design's first slice (R0). Not yet: the Findings,
Participants, Explorer, Integrity & Coverage and Investigations workspaces;
replay mode and the teaching animations; the venue's timezone (times are
UTC); a run selector (the canvas shows every run of the snapshot, and each
lifeline names its run); background preparation of large snapshots; exports.
There is no trading, no control and no editing, by design.
