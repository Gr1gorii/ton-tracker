# TON Wallet Intelligence Dashboard — v0.22.9 RECENT RUN CATALOG Promotion Checklist

Operational gates for promoting privacy-bounded recent-run discovery and
read-only persisted-run loading while preserving strict acquisition evidence,
deterministic selected-run interval coverage, and non-authoritative provider
semantics.

## Version contract

- Product label is `v0.22.9 RECENT RUN CATALOG`.
- Backend `VERSION=0.2.1` remains the independent API-version field.
- `wallet_history_readiness_v0.22.7` is the diagnostic analysis contract.
- `wallet_multi_run_interval_coverage_v1` is the bounded multi-run coverage
  contract.
- `tonapi_event_action_obs_v1`, `ton_account_tx_v1`, and the v0.22.5
  acquisition page contracts remain unchanged.

## Schema and migration gates

- v0.22.9 adds no database migration.
- Alembic head remains `20260710_0005`.
- Fresh, exact legacy, and versioned databases follow the existing baseline
  through revisions 0002-0005 without `create_all()` repair.
- Existing run, activity, identity, acquisition-stream, and acquisition-page
  rows are not rewritten for interval coverage.
- No synthetic interval, cursor, page, or completion evidence is persisted for
  legacy runs.
- Existing uniqueness, foreign-key cascade, retry, integrity, and unsupported-
  downgrade behavior remains intact.

## Recent-run catalog gates

- `GET /api/wallets/ingest` coexists with the existing POST collection route
  and defaults to canonical `limit=8`.
- An explicit `limit` is one ASCII decimal integer from `1` through `50`.
  Leading zeros, signs, whitespace, decimals, booleans, empty values, duplicate
  parameters, unknown parameters, case aliases, and out-of-range values return
  422.
- The response has exactly `runs`, `limit`, and `truncated`. Every run has
  exactly `run_id`, `wallet_hint`, `time_window`, `created_at`, `status`, and
  `data_mode`.
- `run_id` is a canonical positive signed-64-bit decimal string and never a
  JSON number. Catalog and frontend validation accept values only through
  `9223372036854775807`.
- `wallet_hint` uses the first six and last four submitted-address characters
  separated by one ellipsis for values at least 16 characters, while shorter
  legacy values use `stored…run`; maximum response length is 11. The
  full address, canonical identity, custom bounds, requested surfaces,
  provider metadata, activity rows/counts, warnings, and messages are absent.
- New wallet submissions are bounded to 128 characters by both backend request
  validation and the browser input.
- Ordering is fixed to descending persisted run id. The endpoint returns only
  the newest page, reads at most `limit + 1`, and uses `truncated` instead of an
  offset, cursor, total count, filter, or client-selected sort.
- Catalog acquisition is exactly one projected SELECT from
  `wallet_ingestion_runs`. It does not query child activity tables, deserialize
  provider metadata, load settings, construct/call a provider, or perform DML,
  DDL, commit, or mutation.
- The server response and browser request both use `no-store`.

## Persisted-run read gates

- The workspace reuses `GET /api/wallets/ingest/{run_id}`; no parallel loader
  endpoint and no new run-creation path is introduced.
- Backend URL ids match `[1-9][0-9]*` and fit the positive signed-64-bit range
  `1..9223372036854775807`.
- An existing canonical id returns 200, a canonical missing id returns 404, and
  malformed, noncanonical, zero, negative, or out-of-range input returns 422.
- Readback returns exact persisted `custom_start`, `custom_end`, and `created_at`
  fields. Rolling windows have null custom bounds; custom windows have both
  saved bounds.
- The GET path performs no provider or ingestion-adapter construction/call and
  no insert, update, delete, commit, or other database mutation.
- The frontend trims surrounding form whitespace, then rejects noncanonical,
  nonpositive, and non-safe-integer input before issuing a request, even though
  the backend contract spans the wider signed-64-bit range.
- A coherent success atomically replaces wallet, window, exact custom bounds,
  requested surfaces, snapshot, and current run while clearing preview state.
- A 404, 422, transport failure, stale response, or incoherent response keeps
  the previously selected run and its results visible.
- Run-scoped evidence, PnL, signal, and interval cards remount when the selected
  run id changes; no result or error from the prior id survives the remount.
- Datetime request signatures are normalized to canonical UTC before stale-
  state comparison.
- Each loaded custom bound retains its exact canonical UTC value for signatures
  and preview/run payloads until its date field is edited; DST folds and
  persisted microseconds must round-trip unchanged.

## Selected-run request gates

- The request contains 2-50 distinct positive run ids.
- `target_run_id` is explicitly present in the selected set.
- All selected runs resolve to one canonical network-scoped run-wallet identity
  and one data mode, or satisfy the existing exact submitted-address legacy
  fallback.
- Duplicate ids, a missing target, too few or too many ids, mixed wallets, and
  mixed data modes fail before interval coverage is calculated.
- The target selects the UI/report focus only; it does not receive stronger
  interval eligibility.

## Strict evidence revalidation gates

