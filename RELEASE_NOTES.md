# TON Wallet Intelligence Dashboard — v0.23.7 IMMUTABLE NATIVE ACTIVITY LEDGER

v0.23.7 adds forward-only Alembic revision `20260710_0008`, capture-bound
`wallet_native_activity_ledgers` and `wallet_native_activity_rows`, plus
provider-free GET/POST `.../native-activity-ledger`. The first POST materializes
verified native TON flows with canonical asset and counterparty observation
keys; repeated POST and GET re-derive the BOC-backed source, every row, totals,
and canonical digest before returning. Semantic reconstruction is now explicit
for native message transfers, but the ledger remains trace-scoped,
non-authoritative, unmerged across runs, ineligible for cost basis, and unused
by PnL.

---

# TON Wallet Intelligence Dashboard — v0.23.6 COUNTERPARTY OBSERVATION IDENTITY

v0.23.6 adds provider-free `GET .../boc-verification/counterparties`.
Observed native-flow endpoints are grouped by
`ton_counterparty_account_obs_v1|{network}|{canonical_account}` with exact
workchain/account-id decomposition, bound flow identities, directions, and
nanoton totals. The canonical digest covers the upstream message evidence and
sorted groups. This is observation identity only, never actor, owner,
beneficiary, intent, cost-basis, or PnL identity.

---

# TON Wallet Intelligence Dashboard — v0.23.5 NATIVE TON ASSET IDENTITY

v0.23.5 adds provider-free
`GET .../boc-verification/native-ton-asset`. Every verified native TON flow is
bound to `ton_native_asset_v1|{network}`, fixed `TON`/`Toncoin` metadata, nine
decimals, and `nanoton` base units. The binding list and upstream message digest
produce a canonical SHA-256 record. Symbols are display metadata, not identity.
Jetton assets, counterparties, activity merge/deduplication, cost basis, and PnL
remain explicitly outside this contract.

---

# TON Wallet Intelligence Dashboard — v0.23.4 NATIVE TON FLOW OBSERVATIONS

v0.23.4 adds provider-free
`GET .../boc-verification/native-ton-flows`. Verified internal-message headers
that involve the stored run account are classified as incoming, outgoing, or
self. Each row carries a deterministic `ton_native_message_flow_obs_v1`
identity, nanotons, message/transaction binding, observed counterparty endpoint,
body hash, opcode prefix, and bounce state. Totals are recomputed from rows.
This is native TON header evidence only: payload semantic decoding,
authoritative transfer/counterparty identity, activity merge, deduplication,
ownership, cost basis, and PnL remain false.

---

# TON Wallet Intelligence Dashboard — v0.23.3 MESSAGE BODY EVIDENCE

v0.23.3 adds provider-free
`GET .../trace-evidence/boc-verification/messages`. It reparses the immutable
v0.23.2 BOCs and returns one body-safe row per unique persisted message:
transaction preorder/hash, trace role/ordinal, provider and raw cell hashes,
hash convention, verified header fields, body hash, bit/ref count, and an
optional 32-bit opcode prefix. The response is digest-bound to the complete
v0.23.2 verification, uses `Cache-Control: no-store`, and never returns the raw
BOC or message body. Semantic reconstruction, authoritative identity, ownership,
cost basis, and PnL remain explicitly false.

---

# TON Wallet Intelligence Dashboard — v0.23.2 LOCAL BOC VERIFICATION

v0.23.2 adds a separate `ton_boc_trace_verification_v1` record on top of an
existing finalized v0.23.1 trace capture. The first explicit verification
performs exactly one TonAPI trace request, persists each bounded transaction
BOC, and locally deserializes it with pinned `pytoniq-core==0.1.46`. Existing
verification GET and idempotent POST are provider-free and reparse every BOC.

- Transaction root cell hash, account hash, LT, unix time, aborted state, and
  out-message count must match the immutable trace node.
- Internal and external message types, normalized external-in hashes, direct
  cell hashes, canonical endpoints, amounts, fees, flags, and timestamps must
  match the persisted message graph.
