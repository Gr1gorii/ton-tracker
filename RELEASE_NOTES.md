# TON Wallet Intelligence Dashboard - v0.11.3 INGEST UI

Wallet activity ingestion UI handoff for the current wallet intelligence
workspace.

## Release Scope

- Dark matrix-style TON wallet intelligence dashboard.
- Wallet Activity Ingestion Workspace added to the dashboard as a first-class
  wallet-level workflow.
- Shared command center can target wallet ingestion, TonAPI wallet
  intelligence, TonAPI account jettons, and STON.fi pools.
- Ingestion UI supports wallet address, time window, custom window, and surface
  selection for transfers, transactions, swaps, balances, and jettons.
- Ingestion UI can preview coverage through `POST /api/wallets/ingest/preview`.
- Ingestion UI can persist deterministic mock-normalized runs through
  `POST /api/wallets/ingest`.
- Ingestion UI can refresh a stored run through
  `GET /api/wallets/ingest/{run_id}`.
- Results show provider evidence, warnings, freshness/stale state, normalized
  metrics, and activity tables for transfers, transactions, swaps, balances,
  and run warnings.
- Version contract clarified: backend `VERSION=0.2.1` remains the API-version
  field; `v0.11.3 INGEST UI` is the product release label.
- Legacy mock-aware token/wallet report with buyers, PnL, clustering, common
  holdings, interesting wallets, and exports remains separate from ingestion.
- Experimental Bitquery and CSV/JSON import tools remain explicitly
  provider-limited.

## Current Data Contract

- Product label: `v0.11.3 INGEST UI`.
- Backend API `VERSION` remains `0.2.1` and is documented as a separate
  API-version field.
- `DATA_MODE=mock` remains the default.
- Wallet activity ingestion endpoints return `data_mode=mock` and
  `source_status=mock` for generated rows.
- The UI labels ingestion data as mock-normalized and source-labeled.
- The UI does not claim real provider ingestion, real PnL, real clustering, or
  ownership proof.
- TonAPI wallet intelligence preview remains jettons-only, not full wallet
  intelligence.
- STON.fi preview covers STON.fi pools only, not all TON DeFi.
- Bitquery TON coverage may be unavailable/provider-limited.
- Missing provider data must stay visible and must not be inferred.

## Verification Snapshot

Use this checklist before promoting the ingestion UI branch:

- `npm run build` from `frontend/`.
- `.venv/bin/python -m pytest -q` from `backend/`.
- `.venv/bin/python -m pytest tests/test_wallet_activity_ingestion.py -q` from
  `backend/`.
- Browser QA on desktop and mobile widths.
- Confirm UI shows `RELEASE v0.11.3 INGEST UI`.
- Confirm command center includes Wallet ingestion.
- Confirm Wallet Activity Ingestion Workspace can preview coverage, run mock
  ingestion, refresh the stored run, and render activity tables.
- Confirm source badges show mock/source status and data honesty warnings.
- Confirm no user-facing UI copy shows stale product labels such as
  `v0.11.2 MOCK INGEST`, `v0.11.1 SCHEMA`, `v0.11.0 PLAN`, `v0.10.7`,
  `v0.10.6 RC`, `v0.10.5 RC`, `v0.10.4 RC`, or `v0.2.1`.
- Confirm horizontal page overflow is absent on desktop/mobile.
- Confirm browser console has no runtime errors during initial dashboard load
  and after preview/run/refresh interactions.

## Known Limitations

- Full real wallet activity analysis is not implemented yet.
- The ingestion endpoints use deterministic mock fixtures only.
- Mock ingestion runs are not wired into legacy PnL, clustering, or exports.
- Real transaction history, DEX swaps, current TON balances, and full wallet
  behavior are not included in TonAPI wallet intelligence preview.
- Bitquery TON trade coverage remains schema/provider limited.
- Export endpoints rerun analysis instead of exporting a specific stored run id.

## Recommended Next Step

Promote this UI branch after the checklist is accepted. The next logical track
is provider adapter interface scaffolding:

```bash
git checkout -b v0.11.4-wallet-ingestion-adapter-interfaces
```
