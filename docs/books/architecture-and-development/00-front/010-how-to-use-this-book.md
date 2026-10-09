# How to Use This Book

The Architecture and Developer Guide explains **how EduMatcher is built and
why**, and gives contributors what they need to change it safely: the process
and message architecture, the matching engine and order book, an order's path
through the code, the development workflow, verification, and releases.

| | |
|---|---|
| **Who it is for** | Contributors and reviewers, and teachers who use the code as a case study |
| **What it assumes** | You have run the exchange (the [Quick Start Guide](../../quick-start/00-front/010-how-to-use-this-book.md)), read Python comfortably, and know the trading basics from the [Participant Guide](../../participant-guide/00-front/010-how-to-use-this-book.md), Part I |
| **What it leaves to other books** | Using and operating the system (the Participant and Operator's Guides); protocol formats ([Protocols and Clients](../../protocols-and-clients/00-front/010-how-to-use-this-book.md)) |

## How the book is organized

| Part | What you learn |
|---|---|
| **I. Architecture** | Why the system is a set of processes on a message bus, how they are connected, and a guided tour of the whole design |
| **II. Inside the engine** | The order book's data structures and matching algorithm, and one order's path through the engine, step by step |
| **III. Developing** | Setting up, the development loop, deterministic verification, message generation, containers and networks, and ideas for extensions |
| **IV. Releasing** | How a release is produced and published |

## Where to start

- **To understand the design:** [Architecture](../part-1-architecture/010-architecture-overview.md),
  then [Order Flow Through the Engine](../part-2-inside-the-engine/020-order-flow-end-to-end.md).
- **To make a change:** [Development Practice](../part-4-developing/010-development-practice.md)
  and [The Development Loop](../part-4-developing/020-development-workflow.md),
  then the chapters for the area you are changing.
- **For design decisions:** the design notes in the repository's `docs-design/`
  directory record the reasoning behind each major feature.
