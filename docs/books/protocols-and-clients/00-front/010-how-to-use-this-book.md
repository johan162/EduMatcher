# How to Use This Book

Protocols and Clients is for **connecting your own program to EduMatcher**: a
trading client, a market-data consumer, a reconciliation tool, a dashboard or a
test harness. It describes every external protocol, how a session with each
gateway behaves, every message, and how to write and test a client.

| | |
|---|---|
| **Who it is for** | Developers of clients, feed handlers, dashboards and tools |
| **What it assumes** | You can run the exchange (the [Quick Start Guide](../../quick-start/00-front/010-how-to-use-this-book.md)) and you know the trading basics — orders, fills, the order book (the [Participant Guide](../../participant-guide/00-front/010-how-to-use-this-book.md), Part I) |
| **What it leaves to other books** | Starting and configuring the gateways ([Operator's Guide](../../operator-guide/00-front/010-how-to-use-this-book.md), Part V); how the engine works inside ([Architecture and Developer Guide](../../architecture-and-development/00-front/010-how-to-use-this-book.md)) |

## How the book is organized

| Part | What you find |
|---|---|
| **I. Choosing and connecting** | Which protocol fits which purpose, and how they compare |
| **II. Specifications** | The normative reference for ALF, BALF, CALF, RALF, LALF and the REST and WebSocket API |
| **III. Session behavior** | How the market-data and drop-copy feeds behave over time: snapshots, sequence numbers, gaps and replay |
| **IV. Writing clients** | Example client libraries in Python and C, and the spy tools that show you exactly what a gateway sends |
| **V. Message reference** | Every internal message and field, generated from the message specifications |

## Where to start

1. [Protocols Overview](../part-1-choosing-and-connecting/010-protocols-overview.md)
   tells you which protocol to use. For a dashboard or a web application, the
   REST and WebSocket API is usually the right answer.
2. Read that protocol's specification in Part II, and its session behavior in
   Part III where there is one.
3. Start from the matching example in
   [Protocol Support Library Examples](../part-4-writing-clients/030-example-libraries.md),
   and watch the gateway with a spy tool while you develop.

The Training Guide's chapters 22–27 are exercises against each live gateway.
