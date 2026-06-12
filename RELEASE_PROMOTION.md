# TON Wallet Intelligence Dashboard - v0.11.1 SCHEMA Promotion Checklist

Operational checklist for promoting the wallet activity schema scaffold
milestone branch.

## Promotion Gates

- Product label shows `v0.11.1 SCHEMA` in the dashboard header and release
  readiness card.
- README, `RELEASE_NOTES.md`, and this promotion checklist all reference
  `v0.11.1 SCHEMA`.
- Wallet activity SQLAlchemy models and Pydantic contracts are covered by
  `tests/test_wallet_activity_schema.py`.
- Frontend build passes from `frontend/`:

```bash
npm run build
```

- Backend tests pass from `backend/`:

```bash
.venv/bin/python -m pytest -q
```

- Wallet activity schema tests pass from `backend/`:

```bash
.venv/bin/python -m pytest tests/test_wallet_activity_schema.py -q
```

- Browser QA passes on desktop and mobile:
  - dashboard loads without console errors;
  - no horizontal page overflow;
  - Provider Status shows `Endpoint coverage` and `5/5 providers` when the
    backend is running;
  - stale product labels such as `v0.11.0 PLAN`, `v0.10.7`, `v0.10.6 RC`,
    `v0.10.5 RC`, `v0.10.4 RC`, or `v0.2.1` do not appear as user-facing
    product labels.

## Version Contract

- `v0.11.1 SCHEMA` is the product schema scaffold label.
- Backend `VERSION=0.2.1` remains the backend API-version field.
- Do not change backend `VERSION` for this promotion unless the backend API
  contract changes.

## Data Contract

- `DATA_MODE=mock` remains the default.
- TonAPI wallet intelligence is jettons-only, not full wallet intelligence.
- STON.fi preview covers STON.fi pools only.
- Bitquery TON coverage remains provider-limited.
- Legacy buyers, PnL, clustering, and exports remain mock-aware or deferred.
- Full wallet transfers, transaction history, DEX swaps, and current TON
  balances have schema scaffolds only.
- No provider ingestion or analytics wiring is implemented yet.
- Missing provider data must stay visible and must not be inferred.

## Promotion Commands

Run these only after the promotion gates are accepted:

```bash
git checkout main
git merge --no-ff v0.11.1-wallet-activity-schema-scaffold -m "Merge v0.11.1 wallet activity schema scaffold"
git tag v0.11.1
git push origin main
git push origin v0.11.1
```

## Rollback Notes

- If promotion is blocked before push, keep the branch local and patch it.
- If promotion is pushed and must be reverted, create a follow-up revert commit
  on `main` instead of rewriting published history.
- Do not delete or overwrite release tags without explicit maintainer approval.

## Next Branch

If the next track begins mock-normalized wallet activity ingestion:

```bash
git checkout -b v0.11.2-mock-wallet-activity-ingestion
```
