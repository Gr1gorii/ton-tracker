# TON Wallet Intelligence Dashboard — v0.22.7 INTERVAL COVERAGE Promotion Checklist

Operational gates for promoting deterministic selected-run interval coverage
while preserving strict acquisition evidence and non-authoritative provider
semantics.

## Version contract

- Product label is `v0.22.7 INTERVAL COVERAGE`.
- Backend `VERSION=0.2.1` remains the independent API-version field.
- `wallet_history_readiness_v0.22.7` is the diagnostic analysis contract.
- `wallet_multi_run_interval_coverage_v1` is the bounded multi-run coverage
  contract.
- `tonapi_event_action_obs_v1`, `ton_account_tx_v1`, and the v0.22.5
  acquisition page contracts remain unchanged.

## Schema and migration gates

- v0.22.7 adds no database migration.
- Alembic head remains `20260710_0005`.
- Fresh, exact legacy, and versioned databases follow the existing baseline
  through revisions 0002-0005 without `create_all()` repair.
- Existing run, activity, identity, acquisition-stream, and acquisition-page
  rows are not rewritten for interval coverage.
- No synthetic interval, cursor, page, or completion evidence is persisted for
  legacy runs.
- Existing uniqueness, foreign-key cascade, retry, integrity, and unsupported-
  downgrade behavior remains intact.

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
npm run build
```

Run repository hygiene checks before staging:

```bash
git diff --check
git status --short
```

Do not insert a test total into release documents. Record the actual command
results in promotion evidence at execution time.

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

- Dashboard label reads `v0.22.7 INTERVAL COVERAGE` on desktop and mobile.
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
git checkout main
git merge --no-ff codex/v0.22.7-interval-coverage
git tag -a v0.22.7 -m "v0.22.7 INTERVAL COVERAGE"
git push origin main
git push origin v0.22.7
```

## Rollback

- Before push, patch the release branch and rerun all gates.
- After push, use a follow-up revert commit; do not rewrite published history.
- v0.22.7 has no schema migration. Reverting its code removes the computed
  interval view without a database downgrade or data rewrite.
- The existing revision 0005 backup/restore policy remains applicable only to
  older schema changes.