- Parent outgoing messages must partition exactly into child inbound edges and
  remaining outbound messages. Body hashes and available 32-bit opcode prefixes
  are derived locally without semantic promotion.
- Raw BOCs are capped at 1 MiB each and 8 MiB per verification, stored only in
  the database, covered by canonical SHA-256 digests, and never returned to the
  browser. Message bodies are also never returned.
- Alembic `20260710_0007` adds `wallet_trace_boc_verifications` and
  `wallet_trace_boc_transactions`; the migration repairs only exact empty
  interrupted DDL and otherwise fails closed.
- The trace card automatically reads the local verification record after the
  persisted graph. Verification remains an explicit action and is clearly
  separated from blockchain inclusion proof, semantic reconstruction,
  authoritative identity, ownership, merge/deduplication, cost basis, and PnL.

---

# TON Wallet Intelligence Dashboard — v0.23.1 PERSISTED TRACE EVIDENCE

v0.23.1 adds an explicit finalized-only persistence boundary for one bounded
TonAPI low-level trace graph. The existing v0.23.0 live preview remains
read-only and unchanged. A persisted graph is provider-indexed structural
evidence only: it is not blockchain proof, semantic transfer/trade
reconstruction, activity identity, cost basis, ownership proof, or PnL input.

## v0.23.1 scope

- `GET .../trace-evidence/persisted` reads one stored graph and performs no
  provider call. Absence is 404; malformed stored identity or graph is 409.
- `POST .../trace-evidence/persisted` is the only capture operation. The first
  eligible capture makes exactly one `GET /v2/traces/{transaction_hash}` call;
  an already stored graph returns provider-free and mutation-free.
- Only a non-emulated `finalized` trace is persisted. A `pending` trace remains
  preview-only and returns 409 without a database write.
- Capture is atomic: all nodes, parent links, message roles, counts, identities,
  capture context, and the evidence digest are revalidated before commit.
- Each run has 16 database-enforced capture slots. The lowest free slot is used;
  a unique `(run_id, capture_slot)` index prevents concurrent overflow.
- The normalized graph is strict DFS preorder with at most 256 transactions,
  depth 32, 2,048 remaining outgoing messages, and 2,304 total persisted
  message observations.
- Every non-root node has one coherent internal inbound edge from its current
  DFS parent. Root inbound and remaining outbound roles accept only their
  contract-compatible message types.
- Provider names, icons, interfaces, decoded bodies, semantic actions, raw
  transaction/message JSON, BOCs, message bodies, credentials, and headers are
  excluded from persistence.
- The digest covers the canonical graph plus run id, capture slot, exact
  persisted transaction anchor, and capture timestamp. Readback reconstructs
  and re-hashes that document before returning `persisted_graph_revalidated`.
- Every success and handled failure uses `Cache-Control: no-store`.

## v0.23.1 schema

Alembic revision `20260710_0006` adds three forward-only tables:

1. `wallet_trace_evidence_captures` — immutable finalized capture metadata,
   strict per-run slot, aggregate counts, anchor relationship, and digest;
2. `wallet_trace_evidence_nodes` — unique capture preorder/hash/account+LT
   transaction observations with explicit parent linkage;
3. `wallet_trace_evidence_messages` — role/ordinal-scoped sanitized message
   headers and provider-observation identities.

The migration is online-validation-only, repairs only exact empty interrupted
fragments, rejects schema drift or pre-revision rows, performs no legacy
backfill, and refuses downgrade. Foreign keys cascade capture → node → message.
Message observation keys are deliberately non-unique across captures/runs; this
release does not introduce hidden global or cross-run deduplication.

## v0.23.1 workspace

The trace card automatically performs only the database readback for the
selected eligible anchor. Live preview and finalized capture remain separate
manual actions. Scope, abort, and monotonic sequence guards include run, mode,
account, LT, and hash. Read, preview, and capture errors are independent; a
failed live request never removes a previously confirmed immutable record.

---

# TON Wallet Intelligence Dashboard — v0.23.0 TRACE EVIDENCE PREVIEW

