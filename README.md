# EduMatcher

**Learn how real trading systems work. Build it from first principles.**

| Category          | Link         |
| ----------------- | ------------ |
| **Package**       | [![PyPI version](https://img.shields.io/pypi/v/edumatcher.svg)](https://pypi.org/project/edumatcher/) [![Python 3.13+](https://img.shields.io/badge/python-3.13+-blue.svg)](https://www.python.org/downloads/) |
| **Documentation** | [![Documentation](https://img.shields.io/badge/docs-mkdocs-blue)](https://johan162.github.io/EduMatcher/) |
| **License**       | [![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)  |
| **Release**       | [![GitHub release](https://img.shields.io/github/v/release/johan162/edumatcher?include_prereleases)](https://github.com/johan162/edumatcher/releases)  |
| **CI/CD**         | [![Coverage](https://img.shields.io/badge/coverage-85%25-brightgreen.svg)](coverage.svg)   |
| **Code Quality**  | [![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black) [![Checked with mypy](https://www.mypy-lang.org/static/mypy_badge.svg)](https://mypy-lang.org/) [![Linting: flake8](https://img.shields.io/badge/linting-flake8-yellowgreen)](https://flake8.pycqa.org/) |
| Repo URL          | [![GitHub](https://img.shields.io/badge/GitHub-100000?style=flat-square&logo=github&logoColor=white)](https://github.com/johan162/edumatcher) |

EduMatcher is an educational trading system that teaches market microstructure,
matching logic, and exchange architecture through runnable code.

Unlike toy examples, it is designed to be both understandable and fast.


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

## Performance

EduMatcher does not aim to match venues like NYSE or LSE, but it is still
fast for a pure Python educational project. The figures below reflect the performance on an Intel MacBook Pro.
On an ARM M1 MacBook the throughput is roughly 150,000 TPS (an improvement of almost 150%). Latencies are about 25% lower.


### Latency (engine-only, n=1,000 each)

| Order type | min (µs) | median (µs) | P80 (µs) | P90 (µs) | max (µs) |
| ---------- | -------: | ----------: | -------: | -------: | -------: |
| Limit      |      8.1 |         8.5 |      9.6 |     10.0 |       18 |
| Market     |      8.1 |         8.5 |      8.8 |      9.3 |       45 |

### Throughput

| Metric        | Value                                               |
|---------------|-----------------------------------------------------|
| **Max TPS**   | ~60,000 orders/second                               |
| **Order mix** | 20% Market, 30% aggressive Limit, 50% passive Limit |

*Performance note:* price-collar and circuit-breaker checks run in the hot path
for every match. They are required for realistic risk control and add measurable cost.


## Documentation

Main documentation site [EduMatcher Documentation](https://johan162.github.io/EduMatcher/) that among other things includes:

- **Installation Guide**: how to get up and running with EduMatcher
- **User Guide**: step-by-step instructions for installation, configuration, and running EduMatcher
- **Developer Guide**: deep dive into the architecture, design decisions, and code structure- 
- **Training Materials**: self-paced exercises to learn how to setup and manage the Exchange
- **How an Exchange Works**: a primer on exchange mechanics and market microstructure concepts aimed at software developers with no prior financial experience


## Who It's For

- Computer science students learning systems design and concurrency
- Finance students learning market microstructure and trading mechanics
- Developers building exchange technology or trading systems
- Anyone curious about how modern markets actually work


## Contributing

This is an educational project. If you find bugs, improve the documentation, or make other enhancements PRs are welcome!


## Setup a running system 

### ALTERNATIVE 1: Local Python Installation via `pipx`

1. Install Python 3.13+ and Poetry (or use the VM setup below)
2. Install from PyPI with `pipx install edumatcher` 
3. Bootstrap a new session directory and either generate `engine_config.yaml`
with sane defaults, or start from the sample config copied by `pm-setup`:

```bash
mkdir session
cd session
pm-setup
pm-config-gen --symbols AAPL MSFT --gateways TRADER01 TRADER02 OPS01:ADMIN --sessions-enabled --output engine_config.yaml
pm-engine --verbose
```


### ALTERNATIVE 2: Using a Multipass VM

#### Requirements

| Requirement | Notes |
|---|---|
| Multipass | A lightweight VM manager. Install from [multipass.run](https://multipass.run/install) |
| curl | Used to download the VM bootstrap script |
| Internet access | Required for downloading scripts and PyPI packages |
| Host resources | Recommended minimum: 2 vCPU, 3 GB RAM, 10 GB disk |


#### Bootstrap with one command

```bash
curl -fsSL https://raw.githubusercontent.com/johan162/EduMatcher/main/vm/curl_setup_vm.sh | bash -s -- --version 0.12.1 --snapshot
```

This command downloads the VM setup scripts, launches a Multipass VM,
installs EduMatcher in the VM, links all process commands in the exchange `pm-*` commands into
`/usr/local/bin`, prepares `/home/ubuntu/session`, and takes
an initial snapshot to allow you to easily reset the environment. 


#### Start the CME (Central Matching Engine) in the VM

```bash
multipass shell edumatcher-vm
cd /home/ubuntu/session
pm-engine --verbose
```

Open additional host terminals and run `multipass shell edumatcher-vm` in each
terminal to start `pm-gateway`, `pm-viewer`, `pm-clearing`, and `pm-audit`.

**Note:** Running the exchange is complex enough that you really **need** to read the documentation and follow the instructions in the User Guide to get a full exchange up and running. The above commands are just a quick start to get you going. The User Guide will explain how to configure the exchange, start and stop processes, and run the system in a realistic way.


## Citation

If you use this tool in teaching or courses, please cite:

```text
@software{edumatcher,
  title = {EduMatcher},
  author = {Johan Persson},
  year = {2026},
  url = {https://github.com/johan162/edumatcher},
  version = {0.12.1}
}
```

## License

MIT License - see [LICENSE](LICENSE).
