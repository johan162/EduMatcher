/**
 * Help content (WP-UI08): what this app is, how to read it, and what its indicators
 * mean. Authored from the guides in docs/books; data only, rendered by HelpButton.
 */

import type { HelpTopic } from "./HelpButton";

export const HELP_TOPICS: HelpTopic[] = [
  {
    "id": "about",
    "title": "About pm-config",
    "blocks": [
      {
        "paragraphs": [
          "pm-config builds the exchange's configuration file, engine_config.yaml, with forms instead of hand-written YAML. It runs entirely in the browser: your draft is kept in this browser as you edit, and nothing reaches the exchange until you download the file and start the exchange with it."
        ]
      },
      {
        "heading": "The workflow",
        "bullets": [
          "Pick a persona (top bar): it decides how many tabs and fields you see.",
          "Fill in the tabs from the left list. A glyph beside each tab shows whether it is complete, has warnings, or has errors.",
          "Open Review & Export: the diagnostics list problems, each linking to its field; preview the YAML; download it.",
          "Optionally verify it against the real configuration verifier."
        ]
      },
      {
        "note": "The small i beside a field explains it, shows the equivalent command-line flag, and links to the manual. Fields marked * are required."
      }
    ]
  },
  {
    "id": "personas",
    "title": "Personas",
    "blocks": [
      {
        "paragraphs": [
          "The persona is a view filter, never a data filter: switching never discards a value, and a value that is hidden is still exported."
        ],
        "terms": [
          {
            "term": "Beginner",
            "text": "Basics, Sessions & Schedule, Market Maker, Review & Export. Safe defaults for everything else."
          },
          {
            "term": "Intermediate",
            "text": "Adds Risk & Collars, Circuit Breakers, Symbols, Indices, Auxiliary Gateways and Health Monitoring."
          },
          {
            "term": "Expert",
            "text": "Adds Combos and Engine Tuning, and every low-level field."
          }
        ]
      }
    ]
  },
  {
    "id": "tabs",
    "title": "The tabs",
    "blocks": [
      {
        "terms": [
          {
            "term": "Basics",
            "text": "Country and time zone, the symbols, and the participants (who may connect)."
          },
          {
            "term": "Sessions & Schedule",
            "text": "Whether a scheduler drives the trading day and the times of each phase."
          },
          {
            "term": "Risk & Collars",
            "text": "Price bands: how far an order may be from the reference or last price before it is rejected."
          },
          {
            "term": "Circuit Breakers",
            "text": "The ladder of price moves that halt a symbol, and how it reopens (corridor expansion)."
          },
          {
            "term": "Market Maker",
            "text": "Obligations for market makers: spread, minimum size; and starting quotes."
          },
          {
            "term": "Symbols",
            "text": "Per-symbol overrides of everything above."
          },
          {
            "term": "Indices",
            "text": "Cap-weighted market indices and their constituents."
          },
          {
            "term": "Combos",
            "text": "Multi-leg orders placed at start-up."
          },
          {
            "term": "Auxiliary Gateways",
            "text": "The post-trade, market-data, bulk-order and API gateway processes."
          },
          {
            "term": "Health Monitoring",
            "text": "Beacon timing and alert thresholds for pm-monitor."
          },
          {
            "term": "Engine Tuning",
            "text": "Low-level retention and throttling settings."
          },
          {
            "term": "Review & Export",
            "text": "Diagnostics, YAML preview, download and verify."
          }
        ]
      }
    ]
  },
  {
    "id": "diagnostics",
    "title": "Diagnostics & review",
    "blocks": [
      {
        "paragraphs": [
          "Diagnostics run on every edit. Errors (red ✗) would stop the exchange from starting or are inconsistent; warnings (amber !) are legal but suspicious. Click a message to jump to the field, which flashes. The Diagnostics panel on the right lists all of them; the tab at its edge hides it."
        ]
      },
      {
        "note": "\"Comment defaults\" adds a commented-out header to the file listing every optional field at its default, ready to uncomment."
      }
    ]
  },
  {
    "id": "drafts",
    "title": "Drafts, import & export",
    "blocks": [
      {
        "terms": [
          {
            "term": "Autosave",
            "text": "The draft is saved in this browser as you type. A new draft keeps one autosaved copy until you edit it."
          },
          {
            "term": "Import",
            "text": "Reads an existing engine_config.yaml into the forms. Problems are reported rather than silently dropped."
          },
          {
            "term": "New",
            "text": "Starts from an empty draft after confirming."
          },
          {
            "term": "Download",
            "text": "Writes the YAML. The file name is set on the Review tab."
          }
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
