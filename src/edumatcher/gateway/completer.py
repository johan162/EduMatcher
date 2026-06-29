"""Tab-completion for the FIX-like gateway command format."""

from __future__ import annotations

from collections.abc import Iterable

from prompt_toolkit.completion import CompleteEvent, Completer, Completion
from prompt_toolkit.document import Document

# ---------------------------------------------------------------------------
# Top-level command list and field definitions
# ---------------------------------------------------------------------------

_TOP_LEVEL_CMDS = [
    "NEW",
    "QUOTE",
    "QUOTE_CANCEL",
    "QBOOT",
    "QLEGS",
    "KILL",
    "AMEND",
    "CANCEL",
    "STATUS",
    "ORDERS",
    "POS",
    "SYMBOLS",
    "INDEX",
    "HELP",
    "EXIT",
    "QUIT",
]

_FIELD_COMPLETIONS: dict[str, list[str]] = {
    # after NEW|
    "SYM": [],  # populated dynamically from known symbols
    "SIDE": ["BUY", "SELL"],
    "TYPE": [
        "MARKET",
        "LIMIT",
        "STOP",
        "STOP_LIMIT",
        "FOK",
        "ICEBERG",
        "IOC",
        "TRAILING_STOP",
    ],
    "TIF": ["DAY", "GTC", "ATO", "ATC"],
    "QTY": [],
    "PRICE": [],
    "STOP": [],
    "TRAIL": [],
    "VISIBLE": [],
    "SMP": ["NONE", "CANCEL_AGGRESSOR", "CANCEL_RESTING", "CANCEL_BOTH"],
    # after CANCEL|
    "ID": [],
}

# Fields that follow each order type (in typical order)
_TYPE_FIELDS: dict[str, list[str]] = {
    "MARKET": ["SYM=", "SIDE=", "QTY=", "TIF=", "SMP="],
    "LIMIT": ["SYM=", "SIDE=", "QTY=", "PRICE=", "TIF=", "SMP="],
    "STOP": ["SYM=", "SIDE=", "QTY=", "STOP=", "TIF=", "SMP="],
    "STOP_LIMIT": ["SYM=", "SIDE=", "QTY=", "STOP=", "PRICE=", "TIF=", "SMP="],
    "FOK": ["SYM=", "SIDE=", "QTY=", "PRICE=", "SMP="],
    "ICEBERG": ["SYM=", "SIDE=", "QTY=", "PRICE=", "VISIBLE=", "TIF=", "SMP="],
    "IOC": ["SYM=", "SIDE=", "QTY=", "PRICE=", "SMP="],
    "TRAILING_STOP": ["SYM=", "SIDE=", "QTY=", "TRAIL=", "STOP=", "TIF="],
}


