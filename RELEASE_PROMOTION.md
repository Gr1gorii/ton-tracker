# TON Wallet Intelligence Dashboard — v0.22.4 PAGINATION EVIDENCE Promotion Checklist

Operational gates for promoting bounded low-level TonAPI transaction
pagination and its persisted acquisition evidence.

## Version contract

- Product label is `v0.22.4 PAGINATION EVIDENCE`.
- Backend `VERSION=0.2.1` remains the independent API-version field.
- `wallet_history_readiness_v0.22.4` is the diagnostic analysis contract.
- Historical v0.22.3 transaction-identity/backfill references remain valid and
  must not be relabeled as pagination work.

## Schema gates

- Alembic head is `20260710_0004`.
- Fresh databases create the baseline plus revisions 0002, 0003, and 0004.
- Exact unversioned v0.22.0 databases preserve every existing domain row and
  receive zero fabricated acquisition stream/page rows.
- Existing versioned databases upgrade without `create_all()` repair.
- Correct empty fragments from interrupted SQLite DDL are accepted; malformed
  tables, indexes, foreign-key options, partial ordering, or unexpected rows
  fail closed before further DDL.
- Stream identity is unique by run/provider/stream key.
- Page identity is unique by stream/page index.
- Deleting a run cascades through acquisition streams and pages.
- Runtime SQLite connections report `PRAGMA foreign_keys=1`; orphan stream/page
  inserts are rejected by the same engine factory used by the application.
- Downgrade from revision 0004 is rejected with backup-restore guidance.

## Acquisition contract gates

- Every request resolves one frozen half-open UTC interval `[start, end)`.
- Rolling windows use one captured request time; custom bounds normalize to UTC
  and cannot end in the future.
- Only guarded real/live TonAPI low-level `transactions` ingestion paginates.
- `WALLET_ACTIVITY_LIVE_TX_LIMIT` is the page size (`1..1000`).
- `WALLET_ACTIVITY_LIVE_TX_MAX_PAGES` is the page cap (`1..100`, default `10`).
- Every next request uses the prior page's minimum LT as `before_lt`.
- Provider pages and the aggregate chain are strictly descending by LT.
- A page cannot contain more rows than requested; hashes, timestamps, and fee
  integers reject bool/float/non-finite/oversized or noncanonical values.
- Accepted rows are limited to `[start, end)` and retain the v0.22.3 strict
  transaction identity contract.
- Preview fetches one page, reports `preview_only`, and persists nothing.
- Ingest persists aggregate stream and individual page evidence.
- Completion occurs only on a terminal empty provider page or verified ordered
  crossing below the requested start.
- Page cap, provider failure, malformed protocol data, conflicting duplicate,
  missing bounded timestamp, or stalled/non-descending cursor is incomplete.
- Partial acquisition remains visible in `incomplete_surfaces`; successful
  unrelated surfaces do not hide it.

## Data-honesty gates

- Within-run duplicate suppression is not described as cross-run
  deduplication.
- Transfers and swaps remain one-page, event-derived provider views. TonAPI
  high-level actions are not treated as authoritative transaction logic or
  proof of full DEX history.
- Jettons and native TON balances remain point-in-time snapshots without a
  pagination-completeness contract.
- No run stitching, full wallet-history proof, cost basis, or PnL change is
  claimed.
- History readiness continues to return `history_complete: false`,
  `deduplication_applied: false`, `is_cost_basis: false`,
  `eligible_for_cost_basis: false`, and `used_by_pnl: false`.
- Persisted query and error evidence contains no authorization header, API key,
  raw credential, or credential-bearing URL.
- Mock remains the default executable mode; live calls still require all three
  explicit guard settings.

## Automated verification

Run from `backend/`:

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m pytest -q tests/test_database_migrations.py
.venv/bin/python -m pytest -q tests/test_wallet_acquisition_bounds.py
.venv/bin/python -m pytest -q tests/test_tonapi_adapter.py
.venv/bin/python -m pytest -q tests/test_wallet_activity_ingestion.py
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

## Live verification

Use a valid network-matching wallet and the configured server-side TonAPI key
without printing it. Choose a small transaction page size so at least two pages
are exercised when provider history permits.

Verify:

- request and response cursors strictly descend;
- page indexes are contiguous and unique;
- response digests and LT/time extrema are present for successful pages;
- readback returns the same frozen bounds, stream outcome, and page evidence;
- an intentionally low page cap produces `incomplete/page_cap_reached`;
- preview returns one page with `preview_only`;
- provider/protocol failures remain visible and sanitized;
- existing transaction identities still match network/account/LT/hash source
  fields;
- no pagination evidence is invented for other surfaces or legacy runs;
- PnL and history-completeness flags do not change.

## UI and documentation gates

- Dashboard label reads `v0.22.4 PAGINATION EVIDENCE` on desktop and mobile.
- Transaction evidence states whether pagination is complete, incomplete,
  error, preview-only, or unavailable without implying full wallet history.
- No horizontal overflow or console error is introduced.
- README, release notes, ingestion plan, and this checklist describe the same
  narrow low-level transaction scope.
- `PUBLIC_RELEASE.md` remains the explicitly labeled v0.10.7 stable-baseline
  handoff and is not rewritten as the current development release.

## Promotion commands

After every gate passes:

```bash
git checkout main
git merge --no-ff codex/v0.22.4-pagination-evidence
git tag v0.22.4
git push origin main
git push origin v0.22.4
```

## Rollback

- Before push, patch the release branch and rerun all gates.
- After push, use a follow-up revert commit; do not rewrite published history.
- Restore a verified pre-v0.22.4 database backup when schema rollback is
  required. Do not run a destructive downgrade.
