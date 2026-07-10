# TON Wallet Intelligence Dashboard — v0.22.9 RECENT RUN CATALOG

Planning and rollout contract for bounded real-wallet acquisition. Guarded
low-level TonAPI transactions and the v0.22.5 shared account-event page chain
retain their bounded evidence contracts, and v0.22.6 provider event/action
observation identity remains unchanged. v0.22.7 added deterministic interval
coverage across 2-50 explicitly selected runs without promoting a selected
span, provider display events, or derived actions to complete wallet history.
v0.22.8 added read-only selection of an existing persisted run. v0.22.9 adds a
privacy-bounded newest-run catalog that discovers stored ids without loading
full activity or changing any acquisition, identity, readiness, or interval
contract.

## Objective

Make acquisition quality and bounded continuity inspectable before multi-run
history, cost basis, or PnL can consume it. Provider failures, cursor anomalies,
caps, excluded runs, not-requested streams, overlaps, internal gaps, and legacy
evidence limits must remain visible; no missing interval or activity is
inferred. A user must also be able to reopen one exact stored run without
creating another run, contacting a provider, or mutating persisted evidence.
Recent-run discovery must expose only bounded metadata, preserve signed-64-bit
ids exactly, and remain one provider-free, mutation-free database read.

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

## Persisted run loader contract

The wallet workspace reuses `GET /api/wallets/ingest/{run_id}`; the v0.22.8
loader did not add a parallel full-run endpoint or run-creation path. URL ids
are canonical positive signed-64-bit decimal strings: `[1-9][0-9]*`, with maximum
`9223372036854775807`.

- an existing canonical id returns 200 with the persisted run;
- a canonical id with no stored run returns 404;
- malformed, noncanonical, zero, negative, or out-of-range ids return 422;
- readback uses existing database rows only and makes no provider or ingestion
  adapter call;
- readback performs no insert, update, delete, commit, or other database
  mutation.

The response includes exact persisted `custom_start`, `custom_end`, and
`created_at` timestamps. Custom runs return both stored bounds; rolling-window
runs return null custom bounds. The browser deliberately accepts the narrower
positive JavaScript safe-integer range before issuing the GET, then rejects a
response whose id or stored request metadata does not match the request.

On success, wallet address, time window, exact custom bounds, requested
surfaces, request snapshot, and current run are replaced atomically. Preview and
run results remain mutually exclusive. On 404, 422, network failure, stale
response, or incoherent payload, the prior run remains selected and visible.
Run-scoped evidence, PnL, signal, and interval cards use the selected run id as
their remount boundary, so state from a prior run is not reused. Request
signatures normalize valid datetime values to canonical UTC before stale-state
comparison. For a loaded custom run, the exact canonical UTC bounds remain the
signature and preview/run payload source until the corresponding local date
control is edited; this preserves DST-fold instants and sub-millisecond precision.

This loader requires no schema change. Alembic head remains
`20260710_0005` and backend `VERSION=0.2.1` remains the independent API-version
field.

## Recent persisted-run catalog contract

`GET /api/wallets/ingest?limit=8` is a separate minimal collection read that
does not replace `GET /api/wallets/ingest/{run_id}`. The default limit is `8`.
An explicit limit must be a canonical ASCII positive decimal integer from `1`
through `50`. Leading zeros, signs, whitespace, decimals, booleans, empty
values, repeated `limit` keys, unknown query parameters, case aliases, and
out-of-range values return 422.

The response has exactly three top-level fields: `runs`, `limit`, and
`truncated`. Every item in `runs` has exactly six fields:

| Field | Contract |
| --- | --- |
| `run_id` | Canonical positive signed-64-bit decimal string, never a JSON number |
| `wallet_hint` | At least 16 characters: bounded first six + ellipsis + last four; shorter legacy values: `stored…run`; maximum length 11 |
| `time_window` | Persisted `24h`, `3d`, `7d`, or `custom` label |
| `created_at` | Persisted run creation time serialized in UTC |
| `status` | Persisted ingestion status |
| `data_mode` | Persisted `mock` or `real` mode |

The catalog never returns the full submitted address, canonical account
identity, custom bounds, requested surfaces, provider evidence or messages,
activity rows or counts, warnings, or raw payloads. Backend request validation
and the browser wallet input both cap a newly submitted wallet value at 128
characters. The database projection bounds the hint without materializing the
full address into the public response.

Recent means fixed descending `wallet_ingestion_runs.id`. The service executes
one projected SELECT against that table, requests at most `limit + 1` rows,
returns at most `limit`, and sets `truncated` when an older row exists. There is
no offset, cursor, client-selected sort, filter, total count, relationship load,
child-table query, settings load, provider construction/call, insert, update,
delete, commit, or other mutation. Server and browser both use `no-store`.