This release adds one explicit, read-only trace evidence preview for an eligible
low-level transaction already stored in a real wallet-ingestion run. The user
selects a coherent transaction anchor and requests one sanitized TonAPI trace
summary manually. No trace is fetched automatically, persisted, merged into
activity, reconstructed into transfer/trade semantics, or passed to PnL.

## Release scope

- `GET /api/wallets/ingest/{run_id}/transactions/{transaction_hash}/trace-evidence`
  is the only new public endpoint.
- `run_id` is a canonical positive signed-64-bit decimal. `transaction_hash` is
  a canonical lowercase 64-character hexadecimal hash. Noncanonical path values
  return 422 before provider access.
- Missing runs or transactions return 404. An ineligible guard, network, run, or
  stored identity returns 409 before provider access. Provider transport or
  protocol failure and any trace/stored-anchor mismatch return a
  credential-sanitized 502.
- An eligible request performs exactly one TonAPI
  `GET /v2/traces/{transaction_hash}` call with no query or request body. There
  is no account-trace discovery call, pagination, retry loop, hidden fallback,
  or automatic refresh.
- Success and error responses use `Cache-Control: no-store`; the browser request
  also uses `no-store`.
- The endpoint reads existing run/transaction identity only and performs no DML,
  DDL, commit, ingestion, run mutation, or trace persistence.

## Eligibility and exact stored anchor

Before the provider can be contacted, all of the following must hold:

1. the current configuration is `DATA_MODE=real`, selects `tonapi`, enables the
   wallet-activity live guard, and has a valid network-matching base URL;
2. the persisted run exists, is real, and matches the configured TON network;
3. exactly one stored row matches the requested transaction hash;
4. provider/source/raw provenance and the complete persisted
   `ton_account_tx_v1` tuple re-derive coherently;
5. the re-derived canonical hash equals the lowercase path hash.

The returned provider tree must then contain the requested hash exactly once,
and that node's canonical transaction hash, unsigned-64-bit LT, and canonical
raw account must exactly equal the three persisted identity fields. A missing
anchor or a mismatch is a 502 provider-evidence failure, not a partial success.

## Bounded trace normalization and sanitized allowlist

TonAPI's official `GET /v2/traces/{trace_id}` operation can resolve a trace id or
the hash of a transaction in that trace. v0.23.0 deliberately narrows this to a
canonical hash already stored under the selected run. It traverses the recursive
provider response iteratively with trace-specific caps of 256 transaction nodes,
depth 32, and 2,048 outgoing messages, in addition to the existing generic JSON
transport limits. Interfaces must be a bounded list of non-empty strings, with
at most 128 entries per node and 128 characters per value, but interfaces are
never returned.

Each accepted node requires a non-emulated state, canonical 32-byte transaction
hash, canonical raw account, unsigned-64-bit LT, nonnegative signed-64-bit
timestamp, boolean success/aborted fields, list-shaped outgoing messages with
known types, and list-shaped children. Transaction hashes cannot repeat, and one
canonical account + LT coordinate cannot change hash.

The strict response contract is `tonapi_transaction_trace_preview_v1`. Its
allowlist contains only contract/run/provider metadata, `trace_state`, the exact
stored anchor, a structural summary, permanent safety flags, and one bounded
message. The summary contains root hash, transaction count, maximum depth,
outgoing and pending-internal message counts, successful/failed/aborted counts,
and unique-account count. Raw messages, BOCs, decoded bodies, interfaces,
actions, display metadata, and the provider's recursive tree are omitted.

`is_provider_indexed_low_level_trace` is true. Every promotion flag remains
false: `is_blockchain_proof_verified`,
`is_authoritative_activity_identity`, `semantic_reconstruction_applied`,
`activity_merge_applied`, `deduplication_applied`,
`eligible_for_cost_basis`, `used_by_pnl`, and `is_ownership_proof`.

## Finalized and pending semantics

- `finalized` means the accepted non-emulated provider response contains no
  remaining internal outgoing message anywhere in the trace tree.
