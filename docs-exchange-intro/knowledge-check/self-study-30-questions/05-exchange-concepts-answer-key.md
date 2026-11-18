# Answer Key — Exchange Concepts Knowledge Check, Variant 05

Correct statements are listed per question. Scoring: +1 per correct selection, -2 per incorrect selection, 0 for unselected, floor of 0 overall.

| # | Correct | | # | Correct |
|---|---|---|---|---|
| 1 | C, D, E | | 16 | A, B, C, D |
| 2 | A, B, C, E | | 17 | A, B, D, E |
| 3 | C, E | | 18 | B, D, E |
| 4 | A, B, C, D | | 19 | A, B, C |
| 5 | A, B, E | | 20 | A, B, C, D |
| 6 | B, C, E | | 21 | A, C, D |
| 7 | A, B, C, E | | 22 | A, C, D, E |
| 8 | B, C, D, E | | 23 | A, B, D, E |
| 9 | A, C, D, E | | 24 | B, C, D, E |
| 10 | A, C, D, E | | 25 | A, D, E |
| 11 | A, B, D, E | | 26 | A, B, C, D |
| 12 | A, C, D, E | | 27 | A, B, C, D |
| 13 | B, C, D, E | | 28 | A, B, C, E |
| 14 | B, C, D, E | | 29 | A, C, E |
| 15 | A, B, D, E | | 30 | A, B, C, D, E |

## Notes on selected answers

- **Q3(A, B, D):** Consensus protocols (Raft/Paxos) guarantee zero data loss but explicitly *add* latency, so "at essentially no latency cost" is false. A secondary placed *close* to the primary protects against equipment/network failure but specifically *not* against a geographically localised disaster (earthquake, flood) — that is what the distant "far site" is for. Active-active matching engines are described as rare, not common, in production.
- **Q6(A, D):** Exchanges keep their surveillance and self-regulatory duties whoever owns them (D false). Market data and connectivity are a large and growing share of exchange revenue (A false).
- **Q9(B):** The document is explicit that depth "is not a single number, it is a shape" — treating it as one fixed figure is the false framing.
- **Q12(B):** Single-threaded design is described as a deliberate choice for determinism and auditability, not a simplicity shortcut, and specifically *not* a performance limitation.
- **Q14(A):** A buyback shrinks the share count for a non-price reason, exactly the kind of event the divisor mechanism exists to absorb — it does require an adjustment, contrary to A.
- **Q16(E):** No CME futures participant suffered a material uncollateralised loss from the Lehman default; that resilience is precisely the document's point about centrally cleared derivatives versus Lehman's uncleared OTC book.
- **Q18(A, C):** Each of Knight's fills was at a genuine prevailing market price, so they were not clearly erroneous in the regulatory sense (C false). Every order was individually valid, so the exchange had no grounds to reject them; the missing controls were Knight's own (A false).
- **Q19(D, E):** IEX has never displaced the established venues and has captured only a small fraction (roughly 2–3%) of total US equity volume. Its founders argued that speed advantages primarily benefit HFT firms at the expense of long-term investors — D states the opposite framing.
- **Q20(E):** OUCH is NASDAQ's binary order-entry protocol in its own right, not something restricted to cancel messages, and it isn't described as "the FIX counterpart" in that narrow sense.
- **Q29(B, D):** Most crypto venues run continuous 24/7 trading with no defined daily open/close or scheduled closing auction (some larger venues have begun experimenting with auctions, but it isn't the norm the document describes). No single regulator oversees digital asset markets globally; oversight is fragmented.