class GatewayCompleter(Completer):
    """
    Context-aware tab completer for the FIX-like command format.

    Completion rules:
      - Empty or partial first word → top-level commands
      - After NEW|  or CANCEL| → suggest untyped field names (KEY=)
      - After KEY=  with known values → suggest values
    """

    def __init__(self, known_symbols: list[str]) -> None:
        self.known_symbols = known_symbols  # updated by gateway on SYMBOLS reply

    def get_completions(
        self, document: Document, complete_event: CompleteEvent
    ) -> Iterable[Completion]:
        text = document.text_before_cursor
        parts = text.split("|")
        current = parts[-1]  # fragment being typed right now

        # ---- Top-level command (first segment, no | yet) ----
        if len(parts) == 1:
            word = current.upper()
            for cmd in _TOP_LEVEL_CMDS:
                if cmd.startswith(word):
                    yield Completion(cmd, start_position=-len(current))
            return

        cmd = parts[0].upper()
        already_keys = {seg.split("=")[0].upper() for seg in parts[1:] if "=" in seg}

        # ---- Value completion: cursor is after KEY= ----
        if "=" in current:
            key, partial_val = current.split("=", 1)
            key = key.upper()
            partial_val_up = partial_val.upper()

            # Strip LEG{i}. prefix for combo leg field value suggestions
            field = key.split(".")[-1] if "." in key else key

            if field == "SYM":
                candidates = list(
                    self.known_symbols
                )  # snapshot: listener may clear+extend concurrently
            elif field == "SIDE":
                candidates = ["BUY", "SELL"]
            elif key == "TYPE":
                candidates = list(_TYPE_FIELDS.keys()) + ["COMBO", "OCO"]
            elif field == "TYPE":
                # LEG{i}.TYPE= values
                candidates = ["LIMIT", "MARKET", "STOP", "STOP_LIMIT"]
            elif key == "TIF":
                candidates = ["DAY", "GTC", "ATO", "ATC"]
            elif key == "COMBO_TYPE":
                candidates = ["AON"]
            elif cmd == "QLEGS" and key == "SHOW":
                candidates = ["ACTIVE", "RECENT", "ALL"]
            elif field == "SMP" or key == "SMP":
                candidates = [
                    "NONE",
                    "CANCEL_AGGRESSOR",
                    "CANCEL_RESTING",
                    "CANCEL_BOTH",
                ]
            else:
                candidates = []

            for val in candidates:
                if val.upper().startswith(partial_val_up):
                    yield Completion(val, start_position=-len(partial_val))
            return

        # ---- Field-name completion: cursor is at start of a new segment ----
        partial_key = current.upper()

        if cmd == "CANCEL":
            candidates = [
                f
                for f in ["ID=", "COMBO_ID=", "OCO_ID="]
                if f.rstrip("=") not in already_keys
            ]
        elif cmd == "QLEGS":
            candidates = [
                f for f in ["SYM=", "SHOW="] if f.rstrip("=") not in already_keys
            ]
        elif cmd == "QBOOT":
            candidates = [f for f in ["SYM="] if f.rstrip("=") not in already_keys]
        elif cmd == "AMEND":
            candidates = [
                f
                for f in ["ID=", "PRICE=", "QTY="]
                if f.rstrip("=") not in already_keys
            ]
        elif cmd == "NEW":
            # Infer order type from already-entered TYPE= field
            type_val = next(
                (
                    seg.split("=", 1)[1].upper()
                    for seg in parts[1:]
                    if seg.upper().startswith("TYPE=")
                ),
                None,
            )
            if type_val == "COMBO":
                candidates = self._combo_completions(parts, already_keys, partial_key)
                for c in candidates:
                    if c.upper().startswith(partial_key):
                        yield Completion(c, start_position=-len(current))
                return
            elif type_val == "OCO":
                candidates = self._oco_completions(already_keys)
                for c in candidates:
                    if c.upper().startswith(partial_key):
                        yield Completion(c, start_position=-len(current))
                return
            elif type_val and type_val in _TYPE_FIELDS:
                candidates = [
                    f
                    for f in _TYPE_FIELDS[type_val]
                    if f.rstrip("=") not in already_keys
                ]
            else:
                # Before TYPE is known, suggest all field names
                candidates = [
                    f"{k}=" for k in _FIELD_COMPLETIONS if k not in already_keys
                ]
        elif cmd == "QUOTE":
            candidates = [
                f
                for f in [
                    "SYM=",
                    "BID=",
                    "ASK=",
                    "BID_QTY=",
                    "ASK_QTY=",
                    "TIF=",
                    "QUOTE_ID=",
                ]
                if f.rstrip("=") not in already_keys
            ]
        elif cmd in ("QUOTE_CANCEL", "KILL"):
            candidates = ["SYM="] if "SYM" not in already_keys else []
        elif cmd == "INDEX":
            # HISTORY is a bare-word segment; INDEX=/FROM=/TO= are key-value pairs
            bare_words = {s.upper() for s in parts[1:] if "=" not in s}
            if "HISTORY" not in bare_words:
                candidates = ["HISTORY"]
            else:
                candidates = [
                    f
                    for f in ["INDEX=", "FROM=", "TO="]
                    if f.rstrip("=") not in already_keys
                ]
        else:
            candidates = []

        for c in candidates:
            if c.upper().startswith(partial_key):
                yield Completion(c, start_position=-len(current))

    @staticmethod
    def _combo_completions(
        parts: list[str], already_keys: set[str], partial_key: str
    ) -> list[str]:
        """Generate completion candidates for TYPE=COMBO fields."""
        # Top-level combo fields
        combo_meta = ["COMBO_ID=", "COMBO_TYPE=", "TIF=", "LEG_COUNT=", "SMP="]
        candidates = [f for f in combo_meta if f.rstrip("=") not in already_keys]

        # Determine LEG_COUNT to know how many legs to suggest
        leg_count = 2  # default suggestion range
        for seg in parts[1:]:
            if seg.upper().startswith("LEG_COUNT="):
                try:
                    leg_count = int(seg.split("=", 1)[1])
                except ValueError:
                    pass
                break

        # Collect already-used LEG{i}.FIELD keys (with dots)
        already_leg_keys = {
            seg.split("=", 1)[0].upper() for seg in parts[1:] if "=" in seg
        }

        leg_fields = ["SYM=", "SIDE=", "QTY=", "PRICE=", "TYPE="]
        for i in range(leg_count):
            for field in leg_fields:
                key = f"LEG{i}.{field}"
                if key.rstrip("=") not in already_leg_keys:
                    candidates.append(key)

        return candidates

    @staticmethod
    def _oco_completions(already_keys: set[str]) -> list[str]:
        """Generate completion candidates for TYPE=OCO fields."""
        oco_fields = [
            "OCO_ID=",
            "SYM=",
            "QTY=",
            "TIF=",
            "LEG1_SIDE=",
            "LEG1_TYPE=",
            "LEG1_PRICE=",
            "LEG1_STOP=",
            "LEG1_TRAIL=",
            "LEG2_SIDE=",
            "LEG2_TYPE=",
            "LEG2_PRICE=",
            "LEG2_STOP=",
            "LEG2_TRAIL=",
        ]
        return [f for f in oco_fields if f.rstrip("=") not in already_keys]