- `pending` means at least one such internal outgoing message remains.
- An emulated node is rejected instead of being labeled finalized or pending.
- Finalization does not mean every transaction succeeded. Successful, failed,
  and aborted counts remain separate and visible.
- Neither state is locally verified blockchain proof, authoritative semantic
  activity, complete history, ownership proof, cost-basis evidence, or PnL
  eligibility. A later explicit request may observe a provider transition from
  pending to finalized; no background polling occurs.

## Trace evidence UI

- The card renders only for a persisted run and selects only coherent live
  TonAPI transaction identities; duplicate hashes are suppressed in the
  selector.
- Mock runs, runs with no transactions, and runs without an eligible identity
  remain network-silent with a disabled inspect action.
- The initial state says an explicit request is required. Inspecting and
  refreshing have separate accessible running labels; finalized and pending
  results are visually distinct.
- A request-specific abort controller and monotonic sequence guard prevent stale
  responses from replacing the selected anchor. Changing the anchor clears its
  prior result; loading a different run remounts and aborts run-scoped state.
- A failed first request shows an unavailable state. A failed explicit retry
  preserves the last successful result and exposes retry without promoting it to
  fresh evidence.
- The browser revalidates the exact response keys, counts, stored hash + LT +
  account anchor, trace-state coherence, and every permanent false flag before
  rendering the result.

## Retained recent-run catalog

- `GET /api/wallets/ingest?limit=8` returns the newest persisted-run summaries;
  the default catalog limit is `8`.
- `limit` must be one canonical ASCII positive decimal from `1` through `50`.
  Leading zeros, signs, whitespace, decimals, booleans, empty values, duplicate
  `limit` parameters, unknown parameters, and out-of-range values return 422.
- The catalog is fixed to descending persisted run id. It exposes no offset,
  cursor, filter, client-selected sort, or total count; `truncated` reports only
  whether an older run exists beyond the returned newest page.
- Catalog run ids are canonical positive signed-64-bit decimal strings, up to
  `9223372036854775807`, so transport does not round them through a JSON number.
- `GET /api/wallets/ingest/{run_id}` remains the only full stored-run read
  endpoint. Existing, missing, and invalid path ids retain the v0.22.8
  200/404/422 behavior and exact stored timestamp restoration.
- Wallet input is now bounded to 128 characters in backend validation and the
  browser control.

## Minimal catalog response

The top-level response contains exactly `runs`, `limit`, and `truncated`. Each
run summary contains exactly six fields:

1. `run_id`;
2. `wallet_hint`;
3. `time_window`;
4. `created_at`;
5. `status`;
6. `data_mode`.

`wallet_hint` is bounded to at most 11 characters: values at least 16 characters
use the first six and last four submitted characters separated by one ellipsis,
while shorter legacy values use the non-reconstructing `stored…run` sentinel. The full
submitted address, canonical account identity, custom bounds, requested
surfaces, provider evidence, activity rows and counts, warnings, and messages
are deliberately absent.

The backend issues one projected SELECT against `wallet_ingestion_runs`, orders
by id descending, and reads at most `limit + 1` rows. It does not load child
tables, parse stored provider metadata, load settings, construct an adapter,
contact a provider, insert, update, delete, commit, or otherwise mutate the
database. The response sends `Cache-Control: no-store`; the browser request also
uses `no-store`.

## Catalog UI and request races

- The workspace requests eight recent summaries and shows the newest three in
  its collapsed state; the user can expand to all eight.
- Initial load, manual refresh, and retry use a catalog-specific abort
  controller and monotonic request sequence. A stale or aborted request cannot
  overwrite a newer catalog or interfere with preview, ingestion, refresh, or
  full stored-run loading.
- A refresh error keeps the last successful catalog visible and presents a
  retry action. An empty successful catalog remains distinct from an error.
- Successful ingestion refreshes the catalog after the new run is committed.
- Selecting a catalog row passes its id directly to the existing full-run
  loader. A failed row open keeps the prior selected run and catalog current.
