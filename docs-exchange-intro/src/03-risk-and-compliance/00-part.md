# Part III: Risk, Compliance, and Post-Trade

*The safeguards that protect markets and participants, before, during, and after each trade, and the regulatory obligations that underpin them.*

---

!!! note "Historic Notes"

    In the last week of February 1995, Peter Baring, chairman of Barings Bank, had to tell the Bank of England that his bank was in trouble. Barings, founded in 1762, Britain's oldest merchant bank and one of the most respected financial institutions in the world, had a problem. One of its traders in Singapore, a 28-year-old named **Nick Leeson**, had accumulated positions in Nikkei 225 futures that nobody at headquarters knew about. The positions totalled approximately $7 billion in notional exposure. Leeson had hidden the losses in an error account numbered 88888, exploiting gaps in the firm's controls and the geographic distance between Singapore and London. When the 1995 Kobe earthquake sent Japanese equity markets sharply lower, Leeson's positions collapsed. Barings' total losses were £827 million, more than twice the bank's available capital. On 26 February 1995 the bank was placed in administration, and it was sold to the Dutch bank ING for £1. The UK's oldest merchant bank had ceased to exist as an independent firm [Bank of England Board of Banking Supervision, *Report of the Inquiry into the Circumstances of the Collapse of Barings*, July 1995].

    Barings had pre-trade risk controls. They were simply not checking position limits at the firm level, not monitoring the error account's exposure, and not asking why a single trader in Singapore was generating such unusual patterns of activity.

    Every section of Part III is, in some sense, the answer to the question: "What would have stopped Nick Leeson?" Pre-trade position limits would have flagged his accumulation. A firm-level kill switch, properly monitored, could have halted his trading. A drop copy feed to an independent risk team would have revealed the hidden positions. Regulatory surveillance would have detected the anomalous patterns. And the Knight Capital story at the end of this Part shows that a firm can have many of these controls and still fail, if nobody is able to stop a runaway system for 45 minutes.

---

**Part Summary:**

Focus on market safety and accountability: the controls that prevent bad orders, the mechanisms that stabilize volatility, and the post-trade processes that make executed trades legally and financially final.

**Learning Objectives:**

- Explain why pre-trade controls are separated from matching in production architectures.
- Understand circuit breakers, collars, SMP, and kill switches as layered protections.
- Distinguish routine order-management actions from emergency risk interventions.
- Follow the trade path beyond execution into clearing, settlement, and surveillance.

**Content:**

- Pre-Trade Risk Controls: Before the Matching Engine
- Risk Controls, Protecting the Market
- Self-Match Prevention, When You Would Trade with Yourself
- Drop Copy, The Shadow Record
- Clearing and Settlement, When the Trade Becomes Real
- Trade Busting and Clearly Erroneous Trades
- Regulatory Surveillance, Exchanges Are Not Passive
- A Cautionary Tale, Knight Capital, August 1, 2012


