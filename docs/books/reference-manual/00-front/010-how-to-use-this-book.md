# How to Use This Book

The Reference Manual is the place to **look something up**. You arrive from
another book with one question — what does this option do, what values may
this field take, what does this word mean — and leave with the answer. It
contains no tutorials; the other books explain and link here for detail.

| | |
|---|---|
| **Who it is for** | Everyone, in the middle of a task |
| **What it assumes** | You know what you are looking for. If you do not yet, start with the [Quick Start Guide](../../quick-start/00-front/010-how-to-use-this-book.md) |
| **What it leaves to other books** | How-to and explanation (the Participant and Operator's Guides); wire messages ([Protocols and Clients](../../protocols-and-clients/00-front/010-how-to-use-this-book.md)) |

## How the book is organized

| Part | Look here for |
|---|---|
| **I. Command line** | Every `pm-*` process and tool: what it does, its options, the environment variable that decides where data lives, and every network port |
| **II. Configuration** | Every top-level key and field of `engine_config.yaml`, the per-process configuration blocks, and the formal specification the verifier enforces |
| **Appendices** | The [Glossary](../90-backmatter/010-glossary.md) and the [Known Limitations](../90-backmatter/020-known-limitations.md) |

## Finding things fast

- Every command also documents itself: `pm-help` lists all `pm-*` commands
  with a one-line summary, and `pm-help <command>` prints its full manual page.
- `pm-config-show` prints the configuration the running exchange actually
  uses; `pm-cverifier` explains any problem in a configuration file.
- In the online documentation, the search box at the top finds any command,
  option or field name.