- Signed-64-bit ids outside the JavaScript safe-integer range remain visible as
  exact decimal strings, but their open action is disabled rather than rounded
  to another run.

## Atomic full-run workspace state

- A successful load validates the response id and stored request metadata, then
  restores wallet, time window, exact custom bounds, requested surfaces,
  request snapshot, and displayed run as one state transition.
- Preview and persisted-run results are mutually exclusive. A newly loaded or
  ingested run cannot silently shadow a later preview, and preview state cannot
  leak into a stored run.
- A 404, 422, network error, stale response, or incoherent response leaves the
  previously selected run and its rendered results intact.
- Run-scoped evidence, PnL, signal, and interval cards are keyed by selected run
  id and remount when a different stored run is loaded.
- Request signatures canonicalize datetime values before comparison, so a
  restored custom range is not marked stale merely because the form displays a
  local datetime while the API stores UTC.
- Loaded custom bounds keep the exact canonical UTC values for signatures and
  subsequent preview/run payloads until the corresponding date input is edited.
  Local `datetime-local` presentation therefore cannot shift a DST-fold
  instant or truncate persisted microseconds behind a fresh-state label.

## Retained interval-coverage contract

- `analysis_version: wallet_history_readiness_v0.22.7` continues to expose
  `bounded_interval_coverage` under the unchanged
  `wallet_multi_run_interval_coverage_v1` contract.
- The request still requires one explicit target run and 2-50 distinct run ids
  for the same wallet identity and data mode.
- Every selected run is classified independently in each coverage layer as
  `included`, `excluded`, or `not_requested`, with its recorded evidence state
  and rejection reason preserved.
- Accepted intervals use exact half-open UTC semantics: `[start, end)`.
- Durations are calculated with integer microseconds and serialized as
  canonical decimal strings. No floating-point, browser safe-integer, or
  whole-second rounding can hide a one-microsecond gap.
- A deterministic boundary sweep reports accepted intervals, their union,
  adjacency, overlap segments and depth, and internal gap segments.
- Time before the earliest eligible start and at or after the latest eligible
  end remains `unknown`.

## Strict evidence revalidation

Coverage is not derived from stored start/end fields alone. History readiness
first revalidates every selected run's persisted stream and page evidence:

- low-level transaction coverage accepts only one coherent bounded
  `transactions` stream in validated `complete` state;
- provider-display coverage accepts only one coherent bounded `account_events`
  stream in validated `provider_stream_complete` state;
- stream contract, provider, scope, query filters, sort order, page sequence,
  cursors, counts, digests, bounds, completion reason, errors, and run scope must
  satisfy the existing fail-closed page-evidence validators;
- missing, ambiguous, malformed, incomplete, preview-only, legacy, or otherwise
  ineligible evidence is excluded rather than repaired or inferred;
- a surface that was not requested is reported separately as `not_requested`
  and is never silently counted as an excluded or covered interval.

## Two separate coverage layers

The contract contains two layers that are never combined:

1. `low_level_transactions` measures validated low-level transaction-query
   intervals.
2. `provider_display_events` measures validated TonAPI account-event display
   intervals.

`cross_stream_union_applied` is always false. A gap in one layer cannot be
filled by evidence from the other layer, and overlap between the layers has no
coverage meaning. TonAPI event actions remain mutable, display-only provider
interpretations; even contiguous `provider_display_events` coverage is not
authoritative transfer, swap, or activity history.

## Interval semantics

For each layer, the response exposes:

- accepted per-run intervals and the normalized union;
- a selected span from the earliest eligible start to the latest eligible end;
- exact covered, gap, overlap, and span durations as canonical decimal
  microsecond strings;
- overlap segments with contributing run ids and coverage depth;
- internal gap segments with the eligible run ids on each side;
- included, excluded, and not-requested run ids plus per-run evidence reasons;
- `contiguous_selected_span`, `gapped_selected_span`, or
  `no_validated_intervals` state.

