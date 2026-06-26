# TON Wallet Intelligence Dashboard - v0.11.8 HISTORY

Wallet activity guarded transaction-history coverage handoff for the current
wallet intelligence workspace. This milestone adds an ordered TonAPI account
transaction-history timeline to the existing guarded balance snapshots.

## Release Scope

- Dark matrix-style TON wallet intelligence dashboard.
- Wallet Activity Ingestion Workspace remains the user-facing workflow for
  coverage preview, ingestion runs, refresh, evidence, warnings, unavailable
  surfaces, and normalized activity tables.
- `MockWalletActivityAdapter` remains the default executable adapter.
- `TonapiWalletActivityLiveAdapter` still activates only when all three guards
  are enabled: `DATA_MODE=real`, `WALLET_ACTIVITY_PROVIDER=tonapi`, and
  `WALLET_ACTIVITY_LIVE_ENABLED=true`.
- The guarded TonAPI live path now fetches native TON balance snapshots for
  requested `balances`, account jetton balance snapshots for requested
  `jettons`, and an ordered account transaction-history timeline for requested
  `transactions`.
- Transfers, DEX swaps, PnL, clustering, and ownership proof remain unavailable
  in this live path.
- TonAPI without the live guard, TON provider, STON.fi, and Bitquery remain
  scaffold/limited coverage paths for wallet activity ingestion.
- `/api/providers/status` reports guarded TonAPI live scope as native TON
  balance, account jetton balance snapshots, and account transaction history.
- Version contract remains: backend `VERSION=0.2.1` is the API-version field;
  `v0.11.8 HISTORY` is the product release label.

## Current Data Contract

- Product label: `v0.11.8 HISTORY`.
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
- `WALLET_ACTIVITY_LIVE_TX_LIMIT` controls the TonAPI transaction-history page
  size and is clamped to `1..1000`.
- Guarded live responses use `data_mode=real`, provider
  `tonapi_wallet_activity_live`, and source-aware balance and transaction rows
  only for requested `balances`, `jettons`, and `transactions`.
- If one supported TonAPI surface fails and another succeeds, the run remains
  partial and the failed surface is listed in `unavailable_surfaces`.
- Unsupported requested surfaces remain listed in `unavailable_surfaces`.
- Missing provider data must stay visible and must not be inferred.

## Verification Snapshot

Use this checklist before promoting the balance coverage branch:

- `npm run build` from `frontend/`.
- `.venv/bin/python -m pytest -q` from `backend/`.
- `.venv/bin/python -m pytest tests/test_tonapi_adapter.py -q` from `backend/`.
- `.venv/bin/python -m pytest tests/test_wallet_activity_adapter.py -q` from
  `backend/`.
- `.venv/bin/python -m pytest tests/test_wallet_activity_ingestion.py -q` from
  `backend/`.
- `.venv/bin/python -m pytest tests/test_wallet_activity_provider_status.py -q`
  from `backend/`.
- Browser QA on desktop and mobile widths.
- Confirm UI shows `RELEASE v0.11.8 HISTORY`.
- Confirm Provider Status includes Wallet activity and shows dynamic provider
  counts.
- Confirm default wallet ingestion still previews, runs, refreshes, and renders
  mock-normalized activity tables.
- Confirm guarded TonAPI live mode can persist native TON balance snapshots,
  account jetton balance snapshots, and transaction-history rows in tests.
- Confirm no user-facing UI copy shows stale current product labels such as
  `v0.11.6 LIVE GUARDS`, `v0.11.5 SCAFFOLDS`, `v0.11.4 ADAPTERS`,
  `v0.11.3 INGEST UI`, `v0.11.2 MOCK INGEST`, `v0.11.1 SCHEMA`,
  `v0.11.0 PLAN`, `v0.10.7`, or `v0.2.1`.
- Confirm horizontal page overflow is absent on desktop/mobile.
- Confirm browser console has no runtime errors during initial dashboard load
  and after preview/run/refresh interactions.

## Known Limitations

- Full real wallet activity analysis is not implemented yet.
- Guarded TonAPI live mode does not fetch transfers, DEX swaps, PnL inputs,
  clustering inputs, or ownership proof.
- Live transaction-history rows are an ordered account timeline only; they are
  not transfer-level attribution or DEX swap reconstruction.
- Mock ingestion runs and live balance/transaction rows are not wired into
  legacy PnL, clustering, or exports.
- TonAPI wallet intelligence preview remains jettons-only.
- STON.fi remains a pool/swap-scope provider, not complete TON DeFi coverage.
- Bitquery TON trade coverage remains schema/provider limited.
- Export endpoints rerun analysis instead of exporting a specific stored run id.

## Recommended Next Step

Promote this transaction-history branch after the checklist is accepted. The
next logical track is guarded TonAPI transfer-level (event/action) exploration:

```bash
git checkout -b v0.11.9-wallet-ingestion-tonapi-transfers
```
