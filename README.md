# EduMatcher

**Learn how real trading systems work. Build it from first principles.**

| Category          | Link         |
| ----------------- | ------------ |
| **Package**       | [![PyPI version](https://img.shields.io/pypi/v/edumatcher.svg)](https://pypi.org/project/edumatcher/) [![Python 3.13+](https://img.shields.io/badge/python-3.13+-blue.svg)](https://www.python.org/downloads/) |
| **Documentation** | [![Documentation](https://img.shields.io/badge/docs-mkdocs-blue)](https://johan162.github.io/EduMatcher/) |
| **License**       | [![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)  |
| **Release**       | [![GitHub release](https://img.shields.io/github/v/release/johan162/edumatcher?include_prereleases)](https://github.com/johan162/edumatcher/releases)  |
| **CI/CD**         | [![Coverage](https://img.shields.io/badge/coverage-86%25-brightgreen.svg)](coverage.svg)   |
| **Code Quality**  | [![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black) [![Checked with mypy](https://www.mypy-lang.org/static/mypy_badge.svg)](https://mypy-lang.org/) [![Linting: flake8](https://img.shields.io/badge/linting-flake8-yellowgreen)](https://flake8.pycqa.org/) |
| Repo URL          | [![GitHub](https://img.shields.io/badge/GitHub-100000?style=flat-square&logo=github&logoColor=white)](https://github.com/johan162/edumatcher) |

EduMatcher is an educational trading system that teaches market microstructure,
matching logic, and exchange architecture through runnable code.

## Why EduMatcher?

- Real exchange mechanics: order books, auctions, clearing, and risk controls
- Multi-process architecture: gateway, engine, audit, clearing, stats, and tooling
- Performance-aware implementation: ~60,000 orders/second with microsecond latency
- Practical protocol design: ALF (ALmost Fix) command language for gateway order entry, RALF (Reconciliation ALF) for post trade consumers and CALF (Channel ALF) to serve market data to subscribers
- Strong engineering discipline: type hints, linting, and high test coverage

## Key Features

- Complete lifecycle: order entry, matching, clearing, and audit trail
- Rich order support: MARKET, LIMIT, STOP, STOP_LIMIT, IOC/FOK, ICEBERG, combo, OCO
- Market mechanisms: opening/closing auctions 
- Risk handling with circuit breakers and price collars
- Message-based process boundaries with strong observability
- Implement real risk controls such as prioce-collar, kill-switch, circuit-breaker, and mass-cancel
- Easy to understand configuration through single source `engine_config.yaml` which acts as the system reference data. To simplify its creation a CLI tool `pm-config-gen` can be used and a handwritten config file can be verified with `pm-cverifier` 

## Key Functional Limitations

- No spread-order books
- No implied (synthetic) orders

## Key Infrastructure Limitations

- No primary-secondary automatic site failover
- No load balancing
- Limited replay for participants that lose the connection


## Performance

EduMatcher does not aim to match venues like NYSE or LSE, but it is still fairly
fast for a purely Python educational project. 
The figures below reflect the performance on an high end Linux server
with risk checks enabled (price collar and circuit-breaker).

On an ARM M1 MacBook the throughput is roughly 115,000 TPS and latencies are about 35% lower.


### Latency (engine-only, n=1,000 each)

| Order type | min (µs) | median (µs) | P80 (µs) | P90 (µs) | max (µs) |
| ---------- | -------: | ----------: | -------: | -------: | -------: |
| Limit      |     13.1 |        15.0 |     15.4 |     15.7 |    155.7 |
| Market     |     12.1 |        13.9 |     15.2 |     15.7 |     73.6 |


### Throughput

| Metric        | Value                                               |
|---------------|-----------------------------------------------------|
| **Max TPS**   | ~81,000 orders/second                               |
| **µs / order (mean)** | 12.4 µs                                     |
| **Order mix** | 20% Market, 30% aggressive Limit, 50% passive Limit |

*Performance note:* price-collar and circuit-breaker checks run in the hot path
for every match. They are required for realistic risk control and add measurable cost.


## Documentation

Main documentation site [EduMatcher Documentation](https://johan162.github.io/EduMatcher/) that among other things includes:

- **[How an Exchange Works](https://johan162.github.io/EduMatcher/how-exchange-works/)**: a primer on exchange mechanics and market microstructure concepts aimed at software developers with no prior financial experience
- **[Exchange Concepts](https://johan162.github.io/EduMatcher/concepts/01-concepts-order-book/)**: deep dive in core technical concept of an exchange
- **[User Guide](https://johan162.github.io/EduMatcher/user-guide/00-getting-started/)**: step-by-step instructions for installation, configuration, and running EduMatcher
- **[Training Material](https://johan162.github.io/EduMatcher/training/)**: self-paced exercises to learn how to setup and manage the Exchange
- **[Architecture](https://johan162.github.io/EduMatcher/architecture/01-architecture/)**: an overview of the SW architecture
- **[Developer Guide](https://johan162.github.io/EduMatcher/developer/01-dev-practice/)**: deep dive into the architecture, design decisions, and code structure. Necessary reading for anyone wanting to contribute!
- **[Glossary](https://johan162.github.io/EduMatcher/glossary/)**: the finance world uses lot of specialized terms, this glossary lists the most important with an explanation


## Installing

See [User Guide: Installation](https://johan162.github.io/EduMatcher/user-guide/00-getting-started/#installation)

***Note:** Running an exchange is an inherent complex task and unfortunately it is only so much that can be simplified. However, going throught the user guide and training material should give a great start!*


## Citation

If you use this tool in teaching or courses, please cite:

```text
@software{edumatcher,
  title = {EduMatcher},
  author = {Johan Persson},
  year = {2026},
  url = {https://github.com/johan162/EduMatcher},
  version = {0.13.3}
}
```

## License

MIT License - see [LICENSE](LICENSE).
