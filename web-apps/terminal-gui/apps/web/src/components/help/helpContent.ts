/**
 * Help content (WP-UI08): what this app is, how to read it, and what its indicators
 * mean. Authored from the guides in docs/books; data only, rendered by HelpButton.
 */

import type { HelpTopic } from "./HelpButton.js";

export const HELP_TOPICS: HelpTopic[] = [
  {
    "id": "about",
    "title": "About pm-terminal",
    "blocks": [
      {
        "paragraphs": [
          "pm-terminal is the market-information terminal: a read-only, live view of the whole market, in the spirit of a trader's quote screen. It places no orders. Prices arrive from the market-data gateway (pm-md-gwy) and the daily figures from the statistics service."
        ]
      },
      {
        "heading": "The seven views",
        "terms": [
          {
            "term": "Overview",
            "text": "A grid of every symbol with its quote, change and activity. Sort by clicking a heading; the grid pages by itself unless you sort or search."
          },
          {
            "term": "Symbol",
            "text": "One instrument in depth: chart, depth ladder and a table of its figures."
          },
          {
            "term": "Index",
            "text": "The market index level, its chart and its high and low."
          },
          {
            "term": "Tape",
            "text": "Every trade as it happens."
          },
          {
            "term": "Movers",
            "text": "Biggest gainers, losers and most active."
          },
          {
            "term": "Session",
            "text": "The trading day: phase, schedule and halts."
          },
          {
            "term": "News",
            "text": "News items and rumours that move the market."
          }
        ]
      },
      {
        "note": "Hover the small i beside any column heading or figure for a short explanation of it."
      }
    ]
  },
  {
    "id": "overview",
    "title": "Overview",
    "blocks": [
      {
        "paragraphs": [
          "One row per symbol. A star pins the symbol to the top. Type in the search box to filter; the grid stops paging while you sort or search, and \"reset\" returns to automatic paging."
        ],
        "terms": [
          {
            "term": "Last, Chg, %Chg",
            "text": "Latest trade price and its change since the previous close. A * means no previous close is on record, so the change is measured from today's open."
          },
          {
            "term": "Bid sz / Bid / Ask / Ask sz",
            "text": "The best bid and ask and the quantity at each."
          },
          {
            "term": "Spread",
            "text": "Ask minus bid: what an immediate round trip costs."
          },
          {
            "term": "Volume / Turnover",
            "text": "Quantity traded today, and its value (volume × VWAP, an estimate)."
          },
          {
            "term": "Time",
            "text": "When the symbol last traded."
          }
        ]
      },
      {
        "heading": "In an auction",
        "paragraphs": [
          "During a call phase the bid and ask columns are replaced by Indic (the price the auction would settle at now), Indic sz (the quantity that would trade) and Imbalance (surplus on one side). A halted symbol is marked and its quote is greyed: those prices cannot be traded on."
        ]
      }
    ]
  },
  {
    "id": "symbol",
    "title": "Symbol detail",
    "blocks": [
      {
        "paragraphs": [
          "Pick a symbol with the picker in the page or by clicking a row elsewhere. Left: the chart with a timeframe selector. Right: the figures in groups."
        ],
        "terms": [
          {
            "term": "Quote",
            "text": "Bid, ask, spread (with basis points, so tight and wide are comparable across cheap and dear instruments) and the live mid price."
          },
          {
            "term": "Session",
            "text": "Previous close, open, high, low, last and VWAP, with where the last price sits relative to VWAP."
          },
          {
            "term": "Activity",
            "text": "Volume, turnover, number of trades and the average trade size."
          },
          {
            "term": "Auction",
            "text": "Only during a call phase: indicative price, quantity that would match, and imbalance."
          },
          {
            "term": "Status",
            "text": "The trading phase of this symbol."
          }
        ]
      },
      {
        "heading": "Depth ladder",
        "paragraphs": [
          "Bids on the left, asks on the right, best prices in the middle. Cum is the quantity from the best price outward to that level, # the number of orders resting there, and % how far the level is from the best price. The bars show cumulative quantity, so a book with one fat level and a book with five even ones are not confused."
        ]
      },
      {
        "note": "A quote shown muted, with a label, belongs to a book nobody can trade on (halt or auction); the values are the last real book."
      }
    ]
  },
  {
    "id": "index",
    "title": "Index",
    "blocks": [
      {
        "paragraphs": [
          "The market index is a cap-weighted average of its constituent symbols, published about once a second by pm-index. The page shows the level over the chosen timeframe and today's open, high and low. Aggregate cap is the summed market capitalisation of the constituents. Recent changes lists notable events on the index, newest first."
        ]
      }
    ]
  },
  {
    "id": "tape",
    "title": "Trade tape",
    "blocks": [
      {
        "paragraphs": [
          "Every trade, newest first. Filter by symbol with the box."
        ],
        "terms": [
          {
            "term": "Price, Qty",
            "text": "What traded."
          },
          {
            "term": "Side",
            "text": "The aggressor: the side that crossed the spread and took liquidity. ▲ BUY means a buyer hit the ask, ▼ SELL a seller hit the bid. Blank when unknown."
          }
        ]
      }
    ]
  },
  {
    "id": "movers",
    "title": "Movers",
    "blocks": [
      {
        "paragraphs": [
          "Three rankings of the symbols, picked with the tabs."
        ],
        "terms": [
          {
            "term": "Gainers / Losers",
            "text": "Largest rise / fall in percent against the previous close."
          },
          {
            "term": "Active",
            "text": "Largest value traded today."
          }
        ]
      },
      {
        "note": "If previous closes are unavailable the ranking is measured from today's open and the page says so: it is then a different list under the same name."
      }
    ]
  },
  {
    "id": "session-view",
    "title": "Session view",
    "blocks": [
      {
        "paragraphs": [
          "The current session status, the symbols that are halted with their circuit-breaker detail, and the auctions that have uncrossed. A halt reopens through a call auction, so the reopening shows as an auction phase for that symbol only."
        ]
      }
    ]
  },
  {
    "id": "news",
    "title": "News",
    "blocks": [
      {
        "paragraphs": [
          "Headlines that can move prices. Green leans positive, red negative."
        ],
        "terms": [
          {
            "term": "RUMOUR",
            "text": "Not confirmed. The percentage is how credible its source is."
          },
          {
            "term": "CONFIRMED",
            "text": "A later item confirmed an earlier rumour."
          },
          {
            "term": "RETRACTED",
            "text": "Withdrawn; shown struck through."
          },
          {
            "term": "Scope",
            "text": "MARKET moves everything; otherwise the symbols concerned."
          }
        ]
      }
    ]
  },
  {
    "id": "connection",
    "title": "Connection badge",
    "blocks": [
      {
        "paragraphs": [
          "The dot and word at the right of the top bar say whether what you see is live. They look and mean the same in every EduMatcher web app; the text after the word is specific to this one."
        ],
        "terms": [
          {
            "term": "LIVE (green)",
            "text": "The page is connected to its bridge and the bridge has an active feed from the market-data gateway. The name after the word is the gateway."
          },
          {
            "term": "RECONNECTING (amber)",
            "text": "The page is connected to its bridge but the market-data feed is not active (starting, lost, or the gateway restarted). Prices are the last received."
          },
          {
            "term": "OFFLINE (red)",
            "text": "The page has no connection to its bridge. The data on screen is stale."
          }
        ]
      },
      {
        "note": "Whenever the badge is not LIVE, treat the numbers on screen as the last known values, not as the state of the exchange now. The page reconnects by itself; you do not need to reload."
      }
    ]
  },
  {
    "id": "session",
    "title": "Session badge",
    "blocks": [
      {
        "paragraphs": [
          "The coloured badge in the top bar is the phase the exchange is in right now, as reported by the market-data gateway (pm-md-gwy). It is the same badge, in the same colours, in every EduMatcher web app."
        ],
        "terms": [
          {
            "term": "Pre-Open",
            "text": "Before the opening auction. The exchange is not matching yet."
          },
          {
            "term": "Opening Auction",
            "text": "A call phase: orders are collected and then match together at a single uncross price, instead of one by one."
          },
          {
            "term": "Continuous",
            "text": "Normal trading: every new order is matched against the book at once."
          },
          {
            "term": "Closing Auction",
            "text": "A call phase before the close, like the opening auction."
          },
          {
            "term": "Closed",
            "text": "The day is over. Nothing matches."
          },
          {
            "term": "Unknown",
            "text": "The market-data gateway cannot be reached, so the phase is not known. The badge never guesses."
          }
        ]
      },
      {
        "heading": "Next phase and countdown",
        "paragraphs": [
          "When the next phase change is scheduled, the badge is followed by an arrow, the next phase and the time left, for example → Closing Auction in 03:08. With no schedule (a manually driven session) there is no countdown, because a countdown to zero would promise a change that is not coming."
        ]
      },
      {
        "heading": "Exchange clock",
        "paragraphs": [
          "The clock at the right of the badge shows the time in the exchange's own time zone (hover for its name), which may differ from your computer's."
        ]
      }
    ]
  },
  {
    "id": "settings",
    "title": "Settings & theme",
    "blocks": [
      {
        "paragraphs": [
          "Everything here is remembered per browser; nothing is sent to the exchange."
        ],
        "terms": [
          {
            "term": "Theme (sun / moon)",
            "text": "Switches between the dark and the light palette."
          },
          {
            "term": "Font size",
            "text": "In the gear menu. Scales the whole page, text and spacing together, from XS (the default) to XXL. It works in Chrome and Safari only."
          },
          {
            "term": "Density (top bar)",
            "text": "Cycles the row height of grids: comfortable, standard, compact. Compact shows more symbols on one screen."
          }
        ]
      },
      {
        "note": "Colour never carries meaning alone: states are also written out (a glyph or a word), so the page stays readable in either theme and for colour-blind users."
      }
    ]
  }
];
