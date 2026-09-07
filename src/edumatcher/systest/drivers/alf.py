"""The ALF transport Driver, against ``pm-alf-gwy``.

Implements the ``Driver`` protocol over the ALF pipe-delimited TCP text
protocol: the ``WELCOME`` handshake, ``TAG=``/``RTAG=`` client correlation,
and the per-connection unsolicited-event queue. Speaks the wire protocol
directly rather than driving the interactive ``pm-alf-console`` TUI.

See design.md Components §5 (ALF Driver).
"""
