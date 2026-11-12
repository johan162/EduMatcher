# Exchange Intro Book: Full Review (2026-11-12)

Scope: all 46 chapters in `docs-exchange-intro/src/` (plus preface and part openers where they touch terminology).
Goals: correctness, completeness, beginner-friendly language, terms defined before use (Info boxes for
circular dependencies), new illustrations where they clearly help. Nothing committed.

New figure PNGs are rendered by scripts in `docs-exchange-intro/scripts/`. The `-small.png` variants of
new figures are **provisional** 80 % resizes made with PIL so the build works; replace them with
hand-made versions as usual.

## Change log by chapter

### Front matter

### Part I

#### I.1 Before the Exchange: How Companies Raise Capital
- "This section is a brief detour" → "This chapter is a short detour".
- Bond resale sentence rewritten in plainer words.
- First use of **retail investors** and **institutional investors** now glossed inline (both used before ch. I.4 defines them).
- Over-allotment option glossed inline with a pointer to *Listing and Delisting Mechanics* (greenshoe is defined there).
- SpaceX share-price paragraph: the convoluted "blue chip" parenthetical rewritten into plain language.
- "The stock exchange is among the **primary** venues of the **secondary** market" → "best-known venue" (the
  word "primary" collided with "primary market" one paragraph earlier). **OTC** and **lit** now defined at first use.
- "Bonds (some exchange-based, others OTC)" → "some on exchanges, most OTC" (most bond trading is OTC).
- Futures and options now get a one-sentence definition at first use.
- Forward pointer to the "blue chip" story now names the right chapter (*The Language of the Market*).

#### I.2 What Is a Financial Exchange
- NYSE "founded in 1792 under a buttonwood tree" → "traces its origins to an agreement signed in 1792" (formal NYSE came later).
- OTC/ATS/ECN/internaliser paragraph: each now gets a one-line definition; **dark pool** introduced here;
  "order book, spread, price-time priority" flagged as "all explained in Part II".
- **Margin call** defined (was used undefined in the 1929 story).
- **Short sale** defined at first use (Reg SHO bullet; long/short is only explained in ch. I.3).
- MiFID II bullet: **best execution**, **kill switch**, **systematic internaliser** now explained inline.
- South Sea note: "retarded" → "held back"; stray trailing ";" in reference removed.
- "one Euro" → "one euro"; **order book** given a one-line definition at the end of the chapter.

#### I.3 The Language of the Market
- **Structural:** section "The Language Lives in the Code" moved from before Black Monday to after the
  bid/ask/spread, long/short and short-selling sections; it used `spread`, `aggressor_side`, long/short before they
  were explained. Added a lead-in sentence saying lots, ticks, sweeps and TIF codes come in Part II, and short
  glosses for `lot_size`/`tick_size` and "sweep".
- **Correctness:** "thresholds adjusted … most recently after March 2020" was wrong; the 7/13/20 % levels date from 2013,
  March 2020 is when they were triggered four times. Rewritten.
- Settlement section now opens with what **settlement** is and what **T+N** means (was used without definition).
- **Market maker** glossed at first use (specialist paragraph); **resting order** defined at "crossing the spread".
- Naked short selling: "generally illegal" → "prohibited for almost everyone (market makers have a narrow exception)".
- **Prime broker**, **custodian**, **CCP**, **FIX**, **gateway** glossed at first use in the short-selling mechanics.
- "Risk Controls, Protecting the Market section" → correct chapter title; "the floor price" → "the floor" (floor price
  is not a floor-trading term).

#### I.4 The Participants
- **Adverse selection**, **VWAP algorithm**, **smart order routing**, **market impact**, **PFOF**, **arbitrage**,
  **latency arbitrage**, **co-location**, **block order** explained at first use.
- Duplicate maker/taker definition in the Market Makers section removed (kept the first one).
- New: **dealer / broker-dealer** defined in the Brokers section (term is used throughout the book, never defined).
- New short section "Behind the Scenes: Clearing Houses and Depositories" introducing **CCP**, **clearing member**,
  **custodian**, **CSD**; later chapters assume these.
- Regulator acronyms (FSA, SFC, ASIC) expanded; "two linked legs" → "two linked sides" (legs come later).

#### I.5 A Brief Tour of Real-World Exchanges
- New **Info box** "Names before explanations" at the top: price-time priority, pro-rata, auctions, MMP are used in
  the tour before Part II explains them.
