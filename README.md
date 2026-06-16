# EduMatcher

**Learn how real trading systems work. Build it from first principles.**

| Category          | Link         |
| ----------------- | ------------ |
| **Package**       | [![PyPI version](https://img.shields.io/pypi/v/edumatcher.svg)](https://pypi.org/project/edumatcher/) [![Python 3.13+](https://img.shields.io/badge/python-3.13+-blue.svg)](https://www.python.org/downloads/) |
| **Documentation** | [![Documentation](https://img.shields.io/badge/docs-mkdocs-blue)](https://johan162.github.io/EduMatcher/) |
| **License**       | [![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)  |
| **Release**       | [![GitHub release](https://img.shields.io/github/v/release/johan162/edumatcher?include_prereleases)](https://github.com/johan162/edumatcher/releases)  |
| **CI/CD**         | [![Coverage](https://img.shields.io/badge/coverage-84%25-brightgreen.svg)](coverage.svg)   |
| **Code Quality**  | [![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black) [![Checked with mypy](https://www.mypy-lang.org/static/mypy_badge.svg)](https://mypy-lang.org/) [![Linting: flake8](https://img.shields.io/badge/linting-flake8-yellowgreen)](https://flake8.pycqa.org/) |
| Repo URL          | [![GitHub](https://img.shields.io/badge/GitHub-100000?style=flat-square&logo=github&logoColor=white)](https://github.com/johan162/edumatcher) |

EduMatcher is an educational trading system that teaches market microstructure,
matching logic, and exchange architecture through runnable code.

Unlike toy examples, it is designed to be both understandable and fast.

## Quick Start

Bootstrap a new session directory and either generate `engine_config.yaml`
with sane defaults, or start from the sample config copied by `pm-setup`:

```bash
pm-setup
pm-config-gen --symbols AAPL MSFT --gateways TRADER01 TRADER02 OPS01:ADMIN --sessions-enabled --output engine_config.yaml
pm-engine --verbose
```

Alternative: skip `pm-config-gen` and edit the sample `engine_config.yaml`
that `pm-setup` already placed in your working directory.

If you run from source, prefix commands with `poetry run`.

## Why EduMatcher?

- Real exchange mechanics: order books, auctions, clearing, and risk controls
- Multi-process architecture: gateway, engine, audit, clearing, stats, and tooling
- Performance-aware implementation: ~60,000 orders/second with microsecond latency
- Practical protocol design: ALF (ALmost Fix) command language for gateway order entry
- Strong engineering discipline: type hints, linting, and high test coverage

## Key Features

- Complete lifecycle: order entry, matching, clearing, and audit trail
- Rich order support: MARKET, LIMIT, STOP, STOP_LIMIT, IOC/FOK, ICEBERG, combo, OCO
- Market mechanisms: opening/closing auctions and circuit breakers
- Config-driven behavior via `engine_config.yaml` which acts as reference data for EduMatcher
- Message-based process boundaries with strong observability
- Implement real risk controls such as prioce-collar, kill-switch, circuit-breaker, and mass-cancel

## Key Limitations

- No spread-order books
- No implied (synthetic) orders
- No primary-secondary site failover
- No load balancing
- Limited replay for participants that lose the connection
- No index calculations

## Performance

EduMatcher does not aim to match venues like NYSE or LSE, but it is still
fast for a pure Python educational project.


### Latency (engine-only, n=1,000 each)

| Order type | min (µs) | median (µs) | P80 (µs) | P90 (µs) | max (µs) |
| ---------- | -------: | ----------: | -------: | -------: | -------: |
| Limit      |      8.1 |         8.5 |      9.6 |     10.0 |       18 |
| Market     |      8.1 |         8.5 |      8.8 |      9.3 |       45 |

### Throughput

| Metric        | Value                                               |
| ------------- | --------------------------------------------------- |
| **Max TPS**   | ~60,000 orders/second                              |
| **Order mix** | 20% Market, 30% aggressive Limit, 50% passive Limit |

*Performance note:* price-collar and circuit-breaker checks run in the hot path
for every match. They are required for realistic risk control and add measurable cost.



## Explore the Code

Start with these key areas:

- **[src/edumatcher/engine/](src/edumatcher/engine/)** — Core matching logic and order book
- **[src/edumatcher/gateway/](src/edumatcher/gateway/)** — Message handling and order validation
- **[src/edumatcher/clearing/](src/edumatcher/clearing/)** — Trade settlement and P&L calculation

## Documentation

Full docs: [EduMatcher Documentation](https://johan162.github.io/edumatcher/)

Additional references:

- [How an Exchange Works](https://johan162.github.io/how-exchange-works/). This is a generic
document meant for SW developers with no previous financial experience. Reading this document
will give the necessary background both in finance and the core workings of an exchange.
- [ALF Protocol Appendix](https://johan162.github.io/user-guide/20-app-alf-protocol.md). `ALF` 
is the Gatewauy human protocol used to send in orders vi the `ALF` gateway. It is a drastically
simplified `FIX` inspired protocol (`ALF` = `ALmost Fix`)
- [Glossary](https://johan162.github.io/glossary/). An extensiv glossary with all commonly used
financial terms used in these documents.


## Who It's For

- Computer science students learning systems design and concurrency
- Finance students learning market microstructure and trading mechanics
- Developers building exchange technology or trading systems
- Anyone curious about how modern markets actually work


## Contributing

This is an educational project. If you find bugs, improve the documentation, or make other enhancements PRs are welcome!


## Citation

If you use this tool in teaching or courses, please cite:

```text
@software{edumatcher,
  title = {EduMatcher},
  author = {Johan Persson},
  year = {2026},
  url = {https://github.com/johan162/edumatcher},
  version = {0.3.3}
}
```

## License

MIT License - see [LICENSE](LICENSE).
