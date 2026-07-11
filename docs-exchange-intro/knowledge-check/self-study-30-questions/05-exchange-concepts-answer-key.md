# Answer Key — Exchange Concepts Knowledge Check, Variant 05

Correct statements are listed per question. Scoring: +1 per correct selection, -2 per incorrect selection, 0 for unselected, floor of 0 overall.

| # | Correct | | # | Correct |
|---|---|---|---|---|
| 1 | A, C, D | | 16 | A, B, D, E |
| 2 | A, B, C, E | | 17 | A, B, C, E |
| 3 | A, B | | 18 | A, B, C, E |
| 4 | A, B, C, E | | 19 | A, B, C |
| 5 | A, B, E | | 20 | A, B, D, E |
| 6 | A, B, C, D, E | | 21 | A, B, D |
| 7 | A, B, D, E | | 22 | A, B, D, E |
| 8 | A, B, D, E | | 23 | A, B, C, D |
| 9 | A, B, C, D | | 24 | A, B, C, D |
| 10 | A, B, D, E | | 25 | A, B, C |
| 11 | A, B, C, D | | 26 | A, C, D, E |
| 12 | B, C, D, E | | 27 | A, B, D, E |
| 13 | A, B, C, D | | 28 | A, B, D, E |
| 14 | A, B, C, D | | 29 | A, C, D |
| 15 | A, B, C, D | | 30 | A, B, C, D, E |

## Notes on selected answers

- **Q3(C, D, E):** Consensus protocols (Raft/Paxos) guarantee zero data loss but explicitly *add* latency, so "at essentially no latency cost" is false. A secondary placed *close* to the primary protects against equipment/network failure but specifically *not* against a geographically localised disaster (earthquake, flood) — that is what the distant "far site" is for. Active-active matching engines are described as rare, not common, in production.
- **Q9(E):** The document is explicit that depth "is not a single number, it is a shape" — treating it as one fixed figure is the false framing.
- **Q12(A):** Single-threaded design is described as a deliberate choice for determinism and auditability, not a simplicity shortcut, and specifically *not* a performance limitation.
- **Q14(E):** A buyback shrinks the share count for a non-price reason, exactly the kind of event the divisor mechanism exists to absorb — it does require an adjustment, contrary to E.
- **Q16(C):** No CME futures participant suffered a material uncollateralised loss from the Lehman default; that resilience is precisely the document's point about centrally cleared derivatives versus Lehman's uncleared OTC book.
- **Q18(D):** Knight's $440 million loss slightly *exceeded* its roughly $400 million in pre-incident equity capital — "smaller than" is the reverse of what happened.
- **Q19(D, E):** IEX has never displaced the established venues and has captured only a small fraction (roughly 2–3%) of total US equity volume. Its founders argued that speed advantages primarily benefit HFT firms at the expense of long-term investors — E states the opposite framing.
- **Q23(C):** OUCH is NASDAQ's binary order-entry protocol in its own right, not something restricted to cancel messages, and it isn't described as "the FIX counterpart" in that narrow sense.
- **Q29(B, E):** Most crypto venues run continuous 24/7 trading with no defined daily open/close or scheduled closing auction (some larger venues have begun experimenting with auctions, but it isn't the norm the document describes). No single regulator oversees digital asset markets globally; oversight is fragmented.
