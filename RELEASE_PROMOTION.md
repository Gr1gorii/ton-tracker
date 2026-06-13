# TON Wallet Intelligence Dashboard - v0.11.3 INGEST UI Promotion Checklist

Operational checklist for promoting the wallet activity ingestion UI milestone
branch.

## Promotion Gates

- Product label shows `v0.11.3 INGEST UI` in the dashboard header and release
  readiness card.
- README, `RELEASE_NOTES.md`, and this promotion checklist all reference
  `v0.11.3 INGEST UI`.
- Wallet Activity Ingestion Workspace is visible in the dashboard and command
  center.
- Wallet ingestion UI can preview coverage, run mock ingestion, refresh a
  stored run, and render normalized activity tables.
- Frontend build passes from `frontend/`:

```bash
npm run build
```

- Backend tests pass from `backend/`:

```bash
.venv/bin/python -m pytest -q
```

- Wallet activity ingestion tests pass from `backend/`:

```bash
.venv/bin/python -m pytest tests/test_wallet_activity_ingestion.py -q
```

- Browser QA passes on desktop and mobile:
  - dashboard loads without console errors;
  - no horizontal page overflow;
  - command center includes `Wallet ingestion`;
  - Wallet Activity Ingestion Workspace can preview, run, refresh, and display
    activity tables;
  - Provider Status still shows `Endpoint coverage` and `5/5 providers` when
    the backend is running;
  - stale product labels such as `v0.11.2 MOCK INGEST`, `v0.11.1 SCHEMA`,
    `v0.11.0 PLAN`, `v0.10.7`, `v0.10.6 RC`, `v0.10.5 RC`, `v0.10.4 RC`, or
    `v0.2.1` do not appear as user-facing product labels.

## Version Contract

- `v0.11.3 INGEST UI` is the product release label.
- Backend `VERSION=0.2.1` remains the backend API-version field.
- Do not change backend `VERSION` for this promotion unless the backend API
  contract changes.

## Data Contract

- `DATA_MODE=mock` remains the default.
- Wallet activity ingestion endpoints use deterministic mock-normalized rows.
- Wallet activity ingestion returns `data_mode=mock` and `source_status=mock`.
- No real provider calls are made by `/api/wallets/ingest/*`.
- The UI must keep mock-normalized ingestion visually separate from real
  wallet analytics.
- TonAPI wallet intelligence is jettons-only, not full wallet intelligence.
- STON.fi preview covers STON.fi pools only.
- Bitquery TON coverage remains provider-limited.
- Legacy buyers, PnL, clustering, and exports remain mock-aware or deferred.
- Mock ingestion runs are not wired into PnL, clustering, or exports yet.
- Missing provider data must stay visible and must not be inferred.

## Promotion Commands

Run these only after the promotion gates are accepted:

```bash
git checkout main
git merge --no-ff v0.11.3-wallet-ingestion-ui-workspace -m "Merge v0.11.3 wallet ingestion UI workspace"
git tag v0.11.3
git push origin main
git push origin v0.11.3
```

## Rollback Notes

- If promotion is blocked before push, keep the branch local and patch it.
- If promotion is pushed and must be reverted, create a follow-up revert commit
  on `main` instead of rewriting published history.
- Do not delete or overwrite release tags without explicit maintainer approval.

## Next Branch

If the next track begins wallet ingestion adapter interface scaffolding:

```bash
git checkout -b v0.11.4-wallet-ingestion-adapter-interfaces
```
