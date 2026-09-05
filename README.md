# EduMatcher

**Learn how real trading systems work. Build it from first principles.**

| Category          | Link         |
| ----------------- | ------------ |
| **Repo URL**      | [![GitHub](https://img.shields.io/badge/GitHub-100000?style=flat-square&logo=github&logoColor=white)](https://github.com/johan162/edumatcher) |
| **Package**       | [![GitHub release](https://img.shields.io/github/v/release/johan162/edumatcher?include_prereleases)](https://github.com/johan162/edumatcher/releases) [![PyPI version](https://img.shields.io/pypi/v/edumatcher.svg)](https://pypi.org/project/edumatcher/) [![Python 3.13+](https://img.shields.io/badge/python-3.13+-blue.svg)](https://www.python.org/downloads/) |
| **Documentation** | [![Documentation](https://img.shields.io/badge/docs-mkdocs-blue)](https://johan162.github.io/EduMatcher/) |
| **CI/CD**         | [![CI](https://github.com/johan162/EduMatcher/actions/workflows/ci.yml/badge.svg)](https://github.com/johan162/EduMatcher/actions/workflows/ci.yml) |
| **Code Quality**  | [![Coverage](https://img.shields.io/badge/coverage-84%25-green.svg)](https://github.com/johan162/EduMatcher/actions/workflows/ci.yml)  [![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black) [![Checked with mypy](https://www.mypy-lang.org/static/mypy_badge.svg)](https://mypy-lang.org/) [![Linting: flake8](https://img.shields.io/badge/linting-flake8-yellowgreen)](https://flake8.pycqa.org/) |
| **License**       | [![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)  |


EduMatcher is an educational trading system that teaches market microstructure,
matching logic, and exchange architecture through runnable code.

It is a real exchange, not a simulation of one: a matching engine, a session
scheduler, order-entry and market-data gateways, clearing, audit and statistics
services, browser front-ends, and its own wire protocols — all running as
separate processes that talk to each other the way a real venue's do.

## Quick start

With Podman or Docker installed, one command gets you a running exchange and
four web applications:

```bash
curl -fsSL https://raw.githubusercontent.com/johan162/EduMatcher/main/deployment/curl/install.sh | bash
cd ~/.edumatcher && ./edumatcher.sh start
```

Then open <http://localhost:8090> for the market display,
<http://localhost:8091> for the log console, and <http://localhost:8093> for the
trading terminal.

Prefer the Python package? `pipx install edumatcher`, then `pm-setup`. Both
routes, and three more, are covered in
**[Installation](https://johan162.github.io/EduMatcher/user-guide/005-installation/)**.

New here? **[A Path Through the Guide](https://johan162.github.io/EduMatcher/user-guide/001-learning-path/)**
is a staged route from the command above to running a venue of your own, with a
checkpoint at every step.

## Why EduMatcher?

- Real exchange mechanics: order books, auctions, clearing, and risk controls
- Multi-process architecture: gateway, engine, audit, clearing, stats, and tooling
- Performance-aware implementation: ~80,000 orders/second with microsecond latency on a Linux server
- Practical protocol design: ALF (ALmost Fix) command language for gateway order entry, RALF (Reconciliation ALF) for post trade consumers and CALF (Channel ALF) to serve market data to subscribers, and finally BALF (Binary ALF) for high performance trade clients
- Strong engineering discipline: type hints, linting, and high test coverage

## Key Features

- Complete lifecycle: order entry, matching, clearing, and audit trail
- Rich order support: MARKET, LIMIT, STOP, STOP_LIMIT, IOC/FOK, ICEBERG, combo, OCO
- Market mechanisms: opening/closing auctions
- Risk handling with circuit breakers and price collars
- Message-based process boundaries with strong observability
- Real risk controls: price collars, kill switch, circuit breakers, and mass cancel
- Easy to understand configuration through single source `engine_config.yaml` which acts as the system reference data. To simplify its creation either Web-based tool (`http://localhost:8092/`) or a CLI tool `pm-config-gen` can be used. In addition it is of course possible to manually create a handwritten config file that can be verified with `pm-cverifier`. To guarantee correctness and that it is a single-source of truth the YAML file is then compiled and checked by `pm-deploy-config` to be automatically stored in the canonical location used by the system.

## Documentation

Main documentation site [EduMatcher Documentation](https://johan162.github.io/EduMatcher/) that among other things includes:

- **[How an Exchange Works](https://johan162.github.io/EduMatcher/how-exchange-works/)**: a primer on exchange mechanics and market microstructure concepts aimed at software developers with no prior financial experience
- **[Exchange Concepts](https://johan162.github.io/EduMatcher/concepts/01-concepts-order-book/)**: deep dive in core technical concept of an exchange
- **[User Guide](https://johan162.github.io/EduMatcher/user-guide/000-getting-started/)**: step-by-step instructions for installation, configuration, and running EduMatcher
- **[Training Material](https://johan162.github.io/EduMatcher/training/)**: self-paced exercises to learn how to setup and manage the Exchange
- **[Architecture](https://johan162.github.io/EduMatcher/architecture/01-architecture/)**: an overview of the SW architecture
- **[Developer Guide](https://johan162.github.io/EduMatcher/developer/01-dev-practice/)**: deep dive into the architecture, design decisions, and code structure. Necessary reading for anyone wanting to contribute!
- **[Glossary](https://johan162.github.io/EduMatcher/glossary/)**: the finance world uses lot of specialized terms, this glossary lists the most important with an explanation

***Note:** Running an exchange is an inherently complex task and there is only
so much that can be simplified. The user guide and training material are built
to get you through it.*

## Performance

EduMatcher does not aim to match venues like NYSE or LSE, but it is still fairly
fast for a purely Python educational project.
The figures below reflect the performance on an high end Linux server
with risk checks enabled (price collar and circuit-breaker).

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


## Key Functional and Infrastructure Limitations

- Very limited authentication & authorization
- No spread-order books
- No implied (synthetic) orders
- No primary-secondary automatic site failover
- No load balancing
- Limited replay for participants that lose the connection
- MARKET orders are rejected during a circuit-breaker halt rather than joining
  the reopening auction. Both Nasdaq and Xetra accept them into the call; here
  the uncross prices interest by book level, so unpriced interest has no level
  to sit at and would be invisible to `compute_equilibrium()`
- The ACE expansion ladder is exchange-wide only

## Contributing

Contributions are welcome. Start with the
**[Developer Guide](https://johan162.github.io/EduMatcher/developer/01-dev-practice/)**,
which covers the development environment, testing and the conventions this
project follows, then open an issue or pull request on
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
  version = {0.32.0}
}
```

## License

MIT License - see [LICENSE](LICENSE).