Touching half-open intervals are adjacent and form one contiguous union.
Overlapping intervals contribute coverage only once to the union, while their
overlap duration and maximum depth remain visible. Gaps are reported only
inside the earliest-to-latest eligible span; the contract makes no statement
about time outside it.

## Retained catalog, loader, and interval UI

The wallet workspace retains the recent catalog inside the stored-run loader,
with independent loading, refresh, retry, empty, truncated, expanded, current,
opening, and unsafe-id states. A successful full read restores the saved
controls and makes that run current; a failed read reports its own error without
hiding or replacing the previous run. When the id changes, run-scoped cards
remount against the new target. The selected-run history-readiness card still
accepts the remaining run ids for a total of 2-50 distinct runs and keeps
transaction and provider-display interval summaries separate.

## Migration and compatibility

v0.23.0 adds no database migration. Alembic head remains
`20260710_0005`. The v0.22.6 provider event/action observation identity
contract `tonapi_event_action_obs_v1`, transaction identity, and persisted
acquisition evidence remain unchanged. Trace previews are not stored. Backend
`VERSION=0.2.1` remains the independent API-version field;
`wallet_history_readiness_v0.22.7` and
`wallet_multi_run_interval_coverage_v1` are unchanged.

Legacy or malformed stream evidence is not synthesized into interval coverage.
It is represented through explicit per-layer exclusion or not-requested state.

## Explicitly unchanged

- No transaction or event rows are merged across runs.
- No trace response, summary, pending/finalized state, message, or semantic row
  is persisted.
- No automatic provider request, polling, account-trace discovery, retry, or
  ingestion traversal is introduced.
- No trace-derived transfer, swap, jetton-asset, counterparty, or activity
  identity is created.
- No cross-run or semantic deduplication is applied.
- No complete pre-run, global, or full wallet history is established.
- No acquisition cost basis or PnL input is created.
- Provider-display event actions remain non-authoritative.
- `full_pre_run_history_established`, `complete_wallet_history_established`,
  `is_global_history_coverage`, `is_authoritative_activity_coverage`,
  `activity_rows_merged`, `deduplication_applied`, `is_cost_basis`,
  `eligible_for_cost_basis`, and `used_by_pnl` remain false.
- Backend `VERSION=0.2.1` remains the API-version field; `v0.23.0 TRACE EVIDENCE
  PREVIEW` is the product label.

## Verification

```bash
cd backend
.venv/bin/python -m pytest -q

cd ../frontend
npm test
npm run build
npm audit
```

The frontend test/build toolchain is Vitest 4 with Vite 8, and the checked-in
dependency graph reports zero `npm audit` vulnerabilities. Verification covers
the exact explicit trace endpoint, canonical paths, eligibility-before-provider
ordering, one provider GET, exact stored hash + LT + account matching, iterative
node/depth/message limits, malformed and emulated trace rejection, coherent
finalized/pending states, strict sanitized allowlists, 404/409/502 mapping,
credential redaction, no-store, database non-mutation, network-silent mock and
initial UI states, explicit inspection, abort/sequence handling, anchor/run
reset, and last-success preservation. Existing verification continues to cover
canonical `limit` values and rejection of duplicate or unknown query input,
exact six-field summaries, masked bounded wallet hints, decimal-string signed-
64-bit ids, newest-first ordering and truncation, one projected SELECT,
provider-free and mutation-free reads, no-store behavior, the collapsed three-
of-eight UI, refresh/retry preservation, stale-request suppression, and unsafe-
id disabling. It also continues to cover the full-run frontend
safe-integer gate, 200/404/422 behavior, exact persisted timestamp restoration,
atomic state replacement, failed-load preservation, run-card remounting,
strict stream/page revalidation, 2-50 selected runs, exact interval math,
independent layers, and unchanged false merge/history/cost/PnL flags. No
credential may appear in logs, warnings, persisted evidence, errors, exports,
or UI copy.

Vite 8 and the React plugin require Node.js `^20.19.0 || >=22.12.0`; npm 10 or
newer is required. These prerequisites are declared in `frontend/package.json`
instead of relying on an implicit local toolchain.
