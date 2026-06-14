# TON Wallet Intelligence Dashboard - v0.11.6 LIVE GUARDS

Wallet activity live-provider guard handoff for the current wallet intelligence
workspace.

## Release Scope

- Dark matrix-style TON wallet intelligence dashboard.
- Wallet Activity Ingestion Workspace remains the user-facing workflow for
  coverage preview, ingestion runs, refresh, evidence, warnings, unavailable
  surfaces, and normalized activity tables.
- `MockWalletActivityAdapter` remains the default executable adapter.
- `backend/adapters/wallet_activity.py` now includes
  `TonapiWalletActivityLiveAdapter`, guarded by all three settings:
  `DATA_MODE=real`, `WALLET_ACTIVITY_PROVIDER=tonapi`, and
  `WALLET_ACTIVITY_LIVE_ENABLED=true`.
- The guarded TonAPI live path fetches account jetton balance snapshots only.
- Transfers, transactions, swaps, native TON balance, PnL, clustering, and
  ownership proof remain unavailable in this live path.
- TonAPI without the live guard, TON provider, STON.fi, and Bitquery remain
  scaffold/limited coverage paths for wallet activity ingestion.
- `/api/providers/status` reports when guarded TonAPI live wallet activity is
  enabled and explains the jetton-only scope.
- Version contract remains: backend `VERSION=0.2.1` is the API-version field;
  `v0.11.6 LIVE GUARDS` is the product release label.

## Current Data Contract

- Product label: `v0.11.6 LIVE GUARDS`.
- Backend API `VERSION` remains `0.2.1`.
- `DATA_MODE=mock` remains the default.
- `WALLET_ACTIVITY_PROVIDER=mock` remains the default wallet ingestion adapter.
- `DATA_MODE=real` alone does not activate live wallet activity ingestion.
- Guarded live ingestion requires:
  - `DATA_MODE=real`
  - `WALLET_ACTIVITY_PROVIDER=tonapi`
  - `WALLET_ACTIVITY_LIVE_ENABLED=true`
- `WALLET_ACTIVITY_LIVE_JETTON_LIMIT` controls the TonAPI account jetton limit
  and is clamped to `1..500`.
- Guarded live responses use `data_mode=real`, `source_status=live`, provider
  `tonapi_wallet_activity_live`, and normalized balance rows only for requested
  `jettons`.
- Non-jetton requested surfaces remain listed in `unavailable_surfaces`.
- Missing provider data must stay visible and must not be inferred.

## Verification Snapshot

Use this checklist before promoting the live guard branch:

- `npm run build` from `frontend/`.
- `.venv/bin/python -m pytest -q` from `backend/`.
- `.venv/bin/python -m pytest tests/test_wallet_activity_adapter.py -q` from
  `backend/`.
- `.venv/bin/python -m pytest tests/test_wallet_activity_ingestion.py -q` from
  `backend/`.
- `.venv/bin/python -m pytest tests/test_wallet_activity_provider_status.py -q`
  from `backend/`.
- `.venv/bin/python -m pytest tests/test_providers_config.py -q` from
  `backend/`.
- Browser QA on desktop and mobile widths.
- Confirm UI shows `RELEASE v0.11.6 LIVE GUARDS`.
- Confirm Provider Status includes Wallet activity and shows dynamic provider
  counts.
- Confirm default wallet ingestion still previews, runs, refreshes, and renders
  mock-normalized activity tables.
- Confirm guarded TonAPI live mode can persist only jetton balance snapshots in
  tests.
- Confirm no user-facing UI copy shows stale current product labels such as
  `v0.11.5 SCAFFOLDS`, `v0.11.4 ADAPTERS`, `v0.11.3 INGEST UI`,
  `v0.11.2 MOCK INGEST`, `v0.11.1 SCHEMA`, `v0.11.0 PLAN`, `v0.10.7`, or
  `v0.2.1`.
- Confirm horizontal page overflow is absent on desktop/mobile.
- Confirm browser console has no runtime errors during initial dashboard load
  and after preview/run/refresh interactions.

## Known Limitations

- Full real wallet activity analysis is not implemented yet.
- Guarded TonAPI live mode does not fetch transfers, transactions, swaps,
  native TON balance, PnL inputs, clustering inputs, or ownership proof.
- Mock ingestion runs and live jetton snapshots are not wired into legacy PnL,
  clustering, or exports.
- TonAPI wallet intelligence preview remains jettons-only.
- STON.fi remains a pool/swap-scope provider, not complete TON DeFi coverage.
- Bitquery TON trade coverage remains schema/provider limited.
- Export endpoints rerun analysis instead of exporting a specific stored run id.

## Recommended Next Step

Promote this live guard branch after the checklist is accepted. The next
logical track is guarded balance coverage expansion:

```bash
git checkout -b v0.11.7-wallet-ingestion-tonapi-balance-coverage
```
