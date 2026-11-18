# Answer Key — Exchange Concepts Knowledge Check, Variant 06

Correct statements are listed per question. Scoring: +1 per correct selection, -2 per incorrect selection, 0 for unselected, floor of 0 overall.

| # | Correct | | # | Correct |
|---|---|---|---|---|
| 1 | A, D, E | | 16 | B, C, D, E |
| 2 | C, D, E | | 17 | A, B, C, E |
| 3 | A, C, D, E | | 18 | A, C, D, E |
| 4 | B, C, D, E | | 19 | A, B, C |
| 5 | A, B, D, E | | 20 | A, B, C, D |
| 6 | B, C, D | | 21 | B, D, E |
| 7 | A, B, D, E | | 22 | A, C, D, E |
| 8 | B, C, D, E | | 23 | A, B, D, E |
| 9 | A, C, D, E | | 24 | A, B, E |
| 10 | A, C, D, E | | 25 | A, B, C, E |
| 11 | A, B, C, D | | 26 | A, B, D, E |
| 12 | B, C, D, E | | 27 | A, B, C, D |
| 13 | A, B, C, E | | 28 | A, B, C, E |
| 14 | A, B, D, E | | 29 | A, C, D, E |
| 15 | B, C, D, E | | 30 | A, B, C, D |

## Notes on selected answers

- **Q1(B, C):** FX largely trades on electronic networks rather than centralised exchanges, contrary to B. An option grants a *right*, not an obligation, to buy or sell — the obligation sits with the writer, not the holder, so C is false.
- **Q5(C):** CME's actual split is the reverse of what C claims — a largely pro-rata "allocation" algorithm for SOFR futures, FIFO for equity index futures.
- **Q6(A, E):** A raw midpoint tick count of 9999.5 is exactly the "not a valid tick multiple" case the rounding discussion exists to solve. Rule 612 restricts sub-penny quotes and orders; it has no counterparty-consent exception, and (US midpoint executions aside) rounding rules are set by the venue, not negotiated by the parties.
- **Q15(A):** Initial margin is deposited when a position is *opened*, estimating potential loss; a margin call is what's triggered by a *maintenance margin* breach. The statement conflates the two, so A is false.
- **Q16(A):** Coordinated, consistent rulings across venues are explicitly required for multi-venue erroneous-price events — "independent, uncoordinated" is the opposite of the documented practice.
- **Q17(D):** Before CAT, regulators had to request records from each exchange separately and correlate them manually — D states the opposite.
- **Q21(A):** A describes the maker-taker model, not the inverted one: under taker-maker the aggressor is *rebated* and the resting order pays.
- **Q28(B, D, E):** Order-to-trade and cancel-to-fill ratios are listed monitored signals (E true); baselines differ by session phase (D false); traces follow a request by correlation ID (B true).
- **Q29(E):** Auditing, debugging, and disaster recovery are exactly the three reasons the document gives for determinism.
- **Q22(B):** Implementation Shortfall algorithms trade *faster* (increase urgency), not slower, as price moves away from the arrival price — the goal is to avoid further shortfall.
- **Q24(D):** Most headline indexes are price-return indexes: an ordinary dividend pulls the index level down on the ex-date and is *not* absorbed by the divisor. Only special dividends are absorbed; a separate total-return index counts ordinary dividends as reinvested.
- **Q25(D):** Individual equity options are physically settled as the standard; broad index options (SPX) are cash-settled as the standard — this statement reverses the pairing.
