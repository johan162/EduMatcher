/**
 * Help content (WP-UI08): what this app is, how to read it, and what its indicators
 * mean. Authored from the guides in docs/books; data only, rendered by HelpButton.
 */

import type { HelpTopic } from "./HelpButton.js";

export const HELP_TOPICS: HelpTopic[] = [
  {
    "id": "about",
    "title": "About pm-dash",
    "blocks": [
      {
        "paragraphs": [
          "pm-dash is the operator's dashboard: whether the exchange is healthy, how busy it is, and which part is not. Health data comes from the monitor process (pm-monitor), which every EduMatcher process reports to; the dashboard shows it live and keeps history so you can look back."
        ]
      },
      {
        "heading": "The rows",
        "paragraphs": [
          "The page is a stack of rows. Click a row title to collapse it; the choice is remembered."
        ],
        "terms": [
          {
            "term": "Overview",
            "text": "The headline: processes up, participants connected, orders and trades today, order rate, engine latency, host CPU, memory and disk."
          },
          {
            "term": "Session schedule",
            "text": "The week's trading hours, today's phases with the current one lit and the time on the day, and the next bank holiday. Needs the read-only API key (PM_DASH_API_KEY)."
          },
          {
            "term": "Processes",
            "text": "Every process with its state, uptime, memory, CPU and loop timings. Click a row for its detail."
          },
          {
            "term": "Trading activity",
            "text": "Orders, trades and traded value over time, reject ratio and why requests were rejected."
          },
          {
            "term": "Participants",
            "text": "Each participant's connection and order rates. Click a row for detail."
          },
          {
            "term": "Order books",
            "text": "One row per symbol: resting orders, depth, memory, halt state."
          },
          {
            "term": "Gateways & infrastructure",
            "text": "Client counts, dropped events, log ingest, data files, engine diagnostics."
          },
          {
            "term": "Event log",
            "text": "State changes and threshold breaches, newest first."
          }
        ]
      },
      {
        "note": "Hover the small i beside any heading, tile or gauge for a short explanation of it."
      }
    ]
  },
  {
    "id": "states",
    "title": "Process states",
    "blocks": [
      {
        "paragraphs": [
          "The State column is the monitor's verdict, written as a glyph and a word. The monitor judges from the beacons each process sends every couple of seconds."
        ],
        "terms": [
          {
            "term": "HEALTHY",
            "text": "Beacons arrive and the main loop is turning."
          },
          {
            "term": "DEGRADED",
            "text": "Running, but a measure has crossed its warning line, for example the loop is late."
          },
          {
            "term": "HUNG",
            "text": "Beacons arrive but the main loop has not completed an iteration for over 5 s. The process is alive but stuck."
          },
          {
            "term": "SILENT",
            "text": "No beacons, yet the process still exists: the interpreter is stuck or the beacons cannot get through."
          },
          {
            "term": "DEAD",
            "text": "No beacons and the process is gone."
          },
          {
            "term": "MISSING",
            "text": "The active profile expects it but it has never reported."
          },
          {
            "term": "STOPPED",
            "text": "It shut down cleanly and said so."
          }
        ]
      },
      {
        "paragraphs": [
          "The exchange as a whole is the pill in the top bar: OPERATIONAL when the matching engine is up and nothing is wrong, DEGRADED when something has crossed a warning line, IMPAIRED when another expected process is dead, silent, hung or missing, and DOWN when there is no engine. NO DATA means the monitor has not reported yet."
        ]
      }
    ]
  },
  {
    "id": "colours",
    "title": "Colours & thresholds",
    "blocks": [
      {
        "paragraphs": [
          "Tiles, gauges and some columns are coloured by a rule with a warning and a critical line, set in the monitor's configuration. Hover a tile to read its lines. Every colour is also written: OK, WARN, CRIT beside the value.",
          "The Settings menu chooses whether a tile shows its level as the colour of the value or of the whole tile background."
        ]
      },
      {
        "note": "A value that is missing shows — and no colour: \"no data\" is never drawn as \"fine\"."
      }
    ]
  },
  {
    "id": "time",
    "title": "Time range & refresh",
    "blocks": [
      {
        "paragraphs": [
          "The two pickers in the top bar control every chart. Time range sets how far back charts look (the range is in the page address, so a link shows a colleague the same window). Refresh sets how often history charts are re-read; live figures always update as they arrive."
        ],
        "bullets": [
          "All times are in the exchange's time zone, not your computer's.",
          "Charts share a crosshair: hover one and the others mark the same moment.",
          "Dashed vertical lines mark events such as a process changing state."
        ]
      }
    ]
  },
  {
    "id": "drawers",
    "title": "Detail drawers",
    "blocks": [
      {
        "paragraphs": [
          "Clicking a process, a participant or an order book opens a drawer from the right with that item's detail and history. The link in the address bar opens the same drawer, so you can share it. Esc or the close button returns to the page."
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
            "text": "This page is connected to its bridge and receiving snapshots."
          },
          {
            "term": "CONNECTING (amber)",
            "text": "Connecting, or reconnecting after a loss. Figures are the last received."
          },
          {
            "term": "OFFLINE (red)",
            "text": "No connection to the bridge. Everything on screen is stale."
          }
        ]
      },
      {
        "note": "Whenever the badge is not LIVE, treat the numbers on screen as the last known values, not as the state of the exchange now. The page reconnects by itself; you do not need to reload."
      },
      {
        "heading": "The monitor behind it",
        "paragraphs": [
          "The bridge can be reachable while pm-monitor is not. The strip at the bottom of the page shows pm-monitor's own state, and a banner appears when it is down: the page is then connected but the figures are not live."
        ]
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
            "term": "Stat colour",
            "text": "Whether tiles show their level on the value or on the background."
          }
        ]
      },
      {
        "note": "Colour never carries meaning alone: states are also written out (a glyph or a word), so the page stays readable in either theme and for colour-blind users."
      }
    ]
  }
];
