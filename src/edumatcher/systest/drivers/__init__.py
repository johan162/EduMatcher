"""Transport-specific Driver implementations for ``pm-systest``.

Each Driver (ALF, REST, Admin) implements the common verb set defined in
``drivers/base.py`` and translates its wire protocol into the normalised
dataclasses shared across transports.

See design.md Components §4-§7 (Driver Protocol, ALF/REST/Admin Drivers).
"""
