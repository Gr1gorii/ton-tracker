# TON Wallet Intelligence Dashboard — v0.22.9 RECENT RUN CATALOG

This release adds a privacy-bounded recent persisted-run catalog to the wallet
workspace. It discovers the newest stored runs through one projected read-only
query, then delegates selection to the existing full stored-run GET introduced
in v0.22.8. Discovery and loading never re-run ingestion or contact a provider.

## Release scope

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

## UI

The wallet workspace presents the recent catalog inside the stored-run loader,
with independent loading, refresh, retry, empty, truncated, expanded, current,
opening, and unsafe-id states. A successful full read restores the saved
controls and makes that run current; a failed read reports its own error without
hiding or replacing the previous run. When the id changes, run-scoped cards
remount against the new target. The selected-run history-readiness card still
accepts the remaining run ids for a total of 2-50 distinct runs and keeps
transaction and provider-display interval summaries separate.

## Migration and compatibility

v0.22.9 adds no database migration. Alembic head remains
`20260710_0005`. The v0.22.6 provider event/action observation identity
contract `tonapi_event_action_obs_v1`, transaction identity, and persisted
acquisition evidence remain unchanged. Backend `VERSION=0.2.1` remains the
independent API-version field.

Legacy or malformed stream evidence is not synthesized into interval coverage.
It is represented through explicit per-layer exclusion or not-requested state.

## Explicitly unchanged

- No transaction or event rows are merged across runs.
- No cross-run or semantic deduplication is applied.
- No complete pre-run, global, or full wallet history is established.
- No acquisition cost basis or PnL input is created.
- Provider-display event actions remain non-authoritative.
- `full_pre_run_history_established`, `complete_wallet_history_established`,
  `is_global_history_coverage`, `is_authoritative_activity_coverage`,
  `activity_rows_merged`, `deduplication_applied`, `is_cost_basis`,
  `eligible_for_cost_basis`, and `used_by_pnl` remain false.
- Backend `VERSION=0.2.1` remains the API-version field; `v0.22.9 RECENT RUN
  CATALOG` is the product label.

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
canonical `limit` values and rejection of duplicate or unknown query input,
exact six-field summaries, masked bounded wallet hints, decimal-string signed-
64-bit ids, newest-first ordering and truncation, one projected SELECT,
provider-free and mutation-free reads, no-store behavior, the collapsed three-
of-eight UI, refresh/retry preservation, stale-request suppression, and unsafe-
id disabling. Existing verification continues to cover the full-run frontend
safe-integer gate, 200/404/422 behavior, exact persisted timestamp restoration,
atomic state replacement, failed-load preservation, run-card remounting,
strict stream/page revalidation, 2-50 selected runs, exact interval math,
independent layers, and unchanged false merge/history/cost/PnL flags. No
credential may appear in logs, warnings, persisted evidence, errors, exports,
or UI copy.

Vite 8 and the React plugin require Node.js `^20.19.0 || >=22.12.0`; npm 10 or
newer is required. These prerequisites are declared in `frontend/package.json`
instead of relying on an implicit local toolchain.