The browser requests eight summaries, renders the newest three while collapsed,
and can expand to all eight. Catalog state has its own abort controller and
monotonic request sequence, separate from preview, ingestion, full-run load,
and run refresh state. Initial load, refresh, retry, successful-ingestion
refresh, empty success, refresh failure with last-success preservation, and
stale-response suppression remain distinct. Selecting a safe item calls the
existing full-run loader with that explicit id. Signed-64-bit ids above the
JavaScript safe-integer maximum stay visible as exact strings, but their open
action is disabled rather than rounded. A failed item open preserves the prior
current run and the catalog selection state.

v0.22.9 adds no persistence fields or migration. Alembic head remains
`20260710_0005`; backend `VERSION=0.2.1`,
`wallet_history_readiness_v0.22.7`, and
`wallet_multi_run_interval_coverage_v1` are unchanged.

## Multi-run interval coverage

`wallet_multi_run_interval_coverage_v1` is a pure diagnostic contract over an
explicit selected set of 2-50 distinct run ids. The history-readiness request
still names one selected run as `target_run_id`; the target does not silently
expand the selected set or grant stronger coverage semantics.

This release adds no persistence fields or database migration. Alembic head
remains `20260710_0005`; interval coverage is recomputed read-only from the
strictly revalidated acquisition evidence already stored for each run.

### Evidence admission

Recorded interval fields are never trusted by themselves. Before interval math,
history readiness strictly revalidates the complete persisted evidence chain
for every selected run and stream:

- the low-level layer accepts only one coherent bounded `transactions` stream
  whose pages recompute to validated state `complete`;
- the provider-display layer accepts only one coherent bounded
  `account_events` stream whose pages recompute to validated state
  `provider_stream_complete`;
- provider, stream key, contract, scope, query filters, sort order, frozen
  bounds, page indexes, cursors, counts, hashes, completion reason, and error
  state must remain internally coherent with the selected run;
- missing or ambiguous evidence, invalid intervals, preview-only, incomplete,
  error, or legacy-unavailable states are classified as `excluded` with an
  explicit reason;
- a stream that the run did not request is classified separately as
  `not_requested` and is never counted in the union.

No interval is fabricated from run timestamps, observed row timestamps, window
labels, another stream, or neighboring runs.

### Never-mixed layers

The response contains two independent layers:

| Layer | Eligible revalidated state | Meaning |
| --- | --- | --- |
| `low_level_transactions` | `complete` | Bounded low-level TonAPI transaction-query coverage for accepted selected runs |
| `provider_display_events` | `provider_stream_complete` | Bounded TonAPI account-event display coverage only |

`cross_stream_union_applied` is always false. A transaction interval cannot
fill an event-layer gap, an event interval cannot fill a transaction-layer gap,
and cross-layer overlap has no coverage meaning. TonAPI high-level event actions
remain mutable display interpretations, so even a contiguous provider-event
span is not authoritative transfer, swap, or activity history.

### Half-open sweep and exact durations

Each accepted interval uses UTC half-open semantics `[start, end)`. The
deterministic boundary sweep divides the selected eligible span into exact
cells, then reports:

- accepted per-run intervals and their normalized union;
- adjacent intervals as one contiguous union when one `end` equals the next
  `start`;
- overlap segments with exact contributing run ids, coverage depth, total
  overlapped duration, and maximum depth;
- internal gap segments with the eligible run ids immediately to the left and
  right;
- span, covered, gap, and overlap durations as canonical decimal strings of
  integer microseconds.

Integer timedelta decomposition plus decimal-string transport avoids
floating-point, browser safe-integer, and whole-second rounding, including at
one-microsecond boundaries. Overlapping intervals count
once in covered union duration. Gaps are measured only between the earliest
eligible start and latest eligible end. Time before that start and at or after
that end remains `outside_selected_span_coverage: unknown`.

The layer state is `no_validated_intervals`, `contiguous_selected_span`, or
`gapped_selected_span`. Per-run records and summary lists keep `included`,
`excluded`, and `not_requested` classifications visible even when the included
intervals are contiguous.

## Surface status in v0.22.9

