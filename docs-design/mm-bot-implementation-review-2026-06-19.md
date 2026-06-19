# pm-mm-bot Design vs Implementation Review (2026-06-19)

## Scope

Reviewed implementation files:
- src/edumatcher/mm_bot/main.py
- src/edumatcher/mm_bot/bot.py
- src/edumatcher/mm_bot/pricer.py
- tests/test_mm_bot.py

Compared against design:
- docs-design/EduMatcher-MM-bots.md

Reviewed user-facing docs:
- docs/user-guide/17-mm-bot.md

## Differences and Assessment

| Area | Design expectation | Implementation reality | Necessary due better understanding? | Assessment |
|---|---|---|---|---|
| Gap obligation pre-check | Validate `--gap <= mm_max_spread_ticks * tick_size`; auto-default to half max when present | Implemented via symbol metadata from `system.symbols` and startup check/default in bot | Yes | Resolved. Bot now fails fast on explicit oversize gaps and auto-defaults when `--gap` is omitted |
| `--cancel-timeout-sec` behavior | Used as max wait for cancel confirmation before reissue path continues | Implemented in cancel-then-reissue flow with timeout-guarded forced replacement | Yes | Resolved. Parameter now has direct operational effect |
| Reprice path wording | Emphasizes cancel-before-reissue as defensive pattern, with replace allowed | Drift/fill reprice path uses cancel-then-reissue with timeout-guarded forced replacement | Yes | Resolved and aligned with current operational safety policy |
| QLEGS mismatch criteria | Reconcile quote_id and leg IDs/order IDs | Current reconcile checks quote_id divergence and missing legs, but not detailed order-id mismatch under same quote_id | Partly | Acceptable first cut, but weaker than design target; can miss stale local leg mapping edge cases |
| Signal handling location | Design module responsibilities mention signal handling in main | Signal handlers are installed in bot.run() | Yes | Centralizing runtime signal handling in bot loop is reasonable and works in practice |

## Practical behavior review

### What works well in practice

- Startup fail-fast for missing `session.state` is implemented.
- QBOOT/QLEGS startup handshake and adoption flow are implemented and tested.
- Fill buffering before quote ACK is implemented, reducing race issues.
- Cancel-then-reissue strategy with timeout guard is implemented and robust under delayed lifecycle events.
- Session and circuit-breaker pause/resume handling are present.

### Practical risks to address

1. Client-side MM obligation pre-validation is now implemented; residual runtime rejections should mostly indicate server-side policy mismatch.
2. Incomplete QLEGS reconciliation (no explicit leg-ID consistency check) weakens state convergence after message loss or partial desync.
3. `--cancel-timeout-sec` is now active in reissue behavior; operators should tune it for venue/network latency.
4. Validation coverage in main is partial (some timing knobs are validated, others are not), making invalid runtime values easier to pass.

## Documentation consistency status

- Updated docs/user-guide/17-mm-bot.md to match implementation in these points:
  - Drift trigger action wording now reflects cancel-then-reissue behavior.
  - `--cancel-timeout-sec` now documented as active timeout guard for cancel-then-reissue.
  - Gap validation section now reflects implemented client-side check/defaulting plus engine enforcement.
  - Troubleshooting row for quote rejection generalized to actual behavior.

- docs-design/EduMatcher-MM-bots.md remains the target design. Differences above identify where implementation is still behind the design intent.

## Recommendation

Implementation is operationally usable for classroom/demo market making and now closes the three previously identified parity gaps. Prioritize these follow-ups for further hardening:

1. Extend QLEGS reconciliation further for nuanced historical-leg filtering if payloads contain mixed lifecycle legs.
2. Add more end-to-end tests against a live engine fixture for reissue timing under delayed status events.
