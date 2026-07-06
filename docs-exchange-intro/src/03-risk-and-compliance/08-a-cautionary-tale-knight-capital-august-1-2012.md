# A Cautionary Tale, Knight Capital, August 1, 2012


Everything in the *Pre-Trade Risk Controls* section, maximum quantity limits, position limits, kill switches, deployment discipline, exists partly because of what happened to one firm on one morning. The story of Knight Capital is the most important cautionary tale in the history of electronic trading, and every developer who touches exchange-adjacent code should know it.

## The Company

In the summer of 2012, Knight Capital Group was one of the most important firms in US equity markets. As a market maker and broker, Knight handled approximately 10–15% of all US equity trading volume, billions of shares every day across thousands of stocks. It was a highly regarded, well-capitalised firm at the centre of the market structure that had emerged after electronic trading matured.

## The Morning

On August 1, 2012, the NYSE launched a new feature called the **Retail Liquidity Program (RLP)**, designed to attract more retail order flow to the exchange by offering price improvements. Participating firms were required to deploy new software to handle the RLP order types.

Knight deployed new code to its production trading servers. The deployment involved eight servers that handled the firm's market making in NYSE-listed stocks.

Seven of the eight servers received the new code correctly.

One did not.

On the one misconfigured server, old code, a legacy module called **SMARS (Smart Market Access Routing System)** that had been used years earlier for a different purpose and was supposed to be permanently deactivated, was still present and was inadvertently reactivated by the deployment process. This old code had a function called **"Power Peg"** that had been repurposed from its original use. When RLP orders arrived on the live NYSE that morning, the old code on the misconfigured server interpreted them as triggers for Power Peg and began acting on them.

Power Peg, as activated, executed a simple but lethal loop: for each incoming RLP trigger, it would buy shares at the market offer price and then immediately sell them at the market bid price, buying high and selling low, over and over again. It was, in effect, a machine programmed to continuously pay the spread.

## 45 Minutes

At 9:30am, the NYSE opened for trading.

Knight's SMARS system on the one misconfigured server immediately began sending orders into the market. The orders were technically valid, they passed all of the exchange's pre-trade checks. NYSE processed them correctly. From the exchange's perspective, Knight was simply an aggressive, very active participant.

From Knight's perspective, the firm was haemorrhaging money at a speed no human could track in real time.

Over the next 45 minutes, the misconfigured server sent approximately **4 million orders** into the market. Knight accumulated net positions in approximately 154 different stocks, a total long-short exposure of around **$7 billion**. Because Power Peg was designed to flip positions rapidly (buy at the ask, sell at the bid, repeatedly), not to accumulate directional positions, the system was continuously entering and exiting trades, but at a net loss equal to approximately the bid-ask spread on every single round trip, multiplied by millions of times.

Knight's trading operations desk noticed the anomalous activity almost immediately. Error messages appeared. Phones rang. Colleagues tried to identify which system was responsible. They tried to cancel the rogue orders. Several attempts were made and failed, the orders kept coming. It took the operations team approximately 45 minutes to identify the misconfigured server, isolate it, and stop the trading loop.

By 10:15am, Knight had lost approximately **$440 million**, in 45 minutes.

To put that number in context: Knight's entire net equity capital before August 1 was approximately $400 million. The firm had destroyed slightly more than its total equity in less than one trading session.

## The Aftermath

Knight survived only through an emergency capital injection arranged over the following two days. A consortium of investment firms provided $400 million in rescue financing in exchange for equity stakes that gave them majority ownership. Effectively, Knight Capital ceased to exist as an independent firm. Several months later, what remained of Knight merged with Getco LLC to form KCG Holdings, which was eventually acquired by Virtu Financial in 2017.

## What Went Wrong: A Technical Post-Mortem

The SEC conducted a detailed investigation and published its findings in 2013. The root causes, in the order they would need to have been addressed to prevent the disaster:

**1. Deployment process without verification.** Eight servers needed the same software. A manual deployment procedure was used, and it was not verified to confirm all eight servers were identically configured. In any production system where a single misconfigured server can cause catastrophic damage, every deployment must include an automated post-deployment verification step that confirms every node is running the correct version with the correct configuration.

**2. Active dangerous code in a production binary.** The Power Peg code had not been removed from the codebase, it had merely been deactivated. In a production trading system, deprecated code that can cause harmful behaviour should be removed entirely, not commented out or conditionally disabled. Code that is not present cannot be accidentally reactivated.

**3. No position limit or notional limit at the firm level.** Knight's pre-trade risk controls were focused on individual order validation, not on accumulated firm-wide exposure. A firm-level position monitor that triggered a circuit breaker when gross exposure exceeded, say, $100 million in a short window would have halted the rogue system after the first few seconds. The system ran for 45 minutes because nothing automatically stopped it when the positions grew to dangerous size.

**4. Kill switch inaccessible in the moment of crisis.** Knight had kill switch capability in principle. But in the chaos of the morning, the operations team was unable to exercise it quickly. Finding the right kill switch, confirming it was correct, getting approvals, and executing it took far too long. A kill switch that takes 45 minutes to operate is not a kill switch. Emergency controls must be pre-tested, clearly documented, instantly accessible, and operable by a single person under extreme stress.

**5. No automated detection of anomalous trading patterns.** An algorithm sending 4 million orders in 45 minutes, accumulating $7 billion in exposure on one server while the other seven servers show normal activity, should have been automatically detectable. A real-time monitor comparing per-server activity, or watching the rate of position accumulation relative to normal levels, would have flagged the anomaly within seconds. Automated detection should not require a human to notice something is wrong.

**6. The exchange cannot protect you from yourself.** This deserves particular emphasis. NYSE processed every single one of Knight's 4 million orders correctly. None of them violated any exchange rule. The exchange is not in a position to determine whether a participant's trading strategy makes business sense, only whether the orders are technically valid. Pre-trade risk controls at the exchange level (quantity limits, fat-finger price filters, rate limits) exist to protect the market as a whole from clearly erroneous orders. They are not a substitute for participant-side risk management. Knight's situation could not have been prevented at the exchange level alone.

## The Legacy

The Knight Capital incident triggered a wave of regulatory attention to algorithmic trading risk. The SEC's 2013 Market Access Rule (Rule 15c3-5), which had been in effect at the time of the incident, required broker-dealers to have risk controls for market access, but the incident demonstrated that the rule's requirements were insufficient or that compliance was inadequate.

Subsequently, regulators in the US, EU (under MiFID II), and other jurisdictions tightened requirements for:
- Pre-deployment testing of algorithmic trading systems
- Kill switch accessibility and testing requirements (MiFID II mandates regular kill switch testing)
- Intraday position and notional limits
- Automated anomaly detection

Every requirement in the *Pre-Trade Risk Controls* section of this document, and the kill switch discussion, is grounded in part in the lesson that Knight Capital paid $440 million to teach.

> **Key idea:** The market does not stop when your system malfunctions. Every order your system sends is valid in the exchange's eyes until you cancel it or your gateway is disconnected. The only protection against a runaway algorithm is pre-trade risk controls on your own side, deployed correctly, verified after every deployment, and exercisable instantly under pressure.

