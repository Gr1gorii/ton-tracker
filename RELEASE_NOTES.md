# TON Wallet Intelligence Dashboard — v0.22.4 PAGINATION EVIDENCE

This release adds bounded, evidence-backed pagination for the low-level TonAPI
account-transaction surface. It does not claim complete wallet history and does
not change cost basis or PnL.

## Release scope

- Every wallet ingestion request freezes one immutable half-open UTC interval:
  `[resolved_start, resolved_end)`.
- Rolling `24h`, `3d`, and `7d` windows resolve once at request time. Custom
  windows are normalized to UTC and cannot end after acquisition time.
- Only guarded real/live TonAPI `transactions` ingestion follows multiple
  pages. Transfers, swaps, jettons, and balances retain their existing
  one-request or snapshot behavior.
- The existing v0.22.3 transaction identity remains unchanged: eligible
  real/live low-level rows use network + canonical run account + canonical LT +
  canonical 32-byte hash. Original provider values remain visible.

## Transaction pagination contract

- Page size is `WALLET_ACTIVITY_LIVE_TX_LIMIT` (`1..1000`).
- Page cap is `WALLET_ACTIVITY_LIVE_TX_MAX_PAGES` (`1..100`, default `10`).
- Pages must form one globally strict descending logical-time chain. Each next
  request uses the prior page's minimum LT as `before_lt`.
- A provider page may not exceed its requested limit. Transaction hashes must
  be canonical 32-byte hex strings; bounded timestamps and optional fee values
  must be non-lossy integers. Booleans, floats, non-finite/oversized numbers,
  and malformed hashes terminate as protocol evidence, never completeness.
- Duplicate LT/hash observations inside one acquisition are counted and
  suppressed only within that run. This is not cross-run deduplication.
- Rows are accepted only inside the frozen `[start, end)` interval.
- A bounded stream is `complete` only when TonAPI returns a terminal empty page
  or ordered rows verifiably cross below the requested start.
- Page-cap exhaustion, provider failure, malformed response data, changed
  duplicate timestamps, missing required timestamps, or a stalled/non-descending
  cursor leaves the stream `incomplete` or `error`.
- Preview fetches exactly one page and reports `preview_only`; it never proves
  pagination termination or persists a run.

## Persisted evidence

Alembic revision `20260710_0004` adds:

- `wallet_acquisition_streams`: provider/stream contract, frozen bounds, query
  scope, page limits, aggregate counts, completion state, termination reason,
  first/terminal cursors, bounds verification, timestamps, and sanitized
  diagnostics.
- `wallet_acquisition_pages`: page index, request/response cursor, requested
  limit, raw/normalized/duplicate counts, LT and timestamp extrema, response
  digest, attempt count, fetch status, timestamp, and sanitized diagnostics.

The migration is forward-only, validates interrupted SQLite DDL before repair,
and creates only missing correct tables or indexes. Stream identity is unique by
run/provider/key; page identity is unique by stream/page index; run deletion
cascades through stream and page evidence. Runtime SQLite connections enable
foreign-key enforcement before use. Existing runs receive zero fabricated
acquisition records.

Persisted runs expose `acquisition_streams`, `incomplete_surfaces`, and page
evidence through the ingestion response. History readiness uses
`analysis_version: wallet_history_readiness_v0.22.4` to report validated per-run
transaction pagination or its blocker state, while all global history and PnL
flags remain false.

## Explicitly unchanged

- TonAPI transfers and swaps are still derived from high-level account-event
  actions. Those provider interpretations can change and are not authoritative
  transaction logic or proof of full DEX history.
- Jettons and native TON balances remain point-in-time snapshots without an
  equivalent pagination-completeness contract.
- No cross-run merge or deduplication is applied.
- No interval-continuity proof exists across multiple runs.
- No complete pre-run acquisition history or cost basis is established.
- `history_complete`, `is_cost_basis`, `eligible_for_cost_basis`, and
  `used_by_pnl` remain false for history readiness.
- Existing realized/unrealized calculations and Real-PnL gates are unchanged.
- Backend `VERSION=0.2.1` remains the API-version field; `v0.22.4 PAGINATION
  EVIDENCE` is the product label.

## Verification

Before promotion:

```bash
cd backend
.venv/bin/python -m pytest -q

cd ../frontend
npm run build
```

Also verify a guarded live run with a deliberately small transaction page size:
cursor values must descend, evidence must persist after readback, completion
must follow only the two allowed terminal conditions, and no credential may
appear in warnings, query evidence, errors, exports, or logs.