- **Correctness:** SGX "MSCI Asia index futures" replaced by FTSE China A50 (most MSCI Asia derivatives moved to HKEX
  after 2021). Japan's daily price limits do not suspend trading; text corrected. LSE pre-1986 floor was not open
  outcry ("face-to-face trading on the exchange floor"). Cboe list now separates options and equity exchanges.
- JPX ranking caveat shortened; LULD expanded with a pointer to Part III.

#### I.6 Listing and Delisting Mechanics
- All DCF/reverse-DCF arithmetic verified numerically (8 % → $2.79bn, 10 % → $1.97bn, 78 % terminal value; correct).
- **Correctness:** Snowflake raised its range **once** ($75–85 → $100–110), not twice; Facebook also once. Text and
  gallery table fixed.
- EU Listing Act: amendments apply in stages, the last from 5 June 2026 (was "apply from 5 June 2026").
- Equity value example: added "no debt" assumption so equity value = business value.
- Wrong internal pointers fixed: "*Indexes* section of Part II **noted**" (Indexes comes later), "OTC markets described in
  Part I" and "IPO described in Part I" (we are in Part I) now name the actual chapters.
- **Round lot**, **CIK**, **price collars**, **indicative price** glossed at first use.

### Part II

#### II.1 The Order
- Price row: market orders explained in passing; TIF row "its own section below" → "its own chapter, two chapters on".
- **NBBO** and **consolidated tape** defined at first use (were used undefined with only a Part IV pointer).

#### II.2 Order Types
- **Correctness:** the "Price Improvement" section called a fill at the resting ask "price improvement relative to
  your limit". In industry usage and in Rule 605 (cited in the same section) price improvement means a fill better
  than the best *publicly quoted* price. Split into "You Trade at the Resting Order's Price" + a correct
  "Price Improvement" subsection.
- Iceberg: "also called hidden order" removed (a hidden order is a different, fully hidden type); **front-run** glossed.
- New short section **Post-Only Orders** (standard market-maker order type; only mentioned in Part IV before).
- **Call / put / strike** defined before straddles/strangles; butterfly description corrected (1 : −2 : 1 over three strikes).
- OCO: "This is called a bracket order" softened (a bracket strictly includes the entry order).
- Midpoint pointer: "*Tick Sizes* section below" → chapter later in this Part.

#### II.3 Time-In-Force
- GTC: added that several US stock exchanges no longer accept GTC (NYSE dropped them in 2016); futures venues do.
- **Continuous session** and **uncross** defined at first use; **SMP** spelled out with a Part III pointer.

#### II.4 The Order Book
- "A buyer **offering** $150.34" → "bidding" (offer = sell side; confusing for beginners). Same fix in II.5.
- "price improvement (a new best level)" in the insert cost analysis reworded (clashed with the corrected term).
- Spread paragraph points back to its first definition; **P&L** spelled out.
- Blockquote preview of closing auction / static collar converted to an `!!! info` box; wrong pointer
  "Static price collars are covered in the *Trading Sessions* section" → *Risk Controls* (Part III), where they are.

#### II.5 Price-Time Priority / II.6 Tick Sizes
- II.6 opened with "the previous section … showed why prices are stored as integer tick counts", which II.5 never
  did. II.5 now forward-points to II.6; II.6 intro rewritten and "Recap:" dropped from its first heading.
- "US equity futures on CME" → "equity index futures".
- Odd-eighths note (II.6): the fractions were written as Unicode characters (⅛ ⅜ ⅝ ⅞) that the PDF font lacks,
  so the text rendered as "odd eighths ($, , , )". Rewritten with plain fractions, and the note now first explains
  fractional quoting and which eighths are "odd" / "even", then the finding with a concrete $20 1/4 / $20 1/2 example.
  These were the only Unicode fraction characters in the book.

#### II.7 The Matching Engine
- "no garbage-collected language" was too strong (several production engines are Java); reworded to "no GC pauses".
- Mermaid node "Publish all events to PUB socket" → "to participants and market data" (implementation jargon).
- Data-structures section now acknowledges *The Order Book* chapter already covered one design in detail.

#### II.8 The Life of a Trade
- "The viewer, board, stats database" (EduMatcher component names) replaced by generic subscribers.
- Pointers to "the Technology Architecture section" now name the Part IV chapter.

