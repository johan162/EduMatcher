# EduMatcher

**Learn how market microstructure end exchanges works.**

| Category          | Link         |
| ----------------- | ------------ |
| **Repo URL**      | [![GitHub](https://img.shields.io/badge/GitHub-100000?style=flat-square&logo=github&logoColor=white)](https://github.com/johan162/edumatcher) |
| **Package**       | [![GitHub release](https://img.shields.io/github/v/release/johan162/edumatcher?include_prereleases)](https://github.com/johan162/edumatcher/releases) [![PyPI version](https://img.shields.io/pypi/v/edumatcher.svg)](https://pypi.org/project/edumatcher/) [![Python 3.14+](https://img.shields.io/badge/python-3.14+-blue.svg)](https://www.python.org/downloads/) |
| **Documentation** | [![Documentation](https://img.shields.io/badge/docs-mkdocs-blue)](https://johan162.github.io/EduMatcher/) |
| **CI/CD**         | [![CI](https://github.com/johan162/EduMatcher/actions/workflows/ci.yml/badge.svg)](https://github.com/johan162/EduMatcher/actions/workflows/ci.yml) |
| **Code Quality**  | [![Coverage](https://img.shields.io/badge/coverage-91%25-darkgreen.svg)](https://github.com/johan162/EduMatcher/actions/workflows/ci.yml)  [![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black) [![Checked with mypy](https://www.mypy-lang.org/static/mypy_badge.svg)](https://mypy-lang.org/) [![Linting: flake8](https://img.shields.io/badge/linting-flake8-yellowgreen)](https://flake8.pycqa.org/) |
| **License**       | [![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)  |

## Introduction

EduMatcher is an educational trading simulation system that teaches financial market microstructure,
principles, matching logic, and exchange architecture through runnable code paired with *extensive* documentation and references.

It is based on public- and academic-research literature, including the following primary references:

- Harris, Larry. *Trading and Exchanges: Market Microstructure for Practitioners*. Oxford University Press, 2003. ISBN 978-0-19-514470-3.
- Natenberg, S. *Option Volatility and Pricing*. McGraw-Hill, 2nd edition, 1994. ISBN 978-1-55738-486-7
- Hasbrouck, Joel. *Empirical Market Microstructure: The Institutions, Economics, and Econometrics of Securities Trading*. Oxford University Press, 2007. ISBN 978-0-19-530164-3
- CME Group, *Matching Algorithms Explained*. [Link](https://databento.com/blog/cme-matching-algorithms-explained)
- CME Group, *Matching Algorithm Reference*. [Link](https://cmegroupclientsite.atlassian.net/wiki/display/EPICSANDBOX/CME+Globex+Matching+Algorithms)
- NYSE Pillar,  Pillar Functional Differences Guide, [Link](https://www.nyse.com/publicdocs/nyse/markets/nyse-pillar/Pillar_Functional_Differences_Guide.pdf)
- NYSE, Order Type Matrix, [Link](https://www.nyse.com/publicdocs/nyse/NYSE_Pillar_FIX_Gateway_Order_Type_Matrix.xlsx)
- Eurex, *Matching Principles*. [Link](https://www.eurex.com/ex-en/trade/order-book-trading/matching-principles)
- Eurex, *How the market works (price collars, etc)*. [Link](https://www.euronext.com/sites/default/files/euronext_derivatives_how_the_market_works-v2.pdf)

It is a simulation of an exchange, not a simulation of one component: a matching engine, a session
scheduler, order-entry and market-data gateways, clearing, audit and statistics services, 
browser front-ends, and its own wire protocols — all running as separate processes that talk to each other.

## Quick start

### A buzzling and hustling live simulated exchange with 100 of other traders

With Podman or Docker installed, one command gets you a running simulation with 300 made up symbols for fictious companies in different sectors and 100 automated traders that you can watch live and connect to and trade to/with. This is a sophisticated simulation with an advanced market model including news and roumours that affects price discovery. Its the best way to get a feeling of trading in a market. The simulation
itself produces around 3 million orders per day.

```bash
curl -fsSL https://raw.githubusercontent.com/johan162/EduMatcher/main/deployment/curl/install.sh \
| bash -s -- --sim
cd ~/.edumatcher-sim
```

### A clean exchange with only you as a trader

With Podman or Docker installed, one command gets you a running simulation and
five web applications with only two default traders. This will be a silent market as only your actions will move it. 

```bash
curl -fsSL https://raw.githubusercontent.com/johan162/EduMatcher/main/deployment/curl/install.sh \
| bash
cd ~/.edumatcher 
```

The simulation exchange is now running on a bundled configuration.  
The `pm-*` commands, the control plane of the exchange, lives *inside* the container. 

### Commands to try

Regardless if you started an empty or populated simulation  you run it and trade 
within it in the exact same way:

The install script will print out more information at startup. To get started open a shell within the container:

```bash
cd ~/.edumatcher-sim     # Everything lives in this directory
./edumatcher.sh shell    # Open a shell within the container
pm-help                  # Print help of all available commands
pm-alf-console           # Open the ALF console to interact with the market (send orders)
```

Then, on your host, open a browser and go to the following URLs for the more user-friendly ways to trade and watch the market:

```bash
# The trading platform to buy/sell equities. Requires log-in using
# one of the API keys defined in the `engine_config.yaml`
Trader GUI          :  http://localhost:8093.

# The terminal to watch the movements of the market
Trading terminal    :  http://localhost:8090

# One symbol's full order book, session statistics and trade tape
# (the browser companion to the pm-viewer command)
Order book          :  http://localhost:8094

# The exchange operator dashboard
Operator dashboard  : http://localhost:8095

# The central log server to observe what is happening internally
# in the exchange platform
Log viewer          :  http://localhost:8091      

# The Swagger REST-API documentation. The exchange can be
# completely run using REST commands
Clearing read-only  :  http://localhost:8096

# The Swagger REST-API documentation. The exchange can be
# completely run using REST commands
REST API docs       :  http://localhost:8080/docs
```

Configuring the exchange can be done by either 1) Manually edit the config YAML file (and then verify/lint it with `pm-cverifier`) or, 2) generate it in scripts using the `pm-config-gen` tool or, 3) using the Web application reachable at :

```bash
# Configuring the exchange reference data
Config builder   :  http://localhost:8092
```

## Run from a plain Python pip/x 

Prefer a Python package? `pipx install edumatcher`, then `pm-setup`. The web
applications are not in the package, but they are published as ready-built
containers and can be run next to your pipx exchange (plain or simulation) with
`curl -fsSL https://raw.githubusercontent.com/johan162/EduMatcher/main/deployment/curl/install.sh | bash -s -- --guis`.
Both routes, and three more, are covered in
**[Installation](https://johan162.github.io/EduMatcher/books/operator-guide/part-1-install-and-deploy/010-installation/)**.

New here? The **[Quick Start Guide](https://johan162.github.io/EduMatcher/books/quick-start/00-front/010-how-to-use-this-book/)**
takes you from the command above to a first trade, a full trading day and a
venue of your own, with a checkpoint at every step.


## Documentation

Main documentation site [EduMatcher Documentation](https://johan162.github.io/EduMatcher/) that among other things includes:

- **[How an Exchange Works](https://johan162.github.io/EduMatcher/how-exchange-works/)**: a primer on exchange mechanics and market microstructure concepts aimed at software developers with no prior financial experience
- **[Exchange Concepts](https://johan162.github.io/EduMatcher/books/participant-guide/part-1-trading-basics/020-the-order-book/)**: deep dive in core technical concept of an exchange
- **[Quick Start Guide](https://johan162.github.io/EduMatcher/books/quick-start/00-front/010-how-to-use-this-book/)**: install, first trade, a full trading day and your own configuration, step by step
- **[Participant Guide](https://johan162.github.io/EduMatcher/books/participant-guide/part-1-trading-basics/010-gateways-and-how-you-connect/)**, **[Operator's Guide](https://johan162.github.io/EduMatcher/books/operator-guide/part-1-install-and-deploy/010-installation/)**, **[Protocols and Clients](https://johan162.github.io/EduMatcher/books/protocols-and-clients/part-1-choosing-and-connecting/010-protocols-overview/)** and **[Reference Manual](https://johan162.github.io/EduMatcher/books/reference-manual/part-1-command-line/010-processes-environment-and-ports/)**: trading, running an exchange, connecting clients, and looking things up
- **[Training Material](https://johan162.github.io/EduMatcher/books/training-guide/)**: self-paced exercises to learn how to setup and manage the Exchange
- **[AI Traders and Market Simulation](https://johan162.github.io/EduMatcher/books/ai-traders/00-front/010-how-to-use-this-book/)**: an exchange that trades itself — AI traders, hidden true values, news and rumours — in one container that runs for weeks
- **[Architecture](https://johan162.github.io/EduMatcher/books/architecture-and-development/part-1-architecture/010-architecture-overview/)**: an overview of the SW architecture
- **[Developer Guide](https://johan162.github.io/EduMatcher/books/architecture-and-development/part-4-developing/010-development-practice/)**: deep dive into the architecture, design decisions, and code structure. Necessary reading for anyone wanting to contribute!
- **[Glossary](https://johan162.github.io/EduMatcher/books/reference-manual/90-backmatter/010-glossary/)**: the finance world uses lot of specialized terms, this glossary lists the most important with an explanation

***Note:** Running an exchange is an inherently complex task and there is only
so much that can be simplified and still keep it realistic. The user guide and training material are built
to get you through it!

## Key Features

- Complete lifecycle: order entry, matching, clearing, and audit trail
- End-of-day settlement (`pm-eod`): daily mark-to-market settlement in a fictional currency, a statement for every trader, and automatic housekeeping (audit archive, log compression, verified database backups)
- Rich order support: MARKET, LIMIT, STOP, STOP_LIMIT, IOC/FOK, ICEBERG, combo, OCO
- Market mechanisms: opening/closing auctions
- Risk handling with circuit breakers and price collars
- Message-based process boundaries with strong observability
- Real risk controls: price collars, kill switch, circuit breakers, and mass cancel
- Easy to understand configuration through single source `engine_config.yaml` which acts as the system reference data. To simplify its creation either Web-based tool (`http://localhost:8092/`) or a CLI tool `pm-config-gen` can be used. In addition it is of course possible to manually create a handwritten config file that can be verified with `pm-cverifier`. To guarantee correctness and that it is a single-source of truth the YAML file is then compiled and checked by `pm-deploy-config` to be automatically stored in the canonical location used by the system.

## Limitations

- Limited authentication & no authorization 
- Only rudimentary settling and clearing mechanisms (no margining or collateral management)
- Basic set of order types
- No combo-order books (combo orders are supported with coupled order books)
- No implied (synthetic) orders
- No primary-secondary site failover
- No replay functionality on the bus for clients connecting after the opening

## Contributing

Contributions are welcome. Start with the
**[Developer Guide](https://johan162.github.io/EduMatcher/books/architecture-and-development/part-4-developing/010-development-practice/)**,
which covers the development environment, testing and the conventions this
project follows. For business-focused assertions and test-design expectations,
see the [testing guidelines](docs-design/EduMatcher-Testing-Guidelines.md) and
the [test methodology and efficiency workplan](docs-design/EduMatcher-Test-Methodology-and-Efficiency-Plan.md).
Then open an issue or pull request on
[GitHub](https://github.com/johan162/EduMatcher/issues).

Release notes for every version are in [CHANGELOG.md](CHANGELOG.md).

## Citation

If you use this tool in teaching or courses, please cite:

```text
@software{edumatcher,
  title = {EduMatcher},
  author = {Johan Persson},
  year = {2026},
  url = {https://github.com/johan162/EduMatcher},
  version = {0.79.0}
}
```

## License

MIT License - see [LICENSE](LICENSE).
