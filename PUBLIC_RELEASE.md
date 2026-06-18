# TON Wallet Intelligence Dashboard - v0.10.7 Public Release

Public release handoff for the current TON wallet intelligence workspace.

## Public Scope

- Dark matrix-style TON wallet intelligence dashboard.
- Provider status with endpoint coverage and online/degraded/offline counts.
- Shared provider preview workspace for TonAPI wallet intelligence, TonAPI
  account jettons, and STON.fi pools.
- Explicit data honesty surfaces for provider limitations, unavailable data,
  scoped previews, and mock-aware legacy analytics.
- Legacy token/wallet report with buyers, PnL, clustering, common holdings,
  interesting wallets, and exports.
- Experimental Bitquery and CSV/JSON import tools remain provider-limited.

## Release Contract

- Product release label: `v0.10.7`.
- Backend API `VERSION` remains `0.2.1`.
- `DATA_MODE=mock` remains the default.
- Provider previews may use real sources only within their documented scope.
- Missing provider data is shown as unavailable/provider-limited and is not
  inferred.

## Known Limitations

- TonAPI wallet intelligence is jettons-only, not full wallet intelligence.
- Full transaction history, transfers, DEX swaps, current TON balances, and
  full behavior analysis are not implemented yet.
- Legacy buyers, PnL, clustering, and exports remain mock-aware or deferred.
- Bitquery TON coverage remains schema/provider limited.
- Export endpoints rerun analysis instead of exporting a specific stored run id.

## Verification Summary

Before tagging `v0.10.7`, confirm:

- `npm run build` passes from `frontend/`.
- `.venv/bin/python -m pytest -q` passes from `backend/`.
- Browser QA passes on desktop and mobile without console errors or horizontal
  overflow.
- UI shows `RELEASE v0.10.7`.
- Provider Status can show `Endpoint coverage` and `5/5 providers` when the
  backend is running.

## Next Tracks

After this public baseline, `v0.11.1 SCHEMA` added wallet activity schema
scaffolding, `v0.11.2 MOCK INGEST` proves that schema with deterministic
mock-normalized ingestion, `v0.11.3 INGEST UI` adds the dashboard workflow, and
`v0.11.4 ADAPTERS` adds the backend wallet activity adapter interface with the
mock adapter as the default active provider. `v0.11.5 SCAFFOLDS` adds
provider-specific wallet activity scaffolds behind `WALLET_ACTIVITY_PROVIDER`
and the public provider status row. `v0.11.6 LIVE GUARDS` adds the first
guarded live wallet activity path: TonAPI account jetton balance snapshots,
enabled only with `DATA_MODE=real`, `WALLET_ACTIVITY_PROVIDER=tonapi`, and
`WALLET_ACTIVITY_LIVE_ENABLED=true`. `v0.11.7 BALANCES` expands that guarded
path to native TON balance snapshots while keeping broader real provider calls
deferred behind the contract in `REAL_WALLET_INGESTION_PLAN.md`:

- wallet transfers;
- transaction history;
- DEX swaps;
- real wallet-level PnL and clustering inputs.
