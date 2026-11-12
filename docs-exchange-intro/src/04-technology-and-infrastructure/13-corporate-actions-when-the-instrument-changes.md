# Corporate Actions, When the Instrument Changes


An exchange does not just serve static instruments. Companies whose shares trade on an exchange undergo **corporate actions**, events that change the structure of the instrument itself. These events have significant operational consequences for every component of an exchange system.

## Stock Splits

A **stock split** divides each existing share into multiple new shares, reducing the price proportionally. If AAPL trades at $200 and does a 4-for-1 split, each shareholder receives 4 shares for every 1 they held; the price adjusts to approximately $50. The total market capitalisation is unchanged.

Exchange implications:
- Open limit orders must be either adjusted (an order to buy 100 shares at $200 becomes an order to buy 400 shares at $50) or, as many venues prefer, cancelled before the split takes effect so that participants re-enter them at the new price. Whichever policy the venue uses must be applied to every resting order, without exception.
- Historical price data must be adjusted (or marked as pre-split) to avoid false apparent price changes.
- Tick size may change (a lower price may use a different tick increment).
- Reference data (symbol metadata) must be updated.

A **reverse split** works in the opposite direction: multiple shares are consolidated into one, and the price rises proportionally. A company trading at $0.50 might do a 10-for-1 reverse split to bring the price to $5, typically to meet exchange listing requirements.

## Dividends

A dividend comes with a fixed sequence of dates: the **declaration date** (the board announces it), the **ex-dividend date**, the **record date** (whoever is on the shareholder register that day is paid; in the US, since T+1 settlement, it falls on the same day as the ex-date) and the **payment date**. Shares trade **cum-dividend** (with dividend entitlement) up to the **ex-dividend date**, after which they trade **ex-dividend** (without dividend entitlement). The price typically drops by approximately the dividend amount on the ex-dividend date.

Open orders spanning the ex-dividend date may require handling, some exchanges cancel all open orders; others adjust prices.

## Spin-offs and Rights Issues

In a **spin-off**, a company separates part of its business into a new, independently listed company and hands the new shares to its existing shareholders. On the spin-off date a brand-new symbol appears, and the parent's price drops by roughly the value of what was given away. In a **rights issue**, existing shareholders get the right to buy new shares at a discount, in proportion to what they already own; the rights themselves often trade as a separate, short-lived instrument. Both events create instruments that did not exist the day before and change the economics of one that did, so they touch reference data, open orders, positions and historical prices all at once.

## Mergers and Acquisitions

When a company is acquired, its shares may be converted to shares in the acquirer, cash, or a combination. The target company's shares are eventually **delisted**, removed from trading on the exchange. All open orders in the target must be cancelled. Open positions must be settled.

## Symbol Changes and Delistings

Companies change their ticker symbols (rebranding, mergers). Systems that track positions and orders by symbol must handle symbol remapping without losing continuity. **Delistings** require orderly unwinding of all open orders and positions in the symbol.

## Why Corporate Actions Matter to Developers

Corporate actions are among the most operationally complex events an exchange system handles (the *Indexes* chapter showed how index providers have to absorb the same events in their divisors). They require coordination across: the order book engine (cancel or adjust open orders), the clearing system (adjust positions and cost bases), the market data system (update reference data), the audit trail (record the adjustment events), and downstream applications that may have cached the old instrument parameters.

A developer who underestimates corporate action complexity will eventually face a bug report like: "after the split, the order that was resting at $200 for 100 shares is now resting at $200 for 100 shares instead of $50 for 400 shares." The split was never propagated to the open order book.

> **Key idea:** Instruments are not static. Every system that touches order, position, or price data must be prepared to handle corporate action adjustments. Reference data management is a discipline in its own right in production exchange systems.

