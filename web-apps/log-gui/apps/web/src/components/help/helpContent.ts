/**
 * Help content (WP-UI08): what this app is, how to read it, and what its indicators
 * mean. Authored from the guides in docs/books; data only, rendered by HelpButton.
 */

import type { HelpTopic } from "./HelpButton.js";

export const HELP_TOPICS: HelpTopic[] = [
  {
    "id": "about",
    "title": "About pm-log",
    "blocks": [
      {
        "paragraphs": [
          "pm-log is the operator's view of the exchange's log. Every EduMatcher process writes its log lines to one collector, pm-log-srv; this app shows them live, lets you search the history, and turns repeated errors into issues someone can acknowledge.",
          "Data path: the processes → pm-log-srv → the pm-log bridge → this page. The bridge keeps a database (log.db) so history survives a browser reload."
        ]
      },
      {
        "heading": "The six views",
        "terms": [
          {
            "term": "Dashboard",
            "text": "Is anything wrong right now? Event and error rates, the busiest error sources and the latest errors."
          },
          {
            "term": "Logs",
            "text": "Every log line, live or from history, with filters."
          },
          {
            "term": "Alerts",
            "text": "Errors grouped into issues, with acknowledgement."
          },
          {
            "term": "Connections",
            "text": "Which processes are logging and which have gone quiet."
          },
          {
            "term": "Diagnostics",
            "text": "Automatic checks of the log for known problems."
          },
          {
            "term": "Health",
            "text": "The state of the log pipeline itself: server, feed, database, bridge."
          }
        ]
      },
      {
        "note": "Hover the small i beside any heading or figure for a short explanation of it."
      }
    ]
  },
  {
    "id": "levels",
    "title": "Log levels",
    "blocks": [
      {
        "paragraphs": [
          "Every line has a level saying how serious it is. Colours are the same everywhere in the app."
        ],
        "terms": [
          {
            "term": "DEBUG",
            "text": "Detail for developers. Normally hidden."
          },
          {
            "term": "INFO",
            "text": "Normal events: a process started, a session changed."
          },
          {
            "term": "WARNING",
            "text": "Something unusual happened but the process carried on: a rejected request, a retry."
          },
          {
            "term": "ERROR",
            "text": "An operation failed."
          },
          {
            "term": "CRITICAL",
            "text": "The process cannot continue as it should."
          }
        ]
      },
      {
        "heading": "Error rate",
        "paragraphs": [
          "The dashboard shows ERROR and CRITICAL events per minute over the last 60 seconds. Its colour is a band: normal, elevated, high and SEVERE. The thresholds are set in the server's ERROR_RATE settings; a healthy exchange sits near 0."
        ]
      }
    ]
  },
  {
    "id": "dashboard",
    "title": "Dashboard",
    "blocks": [
      {
        "paragraphs": [
          "Built to be read from across a room. If there are unacknowledged issues, a red banner at the top says how many and which process raised the latest; the button opens Alerts."
        ],
        "terms": [
          {
            "term": "Total events",
            "text": "Everything the server has stored since it first started."
          },
          {
            "term": "Error rate",
            "text": "ERROR and CRITICAL per minute, coloured by band."
          },
          {
            "term": "Warnings",
            "text": "WARNING events in the last 60 seconds."
          },
          {
            "term": "Processes",
            "text": "How many different processes have logged."
          }
        ]
      },
      {
        "paragraphs": [
          "Below: events per minute over the last hour, the processes with most errors, and the five latest errors. A burst in the chart with a high error rate usually points to one process in the second chart."
        ]
      }
    ]
  },
  {
    "id": "logs",
    "title": "Logs (Explorer)",
    "blocks": [
      {
        "paragraphs": [
          "The full log. The button in the filter bar switches between two modes."
        ],
        "terms": [
          {
            "term": "▶ LIVE",
            "text": "New lines appear at the top as they arrive, filtered as you type. The count shows lines in the browser's buffer. If you scroll away from the top the stream pauses so a line does not move under your eyes; the bar \"N new rows — jump to top\" resumes it."
          },
          {
            "term": "history",
            "text": "Searches the stored database. The count shows how many lines match, not just those loaded."
          }
        ]
      },
      {
        "heading": "Filters",
        "terms": [
          {
            "term": "message contains",
            "text": "Case-insensitive text in the message."
          },
          {
            "term": "all levels / WARNING+ ...",
            "text": "Shows the chosen level and everything more serious."
          },
          {
            "term": "exceptions only",
            "text": "Only lines that carry a traceback (marked with ⚠)."
          }
        ]
      },
      {
        "note": "Click a line to see it in full, with the traceback. The filter is kept in the page address, so you can paste the link to a colleague."
      }
    ]
  },
  {
    "id": "alerts",
    "title": "Alerts & acknowledging",
    "blocks": [
      {
        "paragraphs": [
          "Thousands of identical errors are one problem. Alerts groups them: lines from the same process, logger and level whose messages are the same once the variable parts (numbers, ids, hex strings, timestamps, quoted text) are stripped become one issue with a count ×N. Grouping is a heuristic and can occasionally merge or split; the issue lists its distinct raw messages so you can check.",
          "For a line with a traceback only the exception and its last frame are compared."
        ]
      },
      {
        "heading": "Acknowledging",
        "paragraphs": [
          "An issue is an open question until someone says \"I have seen this\". Type your name in the box (it is kept in this browser and recorded with the acknowledgement), add a note about what was done, and press Ack. Acknowledgements are shared and survive a restart; Un-ack takes one back."
        ],
        "terms": [
          {
            "term": "recurred since ack",
            "text": "The same problem happened again after it was acknowledged: a fix that did not hold."
          },
          {
            "term": "⚠ N unacked (top bar)",
            "text": "Issues at or above the alert level that nobody has acknowledged. It turns red when above 0."
          }
        ]
      }
    ]
  },
  {
    "id": "connections",
    "title": "Connections",
    "blocks": [
      {
        "paragraphs": [
          "One row for every connection a process has made to the log server, newest first. Click a row to see that process's lines."
        ],
        "terms": [
          {
            "term": "● logging",
            "text": "The process is connected and has sent something recently."
          },
          {
            "term": "⚠ silent",
            "text": "Connected, but nothing has been received for longer than the silence limit shown above the table. A busy process that goes quiet is often a hung one."
          },
          {
            "term": "○ disconnected",
            "text": "The process closed its connection or died."
          }
        ]
      },
      {
        "note": "Every process opens a short-lived probe connection to see whether the log server is there, then a second to log over. The probe shows as a connection that logged nothing; \"Hide probes\" removes them."
      }
    ]
  },
  {
    "id": "diagnostics",
    "title": "Diagnostics",
    "blocks": [
      {
        "paragraphs": [
          "Seven automatic checks (the same ones the command line tool pm-log-cli diagnose runs) look through the log for known patterns of trouble and re-run every minute. Each finding says what was seen, what to do about it, and a command that reproduces it. Checks that found nothing are listed at the bottom.",
          "Diagnostics is optional: if the checking tool is not installed, the page says so and everything else works."
        ]
      }
    ]
  },
  {
    "id": "health",
    "title": "Health",
    "blocks": [
      {
        "paragraphs": [
          "Four parts of the log pipeline that can fail independently, so a problem can be placed."
        ],
        "terms": [
          {
            "term": "pm-log-srv",
            "text": "The collector process: its status, lifetime counters and any events it had to cut or reject."
          },
          {
            "term": "LALF-PS",
            "text": "The live feed between the collector and the bridge: subscribers, last sequence number, dropped events."
          },
          {
            "term": "log.db",
            "text": "The history database: where it is, its size, how far back it goes."
          },
          {
            "term": "Bridge",
            "text": "This app's own server: connected browsers, tracked issues, whether the database can be read."
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
            "text": "The log server is up and its heartbeat is arriving. New lines will appear as they are logged."
          },
          {
            "term": "RECONNECTING (amber)",
            "text": "This page lost its connection to the bridge, or the bridge is catching up with the log server."
          },
          {
            "term": "OFFLINE (red)",
            "text": "No new lines can arrive. The text next to it names the cause: \"log server down\" (it announced a shutdown, or its heartbeat stopped, for example after a crash) or \"log.db unavailable\" (live lines work but history and statistics do not)."
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
          }
        ]
      },
      {
        "note": "Colour never carries meaning alone: states are also written out (a glyph or a word), so the page stays readable in either theme and for colour-blind users."
      }
    ]
  }
];