- Recorded interval bounds are never accepted without revalidating the full
  persisted stream and page contract.
- Low-level transaction coverage admits only one coherent bounded
  `transactions` stream in validated `complete` state.
- Provider-display coverage admits only one coherent bounded `account_events`
  stream in validated `provider_stream_complete` state.
- Provider, stream key, contract, scope, filters, sort order, bounds, page
  ordering, request/response cursors, counts, hashes, terminal reason, errors,
  and run scope satisfy the existing fail-closed validators.
- Missing, ambiguous, malformed, preview-only, incomplete, error, and
  legacy-unavailable evidence is `excluded` with an explicit reason.
- A stream absent because its surface was not requested is classified
  `not_requested`, not covered and not silently converted to a generic
  exclusion.
- Excluded and not-requested runs never enter accepted intervals or unions.

## Interval math gates

- Every accepted interval uses exact UTC half-open semantics `[start, end)`.
- Durations use integer microseconds serialized as canonical decimal strings;
  floating-point timestamps, browser safe-integer coercion, and whole-second
  rounding are not used.
- A one-microsecond gap remains a one-microsecond gap.
- The deterministic boundary sweep produces accepted intervals, union
  intervals, overlap intervals, internal gap intervals, and selected span.
- Touching intervals are adjacent and form a contiguous union.
- Overlapping intervals count once in covered duration while overlap duration,
  contributing run ids, coverage depth, and maximum depth remain visible.
- Internal gaps include exact boundaries and eligible run ids on each side.
- Gaps are measured only inside the span from the earliest eligible start to
  the latest eligible end.
- Time before the earliest eligible start and at or after the latest eligible
  end remains `outside_selected_span_coverage: unknown`.
- No eligible intervals yields `no_validated_intervals`; otherwise the layer is
  `contiguous_selected_span` or `gapped_selected_span`.

## Never-mixed layer gates

- `low_level_transactions` and `provider_display_events` are calculated and
  reported independently.
- `cross_stream_union_applied` remains false.
- Neither layer can fill gaps, increase depth, or establish continuity for the
  other.
- Transaction/event cross-layer overlap has no coverage meaning.
- TonAPI account events and their actions remain mutable, display-only provider
  interpretations.
- Contiguous provider-display coverage is not authoritative transfer, swap,
  semantic activity, or complete wallet history.

## Data-honesty gates

- `full_pre_run_history_established`, `complete_wallet_history_established`,
  `is_global_history_coverage`, and
  `is_authoritative_activity_coverage` remain false.
- `activity_rows_merged`, `deduplication_applied`, `is_cost_basis`,
  `eligible_for_cost_basis`, and `used_by_pnl` remain false.
- Interval union and adjacency never imply activity-row merge or semantic
  deduplication.
- Existing identity conflicts, pagination blockers, incomplete surfaces, and
  provider-display limitations remain visible alongside interval coverage.
- Jettons and native TON balances remain point-in-time snapshots and are absent
  from both interval layers.
- Mock remains the default executable mode; live provider calls still require
  every explicit guard setting.
- Persisted evidence, logs, errors, warnings, exports, and UI copy contain no
  credential.

## Automated verification

