# TON Wallet Intelligence Dashboard - v0.11.5 SCAFFOLDS

Wallet activity provider scaffold handoff for the current wallet intelligence
workspace.

## Release Scope

- Dark matrix-style TON wallet intelligence dashboard.
- Wallet Activity Ingestion Workspace remains the user-facing workflow for
  coverage preview, mock ingestion runs, refresh, evidence, warnings, and
  normalized activity tables.
- `backend/adapters/wallet_activity.py` now includes provider-specific scaffold
  adapters for TonAPI, TON provider, STON.fi, and Bitquery.
- `WALLET_ACTIVITY_PROVIDER=mock` remains the default. The deterministic mock
  adapter still returns the normalized mock rows.
- Explicit `WALLET_ACTIVITY_PROVIDER=tonapi`, `ton_provider`, `stonfi`, or
  `bitquery` activates scaffold-only behavior in `DATA_MODE=real`.
- Scaffold adapters return limited/unavailable provider evidence, warnings, and
  unavailable surfaces. They do not fetch or persist real provider rows.
- `/api/providers/status` now includes a `wallet_activity` row that reports the
  selected adapter and whether it is mock, scaffold-limited, unavailable, or
  misconfigured.
- Provider status UI now counts provider rows dynamically and can display the
  wallet activity adapter row.
- Version contract remains: backend `VERSION=0.2.1` is the API-version field;
  `v0.11.5 SCAFFOLDS` is the product release label.

## Current Data Contract

- Product label: `v0.11.5 SCAFFOLDS`.
- Backend API `VERSION` remains `0.2.1`.
- `DATA_MODE=mock` remains the default.
- Default wallet activity ingestion still returns `data_mode=mock` and
  `source_status=mock`.
- `DATA_MODE=real` alone does not activate real wallet activity ingestion.
- Provider-specific scaffolds require explicit `WALLET_ACTIVITY_PROVIDER`.
- Scaffold responses may use `data_mode=real` and `source_status=limited` or
  `unavailable`, but normalized row counts remain zero.
- No real provider calls are made by `/api/wallets/ingest/*` in this release.
- Legacy buyers, PnL, clustering, and exports remain mock-aware or deferred.
- Missing provider data must stay visible and must not be inferred.

## Verification Snapshot

Use this checklist before promoting the provider scaffold branch:

- `npm run build` from `frontend/`.
- `.venv/bin/python -m pytest -q` from `backend/`.
- `.venv/bin/python -m pytest tests/test_wallet_activity_adapter.py -q` from
  `backend/`.
- `.venv/bin/python -m pytest tests/test_wallet_activity_ingestion.py -q` from
  `backend/`.
- `.venv/bin/python -m pytest tests/test_wallet_activity_provider_status.py -q`
  from `backend/`.
- Browser QA on desktop and mobile widths.
- Confirm UI shows `RELEASE v0.11.5 SCAFFOLDS`.
- Confirm Provider Status includes Wallet activity and shows dynamic provider
  counts.
- Confirm default wallet ingestion still previews, runs, refreshes, and renders
  mock-normalized activity tables.
- Confirm explicit scaffold mode shows limited/unavailable evidence and no real
  wallet activity rows.
- Confirm no user-facing UI copy shows stale current product labels such as
  `v0.11.4 ADAPTERS`, `v0.11.3 INGEST UI`, `v0.11.2 MOCK INGEST`,
  `v0.11.1 SCHEMA`, `v0.11.0 PLAN`, `v0.10.7`, or `v0.2.1`.
- Confirm horizontal page overflow is absent on desktop/mobile.
- Confirm browser console has no runtime errors during initial dashboard load
  and after preview/run/refresh interactions.

## Known Limitations

- Full real wallet activity analysis is not implemented yet.
- Provider-specific scaffold adapters do not fetch live transfers,
  transactions, swaps, balances, or jetton activity.
- Mock ingestion runs and scaffold coverage are not wired into legacy PnL,
  clustering, or exports.
- TonAPI wallet intelligence preview remains jettons-only.
- STON.fi remains a pool/swap-scope provider, not complete TON DeFi coverage.
- Bitquery TON trade coverage remains schema/provider limited.
- Export endpoints rerun analysis instead of exporting a specific stored run id.

## Recommended Next Step

Promote this scaffold branch after the checklist is accepted. The next logical
track is the first guarded live-provider implementation:

```bash
git checkout -b v0.11.6-wallet-ingestion-live-provider-guards
```