#### II.9 Market Makers
- New short section **Inventory: The Position That Builds Up** (inventory + quote skewing); the chapter intro promised
  inventory risk but never covered it.
- Delta/vega glossed in the Eurex MMP sentence.

#### II.10 Opening and Closing Auction
- "call auction, also called a fixing or uncross" corrected: the uncross is the matching moment; explained why it is
  called that.
- "$1 per share of price improvement" → "$1 better than its limit"; **NAV** defined; "next section" pointer fixed.

#### II.11 Trading Sessions
- "As described above" → "in the previous chapter".

#### II.12 Putting It All Together
- **Logic fix:** Step 12 said the $150.20 sell remainder would fill "when buyers at $150.20 appear", but Step 7 had
  just left resting $150.20 bids in the book (blocked by the band). Step 12 now runs the remainder through the
  resumption auction where it can meet those bids.
- **Consistency:** Step 11 allowed HALTED → CONTINUOUS directly, contradicting the II.11 state machine; now always
  goes through the resumption auction. Figure script `gen_putting_together_figures.py` updated to match
  ("PUB socket" → "Publisher"; HALTED → RESUMPTION_AUCTION → CONTINUOUS). `together-message-flow.png` regenerated;
  **`together-message-flow-small.png` is a provisional 80 % resize, please redo by hand** (old hand-made version
  backed up in the session scratchpad).
- `last_sell_price` explained; **price band** and **drop copy** glossed; PUB socket → participants/market data.

#### II.13 Implied Orders / II.14 Multi-Layer Implied Orders
- Every worked example and all exercise solutions re-checked numerically (vector sums, cash balances, depth ladder,
  Level 8 four-order cross, Level 9 rounding, Bellman–Ford table, route counts incl. 108,505,112 = ⌊e·11!⌋, ripple
  counts, E1–E14 / E1–E10). No arithmetic errors found.
- Swedish "terminer" paragraph: grammar fixed ("Swedish only have" → "has") and **forward** defined at first use here.
- Consistency with the corrected II.2 definition: seven places used "price improvement" to mean "better than its own
  limit" (Level 8 ×2, Level 9, E9, E12, E13 in II.13; E8 in II.14). Reworded. The Level 8 heading keeps the term,
  where it is used correctly (implied beats the real book).

#### II.15 Indexes
- **Correctness:** text said the S&P 500 divisor changes when constituents "split" and "pay dividends". In a cap-weighted
  price index a split needs no divisor change (only a consistent price + share-count update; price-weighted Dow is the
  exception), and ordinary cash dividends are deliberately *not* absorbed (price-return vs total-return index; only
  special dividends are). Split and dividend paragraphs, the S&P divisor sentence, the mermaid node and the takeaway
  rewritten.
- New **worked divisor-adjustment example** (Gamma replaced by Delta, divisor 7,007,100,000 → ≈ 7,396,415,265, level
  stays 1043.9 instead of a fake +5.6 % jump) and new figure **`index-divisor-continuity.png`** from new script
  `scripts/gen_index_figures.py` (provisional `-small.png`).
- The divisor mermaid flowchart (tall `flowchart TD`) overflowed the bottom of the page; replaced by hand-drawn
  **`index-divisor-steps.png`** (five steps in one row plus the formula), placed before the worked example; its
  manual "Figure 1" caption is gone.
- MWCB halts "all trading on an exchange" → on every US stock exchange; **tracking error** glossed; "connects back to
  Part III" (forward reference) fixed.

#### II.16 Benchmark Integrity
- SOFR volume "hundreds of billions" → "more than a trillion dollars" a day.
- WM/Reuters fix is median-based, not volume-weighted: "five-minute volume-weighted benchmark" → "five-minute benchmark".
- **Basis point**, **interest-rate swap**, **tenor**, **unsecured/secured**, **repo** glossed at first use.

### Part III

#### III.0 Part opener
- **Error account** glossed.

#### III.1 Pre-Trade Risk Controls
- Position-limit example moved from the credit-limit paragraph to the position-limit paragraph it illustrates.
- **Mark-to-market** glossed. Wrong pointer "*Short Selling* section of Part I" fixed.
- SMP pre-check (step 8) now says only a cheap partial check is possible at the gateway; the real SMP check runs in
  the matching sweep (as III.3 itself says). Previously the two chapters contradicted each other.

