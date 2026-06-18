# TON Wallet Intelligence Dashboard - v0.11.7 BALANCES Promotion Checklist

Operational checklist for promoting the wallet activity guarded balance
coverage milestone branch.

## Promotion Gates

- Product label shows `v0.11.7 BALANCES` in the dashboard header and release
  readiness card.
- README, `RELEASE_NOTES.md`, and this promotion checklist all reference
  `v0.11.7 BALANCES`.
- `MockWalletActivityAdapter` remains the default executable adapter.
- `TonapiWalletActivityLiveAdapter` activates only when `DATA_MODE=real`,
  `WALLET_ACTIVITY_PROVIDER=tonapi`, and
  `WALLET_ACTIVITY_LIVE_ENABLED=true`.
- Guarded live TonAPI wallet activity fetches and persists only native TON
  balance and account jetton balance snapshots.
- Transfers, transactions, swaps, PnL, clustering, and ownership proof remain
  unavailable and visible.
- TonAPI without the live guard, TON provider, STON.fi, and Bitquery remain
  scaffold/limited coverage paths for wallet activity ingestion.
- `/api/providers/status` includes a `wallet_activity` status row and reports
  the guarded TonAPI live scope when enabled.
- Wallet Activity Ingestion Workspace still previews coverage, runs ingestion,
  refreshes a stored run, and renders normalized activity tables.
- Frontend build passes from `frontend/`:

```bash
npm run build
```

- Backend tests pass from `backend/`:

```bash
.venv/bin/python -m pytest -q
```

- TonAPI adapter tests pass from `backend/`:

```bash
.venv/bin/python -m pytest tests/test_tonapi_adapter.py -q
```

- Wallet activity adapter tests pass from `backend/`:

```bash
.venv/bin/python -m pytest tests/test_wallet_activity_adapter.py -q
```

- Wallet activity ingestion tests pass from `backend/`:

```bash
.venv/bin/python -m pytest tests/test_wallet_activity_ingestion.py -q
```

- Wallet activity provider status tests pass from `backend/`:

```bash
.venv/bin/python -m pytest tests/test_wallet_activity_provider_status.py -q
```

- Browser QA passes on desktop and mobile:
  - dashboard loads without console errors;
  - no horizontal page overflow;
  - Provider Status includes Wallet activity and dynamic provider counts;
  - default Wallet Activity Ingestion Workspace can preview, run, refresh, and
    display activity tables;
  - stale current product labels such as `v0.11.6 LIVE GUARDS`,
    `v0.11.5 SCAFFOLDS`, `v0.11.4 ADAPTERS`, `v0.11.3 INGEST UI`,
    `v0.11.2 MOCK INGEST`, `v0.11.1 SCHEMA`, `v0.11.0 PLAN`, `v0.10.7`, or
    `v0.2.1` do not appear as user-facing product labels.

## Version Contract

- `v0.11.7 BALANCES` is the product release label.
- Backend `VERSION=0.2.1` remains the backend API-version field.
- Do not change backend `VERSION` for this promotion unless the backend API
  contract changes.

## Data Contract

- `DATA_MODE=mock` remains the default.
- `WALLET_ACTIVITY_PROVIDER=mock` remains the default wallet ingestion adapter.
- `DATA_MODE=real` alone does not enable live wallet activity ingestion.
- Guarded live wallet activity requires `DATA_MODE=real`,
  `WALLET_ACTIVITY_PROVIDER=tonapi`, and
  `WALLET_ACTIVITY_LIVE_ENABLED=true`.
- `balances` can persist one native TON balance snapshot from TonAPI.
- `jettons` can persist account jetton balance snapshots from TonAPI.
- `WALLET_ACTIVITY_LIVE_JETTON_LIMIT` controls live TonAPI account jetton
  snapshots and is clamped to `1..500`.
- Guarded live mode may return `data_mode=real` and `source_status=live`, but
  it must only persist balance snapshot rows.
- Non-balance requested surfaces must remain in `unavailable_surfaces`.
- Legacy buyers, PnL, clustering, and exports remain mock-aware or deferred.
- Missing provider data must stay visible and must not be inferred.

## Promotion Commands

Run these only after the promotion gates are accepted:

```bash
git checkout main
git merge --no-ff v0.11.7-wallet-ingestion-tonapi-balance-coverage -m "Merge v0.11.7 wallet ingestion TonAPI balance coverage"
git tag v0.11.7
git push origin main
git push origin v0.11.7
```

## Rollback Notes

- If promotion is blocked before push, keep the branch local and patch it.
- If promotion is pushed and must be reverted, create a follow-up revert commit
  on `main` instead of rewriting published history.
- Do not delete or overwrite release tags without explicit maintainer approval.

## Next Branch

If the next track begins guarded TonAPI activity-history exploration:

```bash
git checkout -b v0.11.8-wallet-ingestion-tonapi-activity-history
```