| Surface | Current acquisition behavior | Completion meaning |
| --- | --- | --- |
| Low-level transactions | Strict descending TonAPI LT pagination within frozen bounds | Bounded transaction stream only |
| Transfers | Shared strict account-events pagination plus provider-scoped event/action observation identity | Provider chain can terminate; derived actions remain incomplete and non-authoritative |
| Swaps | Same shared chain, `JettonSwap` interpretation, and shared observation-identity namespace | Provider chain can terminate; derived actions remain incomplete and not full DEX history |
| Jettons | Account jetton balance snapshot | Point-in-time snapshot, not history |
| Native TON balance | One account snapshot | Point-in-time snapshot, not history |
| Recent persisted-run catalog | One bounded ID-descending projection of up to 50 run summaries | Discovery metadata only; no full address, activity, provider call, or mutation |
| Persisted run loading | Existing database-only GET plus validated atomic workspace restoration | Exact readback of one run; no provider call, ingestion, or mutation |
| Multi-run interval diagnostics | Two independent unions over strictly revalidated selected-run evidence | Continuity only inside each eligible selected span; outside time remains unknown |

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
- `GET /api/wallets/ingest?limit=8` returns the bounded six-field newest-run
  catalog under the canonical `1..50` limit, decimal-string signed-64-bit id,
  masked hint, one-SELECT, truncation, no-store, provider-free, and mutation-
  free contract above.
- `GET /api/wallets/ingest/{run_id}` accepts only canonical positive signed-
  64-bit ids, returns 200/404/422 as defined above, and reads persisted evidence
  plus exact custom bounds and creation time without provider access, mutation,
  inferred legacy pages, or inferred action indexes.
- `POST /api/wallets/history/readiness` accepts one explicit target within 2-50
  distinct selected run ids. Under `wallet_history_readiness_v0.22.7`, it
  reports per-run acquisition validation, identity coverage/groups/conflicts,
  and the two independent `wallet_multi_run_interval_coverage_v1` layers.
- The wallet workspace exposes this endpoint through a selected-run card: the
  current run is the target and the user supplies the remaining selected ids.
  Transaction and provider-display continuity remain visibly separate.

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
- No activity-row merge, semantic stitching, or cross-run deduplication. The
  bounded interval union is diagnostic math only.
- No proof of time before the earliest eligible selected interval, time after
  the latest eligible end, or complete wallet history.
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
- Stored-run GET tests cover canonical positive signed-64-bit path ids,
  noncanonical and overflow rejection, exact 200/404/422 behavior, exact
  `custom_start`/`custom_end`/`created_at` readback, repeatability, no provider
  construction or call, and no database mutation.
- Catalog schema and endpoint tests cover default `limit=8`, canonical `1..50`
  boundaries, rejection of duplicate and unknown parameters, the exact six-
  field summary allowlist, bounded masked wallet hints, decimal-string signed-
  64-bit ids, strict ID-descending order, `truncated`, one projected SELECT, no
  child-table read, no-store, no provider/settings call, and no mutation.
- Keyed requests require HTTPS and never forward authorization through a
  redirect; lossy terminal cursor types fail closed.
- Response tests cover the 16 MiB body limit, JSON depth 64, 200,000-node
  limit, malformed JSON protocol classification, and deeply nested input.
- Identity tests preserve original action indexes, reject incoherent tuples and
  same/cross-table conflicts, and keep v0.22.5 rows unavailable.
- Readiness tests cover provider-scoped identity coverage, groups, changed-
  payload conflicts, and unchanged false global history/cost/PnL flags.
- Interval tests cover 2-50 distinct selected run ids, strict transaction/event
  evidence revalidation, independent layers, included/excluded/not-requested
  classification, adjacency, nested and multi-run overlaps, internal gaps, and
  exact one-microsecond boundaries.
- Schema and endpoint tests keep `cross_stream_union_applied`, global-history,
  authoritative-coverage, activity-merge, deduplication, cost-basis, and PnL
  flags false.
- Frontend Vitest 4 tests cover the three-of-eight collapsed catalog, expansion,
  exact response validation, independent abort/sequence races, refresh and
  retry, last-success preservation, safe selection through the full loader,
  unsafe-id disabling, post-ingestion refresh, the positive safe-integer gate,
  response restoration, preview/run exclusivity, failed-load preservation,
  run-card remounting, and normalized datetime signatures.
- Full backend tests, frontend Vitest 4 tests, and the Vite 8 build pass; the
  checked-in frontend dependency graph reports zero `npm audit`
  vulnerabilities.
- The frontend engine contract is Node.js `^20.19.0 || >=22.12.0` with npm 10
  or newer, matching the supported Vite 8 toolchain.

## Roadmap beyond v0.22.9

1. Acquire authoritative low-level transfer/trade evidence or reconstruct it
   from validated traces without treating provider display actions as immutable
   chain logic.
2. Add authoritative semantic transfer/trade reconstruction plus jetton-asset
   and counterparty identity contracts; do not treat the provider observation
   coordinate as a substitute.
3. Use the bounded continuity diagnostics as evidence for a separately designed
   activity-row merge and explicit cross-run deduplication contract; never
   infer those operations from interval adjacency alone.
4. Only after those gates, evaluate multi-run acquisition cost basis and PnL
   integration.