#### III.2 Risk Controls
- **Correctness:** dynamic collar "prevents slowly walking the price away … through a series of trades" was backwards
  (a last-trade collar cannot stop slow drift; the static collar caps it). Paragraph and comparison bullet rewritten.
- **Correctness:** "CME imposes its own ±5% limit on equity futures outside regular hours" (present tense) → 5 % at the
  time, widened since.
- "Automated **Collar** Expansion" in the key idea → **Corridor** (the name defined in the section).
- Price Collars now states explicitly that collars work per order book (own reference prices and band widths per
  instrument, from reference data).
- "trader mistypos" → "typing mistakes"; "publically" → "publicly"; SMP section now points to the SMP chapter.

#### III.3 Self-Match Prevention
- **Correctness:** wash trading's explicit US prohibition is §9(a)(1) of the Exchange Act (and the CEA for futures), not
  "SEC Rule 10b-5 explicitly". "In most production environments SMP is always on" → venues differ (CME: optional).
- Key idea "SMP is a legal requirement on regulated exchanges" overstated → wash trading is illegal, SMP is the tool.

#### III.5 Clearing and Settlement
- New figures **`clearing-novation.png`** (15 bilateral exposures → 6 via the CCP) and
  **`clearing-default-waterfall.png`** from new script `scripts/gen_clearing_figures.py` (provisional `-small.png`).
