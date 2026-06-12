# TON Wallet Intelligence Dashboard - v0.10.6 RC Promotion Checklist

Operational checklist for promoting the current release candidate to a public
release.

## Promotion Gates

- Product label shows `v0.10.6 RC` in the dashboard header and release
  readiness card.
- README, `RELEASE_NOTES.md`, and this promotion checklist all reference
  `v0.10.6 RC`.
- Frontend build passes from `frontend/`:

```bash
npm run build
```

- Backend tests pass from `backend/`:

```bash
.venv/bin/python -m pytest -q
```

- Browser QA passes on desktop and mobile:
  - dashboard loads without console errors;
  - no horizontal page overflow;
  - Provider Status shows `Endpoint coverage` and `5/5 providers` when the
    backend is running;
  - stale product labels such as `v0.10.5 RC`, `v0.10.4 RC`, or `v0.2.1` do not
    appear as user-facing product labels.

## Version Contract

- `v0.10.6 RC` is the product/release-candidate label.
- Backend `VERSION=0.2.1` remains the backend API-version field.
- Do not change backend `VERSION` for this promotion unless the backend API
  contract changes.

## Data Contract

- `DATA_MODE=mock` remains the default.
- TonAPI wallet intelligence is jettons-only, not full wallet intelligence.
- STON.fi preview covers STON.fi pools only.
- Bitquery TON coverage remains provider-limited.
- Legacy buyers, PnL, clustering, and exports remain mock-aware or deferred.
- Missing provider data must stay visible and must not be inferred.

## Promotion Commands

Run these only after the promotion gates are accepted:

```bash
git checkout main
git merge --no-ff v0.10.6-rc-release-promotion-prep -m "Merge v0.10.6 RC release promotion prep"
git tag v0.10.6
git push origin main
git push origin v0.10.6
```

## Rollback Notes

- If promotion is blocked before push, keep the branch local and patch it.
- If promotion is pushed and must be reverted, create a follow-up revert commit
  on `main` instead of rewriting published history.
- Do not delete or overwrite release tags without explicit maintainer approval.

## Next Branch

If public release polish is needed after promotion:

```bash
git checkout -b v0.10.7-public-release-polish
```
