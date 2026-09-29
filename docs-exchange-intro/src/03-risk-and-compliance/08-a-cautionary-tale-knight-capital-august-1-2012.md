# A Cautionary Tale, Knight Capital, August 1, 2012


Everything in the *Pre-Trade Risk Controls* section, maximum quantity limits, position limits, kill switches, deployment discipline, exists partly because of what happened to one firm on one morning. The story of Knight Capital is the most important cautionary tale in the history of electronic trading, and every developer who touches exchange-adjacent code should know it.

## The Company

In the summer of 2012, Knight Capital Group was one of the most important firms in US equity markets. As a market maker and broker, Knight handled approximately 10–15% of all US equity trading volume, billions of shares every day across thousands of stocks. It was a highly regarded, well-capitalised firm at the centre of the market structure that had emerged after electronic trading matured.

## The Morning

On August 1, 2012, the NYSE launched a new feature called the **Retail Liquidity Program (RLP)**, designed to attract more retail order flow to the exchange by offering price improvements. Participating firms were required to deploy new software to handle the RLP order types.

Knight deployed new code to its production trading servers. The deployment involved eight servers that handled the firm's market making in NYSE-listed stocks.

Seven of the eight servers received the new code correctly.

One did not.

The eight servers ran Knight's order router, **SMARS (Smart Market Access Routing System)**. Buried in SMARS was a long-unused piece of functionality called **"Power Peg"**, which had not been used since 2003 but had never been removed. The new RLP code *reused* a flag in the order messages that had formerly meant "use Power Peg". On the seven updated servers, the flag now meant "this is an RLP order". On the eighth server, which still ran the old code, it still meant "Power Peg".

Power Peg had been designed to split a large "parent" order into smaller "child" orders and keep sending children until the parent was complete. But years earlier, the code that counted how much of the parent had been filled had been moved elsewhere, so the dormant Power Peg code could no longer tell when to stop. When RLP orders reached the eighth server that morning, it kept sending child orders indefinitely, buying at the offer and selling at the bid, over and over again. It was, in effect, a machine programmed to continuously pay the spread [SEC, *In the Matter of Knight Capital Americas LLC*, Release No. 34-70694, 16 October 2013].

## 45 Minutes

At 9:30am, the NYSE opened for trading.

Knight's SMARS system on the one misconfigured server immediately began sending orders into the market. The orders were technically valid, they passed all of the exchange's pre-trade checks. NYSE processed them correctly. From the exchange's perspective, Knight was simply an aggressive, very active participant.

From Knight's perspective, the firm was haemorrhaging money at a speed no human could track in real time.

Over the next 45 minutes, the misconfigured server's child orders produced more than **4 million executions** in **154 stocks**, for more than 397 million shares. Knight ended up with about $3.5 billion of unwanted long positions in 80 stocks and $3.15 billion of short positions in 74 others, a gross exposure of roughly **$6.65 billion**. The system was continuously entering and exiting trades, losing roughly the bid-ask spread on each round trip, millions of times over, while also accumulating enormous positions that it then had to unwind in a market that knew it was a forced seller.

The warning signs had started even before the open. Between 8:01am and 9:30am, Knight's systems automatically sent 97 e-mails to a group of its staff, each referring to "Power Peg disabled". Nobody treated them as an alarm. Once trading began, the operations desk noticed the anomalous activity almost immediately: error messages appeared, phones rang, and colleagues tried to identify which system was responsible. Then came the cruellest twist. In one attempt to fix the problem, technicians uninstalled the new RLP code from the seven servers where it had been deployed *correctly*, reasoning that the new code must be the culprit. That made things worse: with the new code gone, the reused flag meant "Power Peg" on all eight servers, and the runaway behaviour spread [SEC Release No. 34-70694]. It took roughly 45 minutes to stop it.

By 10:15am the damage was done. Knight announced a pre-tax loss of about **$440 million** the following day; the SEC later put the loss at more than $460 million. Knight's share price fell by roughly three-quarters within two trading days, and the firm no longer had enough capital to continue operating on its own.

## The Aftermath

