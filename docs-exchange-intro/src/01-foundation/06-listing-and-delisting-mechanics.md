# Listing and Delisting Mechanics

The *Before the Exchange* section described the IPO from the company's side: underwriters, roadshows, pricing. This section first looks more closely at how an IPO actually gets its price, then closes the loop from the exchange's side. Going public is not just a financial event, it is an application to a specific exchange, governed by that exchange's own rulebook, and staying listed is an ongoing obligation, not a one-time achievement.

## Why Exchanges Compete for Listings

A listing is valuable to an exchange for reasons beyond the one-off listing fee. A listed company generates ongoing order flow (every share ever traded on that exchange contributes to trading revenue), market data revenue (see *Market Data Economics* in Part IV), and prestige that attracts further listings. This is why exchanges actively court companies before an IPO, and why the choice between, say, NYSE and NASDAQ for a marquee technology company is itself a competitive sales process, not a formality.

## How an IPO Gets Its Price

Every IPO has to answer one question before a single share can trade: *what is this company worth, and therefore what should one share cost?* Ask five people how that number is found and you will get five answers. An investment banker will describe a disciplined process of financial models, peer comparisons and investor meetings. A venture capitalist will talk about the "story" and the size of the opportunity. A finance professor will talk about discounted cash flows. A cynical trader will say the price is whatever the banks think they can sell the shares for on the day. All of them are partly right. IPO pricing is a structured process wrapped around an irreducible core of judgement, market mood and, at times, something close to black magic.