Run from `backend/`:

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m pytest -q tests/test_wallet_interval_coverage.py
.venv/bin/python -m pytest -q tests/test_wallet_history_readiness.py
.venv/bin/python -m pytest -q tests/test_wallet_event_pagination.py
.venv/bin/python -m pytest -q tests/test_database_migrations.py
.venv/bin/python -m compileall -q .
```

Run from `frontend/`:

```bash
npm test
npm run build
npm audit
```

The frontend release toolchain is Vitest 4 with Vite 8. The checked-in
dependency graph must report zero `npm audit` vulnerabilities.
Node.js must satisfy `^20.19.0 || >=22.12.0`, with npm 10 or newer, as declared
in `frontend/package.json`.

Run repository hygiene checks before staging:

```bash
git diff --check
git status --short
```

Do not insert a test total into release documents. Record the actual command
results in promotion evidence at execution time.

## Focused recent-run catalog verification

- An empty database returns 200 with `runs: []`, `limit: 8`,
  `truncated: false`, and `Cache-Control: no-store`.
- Limits `1` and `50` succeed. Every malformed, noncanonical, duplicate,
  unknown, or out-of-range query case described above returns 422.
- Nine stored runs requested with `limit=8` return the newest eight in strict
  descending decimal-string id order and set `truncated: true`.
- Every item has the exact six-field allowlist, the full submitted wallet does
  not occur in the payload, and the hint is bounded to 11 characters.
- Repeated reads issue one SELECT each against `wallet_ingestion_runs`, never
  reference child activity tables, never load settings/build an adapter, and
  leave every wallet table count unchanged.
- The browser rejects responses with extra/missing fields, invalid dates,
  invalid or overflowing ids, long hints, duplicate/non-descending ids, a
  mismatched limit, or incoherent truncation.
- Catalog requests use their own abort controller and sequence guard. Stale or
  aborted responses cannot overwrite a newer refresh or interfere with
  preview, ingestion, full-run load, or run refresh.
- The UI requests eight rows, initially shows three, expands/collapses without
  refetching, preserves the last successful list on refresh failure, supports
  retry, and refreshes after a successful ingestion commit.
- Selecting a safe catalog id opens that run through the existing full stored-
  run GET. An unsafe JavaScript id remains visible but disabled, and a failed
  open preserves the previous current run.

## Focused persisted-run verification

- Existing and missing canonical ids return 200 and 404 respectively.
- Backend URL ids with zero, negatives, decimal aliases, leading-zero aliases,
  signs, whitespace, non-digits, or values above `9223372036854775807` return
  422 rather than resolving to another run or reaching the database as an
  invalid integer. The UI may trim surrounding form whitespace before sending
  the canonical decimal id.
- Repeated reads return identical payloads, including exact persisted
  `custom_start`, `custom_end`, and `created_at`, and produce no database DML.
- A stored-run read cannot construct or call the configured provider adapter.
- Frontend parsing issues no request for a noncanonical or unsafe id.
- Successful loading restores exact stored controls and shows the selected run;
  preview and run results never shadow one another.
- Failed and out-of-order loads preserve the prior/current run respectively.
- Loading another id remounts every run-scoped card, including selected-run
  interval coverage, and resets state belonging to the prior target.
- Equivalent local-form and UTC custom datetimes produce the same request
  signature and do not create an immediate stale marker.

## Focused interval verification

- Exact adjacent intervals produce one contiguous union and zero gap.
- Disjoint intervals expose the exact internal gap and left/right run ids.
- Nested, partial, and three-or-more-run overlaps expose correct segments,
  durations, depths, and maximum depth without double-counting union coverage.
- Microsecond boundary cases preserve exact integer durations.
- Unsorted selected ids and evidence rows produce deterministic sorted output.
- Missing, ambiguous, invalid, incomplete, preview-only, and legacy evidence is
  excluded with the correct source state and reason.
- Not-requested transaction and event streams remain separate from exclusions.
- Transaction and provider-display layers can report different included sets,
  unions, overlaps, gaps, and selected spans without cross-filling.
- The response schema fixes analysis and contract versions and all false safety
  flags.

## Guarded live verification

Use a valid network-matching wallet and the configured server-side provider key
without printing it. Select 2-50 stored runs, including one explicit target,
and verify:

- persisted transaction and event pages are strictly revalidated before their
  intervals can be included;
- incomplete or malformed evidence remains excluded even if recorded bounds
  look plausible;
- not-requested surfaces remain visibly distinct;
- the two layer cards never imply a combined union;
- provider-display event coverage is labeled display-only and non-authoritative;
- internal gaps, adjacency, overlaps, included runs, and excluded runs match the
  selected evidence;
- time outside each earliest/latest eligible span is labeled unknown;
- no activity merge, deduplication, global history, cost basis, or PnL claim is
  introduced.

## UI and documentation gates

- Dashboard label reads `v0.22.9 RECENT RUN CATALOG` on desktop and mobile.
- The recent-run catalog exposes only bounded hints and five other summary
  fields, initially renders three of eight rows, expands to all eight, and has
  accessible loading, empty, truncated, current, opening, refresh, retry,
  error, and unsafe-id states.
- Catalog refresh failure keeps the last successful list visible; stale
  responses and Strict Mode remounts do not replace newer state or interfere
  with the workspace request lifecycle.
- The stored-run loader accepts one positive safe integer, restores exact stored
  controls only on success, and leaves the previous run visible on failure.
- Loading a different run remounts run-scoped cards without console errors,
  focus loss, stale-state mislabeling, or horizontal overflow.
- The selected-run history-readiness card identifies the current run as target
  and accepts enough additional distinct ids for a total of 2-50 selected runs.
- The card separately renders low-level transaction and provider-display event
  interval coverage.
- Included, excluded, and not-requested runs are visible without treating any
  category as inferred coverage.
- Adjacency, overlaps, internal gaps, microsecond durations, and unknown
  outside-span time are described consistently with the API.
- UI copy never labels provider-display events as authoritative activity.
- No horizontal overflow or console error is introduced.
- README, release notes, ingestion plan, and this checklist describe the same
  contract, versions, migration head, and limitations.
- `PUBLIC_RELEASE.md` remains the explicitly labeled stable-baseline handoff and
  is not rewritten as the current development release.

## Promotion commands

After every gate passes:

```bash
release_branch="$(git branch --show-current)"
git checkout main
git merge --no-ff "$release_branch"
git tag -a v0.22.9 -m "v0.22.9 RECENT RUN CATALOG"
git push origin main
git push origin v0.22.9
```

## Rollback

- Before push, patch the release branch and rerun all gates.
- After push, use a follow-up revert commit; do not rewrite published history.
- v0.22.9 has no schema migration. Reverting its code removes the recent-run
  catalog without a database downgrade or data rewrite; the existing full-run
  loader, persisted runs, and interval diagnostics remain intact.
- The existing revision 0005 backup/restore policy remains applicable only to
  older schema changes.
