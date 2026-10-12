# How to Use This Book

The Operator's Guide is about **running an exchange**: installing it,
configuring it, starting and supervising its processes, running a trading
day, operating the gateways, and finding out afterwards what happened —
including recovering from a crash.

| | |
|---|---|
| **Who it is for** | Instructors running EduMatcher for a class or a demonstration, and anyone operating an EduMatcher exchange |
| **What it assumes** | You have finished the [Quick Start Guide](../../quick-start/00-front/010-how-to-use-this-book.md): you have run the exchange, made a trade and deployed a configuration |
| **What it leaves to other books** | Trading as a participant ([Participant Guide](../../participant-guide/00-front/010-how-to-use-this-book.md)); every configuration field and command option ([Reference Manual](../../reference-manual/00-front/010-how-to-use-this-book.md)); protocol formats ([Protocols and Clients](../../protocols-and-clients/00-front/010-how-to-use-this-book.md)); source-level design ([Architecture and Developer Guide](../../architecture-and-development/00-front/010-how-to-use-this-book.md)) |

## How the book is organized

| Part | What you learn |
|---|---|
| **I. Install and deploy** | Every installation mode, the container networking, every directory the system uses, and the VM runtime image |
| **II. Configure** | Writing, verifying, deploying and inspecting a configuration, the form-based Configuration GUI, and ready-made examples |
| **III. Run** | Starting, monitoring, restarting and shutting down the process set, and the operator console |
| **IV. Run a market** | Listing symbols, valuation, sessions and auctions, risk controls, statistics, and the market index |
| **V. Gateways** | Starting, configuring and troubleshooting each external gateway |
| **VI. Observe and recover** | Persistence, the audit trail and replay, and the central log server |

## A first class session, chapter by chapter

If you are preparing to run EduMatcher for a class, this route covers what
you need:

1. [Installation](../part-1-install-and-deploy/010-installation.md) — pick the
   mode that suits your room; the container mode is the usual choice.
2. [The Configuration Workflow](../part-2-configure/010-the-configuration-workflow.md)
   and [Example Engine Configs](../part-2-configure/040-example-configs.md) —
   choose or build the market your students will trade.
3. [Running the Exchange](../part-3-run/010-running-the-exchange.md) — start
   it, check it, and know what to do when a process fails.
4. [Session Scheduling and Auctions](../part-4-run-a-market/030-sessions-and-scheduling.md)
   and [Risk Controls](../part-4-run-a-market/040-risk-controls.md) — run the
   trading day and keep it orderly.
5. [The Admin Console and Exchange Commands](../part-3-run/020-admin-console-and-commands.md)
   — halt a symbol, cancel orders, disconnect a participant.
6. [Statistics and Reporting](../part-4-run-a-market/060-statistics-and-reporting.md)
   and the [Log Operator Console](../part-6-observe-and-recover/050-log-console.md)
   — show the class what happened.

The [Training Guide](../../training-guide/index.md), chapters 00–19, is the
companion set of exercises for the same material.
