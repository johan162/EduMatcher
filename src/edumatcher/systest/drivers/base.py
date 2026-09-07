"""The ``Driver`` protocol and normalised wire dataclasses.

Defines the transport-agnostic verb set (``connect``, ``disconnect``,
``new_order``, ``cancel_order``, ``amend_order``, ``orders``, ``positions``,
``session``, ``events``, plus the Phase 2+-reserved ``quote`` and
``kill_switch`` verbs) and the normalised dataclasses each verb returns
(``NewOrderRequest``, ``OrderAmendment``, ``Ack``, ``OrderView``,
``PositionView``, ``SessionView``, ``Event``).

See design.md Components §4 (Driver Protocol) and Data Models §2 (Wire
Dataclasses).
"""