Knight survived only through an emergency capital injection arranged over the following two days. A consortium of investment firms provided $400 million in rescue financing in exchange for equity stakes that gave them majority ownership. Effectively, Knight Capital ceased to exist as an independent firm. Several months later, what remained of Knight merged with Getco LLC to form KCG Holdings, which was eventually acquired by Virtu Financial in 2017.

## What Went Wrong: A Technical Post-Mortem

The SEC conducted a detailed investigation and published its findings in October 2013, fining Knight $12 million in the first enforcement action under the Market Access Rule. The root causes, in the order they would need to have been addressed to prevent the disaster:

**1. Deployment process without verification.** Eight servers needed the same software. A manual deployment procedure was used, and it was not verified to confirm all eight servers were identically configured. In any production system where a single misconfigured server can cause catastrophic damage, every deployment must include an automated post-deployment verification step that confirms every node is running the correct version with the correct configuration.

**2. Active dangerous code in a production binary.** The Power Peg code had not been removed from the codebase, it had merely been deactivated. In a production trading system, deprecated code that can cause harmful behaviour should be removed entirely, not commented out or conditionally disabled. Code that is not present cannot be accidentally reactivated.

**3. No position limit or notional limit at the firm level.** Knight's pre-trade risk controls were focused on individual order validation, not on accumulated firm-wide exposure. A firm-level position monitor that triggered a circuit breaker when gross exposure exceeded, say, $100 million in a short window would have halted the rogue system after the first few seconds. The system ran for 45 minutes because nothing automatically stopped it when the positions grew to dangerous size.

**4. No kill switch, and no plan for using one.** The SEC found that Knight "did not have supervisory procedures concerning incident response" and "did not have clear guidance for its technology personnel as to when to disconnect a malfunctioning system". In the chaos of the morning, staff diagnosed, guessed, and rolled back code instead of simply disconnecting. A kill switch that nobody is authorised, trained, or instructed to pull is not a kill switch. Emergency controls must be pre-tested, clearly documented, instantly accessible, and operable by a single person under extreme stress, with explicit authority to act first and investigate afterwards.

**5. No automated detection of anomalous trading patterns.** An algorithm sending 4 million orders in 45 minutes, accumulating $7 billion in exposure on one server while the other seven servers show normal activity, should have been automatically detectable. A real-time monitor comparing per-server activity, or watching the rate of position accumulation relative to normal levels, would have flagged the anomaly within seconds. Automated detection should not require a human to notice something is wrong.

**6. The exchange cannot protect you from yourself.** This deserves particular emphasis. NYSE processed every single one of Knight's 4 million orders correctly. None of them violated any exchange rule. The exchange is not in a position to determine whether a participant's trading strategy makes business sense, only whether the orders are technically valid. Pre-trade risk controls at the exchange level (quantity limits, fat-finger price filters, rate limits) exist to protect the market as a whole from clearly erroneous orders. They are not a substitute for participant-side risk management. Knight's situation could not have been prevented at the exchange level alone.

## The Legacy

The Knight Capital incident triggered a wave of regulatory attention to algorithmic trading risk. The Market Access Rule (Rule 15c3-5, adopted in 2010) was already in effect at the time of the incident and required broker-dealers to have risk controls for market access; the SEC's 2013 order found that Knight's controls had not complied with it.

Subsequently, regulators in the US, EU (under MiFID II), and other jurisdictions tightened requirements for:
- Pre-deployment testing of algorithmic trading systems
- Kill switch accessibility and testing requirements (MiFID II mandates regular kill switch testing)
- Intraday position and notional limits
- Automated anomaly detection

Every requirement in the *Pre-Trade Risk Controls* section of this document, and the kill switch discussion, is grounded in part in the lesson that Knight Capital paid $440 million to teach.

> **Key idea:** The market does not stop when your system malfunctions. Every order your system sends is valid in the exchange's eyes until you cancel it or your gateway is disconnected. The only protection against a runaway algorithm is pre-trade risk controls on your own side, deployed correctly, verified after every deployment, and exercisable instantly under pressure.

