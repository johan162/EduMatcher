# How to Use This Book

This book is about an exchange that trades on its own. A hundred AI traders,
a market maker and a hidden model of what every share is really worth keep
300 order books busy all day, every trading day, for as long as you leave it
running. You watch it, teach with it, trade against it, and change how it
behaves.

| | |
|---|---|
| **Who it is for** | Instructors who want a live market for a class; students who want a market to trade in; anyone curious how prices form |
| **What you need** | A computer with Docker or Podman for the container route, or Python 3.13 and `pipx` for the hand-built route; a terminal and a browser |
| **What you do not need** | Any finance background, any Python, or a copy of the source code |
| **Time** | Ten minutes to a running market (Part I); an afternoon to understand and tune it (Part II) |

## What you will be able to do

After this book you can:

1. start a complete simulated exchange — 300 shares, 100 AI traders, a
   market maker, news — with one command, and leave it running for weeks;
2. explain how a price on the exchange can be *wrong*, what the true value
   behind it is, and how trading discovers it;
3. read the news and rumours the market model publishes, and publish your
   own to move the market in front of a class;
4. change how the traders behave — calmer, wilder, faster to react, more
   or less informed — and know which setting does what;
5. run the calendar faster than real time, so a month of trading passes in
   a day;
6. watch all of it with the browser applications and the command-line tools.

## How the book is organized

| Part | Chapters | What you get |
|---|---|---|
| **I. Start here** | A Market That Runs Itself; Ten-Minute Start | What the simulation is, and a running one |
| **II. How it works** | The True Value; News and Rumours; How the AI Traders Decide; Tuning the Traders | The model behind the prices, the traders, and every setting that changes them |
| **III. Run it** | AI Traders; Running the AI-Trader Swarm; The Market Model; A Complete Set-up by Hand; The Simulation Container; Accelerated Time | The reference for each part, and two ways to run it all |
| **IV. Watch and teach** | Watching the Market; AI Traders & News; Running It for Weeks; Troubleshooting and FAQ | What to look at, classroom exercises, and keeping it healthy |
| **Appendices** | Simulation Glossary | The words this book uses |

Part I is enough to get a market running. Part II is the heart of the book:
read it before you change anything. Part III is reference — dip into it when
you need a flag or a file. Part IV is for the days and weeks after.

!!! note "Chapters shared with other books"
    Five chapters of this book also appear in the book they were written for:
    *AI Traders* and *How the AI Traders Decide* in the Participant Guide,
    *Running the AI-Trader Swarm* and *The Market Model* in the Operator's
    Guide, and *AI Traders & News* in the Training Guide. They are the same
    text, kept in one place. Their links point into those books, and their
    examples use the smaller `s150-*` examples, started by hand. What they
    explain holds for the `s300-sim` set-up this book runs; their commands do
    not all fit the container. In the container, skip the steps that deploy
    an example (the container has deployed `s300-sim`, and the AI traders need
    it), and remove the market maker as
    [Tuning the Traders](../part-2-how-it-works/060-tuning-the-traders.md#the-market-maker)
    shows rather than with Ctrl+C: the container would restart it. Scenario
    files are in the image under
    `/opt/edumatcher/.venv/lib/python3.13/site-packages/docs/examples/news/`.

## The set-up this book runs

Everything here uses one bundled example, `s300-sim`, and one process
profile, `ai-sim`:

| | |
|---|---|
| **Symbols** | 300 shares in 11 industry sectors |
| **AI traders** | `AI001`–`AI100`, eleven kinds (presets), each trading 30 symbols |
| **Market maker** | `MM01`, a bot quoting every symbol, nudged toward the true values |
| **People** | `TRADER01`–`TRADER10` (desks for students), `OPS01` (the instructor) |
| **Market model** | A hidden true value per share, with random news and rumours |
| **Hours** | 09:00–16:05, Monday to Friday, on the Swedish calendar and clock |

The container image `edumatcher-ai-sim` is exactly this set-up, ready to run.

## Conventions

- A bare command in a `bash` block is typed in a normal terminal. Commands
  that run *inside* the simulation container say so, or start with
  `docker exec edumatcher-sim`. From an installed simulation
  (`cd ~/.edumatcher-sim`), `./edumatcher.sh shell <command>` is the same
  thing and works with Podman too; `./edumatcher.sh` also wraps `start`,
  `stop`, `status` and `logs`. Where the book says `./data-sim`, an installed
  simulation's data directory is `~/.edumatcher-sim/data`.
- `[OPS01|ADMIN]>` is the prompt of the operator console (`pm-admin`);
  `[TRADER01]>` the prompt of a trader console (`pm-alf-console`).
- Output shown in a plain block is what you should see. Prices, times and
  counts will differ on your machine: the market is random, and so is the
  moment you look at it.
- Every number this book quotes about the simulation — how far prices stray,
  how much disk a day takes, how much CPU it needs — was measured on the
  set-up it describes. Where a number depends on your machine, the book
  says on what it was measured.
- `!!! tip`, `!!! note` and `!!! warning` boxes hold advice you can skip on a
  first reading; **Checkpoint** paragraphs tell you how to know a step worked.

## Where this book sits

This is one of nine EduMatcher books. If the exchange itself is new to you,
read the [Quick Start Guide](../../quick-start/00-front/010-how-to-use-this-book.md)
first — an hour, and every chapter here will be easier. If markets are new to
you, [How an Exchange Works](../../../how-exchange-works.md) explains order
books, auctions and market makers from scratch.
