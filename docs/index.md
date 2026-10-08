# EduMatcher Documentation

EduMatcher is a multi-process Python trading system for learning how exchanges work in practice. It helps you build intuition for order matching, market microstructure, and exchange architecture through a runnable system. The system
is very close to a real exchange in terms of its architecture and behavior. 

There are operational differences, however, to simplify learning and experimentation. Most notably a much simplified authentication and authorization model is used compared to a real exchange. There is also no operational redundancy or fault tolerance mechanisms implemented. 

![Order book illustration](assets/exchange-and-books-illustration.png)
**Figure 1: The exchange, with order books and the central matching engine.**

## Quick start

With Podman or Docker installed, one command gets you a running exchange and
five web applications:

```bash
curl -fsSL https://raw.githubusercontent.com/johan162/EduMatcher/main/deployment/curl/install.sh | bash
cd ~/.edumatcher 
```

The exchange is now running on a bundled configuration.  
The `pm-*` commands, the control plane of the exchange, lives *inside* the container.  
Use regular Docker/Podman command to open a shell in the conainer or use the shortcut:

```bash
./edumatcher.sh shell        # then pm-help, pm-admin, pm-alf-console, pm-stats-cli, ...
```

Once inside the container, start with reviewing available commands

```bash
pm-help
```

Then, on your host, open a browser and go to the following URLs for the more user-friendly ways to trade and watch the market:

```bash
# The trading platform to buy/sell equities. Requires log-in using
# one of the API keys defined in the `engine_config.yaml`
Trader GUI       :  http://localhost:8093.

# The terminal to watch the movements of the market
Trading terminal :  http://localhost:8090

# One symbol's full order book, session statistics and trade tape
# (the browser companion to the pm-viewer command)
Order book       :  http://localhost:8094

# The central log server to observe what is happening internally
# in the exchange platform
Log viewer       :  http://localhost:8091      

# The Swagger REST-API documentation. The exchange can be
# completely run using REST commands
REST API docs    :  http://localhost:8080/docs
```


## Which book do I need?

This documentation library is organised in a number of books, each focused on a specific role or task you might have when interacting with the exchange. Choose your starting point based on the job you need to do.


| I want to... | Start here | Then open |
|---|---|---|
| Understand exchange concepts | [How an Exchange Works](how-exchange-works.md) | [Quick Start: your first trade](books/quick-start/part-1-see-it-run/030-your-first-trade.md) |
| See the system run | [Operator's Guide: installation](books/operator-guide/part-1-install-and-deploy/010-installation.md) | [Configuration workflow](books/operator-guide/part-2-configure/010-the-configuration-workflow.md) |
| Trade or make markets | [Participant Guide: trader console](books/participant-guide/part-2-orders/010-the-trader-console.md) | [Order types](books/participant-guide/part-2-orders/020-order-types.md) |
| Write a client | [Protocols and Clients: overview](books/protocols-and-clients/part-1-choosing-and-connecting/010-protocols-overview.md) | [Reference Manual: configuration schema](books/reference-manual/part-3-configuration/010-schema-and-process-blocks.md) |
| Change the code | [Architecture: overview](books/architecture-and-development/part-1-architecture/010-architecture-overview.md) | [Development practice](books/architecture-and-development/part-4-developing/010-development-practice.md) |
| Learn by doing | [Training Guide](books/training-guide/index.md) | [Training: first trade](books/training-guide/030-the-first-trade.md) |
| Diagnose a configuration or runtime problem | [Configuration workflow](books/operator-guide/part-2-configure/010-the-configuration-workflow.md) | [Reference Manual](books/reference-manual/part-3-configuration/010-schema-and-process-blocks.md) |

The [Reference Manual](books/reference-manual/part-3-configuration/010-schema-and-process-blocks.md)
is the lookup point shared by the operational, participant, protocol, and
architecture books.

## Which format do I need?

### Download the 📖EPUB

Every book is also available as an EPUB, for e-readers, screen readers, and
adjustable text size:

| Book | EPUB |
|---|---|
| 📖 Quick Start Guide | [⬇️ Download](downloads/edumatcher_quick_start.epub) |
| 📖 Participant Guide | [⬇️ Download](downloads/edumatcher_participant_guide.epub) |
| 📖 Operator's Guide | [⬇️ Download](downloads/edumatcher_operator_guide.epub) |
| 📖 Reference Manual | [⬇️ Download](downloads/edumatcher_reference_manual.epub) |
| 📖 Protocols and Clients | [⬇️ Download](downloads/edumatcher_protocols_and_clients.epub) |
| 📖 Architecture and Developer Guide | [⬇️ Download](downloads/edumatcher_architecture_and_development.epub) |
| 📖 Training Guide | [⬇️ Download](downloads/edumatcher_training_guide.epub) |

### Other formats

Each book also builds as:

| Format | Best for |
|---|---|
| A4 light | Printed reference copies |
| B5 light | Compact print and tablets (B5 is a common book size) |
| A4 or B5 dark | Screen reading in low light |
| Chapter PDF | Sharing one focused chapter |

These are build outputs, not part of this site: contributors with a checkout
of the repository can produce them with the targets in `docs/Makefile` (see
`make help` from the `docs/` directory). 

All documentation files are available to download from the [GitHub EduMatcher Releases](https://github.com/johan162/EduMatcher/releases)

## Reading paths by role

1. **New to finance:** read [How an Exchange Works](how-exchange-works.md), then the [Quick Start](books/quick-start/part-1-see-it-run/030-your-first-trade.md).
2. **Instructor:** use the [Quick Start](books/quick-start/part-1-see-it-run/030-your-first-trade.md), then the [Operator's Guide](books/operator-guide/part-1-install-and-deploy/010-installation.md) and [Training Guide](books/training-guide/index.md).
3. **Student trader:** use the [Quick Start](books/quick-start/part-1-see-it-run/030-your-first-trade.md), then the [Participant Guide](books/participant-guide/part-2-orders/010-the-trader-console.md) and [Training Guide](books/training-guide/index.md).
4. **Client developer:** use [Protocols and Clients](books/protocols-and-clients/part-1-choosing-and-connecting/010-protocols-overview.md), then the [Reference Manual](books/reference-manual/part-3-configuration/010-schema-and-process-blocks.md).
5. **Contributor:** use [Architecture](books/architecture-and-development/part-1-architecture/010-architecture-overview.md), [Development practice](books/architecture-and-development/part-4-developing/010-development-practice.md), and the [release process](books/architecture-and-development/part-5-releasing/010-release-process.md).

## First session

Start with the [Operator's Guide installation chapter](books/operator-guide/part-1-install-and-deploy/010-installation.md),
then follow the [Quick Start first-trade chapter](books/quick-start/part-1-see-it-run/030-your-first-trade.md).

## Most notably omissions

- Simplified authentication and authorization compared to a real exchange and no hierarchical support for members/participants/users type of user hierarchy. This is fully intentional for educational purposes.
- No operational redundancy or fault tolerance mechanisms such as supporting a hot standby mirror systemm..
- Lacks the operational robustness, security measures, and fault tolerance of a real exchange.
- No support for implied/synthetic orders.
- No support for atomic combo-orders, combo orders are implemened as a thin layer on top of individual order-books

## ⚠️ Not for production use
- Not intended for real financial transactions!
- Should only be used in a controlled educational environment!