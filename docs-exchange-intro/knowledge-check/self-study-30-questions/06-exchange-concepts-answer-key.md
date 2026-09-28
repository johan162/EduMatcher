# Answer Key — Exchange Concepts Knowledge Check, Variant 06

Correct statements are listed per question. Scoring: +1 per correct selection, -2 per incorrect selection, 0 for unselected, floor of 0 overall.

| # | Correct | | # | Correct |
|---|---|---|---|---|
| 1 | A, B, D | | 16 | A, B, C, E |
| 2 | A, B, D | | 17 | A, B, D, E |
| 3 | A, B, C, E | | 18 | A, B, D, E |
| 4 | A, B, D, E | | 19 | A, C, D |
| 5 | A, B, C, E | | 20 | A, B, C, D |
| 6 | A, C, D | | 21 | A, C, E |
| 7 | A, B, C, D | | 22 | A, B, D, E |
| 8 | A, B, C, D | | 23 | A, B, C, E |
| 9 | A, B, C, D | | 24 | A, B, C, E |
| 10 | A, B, C, E | | 25 | A, B, C, D |
| 11 | A, B, C, E | | 26 | A, B, C, E |
| 12 | A, B, C, E | | 27 | A, B, C, E |
| 13 | A, C, D, E | | 28 | A, B, C, E |
| 14 | A, B, C, D | | 29 | A, C, D, E |
| 15 | B, C, D, E | | 30 | A, B, D, E |

## Notes on selected answers

- **Q1(C, E):** FX largely trades on electronic networks rather than centralised exchanges, contrary to C. An option grants a *right*, not an obligation, to buy or sell — the obligation sits with the writer, not the holder, so E is false.
- **Q5(D):** CME's actual split is the reverse of what D claims — a largely pro-rata "allocation" algorithm for SOFR futures, FIFO for equity index futures.
- **Q6(B, E):** A raw midpoint tick count of 9999.5 is exactly the "not a valid tick multiple" case the rounding discussion exists to solve. Rule 612 restricts sub-penny quotes and orders; it has no counterparty-consent exception, and (US midpoint executions aside) rounding rules are set by the venue, not negotiated by the parties.
- **Q15(A):** Initial margin is deposited when a position is *opened*, estimating potential loss; a margin call is what's triggered by a *maintenance margin* breach. The statement conflates the two, so A is false.
- **Q16(D):** Coordinated, consistent rulings across venues are explicitly required for multi-venue erroneous-price events — "independent, uncoordinated" is the opposite of the documented practice.
- **Q17(C):** Before CAT, regulators had to request records from each exchange separately and correlate them manually — C states the opposite.
- **Q21(D):** D describes the maker-taker model, not the inverted one: under taker-maker the aggressor is *rebated* and the resting order pays.
- **Q28(B, D, E):** Order-to-trade and cancel-to-fill ratios are listed monitored signals (B true); baselines differ by session phase (D false); traces follow a request by correlation ID (E true).
- **Q29(E):** Auditing, debugging, and disaster recovery are exactly the three reasons the document gives for determinism.
- **Q22(C):** Implementation Shortfall algorithms trade *faster* (increase urgency), not slower, as price moves away from the arrival price — the goal is to avoid further shortfall.
- **Q25(E):** Individual equity options are physically settled as the standard; broad index options (SPX) are cash-settled as the standard — this statement reverses the pairing.
