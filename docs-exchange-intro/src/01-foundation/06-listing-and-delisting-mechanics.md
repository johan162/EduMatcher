# Listing and Delisting Mechanics

The *Before the Exchange* section described the IPO from the company's side: underwriters, roadshows, pricing. This section closes the loop from the exchange's side. Going public is not just a financial event, it is an application to a specific exchange, governed by that exchange's own rulebook, and staying listed is an ongoing obligation, not a one-time achievement.

## Why Exchanges Compete for Listings

A listing is valuable to an exchange for reasons beyond the one-off listing fee. A listed company generates ongoing order flow (every share ever traded on that exchange contributes to trading revenue), market data revenue (see *Market Data Economics* in Part IV), and prestige that attracts further listings. This is why exchanges actively court companies before an IPO, and why the choice between, say, NYSE and NASDAQ for a marquee technology company is itself a competitive sales process, not a formality.

## Initial Listing Standards

Every exchange publishes **initial listing standards**, minimum quantitative and qualitative thresholds a company must meet before its shares can begin trading. These typically combine several dimensions, and both NYSE and NASDAQ offer multiple listing tiers with different thresholds (NASDAQ's Global Select, Global Market, and Capital Market tiers, for example, from most to least stringent):

- **Minimum share price:** commonly a bid price of at least $4.00 at initial listing.
- **Market value of publicly held shares (public float):** a minimum aggregate dollar value of shares actually available for public trading, excluding insider- and affiliate-held blocks, illustratively in the tens of millions of dollars for the least stringent tiers and considerably higher for the most prestigious ones.
- **Minimum number of round-lot shareholders:** a floor on how widely the shares are already held, intended to ensure a genuine public market exists from day one rather than a handful of large holders.
- **Corporate governance requirements:** an independent board majority, an independent audit committee, and public financial disclosure obligations under the exchange's rules and the applicable securities laws.

(Exact numeric thresholds are revised periodically by each exchange and its regulator; treat the figures above as illustrative of the *kind* of requirement, not as current values to hardcode into any reference-data system.)

Meeting every quantitative threshold is necessary but, on some exchanges, not sufficient: as the *Indexes* section of Part II noted for S&P 500 committee discretion, initial listing approval can involve qualitative judgement about the business and its readiness for public markets, not a purely mechanical checklist.

## Continued Listing: An Ongoing Obligation

Initial listing standards get most of the public attention, but **continued listing standards** matter more to exchange system developers, because they generate ongoing, automated compliance monitoring rather than a one-time gate. A company that met every threshold at its IPO can fall out of compliance years later if its stock price declines, its market cap shrinks, or its public float narrows.

The most common continued-listing trigger is the **minimum bid price rule**: if a stock's closing price stays below $1.00 for 30 consecutive trading days, the exchange issues a formal deficiency notice. The company then has a **cure period**, commonly 180 days, to regain compliance (ten consecutive trading days at $1.00 or above), and in some cases a further 180-day extension if it meets other listing criteria. This is the direct, practical reason struggling companies execute a **reverse stock split** (see the *Corporate Actions* section of Part IV): consolidating, say, ten existing shares into one instantly multiplies the nominal share price by ten, curing a bid-price deficiency without changing the company's actual market value by a cent. A reverse split undertaken for this reason is a compliance action, not a statement about the business, and exchange systems must handle it exactly like any other corporate action (adjusting resting orders, historical price series, and reference data) regardless of the reason behind it.

Failure to cure within the allowed window leads to **involuntary delisting**: the exchange begins the formal process of removing the security, the company can appeal to a listing qualifications panel, and if the delisting proceeds, the shares typically continue trading, if at all, on the OTC (over-the-counter) markets described in Part I, with materially less liquidity, visibility, and investor protection than an exchange listing provided.

## Voluntary Delisting

Not all delistings are compliance failures. A company can voluntarily delist because it has been **acquired** (its shares convert to cash or acquirer stock, as described in the *Corporate Actions* section of Part IV), because it has been **taken private** (a controlling investor or management buyout removes public shares from circulation entirely), or, more rarely, because it decides the costs of public-company reporting and exchange fees no longer justify the benefits of a listing. All of these still require an orderly unwind of open orders and positions in the symbol, exactly as described in the *Corporate Actions* section, whether the delisting is voluntary or forced.

## Alternatives to the Traditional IPO

The underwritten IPO described in Part I, banks buy the offering and guarantee the company its proceeds, is not the only path onto an exchange.

**Direct listings.** In a **direct listing**, a company's existing shares begin trading directly on the exchange with no new shares issued, no underwriter guarantee, and no fixed offer price set in advance by a roadshow. Instead, the opening trade is established through the exchange's **opening auction** mechanism (see the *Opening and Closing Auction* section of Part II) exactly like any other trading day's open, just with unusually intense interest and no underwriter smoothing the process. Spotify's April 2018 listing on NYSE and Slack's June 2019 listing on NYSE were the pioneering examples that established direct listings as a credible alternative for companies that do not need to raise new capital and want to avoid underwriting fees and the traditional IPO discount. Because there is no underwriter-set price to anchor expectations, the exchange's auction-price-discovery mechanism carries unusually high scrutiny on a direct listing's first trade.

**SPAC mergers.** A **Special Purpose Acquisition Company (SPAC)** is a shell company with no operating business that itself completes a conventional IPO, raising cash that is held in trust, with the explicit purpose of later merging with a private operating company to take it public. When the merger (a "**de-SPAC**" transaction) completes, the private company's shareholders receive shares in the (now renamed) public shell, and the target company is effectively listed without ever running its own IPO process. SPACs existed for decades as a niche structure but became a major share of total US listing activity in 2020–2021, before a wave of poor post-merger performance and increased SEC disclosure requirements sharply reduced the volume of new SPAC formations from 2022 onward. For exchange and reference-data systems, a de-SPAC transaction looks much like the symbol changes and delistings described in *Corporate Actions*, the shell's original ticker and CIK are typically replaced by the operating company's, but compressed into a single scheduled event that must be coordinated precisely across trading, clearing, and market data simultaneously.

> **Key idea:** An IPO is a financial event; a listing is a continuing regulatory relationship with a specific exchange, governed by initial standards to get in and continued standards to stay in. Reverse splits, delistings, direct listings, and SPAC mergers are all variations on the same underlying reference-data and corporate-action machinery described in Part IV, the trigger differs, but the exchange-side mechanics of updating symbols, adjusting orders, and coordinating the change across every downstream system are the same.
