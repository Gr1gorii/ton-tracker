# TON Wallet Intelligence Dashboard - v0.11.0 PLAN

Real wallet ingestion planning handoff for the current wallet intelligence
workspace.

## Release Scope

- Dark matrix-style TON wallet intelligence dashboard.
- Shared provider preview workspace for TonAPI wallet intelligence, TonAPI
  account jettons, and STON.fi pools.
- Provider status panel with endpoint coverage and online/degraded/offline
  counts.
- Evidence and data honesty cards for unavailable provider data, scoped
  previews, mock-aware legacy analytics, and provider limitations.
- Final browser signoff marker in the release-readiness panel for desktop and
  mobile QA.
- Favicon configured so release browser QA has no missing asset console noise.
- Release promotion checklist captured in `RELEASE_PROMOTION.md`.
- Version contract clarified: backend `VERSION=0.2.1` remains the API-version
  field; `v0.11.0 PLAN` is the product planning label.
- Real wallet ingestion phases, non-goals, data model, and rollout gates are
  captured in `REAL_WALLET_INGESTION_PLAN.md`.
- Public release baseline remains documented in `PUBLIC_RELEASE.md`.
- Legacy mock-aware token/wallet report with buyers, PnL, clustering, common
  holdings, interesting wallets, and exports.
- Experimental Bitquery and CSV/JSON import tools remain explicitly
  provider-limited.

## Current Data Contract

- Product planning label: `v0.11.0 PLAN`.
- Backend API `VERSION` remains `0.2.1` and is documented as a separate
  API-version field.
- `DATA_MODE=mock` remains the default.
- TonAPI wallet intelligence preview is jettons-only, not full wallet
  intelligence.
- STON.fi preview covers STON.fi pools only, not all TON DeFi.
- Bitquery TON coverage may be unavailable/provider-limited.
- Legacy buyers, PnL, clustering, and exports remain mock-aware or deferred.
- Missing provider data must stay visible and must not be inferred.
- Full wallet transfers, transaction history, DEX swaps, and current TON
  balances are planned but not implemented in this milestone.

## Verification Snapshot

Use this checklist before promoting the planning milestone branch:

- `npm run build` from `frontend/`.
- `.venv/bin/python -m pytest -q` from `backend/`.
- Browser QA on desktop and mobile widths.
- Confirm UI shows `RELEASE v0.11.0 PLAN`.
- Confirm `RELEASE_PROMOTION.md` lists the promotion gates, commands, and
  rollback notes.
- Confirm `REAL_WALLET_INGESTION_PLAN.md` states ingestion phases, non-goals,
  and rollout gates.
- Confirm Provider Status can show `Endpoint coverage` and `5/5 providers`
  when the backend is running.
- Confirm provider/source badges distinguish loading, error, mock/offline,
  live, and unknown states.
- Confirm no user-facing UI copy shows stale product labels such as
  `v0.10.7`, `v0.10.6 RC`, `v0.10.5 RC`, `v0.10.4 RC`, or `v0.2.1`.
- Confirm horizontal page overflow is absent on desktop/mobile.
- Confirm browser console has no runtime errors during initial dashboard load.

## Known Limitations

- Full real wallet activity analysis is not implemented yet.
- Real transaction history, DEX swaps, current TON balances, and full wallet
  behavior are not included in TonAPI wallet intelligence preview.
- Legacy PnL/clustering surfaces are mock-aware, not real on-chain analytics.
- Bitquery TON trade coverage remains schema/provider limited.
- Export endpoints rerun analysis instead of exporting a specific stored run id.

## Recommended Next Step

Promote this planning branch after the ingestion-plan checklist is accepted. If
the next track begins schema work, use:

```bash
git checkout -b v0.11.1-wallet-activity-schema-scaffold
```
