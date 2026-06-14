# TON Wallet Intelligence Dashboard - v0.11.5 SCAFFOLDS Promotion Checklist

Operational checklist for promoting the wallet activity provider scaffolds
milestone branch.

## Promotion Gates

- Product label shows `v0.11.5 SCAFFOLDS` in the dashboard header and release
  readiness card.
- README, `RELEASE_NOTES.md`, and this promotion checklist all reference
  `v0.11.5 SCAFFOLDS`.
- `backend/adapters/wallet_activity.py` includes TonAPI, TON provider,
  STON.fi, and Bitquery scaffold adapters behind `WALLET_ACTIVITY_PROVIDER`.
- `MockWalletActivityAdapter` remains the default executable adapter.
- `/api/providers/status` includes a `wallet_activity` status row.
- Wallet Activity Ingestion Workspace still previews coverage, runs mock
  ingestion, refreshes a stored run, and renders normalized activity tables.
- Explicit scaffold mode returns limited/unavailable evidence and zero
  normalized rows.
- Frontend build passes from `frontend/`:

```bash
npm run build
```

- Backend tests pass from `backend/`:

```bash
.venv/bin/python -m pytest -q
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
  - stale current product labels such as `v0.11.4 ADAPTERS`,
    `v0.11.3 INGEST UI`, `v0.11.2 MOCK INGEST`, `v0.11.1 SCHEMA`,
    `v0.11.0 PLAN`, `v0.10.7`, or `v0.2.1` do not appear as user-facing
    product labels.

## Version Contract

- `v0.11.5 SCAFFOLDS` is the product release label.
- Backend `VERSION=0.2.1` remains the backend API-version field.
- Do not change backend `VERSION` for this promotion unless the backend API
  contract changes.

## Data Contract

- `DATA_MODE=mock` remains the default.
- `WALLET_ACTIVITY_PROVIDER=mock` remains the default wallet ingestion adapter.
- `DATA_MODE=real` alone does not enable real wallet activity ingestion.
- `WALLET_ACTIVITY_PROVIDER=tonapi`, `ton_provider`, `stonfi`, or `bitquery`
  activates scaffold-only metadata in `DATA_MODE=real`.
- Scaffold mode may return `data_mode=real` and `source_status=limited` or
  `unavailable`, but it must not fetch or persist real provider rows.
- No real provider calls are made by `/api/wallets/ingest/*`.
- Legacy buyers, PnL, clustering, and exports remain mock-aware or deferred.
- Missing provider data must stay visible and must not be inferred.

## Promotion Commands

Run these only after the promotion gates are accepted:

```bash
git checkout main
git merge --no-ff v0.11.5-wallet-ingestion-provider-scaffolds -m "Merge v0.11.5 wallet ingestion provider scaffolds"
git tag v0.11.5
git push origin main
git push origin v0.11.5
```

## Rollback Notes

- If promotion is blocked before push, keep the branch local and patch it.
- If promotion is pushed and must be reverted, create a follow-up revert commit
  on `main` instead of rewriting published history.
- Do not delete or overwrite release tags without explicit maintainer approval.

## Next Branch

If the next track begins guarded live-provider implementation:

```bash
git checkout -b v0.11.6-wallet-ingestion-live-provider-guards
```
