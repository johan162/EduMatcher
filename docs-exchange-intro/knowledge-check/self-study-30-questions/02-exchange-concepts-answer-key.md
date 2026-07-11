# Answer Key — Exchange Concepts Knowledge Check, Variant 02

Correct statements are listed per question. Scoring: +1 per correct selection, -2 per incorrect selection, 0 for unselected, floor of 0 overall.

| # | Correct | | # | Correct |
|---|---|---|---|---|
| 1 | A, C, D | | 16 | A, C, D |
| 2 | A, B, D | | 17 | A, C, D, E |
| 3 | B, C, E | | 18 | A, B, C, E |
| 4 | A, B, D, E | | 19 | A, C, D, E |
| 5 | A, B, C, E | | 20 | A, B, D, E |
| 6 | B, C, D | | 21 | A, B, C, E |
| 7 | A, C, E | | 22 | A, B, C, E |
| 8 | A, B, D, E | | 23 | A, B, D, E |
| 9 | A, C, D | | 24 | A, B, C, D |
| 10 | A, B, C | | 25 | A, C, E |
| 11 | A, C, E | | 26 | A, B, C, E |
| 12 | A, B, C, E | | 27 | A, B, D |
| 13 | A, B, D | | 28 | B, C, D, E |
| 14 | A, B, D | | 29 | B, C, D, E |
| 15 | A, C, D, E | | 30 | A, C, E |

## Notes on selected answers

- **Q3(A, D):** The aggressive order that crosses the spread is the "taker," not the "maker" (A false as written). A quote is specifically a market maker's two-sided bid/ask pair, not a one-sided instruction (D false).
- **Q6(A):** Futures and options are contracts about future transactions, not claims on assets that already exist — that description applies to equities, not derivatives.
- **Q9(B):** "Back of queue on refresh" is described as the *most* common rule for iceberg replenishment, not the least common.
- **Q11(B):** A spread price of −$2.00 means January trades $2.00 *below* February, not above it.
- **Q14(C, E):** The spread between a $150.34 bid and $150.35 ask is $0.01, not $0.02. Sweeping multiple levels routinely produces a worse average price than the top-of-book quote — that is the definition of market impact/slippage.
- **Q18(D):** The state machine diagram checks dormant stops *after* publishing the FILLED/PARTIAL event for the triggering trade, then publishes all events together — stops are not checked before any fill event is published.
- **Q25(B, D):** Position/credit limit checks require live clearing-system data and are explicitly the *most* expensive check, run last; checks are deliberately sequenced fail-fast rather than run in parallel.
- **Q28(A):** Mass cancel can be initiated by the participant; a kill switch can be triggered by the participant, the exchange, or an automatic disconnect handler — the "only the exchange" framing in A is reversed from the source.
- **Q30(D):** NYSE processed every one of Knight's roughly four million orders correctly and validly; none were rejected by the exchange, since each was individually valid at the prevailing market price.
