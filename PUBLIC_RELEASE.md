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

## Next Track

The next major track should not be more release-label polish. Start planning
real wallet ingestion:

- wallet transfers;
- transaction history;
- DEX swaps;
- current TON balances;
- real wallet-level PnL and clustering inputs.
