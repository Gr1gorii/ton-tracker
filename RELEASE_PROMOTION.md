# TON Wallet Intelligence Dashboard - v0.11.4 ADAPTERS Promotion Checklist

Operational checklist for promoting the wallet activity adapter interfaces
milestone branch.

## Promotion Gates

- Product label shows `v0.11.4 ADAPTERS` in the dashboard header and release
  readiness card.
- README, `RELEASE_NOTES.md`, and this promotion checklist all reference
  `v0.11.4 ADAPTERS`.
- Wallet activity preview/run orchestration uses the adapter contract in
  `backend/adapters/wallet_activity.py`.
- `MockWalletActivityAdapter` remains the only active adapter.
- Wallet Activity Ingestion Workspace still previews coverage, runs mock
  ingestion, refreshes a stored run, and renders normalized activity tables.
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

- Browser QA passes on desktop and mobile:
  - dashboard loads without console errors;
  - no horizontal page overflow;
  - Wallet Activity Ingestion Workspace can preview, run, refresh, and display
    activity tables;
  - stale product labels such as `v0.11.3 INGEST UI`, `v0.11.2 MOCK INGEST`,
    `v0.11.1 SCHEMA`, `v0.11.0 PLAN`, `v0.10.7`, `v0.10.6 RC`,
    `v0.10.5 RC`, `v0.10.4 RC`, or `v0.2.1` do not appear as user-facing
    product labels.

## Version Contract

- `v0.11.4 ADAPTERS` is the product release label.
- Backend `VERSION=0.2.1` remains the backend API-version field.
- Do not change backend `VERSION` for this promotion unless the backend API
  contract changes.

## Data Contract

- `DATA_MODE=mock` remains the default.
- Wallet activity ingestion endpoints use deterministic mock-normalized rows.
- Wallet activity ingestion returns `data_mode=mock` and `source_status=mock`.
- `DATA_MODE=real` does not enable real wallet activity ingestion yet.
- No real provider calls are made by `/api/wallets/ingest/*`.
- The adapter contract is a backend boundary only; it must not make mock data
  appear real.
- Legacy buyers, PnL, clustering, and exports remain mock-aware or deferred.
- Mock ingestion runs are not wired into PnL, clustering, or exports yet.
- Missing provider data must stay visible and must not be inferred.

## Promotion Commands

Run these only after the promotion gates are accepted:

```bash
git checkout main
git merge --no-ff v0.11.4-wallet-ingestion-adapter-interfaces -m "Merge v0.11.4 wallet ingestion adapter interfaces"
git tag v0.11.4
git push origin main
git push origin v0.11.4
```

## Rollback Notes

- If promotion is blocked before push, keep the branch local and patch it.
- If promotion is pushed and must be reverted, create a follow-up revert commit
  on `main` instead of rewriting published history.
- Do not delete or overwrite release tags without explicit maintainer approval.

## Next Branch

If the next track begins provider-specific wallet activity adapter scaffolds:

```bash
git checkout -b v0.11.5-wallet-ingestion-provider-scaffolds
```
