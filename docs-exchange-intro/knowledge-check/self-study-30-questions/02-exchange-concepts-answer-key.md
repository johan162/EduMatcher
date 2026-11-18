# Answer Key — Exchange Concepts Knowledge Check, Variant 02

Correct statements are listed per question. Scoring: +1 per correct selection, -2 per incorrect selection, 0 for unselected, floor of 0 overall.

| # | Correct | | # | Correct |
|---|---|---|---|---|
| 1 | B, C, E | | 16 | A, B, C |
| 2 | A, B, D | | 17 | B, C, D, E |
| 3 | A, C, E | | 18 | B, C, D, E |
| 4 | A, B, C, E | | 19 | A, B, C, D |
| 5 | A, B, D, E | | 20 | A, B, D, E |
| 6 | B, D, E | | 21 | A, B, C, D |
| 7 | A, B, D | | 22 | A, B, D, E |
| 8 | B, C, D, E | | 23 | B, C, D, E |
| 9 | B, C, E | | 24 | A, C, D, E |
| 10 | A, C, D | | 25 | A, D, E |
| 11 | C, D, E | | 26 | A, C, D, E |
| 12 | B, C, D, E | | 27 | A, C, D |
| 13 | A, B, E | | 28 | A, B, D, E |
| 14 | B, C, D | | 29 | A, B, C, E |
| 15 | A, C, D, E | | 30 | A, B, C |

## Notes on selected answers

- **Q1(A):** A single bank may not be willing or able to lend hundreds of millions to one borrower; a bond issue raises that kind of sum from thousands of investors.
- **Q3(B, D):** The aggressive order that crosses the spread is the "taker," not the "maker" (D false as written). A quote is specifically a market maker's two-sided bid/ask pair, not a one-sided instruction (B false).
- **Q6(A):** Futures and options are contracts about future transactions, not claims on assets that already exist — that description applies to equities, not derivatives.
- **Q9(D):** "Back of queue on refresh" is described as the *most* common rule for iceberg replenishment, not the least common.
- **Q11(A):** A spread price of −$2.00 means January trades $2.00 *below* February, not above it.
- **Q14(A, E):** The spread between a $150.34 bid and $150.35 ask is $0.01, not $0.02. Sweeping multiple levels routinely produces a worse average price than the top-of-book quote — that is the definition of market impact/slippage.
- **Q18(A):** The state machine diagram checks dormant stops *after* publishing the FILLED/PARTIAL event for the triggering trade, then publishes all events together — stops are not checked before any fill event is published.
- **Q25(B, C):** Position/credit limit checks require live clearing-system data and are explicitly the *most* expensive check, run last; checks are deliberately sequenced fail-fast rather than run in parallel.
- **Q28(C):** Mass cancel can be initiated by the participant; a kill switch can be triggered by the participant, the exchange, or an automatic disconnect handler — the "only the exchange" framing in C is reversed from the source.
- **Q30(D):** NYSE processed Knight's orders (more than four million executions) correctly and validly; none were rejected by the exchange, since each was individually valid at the prevailing market price.
