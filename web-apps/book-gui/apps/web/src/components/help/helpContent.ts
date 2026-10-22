/**
 * Help content (WP-UI08): what this app is, how to read it, and what its indicators
 * mean. Authored from the guides in docs/books; data only, rendered by HelpButton.
 */

import type { HelpTopic } from "./HelpButton.js";

export const HELP_TOPICS: HelpTopic[] = [
  {
    "id": "about",
    "title": "About pm-book",
    "blocks": [
      {
        "paragraphs": [
          "pm-book shows the order book of one symbol, live: who wants to buy and sell at which price, the latest trades, and the day's statistics. It is a read-only view for learning how a limit order book works."
        ]
      },
      {
        "heading": "Reading the screen",
        "terms": [
          {
            "term": "Top rows",
            "text": "Last price, change, size of the last trade, best bid and ask, spread, then open/high/low/close, previous close, range and volume."
          },
          {
            "term": "BIDS",
            "text": "Buy orders waiting, best (highest) price at the top. Ord = number of orders at the price, Qty = their total quantity, Price, and a bar for Depth."
          },
          {
            "term": "ASKS",
            "text": "Sell orders waiting, best (lowest) price at the top. Mirrored, so the best prices meet in the middle."
          },
          {
            "term": "TRADES",
            "text": "The latest trades, newest first. Green: the price rose against the trade before it, red: fell, grey: same."
          }
        ]
      },
      {
        "note": "Hover the small i beside any label or heading for a short explanation. Change symbol with the picker in the top bar (press s or F1)."
      }
    ]
  },
  {
    "id": "book",
    "title": "How the book works",
    "blocks": [
      {
        "paragraphs": [
          "Orders at the same price form one level. Within a level the oldest order trades first (price-time priority). A trade happens when the best bid meets or crosses the best ask; the trade prints at the resting order's price.",
          "The depth bars are scaled to the biggest level shown, so they compare levels of this book only. A long bar is a wall of waiting quantity; a thin book has short bars everywhere and moves easily."
        ]
      },
      {
        "heading": "Spread",
        "paragraphs": [
          "Best ask minus best bid. Narrow means many participants compete and trading in and out is cheap; wide means the opposite. The spread is empty while one side of the book is empty."
        ]
      },
      {
        "note": "Hidden quantity (the reserve of an iceberg order) is not shown: you see only the visible slice of each order."
      }
    ]
  },
  {
    "id": "stats",
    "title": "Statistics rows & basis",
    "blocks": [
      {
        "paragraphs": [
          "Change and Chg% are measured against a reference, and the Basis field says which:"
        ],
        "terms": [
          {
            "term": "prev-close",
            "text": "The previous session's closing price. The usual case."
          },
          {
            "term": "session-open",
            "text": "Today's opening price, used when there is no previous close, for example a symbol listed today."
          },
          {
            "term": "live since HH:MM",
            "text": "History could not be read, so every figure covers only the trades seen since that time, not the whole day."
          }
        ]
      },
      {
        "paragraphs": [
          "The arrow and colour of Last follow the reference: ▲ green above it, ▼ red below, ▬ grey equal. The thin line under the rows shows the trend of the close the same way."
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
            "text": "The page is connected to its bridge and the bridge is reading the exchange (through pm-api-gwy). The text after the word names the source."
          },
          {
            "term": "RECONNECTING (amber)",
            "text": "Connected to the bridge but the bridge's feed from the exchange is down or starting. The book shown is the last received."
          },
          {
            "term": "OFFLINE (red)",
            "text": "No connection to the bridge. The book is stale."
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
            "term": "Max levels",
            "text": "How many price levels each side shows: Fit (as many as fit the screen) or a fixed 10, 20 or 50."
          },
          {
            "term": "Zebra rows",
            "text": "Alternating row shading, as in pm-viewer."
          }
        ]
      },
      {
        "note": "Colour never carries meaning alone: states are also written out (a glyph or a word), so the page stays readable in either theme and for colour-blind users."
      }
    ]
  }
];
