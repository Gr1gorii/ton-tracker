# TON Wallet Intelligence Dashboard — v0.22.6 ACTION IDENTITY

Planning and rollout contract for bounded real-wallet acquisition. Guarded
low-level TonAPI transactions and the v0.22.5 shared account-event page chain
retain their bounded evidence contracts. v0.22.6 adds an exact provider-scoped
event/action observation coordinate for derived transfer and swap rows without
promoting mutable event actions to authoritative or complete wallet history.

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

## Shared account-event pagination

When guarded-live `transfers`, `swaps`, or both are requested, ingestion follows
one TonAPI `/events` chain:

- `WALLET_ACTIVITY_LIVE_EVENT_LIMIT` controls page size (`1..100`);
- `WALLET_ACTIVITY_LIVE_EVENT_MAX_PAGES` controls the attempt cap (`1..100`,
  default `10`);
- `start_date` and `end_date` safely widen fractional provider filters, then
  exact local `[start, end)` filtering decides which events are materialized;
- each page requires canonical event id, uint64 LT, integer timestamp, boolean
  `in_progress`, typed actions, strict LT descent, non-increasing timestamps,
  and exact `before_lt` advancement;
- event ids remain unique across the chain; conflicting LT, timestamp, or
  payload reuse is protocol evidence rather than a second derived row;
- accepted events are normalized into requested transfer and/or swap rows only
  once, so requesting both surfaces never duplicates provider traversal;
- in-progress events are excluded and keep the provider stream incomplete.

The same empty-terminal and requested-start-crossed conditions can complete the
bounded provider page chain. That completion means only that TonAPI's recorded
display stream terminated for the query. Derived actions remain mutable,
non-authoritative, and listed in `incomplete_surfaces`.

## TonAPI response limits

Every TonAPI JSON response is read and validated within explicit resource
bounds:

- maximum response body: 16 MiB;
- maximum parsed JSON depth: 64;
- maximum parsed JSON nodes: 200,000;
- maximum JSON numeric token length: 128 characters, with non-finite and
  non-standard numeric constants rejected.

The structural check is iterative. Malformed JSON, invalid UTF-8, non-byte
bodies, excessive body or structure size, and recursion/memory failures during
parsing become sanitized provider protocol errors; transport/read failures keep
their provider/network classification. None establishes stream completion or
leaks a credential. Keyed requests still require HTTPS, and authorization is
not forwarded through redirects.

## Acquisition persistence contract

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

## Event-action observation persistence

Alembic revision `20260710_0005` adds the following fields to both
`wallet_transfers` and `wallet_swaps`:

- identity status and contract version;
- TON network and canonical run account;
- canonical event id and event LT;
- original zero-based action index and observed action type;
- deterministic provider observation identity key.

The migration verifies exact columns and indexes, rejects same-table or
cross-table identity conflicts, and fails closed on malformed partial schema.
It does not guess a missing action index. Consequently, rows created by
v0.22.5 remain explicitly `unavailable`; their order, payload, type, or
timestamp is insufficient evidence for a safe backfill.

Runtime ingestion enforces one shared transfer/swap identity namespace in
addition to the per-table unique indexes. Reinterpreting the same event/action
coordinate as another surface is a conflict, not a new observation.

## Surface status in v0.22.6

| Surface | Current acquisition behavior | Completion meaning |
| --- | --- | --- |
| Low-level transactions | Strict descending TonAPI LT pagination within frozen bounds | Bounded transaction stream only |
| Transfers | Shared strict account-events pagination plus provider-scoped event/action observation identity | Provider chain can terminate; derived actions remain incomplete and non-authoritative |
| Swaps | Same shared chain, `JettonSwap` interpretation, and shared observation-identity namespace | Provider chain can terminate; derived actions remain incomplete and not full DEX history |
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

The v0.22.6 `tonapi_event_action_obs_v1` identity is deliberately narrower than
semantic activity identity. Its key coordinate is:

```text
tonapi_event_action_obs_v1
| tonapi
| network
| canonical_account
| canonical_event_id
| canonical_event_lt
| original_action_index
```

The action index is captured from the complete provider action array before
unsupported actions are filtered. `action_type` and activity surface are not
part of the key, so changed provider interpretation of one coordinate is
reported as a conflict. The coordinate proves only that this application
recorded one coherent TonAPI observation. It is not locally verified blockchain
proof, authoritative activity identity, ownership proof, cost-basis evidence,
or a PnL/deduplication key. The public flags state those limits explicitly.

## API behavior

- `POST /api/wallets/ingest/preview` returns one page per requested paginated
  stream with `preview_only`; it persists nothing.
- `POST /api/wallets/ingest` persists accepted transaction rows, derived event
  rows, and both stream/page contracts. Partial or display-only surfaces remain
  visible through `incomplete_surfaces`.
- `GET /api/wallets/ingest/{run_id}` reads the persisted evidence back without
  inferring legacy pages or missing action indexes.
- `POST /api/wallets/history/readiness` reports per-run bounded transaction and
  provider-event acquisition plus event-action observation identity coverage,
  groups, and conflicts under `wallet_history_readiness_v0.22.6`, but remains
  diagnostic.

One failing transaction page after earlier successful pages preserves the
accepted rows and evidence while marking the stream incomplete. A failure before
any usable page can mark that surface/error path unavailable. Other successful
surfaces do not convert an incomplete transaction stream into complete history.

## Non-goals

- No authoritative transfer/swap completion from provider event actions.
- No blockchain-verified or authoritative semantic activity identity from the
  provider-scoped observation coordinate.
- No jetton or native-balance history completion from snapshots.
- No authoritative logic built from TonAPI high-level event actions.
- No cross-run merge, interval stitching, or deduplication.
- No proof of all wallet history before the selected interval.
- No acquisition cost basis from pagination evidence alone.
- No PnL, realized/unrealized, fee-linkage, clustering, or ownership-proof
  change.
- No synthetic migration evidence for legacy runs.

## Verification gates

- Fresh, exact legacy, and interrupted SQLite migrations reach revision 0005
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
- Keyed requests require HTTPS and never forward authorization through a
  redirect; lossy terminal cursor types fail closed.
- Response tests cover the 16 MiB body limit, JSON depth 64, 200,000-node
  limit, malformed JSON protocol classification, and deeply nested input.
- Identity tests preserve original action indexes, reject incoherent tuples and
  same/cross-table conflicts, and keep v0.22.5 rows unavailable.
- Readiness tests cover provider-scoped identity coverage, groups, changed-
  payload conflicts, and unchanged false global history/cost/PnL flags.
- Full backend tests and frontend build pass.

## Roadmap beyond v0.22.6

1. Acquire authoritative low-level transfer/trade evidence or reconstruct it
   from validated traces without treating provider display actions as immutable
   chain logic.
2. Add authoritative semantic transfer/trade reconstruction plus jetton-asset
   and counterparty identity contracts; do not treat the provider observation
   coordinate as a substitute.
3. Prove interval continuity and gaps across selected runs, then implement
   explicit cross-run deduplication.
4. Only after those gates, evaluate multi-run acquisition cost basis and PnL
   integration.
