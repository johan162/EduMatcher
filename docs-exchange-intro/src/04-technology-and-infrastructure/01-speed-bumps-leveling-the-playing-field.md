# Speed Bumps, Leveling the Playing Field


Not all exchange participants operate on equal footing. High-frequency trading (HFT) firms invest heavily in co-location, low-latency network links between venues, and specialised hardware to be a few microseconds faster than competitors. Being faster often means seeing price changes and reacting before others, which can be profitable but is also controversial from a market-structure perspective.

## What Is a Speed Bump?

A **speed bump** is a deliberate artificial delay introduced by the exchange to incoming orders. A fixed delay (for example, 350 microseconds) does **not** erase relative timing differences: if one order is 1 microsecond earlier before the delay, it is still 1 microsecond earlier after the delay. What the speed bump can do is reduce the value of ultra-small latency edges and make some short-horizon race strategies harder, especially when combined with venue rules on cancels, quote updates, and matching behavior.

## IEX: The Most Famous Speed Bump

**IEX (Investors Exchange)**, founded as a company in 2012, began operating as a dark pool in 2013, and became a registered national securities exchange in 2016, introduced the speed bump concept to mainstream exchange operation [6]. IEX routes all orders through 38 miles of coiled fibre-optic cable (housed in a small box called the "magic shoe") before they reach the matching engine. The cable introduces a fixed 350-microsecond delay.

IEX's founders argued in the book *Flash Boys* (Lewis, 2014) [6] that speed advantages primarily benefit HFT firms at the expense of long-term investors. The speed bump was their answer. IEX gained regulatory recognition as a licensed national securities exchange and stimulated substantial regulatory and academic debate about speed bump design, though it has consistently captured a small fraction of total US equity volume (around 2–3%) rather than displacing the established venues [1]. Its significance lies more in having demonstrated that speed bump mechanisms are legally and operationally viable, and in influencing ongoing market structure policy discussions, than in market share.

## Speed Bumps in Broader Design

Speed bumps can also be **asymmetric**: applied to some message types and not others. The common modern design delays *aggressive* orders (those that would trade immediately on arrival) while letting passive orders and cancellations through at full speed. The purpose is to protect liquidity providers from **latency arbitrage**: when the market moves, a fast trader races to hit a market maker's now-stale quote before the market maker can cancel it. Delay the aggressor by a millisecond or two, and the market maker's cancel wins the race. Supporters argue this lets market makers quote tighter and larger, because they are picked off less often; critics argue it gives one class of participant a structural privilege and invites "fading" (quotes that vanish just as you try to trade with them).

Real examples are no longer rare. Canada's TSX Alpha Exchange introduced a randomised delay of 1 to 3 milliseconds on most incoming orders in 2015, exempting post-only orders. Eurex introduced **Passive Liquidity Protection** in 2019, delaying "all aggressive orders" by 1 millisecond in German equity options and 3 milliseconds in French equity options, and by a product-specific time in certain FX futures, before they can interact with the book [Eurex, *Passive Liquidity Protection*]. The design space is wide: symmetric or asymmetric, fixed or randomised, all messages or only some, and every choice shifts advantage between participants in a way the exchange must be able to defend to its regulator.

