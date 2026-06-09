# TON Wallet Intelligence Dashboard - v0.10.4 RC

Release candidate handoff for the current wallet intelligence workspace.

## Release Scope

- Dark matrix-style TON wallet intelligence dashboard.
- Shared provider preview workspace for TonAPI wallet intelligence, TonAPI
  account jettons, and STON.fi pools.
- Provider status panel with endpoint coverage and online/degraded/offline
  counts.
- Evidence and data honesty cards for unavailable provider data, scoped
  previews, mock-aware legacy analytics, and provider limitations.
- Legacy mock-aware token/wallet report with buyers, PnL, clustering, common
  holdings, interesting wallets, and exports.
- Experimental Bitquery and CSV/JSON import tools remain explicitly
  provider-limited.

## Current Data Contract

- Product release label: `v0.10.4 RC`.
- Backend API `VERSION` remains `0.2.1` and is documented as a separate API
  version field.
- `DATA_MODE=mock` remains the default.
- TonAPI wallet intelligence preview is jettons-only, not full wallet
  intelligence.
- STON.fi preview covers STON.fi pools only, not all TON DeFi.
- Bitquery TON coverage may be unavailable/provider-limited.
- Legacy buyers, PnL, clustering, and exports remain mock-aware or deferred.
- Missing provider data must stay visible and must not be inferred.

## Verification Snapshot

Use this checklist before promoting the RC:

- `npm run build` from `frontend/`.
- `.venv/bin/python -m pytest -q` from `backend/`.
- Browser QA on desktop and mobile widths.
- Confirm UI shows `RELEASE v0.10.4 RC`.
- Confirm Provider Status can show `Endpoint coverage` and `5/5 providers`
  when the backend is running.
- Confirm provider/source badges distinguish loading, error, mock/offline,
  live, and unknown states.
- Confirm no user-facing UI copy shows stale product labels such as `v0.2.1`.
- Confirm horizontal page overflow is absent on desktop/mobile.

## Known Limitations

- Full real wallet activity analysis is not implemented yet.
- Real transaction history, DEX swaps, current TON balances, and full wallet
  behavior are not included in TonAPI wallet intelligence preview.
- Legacy PnL/clustering surfaces are mock-aware, not real on-chain analytics.
- Bitquery TON trade coverage remains schema/provider limited.
- Export endpoints rerun analysis instead of exporting a specific stored run id.

## Recommended Next Step

Promote this RC only after one final end-to-end browser pass with backend
running. If more polish is needed, use a patch branch such as:

```bash
git checkout -b v0.10.5-rc-final-browser-signoff
```
