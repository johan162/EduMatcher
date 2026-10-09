# When Something Does Not Work

Try these in roughly this order. Most first-day problems are one of the
first three.

## Quick checks

| Question | Containers | Python package |
|---|---|---|
| Is everything running? | `./edumatcher.sh status` | `pm-opctl-cli list` |
| What did the exchange say when it started? | `./edumatcher.sh logs` | the log files listed by `pm-opctl-cli show` |
| Which configuration is actually deployed? | `./edumatcher.sh shell pm-config-show` | `pm-config-show` |
| What is each process doing? | Log Operator Console at <http://localhost:8091> | `pm-log-cli` |
| Am I looking at the exchange I think I am? | `./edumatcher.sh mounts` | `pm-setup --show` |
| Which ports are published? | `./edumatcher.sh urls` | — |

## Common first-day problems

**My order does not trade.** Nobody is waiting on the other side at a price
that crosses yours. That is the market working correctly. Look at the book
(`pm-viewer --symbol AAPL`, `BOOK|SYM=AAPL` in `pm-admin`, or the Order Book
Viewer) to see the best bid and ask.

**My order traded immediately, before the other trader did anything.** The
book already had liquidity: a market maker's seeded quote, or the
market-maker bot of the container's `mm-demo` profile. Use an `-nomm`
configuration and the `default` profile, as in
[Your First Trade](../part-1-see-it-run/030-your-first-trade.md), to start
from an empty book.

**Every order is rejected with *Market is closed*.** The configuration has a
timetable and the exchange is outside trading hours, or was left in `CLOSED`.
Move it on by hand from `pm-admin` (`SESSION|STATE=PRE_OPEN`, then
`SESSION|STATE=CONTINUOUS`), as in
[Run a Trading Session](../part-2-next-steps/010-run-a-trading-session.md),
or use a `-basic` configuration, which has no timetable.

**The console will not connect, or says the participant is unknown.**
Participant IDs are case-sensitive and must exist in the deployed
configuration; `pm-config-show` lists them. On the container route, run the
console inside the exchange (`./edumatcher.sh shell`), not on your own
machine.

**`pm-*: command not found`.** On the container route the commands only exist
inside the exchange: open `./edumatcher.sh shell` first. On the Python route,
check that `pipx` put its directory on your `PATH` (`pipx ensurepath`).

**A recorder's numbers are missing trades.** `pm-stats`, `pm-clearing` and
`pm-audit` only record what happens while they are running. Start them before
the engine, which `pm-opctl-cli` and the container do for you.

**I changed the configuration but nothing changed.** A configuration must be
deployed and the processes restarted. On the container route,
`./edumatcher.sh config …` only takes effect after `./edumatcher.sh restart`.

**Two installations at once.** A curl installation and a stack built from the
source checkout use the same container names and ports, so only one can run.
Both refuse to start on top of the other; `./edumatcher.sh mounts` shows
which one owns the ports.

## Still stuck?

The [FAQ](010-faq.md) answers the next layer of questions, and the Operator's
Guide has a full troubleshooting section in
[Running the Exchange](../../operator-guide/part-3-run/010-running-the-exchange.md).
If something in this guide does not work as written, that is a documentation
bug — please report it on GitHub.