- Loss chain rewritten as the actual **default waterfall** (defaulter's margin → its default-fund contribution → CCP
  skin in the game → survivors' default fund); **default fund** defined. The 1907 note already referred to "CCP default
  waterfalls described in this Part" but the term never appeared.
- **GameStop:** price was under $20 at the start of January 2021, not "single digits"; largest broker calls were in the
  billions, not just "hundreds of millions".
- "T+0 eliminates settlement risk entirely" → shrinks the window almost to nothing.
- Maintenance-margin close-out attributed to "the broker or the CCP" (maintenance margin is mostly a broker-level concept).

#### III.6 Trade Busting
- Chapter/section pointer fixes (*Market Orders* section → market-order section of *Order Types*, etc.).

#### III.7 Regulatory Surveillance
- **Fiduciary duty** and **material non-public information** glossed; new one-line **Marking the close** entry
  (pointer to the auction chapter's Athena case).

#### III.8 Knight Capital
- "4 million orders" → "more than 4 million executions" (and "millions of orders"); "$7 billion" → "nearly $7 billion".
- Legacy: added **Regulation SCI** (2014), the SEC's response to the 2012 Knight / Facebook / BATS technology failures.

### Part IV

#### IV.1 Speed Bumps
- "magic shoe" → "magic shoebox"; *Flash Boys* was written by Michael Lewis, not by IEX's founders.
- New paragraph explaining *why* a delay applied to everyone helps: IEX's own peg repricing is not delayed, so stale
  pegs cannot be picked off. Previously the chapter said only that a fixed delay does not change relative timing.

#### IV.2 The Technology Architecture
- Self-reference "discussed in the *Matching Engine* section above" (= this section) → Part II chapter.
- **Correctness/clarity:** subscriber list had "AI trader / algorithmic participants" as subscribers of the engine's
  internal bus; real participants connect via gateways and read public market data. Replaced by a market-data
  publisher entry; viewer/board/ticker merged into generic operations displays.
- FIX 4.2 housekeeping note now also mentions HandlInst (21) and TransactTime (60).

#### IV.3 Conformance Testing
- "an invalid tick-aligned price" (self-contradictory) → "a price that is not on a valid tick".

#### IV.4 Primary and Secondary Sites
- Mermaid diagram moved from the middle of the sentence "It may be:" to after the failover list.
- That mermaid diagram (tall `flowchart TD`) overflowed the bottom of the B5 page; replaced by hand-drawn
  **`resilience-active-passive.png`** (two-row layout, adds the fencing step the text describes) from new script
  `scripts/gen_resilience_figures.py`.

#### IV.5 Load Balancing
- **Correctness:** pre-allocated ID ranges as described (secondary owns a fixed range, primary gets "the next block")
  break monotonicity after a later failover. Rewritten: secondary takes a fresh block above all issued blocks.
- **Correctness:** "Exchange systems typically use … UUIDs for order IDs" → high-performance engines mostly use 64-bit
  integer IDs (ITCH carries an 8-byte order reference); UUIDs attributed to this book's reference exchange.
- Gateway load balancer softened (many exchanges pin each session to one gateway); UUID v7 mentioned; NTP/PTP glossed.

#### IV.6 Market Data Architecture
- Tick-to-trade redefined as time from receiving the tick to sending the order (was the exchange-to-exchange round trip).

#### IV.7 Market Data Economics
- **Ordering:** three references treated *later* chapters as already read ("introduced briefly in *Smart Order Routing*",
  "Recall from *Latency and Co-location*", "fee structures described in *Smart Order Routing*"). Rephrased as
  forward references. Added that there are strictly two SIPs.

#### IV.8 Smart Order Routing
- Taker-maker paragraph rewritten (was garbled; now explains the queue-length rationale for inverted venues).
- "the SEC's duty of best execution" → a broker's long-standing duty, codified in FINRA 5310. "PFOF kickback" neutralised.

#### IV.9 Fixed Income
- **CLOB**, **CUSIP**, **seniority / covenants / callability**, **day-count** defined. LTCM and Archegos ("lessons")
  were never explained anywhere in the book; now one-line context each.
- "*Raising Capital* chapter" → actual chapter names; two forward references to *Reference Data* / *Latency* rephrased.

#### IV.10 Crypto Venues
- **Correctness:** integer-precision claim refined (satoshi fits int64; 18-decimal tokens overflow at ~9 tokens).
- New short section **Perpetual Futures** (funding rate) — the dominant crypto derivative was missing. **Mark price** glossed.

#### IV.11 Latency and Co-location
- "ConnectX's RDMA stack" → NVIDIA's kernel-bypass library (VMA).

#### IV.12 Observability
- MTTD/MTTR are *mean* time to detect/recover; "publishable and production-grade" → "production-grade".

#### IV.13 Corporate Actions
- Split handling: venues either adjust *or cancel* resting orders (dividend section already said so; now consistent).
- Dividend date sequence (declaration, ex, record, payment; ex = record date under US T+1) added.
- New short section **Spin-offs and Rights Issues**; pointer to the *Indexes* divisor discussion.

#### IV.14 Options Mechanics
- **Correctness:** "if they do not already own them (a covered call)" was inverted; covered = owns the shares; naked
  call defined. "several writers if the exercised quantity is *smaller*" → larger.
- Forward reference to *Reference Data* fixed; VIX-options pointer corrected; after-close exercise window added to
  pin risk.

#### IV.16 Reference Data
- Expiry: clearing (not the matching engine) settles open positions. Cash-settlement definition corrected for futures.
- Tick-size error example reworded; NYSE 2015 outage cross-referenced to its first mention.

### Book-wide
- 27 cross-references of the form "*Chapter Title* section" now say "chapter" (book consistently uses chapters;
  genuine section references like *Black Monday…* or *How Exchanges Are Regulated* left as is).
- Holistic first-use scan (term → first occurrence in book order). Added first-use definitions for **derivative /
  underlying** (I.1, used from I.3 on, never defined), **hedge fund** and **leverage** (I.4), **marketable limit order**
  (II.4), **notional** (II.10), **ETP** (III.2). All other scanned terms (liquidity, price discovery, CCP, clearing member,
  FIX, NBBO, dark pool, LULD, MMP, maker/taker, P&L, basis point, …) are now defined at or before first real use.
- Preface: typos ("this books draws", "proveable", double space, stray comma).

### Glossary (back matter)
- Entries that contradicted the corrected chapters fixed: **Dynamic Price Collar** (gradual-drift claim), **Iceberg**
  (no longer "= Hidden Order"), **Tick-to-Trade**, **Wash Trading** (10b-5 → §9(a)(1)/CEA; "also called a wash sale" was
  wrong, a wash sale is a tax term), **ACE** ("Collar" → "Corridor", matching the chapter and the operator guide).
- New entries: Broker-Dealer, Covered Call, Default Fund, Default Waterfall, Derivative, Funding Rate, Marketable Limit
  Order, Notional, Perpetual Future, Post-Only Order, Price Improvement, Price-Return / Total-Return Index, Underlying.

### Figures
All new scripts follow the existing pattern (hand-built SVG → headless Chrome PNG at 2×, `--chrome PATH`).

| Figure | Script | Chapter |
|---|---|---|
| `participants-map.png` | `gen_participants_figures.py` | I.4 |
| `listing-dcf-value.png` | `gen_listing_figures.py` | I.6 |
| `order-trailing-stop.png` | `gen_order_types_figures.py` | II.2 |
| `priority-fifo-vs-prorata.png` | `gen_priority_figures.py` | II.5 |
| `together-message-flow.png` (updated) | `gen_putting_together_figures.py` | II.12 |
| `index-divisor-continuity.png`, `index-divisor-steps.png` (replaces a mermaid diagram) | `gen_index_figures.py` | II.15 |
| `clearing-novation.png`, `clearing-default-waterfall.png` | `gen_clearing_figures.py` | III.5 |
| `risk-collars-static-dynamic.png`, `risk-ace-expansion.png`, `risk-halt-states.png` (replaces a mermaid diagram that rendered too small) | `gen_risk_controls_figures.py` | III.2 |
| `resilience-active-passive.png` (replaces a mermaid diagram) | `gen_resilience_figures.py` | IV.4 |

**All thirteen `-small.png` files above are provisional**: 80 % LANCZOS resizes with 340 DPI metadata (300 DPI for
`together-message-flow-small.png`, matching the previous hand-made one), so LaTeX sizes them like the hand-made ones.
Replace by hand as usual. The book builds cleanly (`make pdf-docs`, all four variants) and the new figures were
spot-checked in the A4 PDF. The build added 2 new files to `build-tools/.mermaid-cache/` (edited mermaid diagrams).

## Open items / not changed (for the author)

1. **Front-matter metadata:** preface says `Version: 1.0.0`, `Date: 2026-05-31`, but the text cites the June 2026
   SpaceX IPO and 2026 index decisions, and the build is 1.11.1.
2. **Facts I could not verify** (after my knowledge horizon or too specific): SpaceX IPO details, SIC code, TAM claims and
   lock-ups; S&P DJI 4 June 2026 decision and Nasdaq-100 "fast entry"; Rule 612 half-penny tick "survived a court
   challenge in October 2025"; CME 2025 record ADV 28.1 M; SEC Release 34-102336 (Nasdaq Halt Cross); Hong Kong IPO
   allocation rules from 4 Aug 2025. Left unchanged.
3. **LULD close-doubling:** III.2 says bands double "after 3:35pm". LULD Amendment 18 (2019) is reported to have ended
   the end-of-day doubling for stocks above $3. Please check against the current Plan before relying on the table.
4. **ACE naming contradiction (III.2):** the text says "ACE is this book's label … not a standardised industry term" and
   two paragraphs later "Deutsche Boerse adopted the ACE (Automated Corridor Expansion) Model for ETFs in 2021".
   One of the two needs adjusting; I could not verify the Deutsche Börse claim.
5. **Citation style** is mixed: numbered `[1]`, inline bracketed sources, and bare URLs (e.g. ch. I.1
   "[Initial public offering of SpaceX, Wikipedia; CoinDesk, 11 June 2026]").
6. **Manual "Figure 1" captions** (II.4, II.7) sit next to auto-numbered figures (e.g. "Figure 21.1"); the II.15
   one went away with its mermaid diagram.
7. **Chapter order suggestion:** *Speed Bumps* opens Part IV but leans on latency arbitrage, co-location and pegs; it
   would read more naturally right after *Latency and Co-location*. Not moved.
8. **Duplicate content:** SMP is described twice (III.2 section and III.3 chapter); III.2 now points to III.3, but the
   section could be trimmed to a short pointer.

## Missing topics (not added, per instructions)

- **Listed options market structure:** quoting thousands of series, options market-maker quoting obligations, complex
  order books, the OPRA feed and its message rates. Only exercise/assignment/expiry is covered (IV.14).
- **Futures lifecycle:** contract specifications, daily settlement-price determination, rolling, first notice day and
  physical delivery. Touched on only inside the implied-orders chapters.
- **Margin methodology:** SPAN / VaR-style models, portfolio and cross-margining. Margin is explained conceptually only.
- **Negotiated / off-book trades:** block trades, cross orders, EFP/EFRP, and how exchanges register trades agreed
  away from the book.
- **ETF creation / redemption** and the authorised-participant arbitrage that keeps an ETF near its NAV.
- **Periodic / frequent batch auctions** (e.g. Cboe Europe periodic auctions) as an alternative to continuous matching.
- **FX market structure** (EBS, Refinitiv Matching, last look); FX is mentioned only in passing.
- **Exchange security:** access control, credential handling, DDoS protection, cyber-resilience requirements (DORA in
  the EU).