The valuation scholar Aswath Damodaran draws a distinction that helps make sense of this. **Valuing** a company means estimating what its business is worth from its fundamentals, because in the end "it's cash in, cash out. You can't get away from that." **Pricing** a company means looking at "what other people are paying" for similar assets and "trusting the crowd on average to get it right" [Damodaran, interviewed by The Acquirer's Multiple, 2024]. An IPO is fundamentally a *pricing* exercise dressed in the language of *valuation*: the models set a plausible range, but the final number is the price at which enough real investors, on a particular week, are willing to buy.

### Why getting the number "right" matters so much

The price has to thread a needle:

- **Too high, and the deal fails.** Investors refuse to buy, the offering has to be cut or pulled, or the shares sink below the offer price soon after trading starts (Wall Street calls this "breaking issue"). The damage is lasting: early buyers lose money, the company's reputation suffers, and raising more capital later becomes harder. Facebook raised its price range from $28–$35 to $34–$38, priced at the top, $38, raised $16.08 billion at a valuation of $104.2 billion in May 2012 [Forbes, 17 May 2012], and then fell below $38 on its second trading day. It spent more than a year below its offer price.
- **Too low, and the company "leaves money on the table".** If the shares are priced at $20 and trade at $40 on day one, the company sold part of itself for half of what the market was demonstrably willing to pay. The difference went to the lucky first buyers, not to the company. Snowflake raised its range twice (the top rose from $85 to $110), priced its September 2020 IPO at $120, above even the raised range, and sold 28 million shares for $3.36 billion [CNBC, 15 September 2020]. The stock then more than doubled on its first day, closing at about $254. On those 28 million shares, the gap between the offer price and the first close was roughly 28 million × $134 ≈ **$3.75 billion**: more than the company itself raised.

Most IPOs are deliberately priced a little low. Across US IPOs from 1980 to 2025 the average first-day return was about **19%**, and at the height of the dot-com bubble in 1999–2000 it averaged about **65%**; in total, some $250 billion has been "left on the table" over that period [Jay Ritter, *IPO Statistics*, University of Florida] (see [Initial Public Offerings: Updated Statistics](https://site.warrington.ufl.edu/ritter/files/IPO-Statistics.pdf) ). A modest first-day rise is seen as healthy: it rewards the investors who committed early, creates good publicity, and makes the next offering easier. A huge first-day jump, on the other hand, usually means the price was wrong.

### The paperwork: the S-1 in the US, the prospectus in the EU

**The S-1.** In the United States, a company offering shares to the public must register them with the SEC under the Securities Act of 1933. For a US company the registration statement is **Form S-1**; a foreign company typically files the equivalent **Form F-1**. The S-1 contains the **prospectus**, the document every investor is given, plus additional information for the SEC. It is long, often several hundred pages, and describes the business, its risks (the "risk factors" section alone can run to dozens of pages), audited financial statements, management and pay, who owns what before and after the offering, and the terms of the deal.

The process runs roughly as follows. Most companies first submit a draft **confidentially**, so that the SEC's staff can comment before anything becomes public; the SEC's staff review the filing and send comment letters, and the company answers and amends until the comments are resolved. The public filing then goes out, followed by a *preliminary* prospectus that includes the proposed price range, traditionally nicknamed the **red herring** after the red warning text on its cover saying that the document is not yet final. Once the SEC declares the registration statement **effective**, the shares can be sold, and the final price appears in the final prospectus.

Two parts of the S-1 deserve special attention, because they shape how the market will see the company:

- **Classification.** The cover of Form S-1 asks for the company's **Primary Standard Industrial Classification (SIC) code**. It sounds bureaucratic, but classification decides which SEC review office examines the filing, which peer companies analysts will compare it with, and, eventually, in which sector index providers place it. It is therefore also part of the *story*. When SpaceX filed for its 2026 IPO, it was widely reported to have chosen SIC code 7370, computer programming and data processing, rather than an aerospace code, placing itself alongside software and AI companies rather than rocket makers. Separately, the US JOBS Act of 2012 created the **emerging growth company** category for smaller issuers (defined by annual revenue below roughly $1.2 billion), which may file with reduced disclosure. How a company is classified affects both its obligations and its valuation.
- **Use of proceeds.** SEC rules (Item 504 of Regulation S-K) require the prospectus to state what the company intends to do with the money it raises. The answer matters to investors in two ways. First, an IPO can sell **primary** shares, newly issued by the company, whose proceeds go to the company, and **secondary** shares, sold by existing shareholders such as founders and venture capital funds, whose proceeds go to *them*. A deal that is mostly secondary is an exit for insiders, not fresh capital for the business, and investors read it accordingly. Second, a specific plan ("build three factories", "repay this loan") is easier to judge than the vague and very common "general corporate purposes".

**The EU prospectus.** In the European Union the equivalent document is the **prospectus** required by the Prospectus Regulation (Regulation (EU) 2017/1129). It is approved by the *national competent authority* of the company's home member state (BaFin in Germany, the AFM in the Netherlands, Finansinspektionen in Sweden, and so on), and once approved it can be **passported**: used to offer the shares across the whole EU without a second approval. Its content is standardised by EU rules and covers the same ground as an S-1, including a required section on the **reasons for the offer and the use of proceeds**. The regime has just been revised by the EU Listing Act (Regulation (EU) 2024/2809), whose amendments to the Prospectus Regulation apply from 5 June 2026, with the aim of making prospectuses shorter, more standardised and cheaper to produce. The United Kingdom, outside the EU since 2020, runs its own separate prospectus regime.

### The valuation toolbox

Bankers and investors use two families of tools, and every serious IPO uses both.

**Comparable companies ("comps").** Find listed companies that look similar, see what the market pays for them relative to some measure of their business, and apply the same multiple. Common multiples are **price-to-earnings (P/E)** (share price divided by profit per share), **EV/EBITDA** (enterprise value, meaning the value of the whole business including its debt, divided by earnings before interest, tax, depreciation and amortisation) and, for companies without profits, **EV/Sales**. If similar companies trade at 20 times earnings and our company earns $100 million, a comps-based value is about $2 billion. This is *pricing* in Damodaran's sense: it inherits whatever optimism or pessimism is already in the comparable stocks.

**Discounted cash flow (DCF).** This is *valuing* in the intrinsic sense. A company is worth the cash it will generate for its owners in the future, adjusted for the fact that money later is worth less than money now. Two ideas carry the whole method:

- **Discounting.** $100 received a year from now is worth less than $100 today, because today's $100 could be invested in the meantime and because the future is uncertain. With a **discount rate** of 9%, $100 in one year is worth 100 / 1.09 ≈ $91.74 today, and $100 in five years is worth 100 / 1.09⁵ ≈ $64.99. The discount rate reflects the return investors demand for the risk they take; riskier businesses get higher rates.
- **Terminal value.** Nobody can forecast cash flows forever, so analysts forecast a few years in detail and then assume steady growth from then on. A cash flow *C* growing at rate *g* forever, discounted at rate *r*, is worth *C* / (*r* − *g*) (the "Gordon growth" formula).

A worked example. A company's free cash flow (the cash left after running and investing in the business) is $100 million this year. Analysts expect it to grow 10% a year for five years, then 3% a year forever, and they use a 9% discount rate:

| Year | Free cash flow ($m) | Discount factor 1 / 1.09^t | Present value ($m) |
|---|---|---|---|
| 1 | 110.0 | 0.917 | 100.9 |
| 2 | 121.0 | 0.842 | 101.8 |
| 3 | 133.1 | 0.772 | 102.8 |
| 4 | 146.4 | 0.708 | 103.7 |
| 5 | 161.1 | 0.650 | 104.7 |
| | | **Sum of years 1–5** | **513.9** |

The terminal value at the end of year 5 is 161.1 × 1.03 / (0.09 − 0.03) ≈ $2,765 million, worth 2,765 / 1.09⁵ ≈ $1,797 million today. The business is therefore worth about 513.9 + 1,797 ≈ **$2.31 billion**.

Two lessons hide in that arithmetic, and both matter enormously for IPOs:

1. **Most of the value is in the distant future.** About 78% of the $2.31 billion comes from the terminal value, from cash flows *after* year five, which nobody can forecast with any confidence.
2. **Small changes in assumptions cause big changes in value.** Use an 8% discount rate instead of 9% and the value rises to about $2.79 billion (+21%); use 10% and it falls to about $1.97 billion (−15%). A one-point disagreement about risk moves the answer by hundreds of millions of dollars.

**From company value to share price.** Suppose the valuation work (DCF, comps, and conversations with investors) lands at an equity value of about $2.3 billion for a company with 100 million shares outstanding before the IPO: about $23 per share. The underwriters will typically propose a range somewhat below that, say $19–$21, building in the deliberate **IPO discount** that rewards early buyers for taking a chance on an untested stock. If the company then sells 20 million *new* shares at $20, it raises $400 million, and afterwards there are 120 million shares outstanding.

### When the toolbox breaks: valuing hype

The DCF method works best for businesses with positive, reasonably predictable cash flows. It struggles badly with the companies that attract the most excitement: young businesses that burn cash today and promise enormous cash flows later. For them, the near-term cash flows are *negative*, so essentially all of the value sits in a terminal value many years out, built on assumptions about growth, margins and competition that are close to guesses. Change the guesses slightly and the value can move by a factor of two or three.

Analysts therefore often run the method backwards. A **reverse DCF** asks: *what would have to be true for today's price to make sense?* Take SpaceX, which priced its June 2026 IPO at $135 per share, a valuation of about $1.77 trillion, against 2025 revenue of $18.7 billion and an operating loss of $2.6 billion [Fortune, 20 May 2026]. That is roughly 95 times last year's revenue. A deliberately simple reverse DCF: an investor who wants a 10% annual return needs the company to be worth about $1.77 trillion × 1.1¹⁰ ≈ $4.6 trillion in ten years. At a mature price-to-earnings ratio of 25, that requires annual profits of about $184 billion; at a healthy 20% profit margin, that requires annual revenue of about $920 billion. Growing from $18.7 billion to $920 billion in ten years means growing about **48% a year, every year, for a decade**. Perhaps that will happen; the point is that the price is a statement of belief about the far future, not a conclusion derived from present-day numbers. Independent valuations of the same company at the time ranged from well under a trillion dollars to around $1.3 trillion, which shows how much room the method leaves.

**The TAM argument.** When the cash flows cannot carry the valuation, the story often shifts to the size of the opportunity. The **total addressable market (TAM)** is the total revenue available if a company captured *all* of the demand for what it sells. (Analysts often narrow it further to the *serviceable* market the company can realistically reach, and to the share it can realistically obtain.) A huge TAM makes a high valuation look modest: capture "just" a few percent of a multi-trillion-dollar market and today's price seems cheap. Recent prospectuses have made remarkable TAM claims:

- **Uber (2019)** described a total addressable market of about **$12 trillion** across personal mobility, food delivery and freight [Forbes, 22 April 2019].
- **WeWork (2019)** claimed a **$3.0 trillion** market opportunity in 280 target cities, noting that it had realised "approximately 0.2%" of it [WeWork S-1, August 2019], while its 2018 revenue was about $1.8 billion against a net loss of about $1.9 billion.
- **SpaceX (2026)** claimed a TAM of **$28.5 trillion**, of which $26.5 trillion, about 93%, was attributed to artificial intelligence rather than to rockets or satellite internet [Fortune, 20 May 2026].

TAM is a useful sanity check on whether a business *could* become large. It is a poor guide to whether it *will*, because it says nothing about competitors, pricing power, costs or execution. Several spectacular failures had impressive TAMs. WeWork was valued at **$47 billion** in a private funding round in January 2019; it filed its S-1 on 14 August 2019; within weeks the valuation being discussed fell to about $10 billion; the IPO was withdrawn on 30 September 2019; the company later listed through a SPAC merger in October 2021 at about $9 billion and filed for bankruptcy on 6 November 2023 [Forbes, 7 November 2023].

History offers plenty of company for WeWork. **Pets.com** went public in February 2000 at $11 per share, raising $82.5 million, and announced its liquidation on 7 November 2000 with its shares at $0.19, having become famous mainly for its sock-puppet mascot. **Rivian** raised its range from $57–$62 to $72–$74 and then priced its November 2021 IPO at $78, valuing the electric-truck maker at about $66.5 billion, although its prospectus showed that it expected quarterly revenue of between zero and $1 million and it had not yet delivered vehicles to customers [CNBC, 9 November 2021]. On its first trading day its market value passed Ford's; a few years later its shares traded at a small fraction of the IPO price. The pattern is the same each time: the valuation rested on a story about the future, and the future turned out different.

None of this means hyped valuations are always wrong. Amazon went public in May 1997 at $18 per share as an unprofitable online bookseller, and Google's 2004 IPO valued it at about $23 billion; both look like bargains in hindsight. The honest conclusion is that for high-growth companies, the IPO price is a bet, and the process described next is how the market places it.

### Book-building: discovering the price

A conventional US IPO establishes its price through **book-building**, a process run by the lead underwriters (the "bookrunners"):

1. **Setting a range.** Using the valuation work above and early informal conversations with investors ("testing the waters"), the company and its underwriters publish a **price range** in the preliminary prospectus, for example $19–$21 per share.
2. **The roadshow.** Management and bankers spend one to two weeks presenting to institutional investors (mutual funds, pension funds, hedge funds), historically in person across several cities, today largely by video.
3. **Building the book.** Investors submit **indications of interest**: how many shares they would buy, and often at what maximum price. These are not binding orders. The bookrunners record them in "the book" and watch how much demand there is at each price and from which kinds of investors. A book "covered ten times" has indications for ten times the shares on offer.
4. **Revising the range.** If demand is strong, the range is raised (Facebook, Snowflake and Rivian all raised theirs); if it is weak, the range is lowered or the deal is made smaller. CoreWeave, an AI cloud company, marketed its shares at **$47–$55** in March 2025 but priced at **$40**, below the range, and cut the deal to 37.5 million shares, raising $1.5 billion [CoreWeave press release, 27 March 2025; Reuters]. Within days of its debut the stock had risen well above the offer price, a reminder that a weak book says as much about the market's mood that week as about the company.
5. **Pricing.** The final price is set on the evening before trading begins, after the SEC declares the registration effective. The underwriters then **allocate** shares. Allocation is discretionary, not pro-rata: underwriters favour investors they expect to hold for the long term over those they expect to "flip" the shares on day one.
6. **The first trade.** The next morning, the stock opens on the exchange through a special opening auction (on NASDAQ the **IPO Cross**), using exactly the equilibrium-price mechanics described in the *Opening and Closing Auction* chapter of Part II. The IPO price is what the company received; the opening auction price is the market's first verdict.
7. **The greenshoe.** Underwriters usually have an **over-allotment option**, known as the **greenshoe** after the 1960s Green Shoe Manufacturing Company deal that first used it, to sell up to 15% more shares than planned. They can use it to support the price if it falls in early trading ("stabilisation") or simply sell the extra shares if demand is strong.

For this work the underwriters earn a fee, the **gross spread**, deducted from the proceeds. On moderate-sized US IPOs it has remained at about **7%** for decades [Ritter, *IPO Statistics*]; mega-deals negotiate far less (SpaceX's banks reportedly took under 1%).

### Book-building is a custom, not a law

Nothing in US or EU law requires a company to use book-building. The securities laws regulate *disclosure* (what the prospectus must say and when shares may be sold), not the *method* by which the price is found. Book-building dominates because underwriters prefer it and issuers value the guarantee and the investor relationships that come with it. The alternatives are real:

- **Auctions.** Google's August 2004 IPO used a modified **Dutch auction**, open to large and small investors alike, in which bidders named a price and quantity and a single clearing price was set from the bids. It did not go smoothly: the range was cut from $108–$135 to $85–$95 and the shares were priced at $85, raising $1.67 billion [The Register, 19 August 2004]. Few large companies have copied the approach since.
- **Direct listings and SPAC mergers**, described in *Alternatives to the Traditional IPO* below, reach the market with no book-building at all.

### Who gets the shares: institutions and retail

In a typical US IPO, most shares go to **institutional investors**. There is no legal minimum for retail investors; retail access usually comes through brokers that receive a small allocation from the underwriters, and IPO shares have traditionally been "reserved for wealthier brokerage clients and institutional investors" [CNBC, 2 July 2021]. That has been changing. Robinhood reserved **20% to 35%** of the shares in its own 2021 IPO for its customers [CNBC, 2 July 2021], and SpaceX's 2026 offering was reported to have used an institutional-to-retail ratio of 70:30.

Other markets write the split into the rules. Many European IPOs combine an *institutional offering* with a separate *public offering* to retail investors in the home country. Hong Kong specifies it precisely: under rules in force since 4 August 2025, at least 40% of the shares must go to the book-built institutional tranche, and the public subscription tranche either starts at a minimum of 5% and is "clawed back" up to 35% if retail demand is very heavy, or is fixed at between 10% and 60% [Bird & Bird, 2025].

### The lock-up

Before the IPO, founders, employees and venture capital funds own all of the company. If they could all sell on the first day, the flood of shares would swamp the market and the price would collapse. The **lock-up agreement** prevents this: insiders promise the underwriters not to sell for a fixed period, most commonly **180 days** [Investor.gov, *Lockup Agreements*]. Lock-ups are *contracts*, not law; securities law only requires that their terms be disclosed in the prospectus. The underwriters can release insiders early, and modern lock-ups are often staggered, releasing some shares early if the stock performs well. SpaceX's insiders reportedly agreed to a 366-day lock-up, other pre-IPO investors to 180 days.

The day a lock-up expires is a known date, and it is marked on every trader's calendar: a large block of shares suddenly becomes sellable, and prices often weaken around it.

### Joining the index

A newly listed stock is not automatically part of the market indexes, and that matters a great deal. As the *Indexes* chapter of Part II explains, index funds *must* buy every stock in their index, in proportion to its weight. Inclusion in a major index therefore triggers large, price-insensitive buying.

Index providers traditionally made newcomers wait. The S&P 500 requires an IPO to have traded for at least **12 months** and to have positive earnings in its most recent quarter and over its most recent four quarters combined [S&P Dow Jones Indices, *U.S. Indices Methodology*]. In 2026 the arrival of several enormous IPOs put this under pressure. S&P Dow Jones Indices consulted on shortening the wait to six months and on exceptions for "mega-cap" companies, and on 4 June 2026 decided *not* to change the S&P 500's rules, stating that exceptions "should not be granted solely based on market capitalization" [S&P DJI, 4 June 2026]. Nasdaq went the other way: in spring 2026 it adopted a "fast entry" rule allowing a very large new listing to join the Nasdaq-100 after just **15 trading days**, with five trading days' notice. SpaceX joined the Nasdaq-100 under this rule, while its losses kept it out of the S&P 500. Critics pointed out the uncomfortable side effect: investors who bought at the IPO could sell to index funds that were obliged to buy only a few weeks later.

### A gallery of outcomes

| Company | IPO | Price and valuation | What happened |
|---|---|---|---|
| Amazon | May 1997 | $18 per share | An unprofitable online bookseller at IPO; became one of the most valuable companies in the world |
| Pets.com | Feb 2000 | $11 per share, raised $82.5m | Liquidated nine months later, shares at $0.19 |
| Google | Aug 2004 | $85 (Dutch auction, range cut from $108–$135), about $23bn | Priced below its hoped-for range; a long-term success |
| Facebook | May 2012 | $38 (range raised twice), $104.2bn | Broke issue within days; later far exceeded its IPO price |
| WeWork | 2019 (withdrawn) | $47bn private valuation, then talk of about $10bn | IPO pulled; SPAC listing 2021; bankrupt 2023 |
| Snowflake | Sep 2020 | $120 (range raised twice), $33.3bn | Doubled on day one, leaving roughly $3.75bn "on the table" |
| Rivian | Nov 2021 | $78 (range raised), $66.5bn, with almost no revenue | Worth more than Ford on day one; later fell far below its IPO price |
| CoreWeave | Mar 2025 | $40, below its $47–$55 range, deal cut | Weak book, then a strong rally within days |
| SpaceX | Jun 2026 | $135, about $1.77tn, largest IPO ever | Rose about 19% on day one; valuation rests on a $28.5 trillion TAM story |

### What this means for exchange developers

The valuation debate happens before the exchange is involved, but IPO day itself lands squarely on exchange systems. A new symbol must be created in the reference data (see *Reference Data* in Part IV), with no trading history, so there is no previous close to anchor price collars or circuit breakers: the IPO price and the opening auction take that role. The opening auction may be delayed repeatedly while the indicative price settles and the lead underwriter confirms it is ready to open, so the auction logic must support extended, supervised call periods. Market-data volumes on a hot IPO's first morning can be extreme. And 180 days later, the lock-up expiry produces a predictable, scheduled surge in selling that risk and capacity planning should expect.

> **Key idea:** An IPO price is found, not calculated. Valuation models such as comparable multiples and discounted cash flow set a plausible range, but for young, high-growth companies nearly all of the value lies in distant, uncertain cash flows, and stories about total addressable markets fill the gap. Book-building, a customary rather than legally required process, then discovers what real investors will pay. Allocation rules decide who gets the shares, lock-ups keep insiders from selling too early, and index rules decide when forced buying arrives. Price it too high and the deal fails; price it too low and the company gives away capital it could have raised.

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

**Direct listings.** In a **direct listing**, a company's existing shares begin trading directly on the exchange, in the classic form with no new shares issued, no underwriter guarantee, and no fixed offer price set in advance by a roadshow. Instead, the opening trade is established through the exchange's **opening auction** mechanism (see the *Opening and Closing Auction* section of Part II) exactly like any other trading day's open, just with unusually intense interest and no underwriter smoothing the process. Spotify's April 2018 listing on NYSE and Slack's June 2019 listing on NYSE were the pioneering examples that established direct listings as a credible alternative for companies that do not need to raise new capital and want to avoid underwriting fees and the traditional IPO discount. Because there is no underwriter-set price to anchor expectations, the exchange's auction-price-discovery mechanism carries unusually high scrutiny on a direct listing's first trade. (Since 2020 the SEC has also approved NYSE and Nasdaq rules for *primary* direct listings, in which the company sells new shares in that opening auction.)

**SPAC mergers.** A **Special Purpose Acquisition Company (SPAC)** is a shell company with no operating business that itself completes a conventional IPO, raising cash that is held in trust, with the explicit purpose of later merging with a private operating company to take it public. When the merger (a "**de-SPAC**" transaction) completes, the private company's shareholders receive shares in the (now renamed) public shell, and the target company is effectively listed without ever running its own IPO process. SPACs existed for decades as a niche structure but became a major share of total US listing activity in 2020–2021, before a wave of poor post-merger performance and increased SEC disclosure requirements sharply reduced the volume of new SPAC formations from 2022 onward. For exchange and reference-data systems, a de-SPAC transaction looks much like the symbol changes and delistings described in *Corporate Actions*, the shell's ticker and name are typically replaced by the operating company's (the surviving legal entity, and with it the SEC's CIK identifier, is often the shell itself), but compressed into a single scheduled event that must be coordinated precisely across trading, clearing, and market data simultaneously.

> **Key idea:** An IPO is a financial event; a listing is a continuing regulatory relationship with a specific exchange, governed by initial standards to get in and continued standards to stay in. Reverse splits, delistings, direct listings, and SPAC mergers are all variations on the same underlying reference-data and corporate-action machinery described in Part IV, the trigger differs, but the exchange-side mechanics of updating symbols, adjusting orders, and coordinating the change across every downstream system are the same.
