# TON Wallet Intelligence Dashboard — v0.22.5 EVENT PAGINATION

This release adds one strict, bounded TonAPI account-event page chain shared by
the transfer and swap surfaces. It records provider acquisition evidence while
preserving TonAPI's display-only event semantics: derived actions remain
non-authoritative, incomplete activity evidence and do not change cost basis or
PnL.

## Release scope

- Every wallet request still freezes one immutable half-open UTC interval:
  `[resolved_start, resolved_end)`.
- Guarded real/live `transfers` and `swaps` now share one account-events request
  chain, including when both surfaces are requested together.
- Provider date filters safely widen fractional interval edges; normalization
  applies the exact local `[start, end)` test before materializing rows.
- Low-level transaction pagination and the v0.22.3 transaction identity remain
  unchanged.
- Jetton and native TON balances remain point-in-time snapshots.

## Account-event acquisition contract

- Page size is `WALLET_ACTIVITY_LIVE_EVENT_LIMIT` (`1..100`, default `100`).
- Page cap is `WALLET_ACTIVITY_LIVE_EVENT_MAX_PAGES` (`1..100`, default `10`).
- Pages form one globally strict descending LT and non-increasing timestamp
  chain. Each next request uses the prior page's minimum LT as `before_lt`.
- The provider envelope is validated before use: canonical 32-byte hex event
  id, canonical uint64 LT, bounded integer timestamp, boolean `in_progress`,
  action objects with non-empty types, exact cursor advancement, and no
  oversized response page.
- Keyed TonAPI requests require HTTPS, and authorization is never copied into a
  redirect request. Boolean or floating-point zero cursors cannot masquerade as
  the provider's integer terminal cursor.
- Event ids must remain unique across the page chain. An exact repeated
  observation can be counted and suppressed inside one acquisition; reuse with
  a changed LT, timestamp, or payload is a protocol error. This is not cross-run
  deduplication.
- In-progress events are not materialized and prevent a completion claim for
  the event stream.
- A bounded provider page chain is `complete` only after an empty terminal page
  or an ordered crossing below the requested start. A cap, provider failure,
  malformed protocol data, stalled cursor, or in-progress event remains
  `incomplete` or `error`.
- Preview fetches exactly one page, reports `preview_only`, and persists no
  rows.

## Display-only semantics

TonAPI account events and actions are provider-derived presentation data that
can change. Therefore:

- `account_events` completion verifies only the recorded provider page chain;
- derived transfers and swaps always remain in `incomplete_surfaces`;
- a successful event acquisition returns limited/partial coverage rather than
  authoritative live history;
- event actions cannot establish complete transfer history, complete DEX trade
  history, ownership, acquisition cost basis, or PnL.

## Persisted and diagnostic evidence

The existing Alembic revision `20260710_0004` already supports multiple stream
keys. v0.22.5 persists `account_events` aggregate/page evidence alongside
`transactions` without a schema change: sanitized query scope, cursors, counts,
LT/time extrema, response digests, termination, errors, and exact requested
bounds.

History readiness uses
`analysis_version: wallet_history_readiness_v0.22.5`. It validates the persisted
event chain separately and may report `provider_stream_complete`; that state is
deliberately not authoritative activity completeness. All global history,
deduplication, cost-basis, and PnL flags remain false.

## Explicitly unchanged

- No canonical transfer, swap-action, jetton-asset, or counterparty identity is
  introduced.
- No cross-run merge, interval stitching, or deduplication is applied.
- No complete pre-run acquisition history is established.
- Existing realized/unrealized calculations and Real-PnL gates are unchanged.
- Backend `VERSION=0.2.1` remains the API-version field; `v0.22.5 EVENT
  PAGINATION` is the product label.

## Verification

```bash
cd backend
.venv/bin/python -m pytest -q

cd ../frontend
npm run build
```

For guarded live verification, use a deliberately small event page size and
cap. Confirm one chain serves both derived surfaces, cursor values descend,
evidence survives readback, an empty bounded interval terminates safely,
partial semantics remain visible even for a complete provider chain, and no
credential appears in logs, warnings, query evidence, errors, or exports.
