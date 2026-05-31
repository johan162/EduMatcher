# EduMatcher

**Learn how real trading systems work. Build it from first principles.**

| Category          | Link                                                                                                                                                                                                                                                                                                                      |
| ----------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Package**       | [![PyPI version](https://img.shields.io/pypi/v/mcprojsim.svg)](https://pypi.org/project/mcprojsim/) [![Python 3.13+](https://img.shields.io/badge/python-3.13+-blue.svg)](https://www.python.org/downloads/)                                                                                                              |
| **Documentation** | [![Documentation](https://img.shields.io/badge/docs-mkdocs-blue)](https://johan162.github.io/edumatcher/)                                                                                                                                                                                                                 |
| **License**       | [![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)                                                                                                                                                                                                               |
| **Release**       | [![GitHub release](https://img.shields.io/github/v/release/johan162/edumatcher?include_prereleases)](https://github.com/johan162/edumatcher/releases)                                                                                                                                                                     |
| **CI/CD**         | [![Coverage](https://img.shields.io/badge/coverage-85%25-brightgreen.svg)](coverage.svg)                                                                                                                                                                                                                                  |
| **Code Quality**  | [![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black) [![Checked with mypy](https://www.mypy-lang.org/static/mypy_badge.svg)](https://mypy-lang.org/) [![Linting: flake8](https://img.shields.io/badge/linting-flake8-yellowgreen)](https://flake8.pycqa.org/) |
| Repo URL          | [![GitHub](https://img.shields.io/badge/GitHub-100000?style=flat-square&logo=github&logoColor=white)](https://github.com/johan162/edumatcher)                                                                                                                                                                             |


> [!CAUTION]
>!!! warning "Not yet ready!"
>    While the system works as designed and the documentation is mostly ready
>    the project is not. Before 1.0.0 the CI/CD pipeline needs to be completed
>    with publication to PyPi. In addition the rendered documentation also needs to be
>    put via `gh-pages` branch to actual github pages (as part of the CI/CD) process.
>    The release process will also need to be designed. Most likely similar to my other
>    project, e.g. `mcprojsim`. I will also need to consider if the docs should be released
>    as PDFs (from Latex).


EduMatcher is a comprehensive, production-grade educational trading system that teaches the fundamentals of order matching, market microstructure, and multi-process system design. Unlike toy implementations, EduMatcher is *genuinely fast and realistic* — perfect for learning how modern exchanges actually work.


| Category          | Details                                                                                    |
| ----------------- | ------------------------------------------------------------------------------------------ |
| **Purpose**       | Educational trading system: order matching engine, gateway architecture, market mechanisms |
| **Performance**   | ~160,000 orders/second with sub-10µs latency — comparable to real exchange engines         |
| **Language**      | Python 3.10+ with full type hints and comprehensive test coverage (85%+)                   |
| **Learning Path** | Audit trails → Order books → Matching algorithms → Auctions → Multi-process systems        |
| **Documentation** | Extensive docs covering concepts, architecture, configuration, and deployment              |

## What You'll Learn

EduMatcher teaches **real market mechanics** through hands-on code:

- **Order Book Dynamics**: How limit order books work, what drives price discovery, and why market microstructure matters
- **Matching Algorithms**: Fair and efficient order matching across market, limit, and combo orders
- **Trading Day Lifecycle**: Opening auctions, continuous trading, market-on-close, and clearing
- **Risk Management**: Auction mechanics, position limits, credit controls, and trade validation
- **Multi-Process Architecture**: Separate gateway and engine processes with message-based communication
- **Real Performance**: Achieve microsecond-latency execution—exactly what production systems need

## Key Features

- **Complete Trading Lifecycle**: From order entry through clearing with full audit trails
- **Multiple Order Types**: Market, Limit, STOP, STOP_LIMIT, IOC/FOK, ICEBERG, combo, and OCO workflows
- **Realistic Matching**: Price-time priority with sophisticated combo order handling
- **Market Mechanisms**: Opening auctions, intra-day auctions, circuit breakers, and clearing
- **Gateway & Engine**: Separate processes demonstrating proper exchange architecture
- **Comprehensive Configuration**: Control symbols, limits, market hours, auction rules via YAML
- **Message-Based**: FIX-like message protocol for realistic connectivity
- **Rich Reporting**: Order statistics, P&L tracking, clearing reports, and performance metrics
- **Extensive Tests**: 85%+ coverage with integration tests covering realistic trading scenarios
- **Verification Tools**: Compare results, replay trading days, and validate matching logic

## Performance

EduMatcher achieves **real-world latency** while remaining purely educational:

### Latency (engine-only, n=1,000 each)

| Order type | min (µs) | median (µs) | P80 (µs) | P90 (µs) | max (µs) |
| ---------- | -------: | ----------: | -------: | -------: | -------: |
| Limit      |      8.1 |         8.5 |      9.6 |     10.0 |       18 |
| Market     |      8.1 |         8.5 |      8.8 |      9.3 |       45 |

### Throughput

| Metric        | Value                                               |
| ------------- | --------------------------------------------------- |
| **Max TPS**   | ~160,000 orders/second                              |
| **Order mix** | 20% Market, 30% aggressive Limit, 50% passive Limit |

These numbers aren't just impressive—they're *realistic*. You're learning how production exchanges actually perform.

## Getting Started

### Quick Start

Install the project with the documentation and development dependencies:

```bash
poetry config virtualenvs.in-project true
poetry install --with dev,docs
```

Run the documentation site:

```bash
poetry run mkdocs serve
```

Then open **http://127.0.0.1:8000** for interactive learning.

To run the exchange itself, use the dedicated [Running the System](#running-the-system)
section below.

### For Developers

```bash
# install with dev tools (testing, linting, type checking)
poetry config virtualenvs.in-project true
poetry install --with dev,docs

# run the test suite
poetry run pytest tests/ -n auto

# check code quality
poetry run black --check src tests
poetry run mypy src tests
poetry run flake8 src tests
```

### Explore the Code

Start with these key areas:

- **[src/edumatcher/engine/](src/edumatcher/engine/)** — Core matching logic and order book
- **[src/edumatcher/gateway/](src/edumatcher/gateway/)** — Message handling and order validation
- **[src/edumatcher/clearing/](src/edumatcher/clearing/)** — Trade settlement and P&L calculation
- **[docs/](docs/)** — Concept guides, architecture, and trading mechanics

## Documentation

EduMatcher includes comprehensive, well-written documentation:

- **[Architecture](docs/architecture.md)** — System design and multi-process model
- **[Order Book Concepts](docs/concepts-order-book.md)** — How limit order books work
- **[Order Types](docs/order-types.md)** — Market, Limit, Pegged, combos, and more
- **[Trading Day](docs/concepts-trading-day.md)** — Market hours, auctions, clearing
- **[Matching Rules](docs/auction.md)** — Fair and efficient order matching
- **[Configuration](docs/configuration.md)** — Customize the system for your use case
- **[Verification](docs/verification.md)** — Test and replay trading scenarios
- **[Glossary](docs/glossary.md)** — Trading terminology defined

## Performance Tests

Run performance benchmarks:

```bash
# just perf tests (verbose output)
poetry run pytest -o addopts='' tests/test_perf.py -v -s -m perf -p no:cov

# throughput-only (TPS table)
poetry run pytest -o addopts='' tests/test_perf.py -v -s -m perf -k max_tps -p no:cov

# exclude from normal CI runs
poetry run pytest tests/ -m "not perf"
```

### Latest TPS sample output

The command above prints a throughput block. A recent local run produced:

| Metric              |       Value |
| ------------------- | ----------: |
| Timed orders (`n`)  |       9,900 |
| Market BUY          | 2,000 (20%) |
| Aggressive LIMIT    | 3,000 (30%) |
| Passive BUY         | 2,500 (25%) |
| Passive SELL        | 2,500 (25%) |
| Elapsed             |     0.160 s |
| Trades generated    |       7,421 |
| TPS (orders/sec)    |      61,870 |
| Mean time per order |   16.163 µs |

These values are machine-dependent and should be treated as a baseline example,
not a fixed performance guarantee.

## Why EduMatcher?

Most trading system tutorials oversimplify. EduMatcher doesn't. You get:

✅ **Real-world latency** — Microsecond-precision, no artificial delays  
✅ **Production patterns** — Message queues, multi-process architecture, proper error handling  
✅ **Complete coverage** — Opening auctions through clearing, not just simple matching  
✅ **Extensive tests** — Learn from 85%+ test coverage and realistic integration tests  
✅ **Rich documentation** — Concepts explained, diagrams provided, code heavily commented  
✅ **Actually fast** — 160K+ orders/second, so you understand performance-conscious design  

Perfect for:
- **Computer Science students** learning systems design and concurrency
- **Finance students** understanding market microstructure and trading mechanics
- **Developers** building exchange technology or trading systems
- **Anyone** curious how modern markets actually work

## Running the System

Start the runtime processes in separate terminals. A minimal manual session is:

```bash
# Terminal 1 — matching engine
poetry run pm-engine --verbose

# Terminal 2 — full event log
poetry run pm-audit --terminal

# Terminal 3 — clearing / P&L
poetry run pm-clearing

# Terminal 4 — live order book
poetry run pm-viewer --symbol AAPL

# Terminal 5 — trading gateway
poetry run pm-gateway --id GW01
```

`GW01` must exist in `engine_config.yaml` under `gateways.fix` or the gateway
will be rejected during startup.

Optional processes you will commonly add during demos:

```bash
poetry run pm-orders
poetry run pm-stats
poetry run pm-scheduler --now
```

On macOS, `./launch_all.sh` is a convenience launcher that opens the standard
process set in Terminal windows via AppleScript. It is not a generic Linux or
Windows process supervisor.

## Contributing

This is an educational project. If you find bugs, improve the documentation, or enhance the teaching value—contributions are welcome!

## Citation

If you use this tool in teaching or courses, please cite:

```text
@software{edumatcher,
  title = {EduMatcher},
  author = {Johan Persson},
  year = {2026},
  url = {https://github.com/johan162/edumatcher},
  version = {1.0.0-beta}
}
```

## License

MIT License - see [LICENSE](LICENSE).
