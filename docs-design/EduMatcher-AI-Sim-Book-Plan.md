Version: 1.0.0

Date: 2026-10-10

Status: Implemented (2026-10-11) — see §7 for deviations

# EduMatcher — "AI Traders and Market Simulation": book, container and image

## 1. Goal

A newcomer can run an autonomous, simulated exchange — AI traders trading
300 symbols around a hidden true value, with news and rumours — with one
command, leave it running for weeks, watch it with the normal GUIs and CLI
tools, and understand from one book *why* prices move the way they do and
which knob changes what.

Deliverables:

1. A new book, **AI Traders and Market Simulation** (slug `ai-traders`), with
   its own cover, built by `docs/Makefile` like the other seven, and in the
   MkDocs site.
2. A new example configuration `s300-sim` tuned for a long unattended run.
3. A new container image `edumatcher-ai-sim` (multi-arch, GHCR, built in
   `publish-images.yml` with the others) and a compose set-up that runs it with
   the four web GUIs (`trader-gui`, `terminal-gui`, `log-gui`, `book-gui`).
4. Evidence that the container runs unattended: an accelerated multi-week
   soak, a real-time multi-hour run, and measured disk growth per day.

## 2. Decisions (interview 2026-10-10)

| # | Decision |
|---|---|
| S1 | Title "AI Traders and Market Simulation", slug `ai-traders` |
| S2 | Existing AI chapters are **included single-source**: the new book's manifest points at the files in their own books; they stay where they are. The book build is extended to allow that |
| S3 | Container default: **real trading hours**, 09:00–16:05 weekdays, **Europe/Stockholm**; `EM_SPEED=N` switches to accelerated time (N× faster calendar); `TZ` overridable |
| S4 | **New thin image** `edumatcher-ai-sim`, built from the same Dockerfile as `edumatcher` (a separate build stage), multi-arch, GHCR |
| S5 | Scale: **300 symbols, 100 AI agents** |
| S6 | Compose starts all four web GUIs: trader-gui, terminal-gui, log-gui, book-gui |
| S7 | Disk: **rotate, keep N days** of audit/log files; stats DB and daily AI summaries kept; growth measured and documented |
| S8 | Generated news **on** (pm-market-sim's random headlines and rumours); instructors add scripted news with `pm-news` |
| S9 | Cover: same layout and typography as the series; a **robot-trader silhouette** over a candlestick chart; "simulation" accent colour |

## 3. Assumptions — please confirm or correct

- A1. Single-source inclusion means one file can appear in two books. The
  PDF/EPUB builds and the MkDocs nav must accept that; relative links inside
  an included chapter keep pointing where they point in its home book.
  If MkDocs cannot list one page twice in the nav, the site shows the
  included chapters as links into their home books (the PDF/EPUB still
  contain them in full). Decided in WP-B1 after a spike.
- A2. The new image is the `edumatcher` image plus defaults (env, the
  `s300-sim` example, an `ai-sim` process profile). Nothing in it is a
  fork of the backend.
- A3. `s300-sim` is a new example derived from `s300-load`: the same 300
  symbols, `TRADER01`–`TRADER10`, `OPS01`, `MM01`, and `AI001`–`AI100`; sessions
  on with the Stockholm schedule; seeded MM quotes; a `market_sim.yaml`; a
  `swarm.yaml` for 100 agents (every symbol traded by about 10 agents) with the
  anchored market maker. `s300-load` stays as is.
- A4. "Runs for at least 30 days" is proven here by (a) an accelerated soak
  of the image covering 30+ trading days, (b) a real-time run of several
  hours, (c) disk growth per real trading day measured and extrapolated to
  30 days with the retention in place. My test environment is reclaimed
  every few hours, so the 30-day real-time run itself is yours; the book
  gives a checklist and a health command for it.
- A5. The book's new chapters are written for a newcomer: every command can
  be copied and run as is; every number in it was measured.

## 4. Book outline

Front matter: *How to use this book* (who it is for, three reading paths:
"just run it", "understand it", "teach with it").

| Part | Chapter | Source |
|---|---|---|
| I Start here | 010 A market that runs itself — what you will see, why it is unusual (a hidden true value, price discovery, news), the moving parts in one picture | **new** |
| | 020 Ten-minute start — the `edumatcher-ai-sim` container, opening the four GUIs, what to look at first | **new** |
| II How it works | 030 The true value — the market model in detail: log-normal steps, market/sector/symbol factors, jumps, intraday U-curve, overnight gap, compressed days, determinism; why the price is "correct but unknown"; how trading discovers it, with measured examples | **new** |
| | 040 News and rumours — scopes, kinds, sentiment vs secret impact, credibility, rumour life cycle (generated and injected), how each strategy reacts (lags, decay, value-view shift, anchored limits), what a retraction does; worked timelines from the E4/E6 runs | **new** |
| | 050 How the AI traders decide | *included*: participant-guide `020-how-the-bots-decide.md` |
| | 060 Tuning the traders — every preset parameter: what it does, its range, the behaviour you see when you raise or lower it, and recipes ("more liquidity", "faster price discovery", "a nervous market", "news-driven class"); swarm-level knobs (count, composition, budget, per_agent); market-maker anchoring; market-model and news parameters | **new** |
| III Run it | 070 AI traders | *included*: participant-guide `010-ai-traders.md` |
| | 080 Running the AI-trader swarm | *included*: operator-guide `030-ai-trader-swarm.md` |
| | 090 The market model (`pm-market-sim`) | *included*: operator-guide `090-market-model.md` |
| | 100 A complete set-up by hand — `s300-sim` from `pm-config-deploy` to a running market, process by process, with the order, the checks, and how to stop | **new** |
| | 110 The simulation container — image, compose, every environment variable, ports, volumes, GUIs, logs, upgrade, backup, reset | **new** |
| | 120 Accelerated time — `pm-scheduler --speed/--start`, `EM_SPEED`, what is compressed and what is not (wall-clock order ages, decision rates), choosing a speed, a 30-day soak in an afternoon | **new** |
| IV Watch and teach | 130 Watching the market — trader-gui, TapeDeck, book-gui, log-gui, `pm-ticker`, `pm-board`, `pm-market-sim --status`, daily summaries, stats queries; what healthy looks like | **new** |
| | 140 AI Traders & News (exercises) | *included*: training-guide `140-ai-traders.md` |
| | 150 Running it for weeks — health checks, disk, rotation, restarts, what to do when something stops | **new** |
| | 160 Troubleshooting and FAQ | **new** |
| Back | Glossary of simulation terms | **new** |

## 5. Work packages

Each WP lists its tests and acceptance criteria. "checkdocs" means
`scripts/checkdocs.py` clean; "lint" means black, flake8, mypy and pyright
clean on every changed Python file (tests included).

### Phase A — book infrastructure

**WP-A1 Single-source inclusion in the book build.**
Extend `docs/build/book_sources.py` and `gen_nav.py` so a part's `dir` may
point into another book (`../participant-guide/part-4-automated-trading`).
Spike first: PDF and EPUB build with an included chapter; MkDocs with the same
page in two navs.
- Tests: unit tests for `book_sources.sources()` (outside-dir path, duplicate
  basename still refused, missing file refused); `gen_nav.py --check` passes.
- Accept: `make pdf-ai-traders` (stub book with one included chapter) builds;
  links inside the included chapter resolve in the PDF and the site; the
  existing seven books build byte-identical navs; decision on A1 recorded.

**WP-A2 Book skeleton and Makefile.**
`docs/books/ai-traders/book.toml`, front matter, part files, empty new
chapters with headings; `BOOKS` and `COVER_TITLE_ai-traders` in
`docs/Makefile`; MkDocs nav regenerated; `docs.yml` workflow builds it.
- Tests: `make -C docs pdf-ai-traders epub-ai-traders chapters-ai-traders`;
  `gen_nav.py --check`; checkdocs.
- Accept: PDF, EPUB, chapter zip and all-format bundle are produced; the book
  appears in the site nav; CI docs workflow lists it.

**WP-A3 Cover.**
`docs/assets/cover-ai-traders-template.html` (+ generated html/png) in the
series layout; robot-trader silhouette over a candlestick chart; simulation
accent colour; built by `make cover-ai-traders` via `mkcover.sh`.
- Tests: `make cover-ai-traders`; PNG size equals the other covers.
- Accept: side-by-side with two existing covers it reads as the same series;
  you approve the PNG.

### Phase B — simulation configuration and container

**WP-B1 `s300-sim` example.**
Generator script (as `mks300.sh`), engine config (300 symbols, participants per
A3, Stockholm schedule, seeded quotes), `market_sim.yaml`, `swarm.yaml`
(100 agents, composition, `per_agent` ≈ 30, budget sized for ~1 core),
README; `pm-config-deploy --example s300-sim`; `config_deploy` example list;
curl installer allowlist.
- Tests: `TestExamples` entry; contract test: 300 symbols, `AI001`–`AI100`,
  schedule timezone; swarm/market_sim files load; news scenarios fit it
  (existing scenario test extended).
- Accept: deploys and verifies (`pm-cverifier`) clean; a 10-minute live run
  trades ≥ 290/300 symbols per 5 minutes with the anchored maker, RMS
  ln(mid/V) < 1 %, rejects < 0.1 %, total CPU measured and recorded.

**WP-B2 `ai-sim` process profile and accelerated switch.**
`pm-opctl` profile `ai-sim`: default set + anchored `pm-mm-bot` + `pm-market-sim`
+ `pm-ai-swarm --swarm <s300-sim swarm.yaml>`; `pm-scheduler --daily` with
`--speed`/`--start` taken from `EM_SPEED`/`EM_START` (mechanism chosen in the
WP: entrypoint-written profile or scheduler env vars — the smaller one).
- Tests: `test_emo_cli` profile tests; entrypoint unit test (bats or a Python
  test of the generated profile) for `EM_SPEED` unset/1/24.
- Accept: `pm-opctl-cli start --profile ai-sim` brings everything up on a
  laptop; with `EM_SPEED=24` a trading day passes in ~1 h of wall time.

**WP-B3 Retention for long runs.**
Audit-log rotation keep-N, `pm-opctl` process logs, pm-log-srv database,
stats DB, AI daily summaries, market-sim state: inventory what grows, add
keep-N where rotation already exists, add it where it is missing (smallest
change), defaults in `s300-sim`.
- Tests: unit tests for each new keep-N; rotation test with a tiny size.
- Accept: measured disk growth per real trading day for each file, and a
  30-day projection below a stated bound (target < 5 GB); documented.

**WP-B4 Image `edumatcher-ai-sim`.**
New `ai-sim` stage in `deployment/docker/Dockerfile` (`FROM` the runtime
stage): env defaults (`EM_CONFIG=s300-sim`, `EM_PROFILE=ai-sim`,
`TZ=Europe/Stockholm`, `EM_SPEED=1`), healthcheck.
- Tests: `docker build --target ai-sim` locally; container starts, health
  turns healthy; `pm-opctl-cli list` shows every process.
- Accept: image starts from scratch in < 60 s to a running market (or
  waiting for the open, with the next open shown); restarts keep the data.

**WP-B5 Compose set-up.**
`deployment/docker/compose.ai-sim.yaml` (backend from the `ai-sim` image +
the four GUIs, wired like `compose.guis.yaml`), Makefile targets
`up-sim`/`down-sim`/`sim-status`, a pull-only variant for the GHCR images
(no build needed), `.env.example` entries.
- Tests: `docker compose config` validates; a smoke script brings it up,
  waits for health, checks each GUI's HTTP port and the API `/healthz`.
- Accept: on a clean machine with Docker, `make up-sim` (or one documented
  `docker compose` command with GHCR images) gives a running market and four
  GUIs reachable on their documented ports; `make down-sim` stops cleanly.

**WP-B6 GHCR pipeline.**
`publish-images.yml`: matrix entry `edumatcher-ai-sim` (context
`deployment/docker`, target `ai-sim`, wheel built like `edumatcher`); merge job
handles the name (note: `edumatcher` is a prefix of every image name — the
digest selection must not mix them); curl installer/README mention.
- Tests: `actionlint`; a dry run of the matrix with `act` if available,
  otherwise a careful diff review; workflow_dispatch run by you on a tag.
- Accept: a release produces `ghcr.io/<owner>/edumatcher-ai-sim:<version>`
  for amd64 and arm64 next to the other six.

**WP-B7 Soak and long-run evidence.**
(a) Accelerated: image with `EM_SPEED` high enough for 30+ trading days in a
few hours; (b) real time: several hours across an open/close; (c) health
command (`sim-status`) used throughout.
- Accept: no process exits; daily summaries for every day; worker and engine
  RSS flat (±10 % after day 2); disk per day measured; results file
  `docs-design/reviews/ai-sim/B7.md`.

### Phase C — book content

**WP-C1 Part I (010, 020) and front matter.**
- Accept: a newcomer path from nothing to a running market with GUIs in ≤ 10
  minutes, every command verified on the WP-B5 set-up; one diagram of the
  moving parts; screenshots of the four GUIs (captured from the running sim).

**WP-C2 Chapter 030 The true value.**
Model equations, every `market_sim.yaml` parameter with effect and range,
determinism/seeds, compressed days; "correct but unknown" explained with a
measured price-vs-value chart from a run.
- Tests: every formula and default checked against `market_sim/model.py`,
  `config.py` (a doc-vs-code check list in the review file).
- Accept: the chart and numbers come from a recorded run; checkdocs.

**WP-C3 Chapter 040 News and rumours.**
Life cycle diagrams; generated-news rates and kinds; impact by scope (β);
reactions of `news` and `value` strategies with the actual formulas; worked
timelines (earnings, confirmed rumour, retracted rumour, sector) from E4/E6
runs; `pm-news` and scenarios.
- Accept: every behaviour claimed is shown by a recorded run or a cited test.

**WP-C4 Chapter 060 Tuning the traders.**
Every parameter of every strategy, execution style, tempo, risk, swarm and
market-maker anchoring: meaning, range, default per preset, observable
effect; ≥ 6 recipes, each with the YAML and the measured outcome.
- Tests: a script (kept in `tools/` or tests) that runs each recipe for a few
  minutes and records the metric the recipe promises.
- Accept: each recipe's promised effect is measured and quoted.

**WP-C5 Chapters 100–120 (set-up by hand, container, accelerated time).**
- Accept: every command run as written; every env var, port and volume of
  WP-B4/B5 documented and checked against the files; accelerated-time
  chapter states what is and is not compressed, with a measured example.

**WP-C6 Chapters 130, 150, 160 and glossary.**
- Accept: each "what healthy looks like" number comes from WP-B7; each FAQ
  answer reproduced; glossary covers every simulation term used in the book.

### Phase D — close-out

**WP-D1 Review and polish.**
A fresh read-through as a newcomer (separate reviewer agent with no prior
context), fix findings; cross-links from the seven books to the new one.
- Accept: reviewer findings closed; checkdocs, docs build, full test suite,
  lint all clean.

**WP-D2 Close-out.**
Results files present, plan status Implemented with deviations, commit
message proposed (no commits).

## 6. Risks

| Risk | Mitigation |
|---|---|
| One file in two MkDocs navs / two books' link contexts | Spike in WP-A1 before any writing |
| 100 agents × 300 symbols too heavy for a laptop over weeks | Measure in WP-B1; budget sized for ~1 core; document CPU/RAM |
| Real-time 30-day proof impossible in my environment | Accelerated soak + measured growth + your run with the checklist (A4) |
| `edumatcher` name prefix in the GHCR merge job | Explicit name matching in WP-B6 |
| Screenshots go stale | Captured from the WP-B5 set-up at the end (WP-D1) |

## 7. Implementation notes and deviations

Results files: [B1](reviews/ai-sim/B1.md) (live acceptance), [B7](reviews/ai-sim/B7.md)
(soak and disk), [C2](reviews/ai-sim/C2.md) (doc-vs-code), [C4](reviews/ai-sim/C4.md)
(recipes); the measurement harness in `reviews/ai-sim/harness/`.

**Changed from the plan, on measurements**

- The `ai-sim` market maker runs `--strategy symmetric` (no fade), not the
  `passive` strategy: the passive bot produced 83 % of all order messages and
  half the CPU under 100 AI traders, for the same price quality (B1).
- The swarm budget is 80 order actions a second (plan: sized for about one
  core): half a core, 1 400 trades a minute, 290/300 symbols per 5 minutes.
- Retention (WP-B3) needed new code, not only configuration:
  `pm-stats --keep-days` and `--keep-order-events-days`; `pm-clearing` prunes
  at every session close, not only at start-up; `pm-api-gwy` honoured no
  `order_retention_sec` (pre-existing bug); the RALF replay journal and API
  order retention are set by the `s300-sim` generator.
- Bugs found by the runs and fixed: `pm-setup` dropped `market_sim.yaml`;
  `pm-log-srv` shared its writer connection without the lock; `pm-mm-bot`
  scanned every order per event and leaked buffered fills; `pm-mm-bot` died
  on a not-yet-connected engine, and never heartbeat or disconnected, so the
  engine refused its restart for ever (B7).
- Recipes (C4): *Auction lesson* lost its `budget: 30` (it shrank the
  auction); *Efficient market* is described as the ceiling it measured to be;
  news and rumour recipes are measured over a day at `EM_SPEED=24`.

**Not done or done differently**

- The images (WP-B4–B6) were not built here: no container daemon, and the
  registries are blocked in this environment. The Dockerfile stage, compose
  file and workflow were validated statically (`docker compose config`,
  actionlint); the container's behaviour was exercised by running
  `entrypoint.sh` itself. Run `make -C deployment/docker build-sim` and
  `make up-sim LOCAL=1` once before relying on them.
- WP-B7 (b): no multi-hour real-time run; real-speed evidence is B1's
  16-minute runs plus a whole day at `EM_SPEED=24`. Engine RSS rose 15 % over
  34 accelerated trading days (≈ 0.3 MB a day), not shown flat.
- WP-C1: no screenshots of the four GUIs (they need the images). WP-C2: the
  measured price-vs-value comparison is a table, not a chart.
- WP-C4: the recipe script is kept as evidence under
  `reviews/ai-sim/harness/`, not in `tools/` or the tests: it drives the real
  entrypoint for hours with this environment's paths.
- WP-D1: the docs build is strict-clean except the download link to
  `downloads/edumatcher_ai_traders.epub`, which `make docs` (EPUB build, needs
  Chrome for Mermaid) creates; `test_config_gen_cli_help` needs `poetry` on
  the PATH (environment only).

