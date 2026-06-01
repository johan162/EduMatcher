# EduMatcher

**Learn how real trading systems work. Build it from first principles.**

| Category          | Link         |
| ----------------- | ------------ |
| **Package**       | [![PyPI version](https://img.shields.io/pypi/v/edumatcher.svg)](https://pypi.org/project/edumatcher/) [![Python 3.13+](https://img.shields.io/badge/python-3.13+-blue.svg)](https://www.python.org/downloads/) |
| **Documentation** | [![Documentation](https://img.shields.io/badge/docs-mkdocs-blue)](https://johan162.github.io/edumatcher/)  
| **License**       | [![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)  |
| **Release**       | [![GitHub release](https://img.shields.io/github/v/release/johan162/edumatcher?include_prereleases)](https://github.com/johan162/edumatcher/releases)  |
| **CI/CD**         | [![Coverage](https://img.shields.io/badge/coverage-84%25-brightgreen.svg)](coverage.svg)   |
| **Code Quality**  | [![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black) [![Checked with mypy](https://www.mypy-lang.org/static/mypy_badge.svg)](https://mypy-lang.org/) [![Linting: flake8](https://img.shields.io/badge/linting-flake8-yellowgreen)](https://flake8.pycqa.org/) |
| Repo URL          | [![GitHub](https://img.shields.io/badge/GitHub-100000?style=flat-square&logo=github&logoColor=white)](https://github.com/johan162/edumatcher) |


>[!CAUTION]
>!!! note "Key Limitations of EduMatcher"
>    
>  - EduMatcher does not support spread-order books
>  - EduMatcher does not support implied-orders (a.k.a. syntethic-orders) Adding these concepts would significantly reduce TPS as it requires a sweep and re-calculation after each fill. 
>  - EduMatcher does not support primary-secondary site failover
>  - EduMatcher does not support load-balancing
>  - EduMatcher does only support limited re-play for participants loosing the connection
>  - EduMatcher does not support index calculations




EduMatcher is a comprehensive, educational trading system that teaches the fundamentals of order matching, market microstructure, and multi-process system design. 
Unlike toy implementations, EduMatcher is *genuinely fast and realistic* — perfect for learning how modern exchanges actually work.


| Category          | Details                                                                                    |
| ----------------- | ------------------------------------------------------------------------------------------ |
| **Purpose**       | Educational trading system: order matching engine, gateway architecture, market mechanisms |
| **Performance**   | ~60,000 orders/second with sub-10µs latency         |
| **Language**      | Python 3.13+ with full type hints and comprehensive test coverage (85%+)                   |
| **Learning Path** | Audit trails → Order books → Matching algorithms → Auctions → Multi-process systems        |
| **Documentation** | Extensive docs covering concepts, architecture, configuration, and deployment              |

*A note on performance:* The primary drag for increasing performance is the need to do a price collar (and circuit-breaker) check in the hot path for every match. This is necessary in order to do real risk-management. There is no way around this. 

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

While EduMatcher cannot achieve the same performance as NYSE (New York Stck Exchange) or LSE (London Stock Exchange)
it still manage to be fairly impressive considering its written in purely in Python and primary for my own educational purposes.


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



### Explore the Code

Start with these key areas:

- **[src/edumatcher/engine/](src/edumatcher/engine/)** — Core matching logic and order book
- **[src/edumatcher/gateway/](src/edumatcher/gateway/)** — Message handling and order validation
- **[src/edumatcher/clearing/](src/edumatcher/clearing/)** — Trade settlement and P&L calculation

## Documentation

EduMatcher includes comprehensive and what I believe to be well-written documentation:

The full documentation is available at GitHub pages [EduMatcher Documentation](https://johan162.github.io/edumatcher/) or as raw Markdow files.
In addition to the EduMatcher specific documentation there a beginner friendly document meant for the SW Developer without any
financial background to learn the basic financial terminology and how the financial market and 
exchanges work, aptly named: [How an Exchange Works](https://johan162.github.io/how-exchange-works/)
Most likely you will also find a lot of use for the (very extensive) [Glossary](https://johan162.github.io/glossary/) 


## Why EduMatcher?

Most trading system tutorials oversimplify. EduMatcher doesn't. You get:

✅ **Real-world latency** — Microsecond-precision, no artificial delays  
✅ **Production patterns** — Message queues, multi-process architecture, proper error handling  
✅ **Complete coverage** — Opening auctions through clearing, not just simple matching  
✅ **Extensive tests** — Learn from 80%+ test coverage and realistic integration tests  
✅ **Rich documentation** — Concepts explained, diagrams provided, code heavily commented  
✅ **Actually fast** — 60K+ orders/second, so you understand performance-conscious design  


Perfect for:
- **Computer Science students** learning systems design and concurrency
- **Finance students** understanding market microstructure and trading mechanics
- **Developers** building exchange technology or trading systems
- **Anyone** curious how modern markets actually work


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
  version = {0.1.0rc1}
}
```

## License

MIT License - see [LICENSE](LICENSE).
