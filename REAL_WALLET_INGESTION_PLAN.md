# TON Wallet Intelligence Dashboard — v0.22.4 PAGINATION EVIDENCE

Planning and rollout contract for bounded real-wallet acquisition. The current
milestone makes one narrow improvement: guarded low-level TonAPI transaction
ingestion can follow and persist a verifiable page chain inside one frozen UTC
interval. It does not promote the other wallet surfaces to complete history.

## Objective

Make acquisition quality inspectable before multi-run history, cost basis, or
PnL can consume it. Provider failures, cursor anomalies, caps, and legacy gaps
must remain visible; no missing data is inferred.

## Frozen interval contract

Every preview or ingest request resolves one immutable half-open interval
`[start, end)`:

- `24h`, `3d`, and `7d` use one captured request time as `end`;
- `custom` timestamps are parsed and normalized to UTC;
- `custom_end` cannot be later than acquisition time;
- the start must be strictly earlier than the end;
- persisted bounds do not move while pages are fetched.

The interval contract is `wallet_time_bounds_v1`. Rows at `start` are included;
rows at `end` are excluded.

## Live transaction pagination

Pagination applies only when all guarded-live conditions are true:

- `DATA_MODE=real`;
- `WALLET_ACTIVITY_PROVIDER=tonapi`;
- `WALLET_ACTIVITY_LIVE_ENABLED=true`;
- `transactions` is requested;
- the run has resolved bounds.

The page contract is:

- `WALLET_ACTIVITY_LIVE_TX_LIMIT` controls page size (`1..1000`);
- `WALLET_ACTIVITY_LIVE_TX_MAX_PAGES` controls the attempt cap (`1..100`,
  default `10`);
- the first page omits `before_lt`;
- every later page uses the prior page's minimum canonical LT;
- provider rows and the cross-page chain must remain strictly descending by LT;
- bounded rows must carry usable timestamps and remain globally ordered;
- duplicate LT/hash observations are counted and suppressed only within that
  acquisition; conflicting duplicate timestamps are a protocol error;
- only rows in `[start, end)` are normalized into the run.

A bounded transaction stream becomes `complete` only when:

1. TonAPI returns an empty terminal page; or
2. a valid descending page crosses below the requested start.

The following are never completion:

- reaching the configured page cap;
- a provider/network/HTTP failure;
- invalid JSON or malformed normalized fields;
- a repeated, non-advancing, or otherwise non-descending cursor;
- missing timestamps needed for bounded verification;
- conflicting duplicates;
- a legacy run without immutable resolved bounds.

Preview deliberately fetches one page, returns `preview_only`, and does not
persist a run. It is coverage inspection, not a dry run of full pagination.

## Persistence contract

Alembic revision `20260710_0004` adds two evidence tables:

### `wallet_acquisition_streams`

One row per run/provider/stream identity, containing:

- provider, stream key, contract version, and scope kind;
- resolved start/end and sanitized query metadata;
- page size, page cap, and item cap;
- completion state and termination reason;
- attempted/succeeded page counts;
- raw, normalized, and duplicate item counts;
- first and terminal cursors;
- `bounds_verified`;
- start/finish timestamps and sanitized errors.

### `wallet_acquisition_pages`

One row per stream/page index, containing:

- request and response cursor plus requested limit;
- raw, normalized, and duplicate counts;
- oldest/newest LT and activity timestamp;
- SHA-256 response evidence digest;
- attempt count, fetch status, fetched timestamp, and sanitized errors.

Both identities are enforced with unique indexes. Foreign keys cascade from run
to stream to page. Migration retry accepts only empty, exactly matching SQLite
fragments left by interrupted non-transactional DDL; malformed shapes, foreign
key options, indexes, or unexpected rows fail closed. Downgrade is unsupported.

Existing runs are not backfilled with guessed cursors or synthetic pages. Zero
evidence rows accurately means that pagination evidence is unavailable.

## Surface status in v0.22.4

| Surface | Current acquisition behavior | Completion meaning |
| --- | --- | --- |
| Low-level transactions | Strict descending TonAPI LT pagination within frozen bounds | Bounded transaction stream only |
| Transfers | One account-events request, provider-derived actions | Pagination incomplete; not authoritative logic |
| Swaps | One account-events request, `JettonSwap` interpretation | Pagination incomplete; not full DEX history |
| Jettons | Account jetton balance snapshot | Point-in-time snapshot, not history |
| Native TON balance | One account snapshot | Point-in-time snapshot, not history |

TonAPI documents high-level event actions as presentation-oriented structures
that can change. Transfer and swap event actions therefore remain provider
evidence, never an authoritative transaction ledger or ownership proof.

## Identity relationship

The v0.22.3 `ton_account_tx_v1` identity remains required for exact low-level
transaction evidence: network, canonical run account, canonical LT, canonical
32-byte hash, and coherent real/live TonAPI provenance. Pagination does not
weaken or replace it.

Within-run duplicate suppression during page acquisition is not cross-run
deduplication. Original provider hash and LT values remain available for audit.

## API behavior

- `POST /api/wallets/ingest/preview` returns one-page transaction acquisition
  evidence with `preview_only`; it persists nothing.
- `POST /api/wallets/ingest` persists accepted transaction rows plus stream/page
  evidence. Partial pages remain visible through `incomplete_surfaces`.
- `GET /api/wallets/ingest/{run_id}` reads the persisted evidence back without
  recomputing or inferring legacy pages.
- `POST /api/wallets/history/readiness` reports per-run bounded transaction
  pagination under `wallet_history_readiness_v0.22.4`, but remains diagnostic.

One failing transaction page after earlier successful pages preserves the
accepted rows and evidence while marking the stream incomplete. A failure before
any usable page can mark that surface/error path unavailable. Other successful
surfaces do not convert an incomplete transaction stream into complete history.

## Non-goals

- No transfer, swap, jetton, or native-balance pagination completion.
- No authoritative logic built from TonAPI high-level event actions.
- No cross-run merge, interval stitching, or deduplication.
- No proof of all wallet history before the selected interval.
- No acquisition cost basis from pagination evidence alone.
- No PnL, realized/unrealized, fee-linkage, clustering, or ownership-proof
  change.
- No synthetic migration evidence for legacy runs.

## Verification gates

- Fresh, exact legacy, and interrupted SQLite migrations reach revision 0004
  without changing pre-existing domain rows.
- Malformed partial tables, indexes, foreign-key options, or unexpected evidence
  rows fail before further DDL.
- Stream/page uniqueness and run-to-page cascade behavior are tested.
- Bounds tests freeze rolling windows and enforce `[start, end)` semantics.
- Adapter tests cover first/next/terminal pages, strict LT descent, cursor
  advancement, duplicate handling, requested-start crossing, empty terminal
  page, page cap, provider error, and protocol error.
- Preview remains exactly one page and `preview_only`.
- Persisted evidence survives run readback with no API key or credential in
  query/error evidence.
- Full backend tests and frontend build pass.

## Roadmap beyond v0.22.4

1. Define safe pagination and completeness contracts for the remaining
   surfaces without treating provider event actions as immutable chain logic.
2. Add canonical transfer, swap-action, jetton-asset, and counterparty
   identities.
3. Prove interval continuity and gaps across selected runs, then implement
   explicit cross-run deduplication.
4. Only after those gates, evaluate multi-run acquisition cost basis and PnL
   integration.
