# TON Wallet Intelligence Dashboard - v0.11.4 ADAPTERS

Wallet activity adapter interface handoff for the current wallet intelligence
workspace.

## Release Scope

- Dark matrix-style TON wallet intelligence dashboard.
- Wallet Activity Ingestion Workspace remains the user-facing workflow for
  coverage preview, mock ingestion runs, refresh, evidence, warnings, and
  normalized activity tables.
- New `backend/adapters/wallet_activity.py` defines the wallet activity adapter
  contract used by preview and ingestion orchestration.
- New `MockWalletActivityAdapter` is the only active adapter. It returns the
  same deterministic mock-normalized transfers, transactions, swaps, balances,
  warnings, and provider evidence as v0.11.3.
- Ingestion service now persists adapter results instead of owning provider
  fixture constants directly.
- Adapter tests cover preview coverage, requested-surface filtering,
  data-honest `DATA_MODE=real` behavior, and adapter factory routing.
- Version contract clarified: backend `VERSION=0.2.1` remains the API-version
  field; `v0.11.4 ADAPTERS` is the product release label.
- Legacy mock-aware token/wallet report with buyers, PnL, clustering, common
  holdings, interesting wallets, and exports remains separate from ingestion.
- Experimental Bitquery and CSV/JSON import tools remain explicitly
  provider-limited.

## Current Data Contract

- Product label: `v0.11.4 ADAPTERS`.
- Backend API `VERSION` remains `0.2.1` and is documented as a separate
  API-version field.
- `DATA_MODE=mock` remains the default.
- Wallet activity ingestion endpoints still return `data_mode=mock` and
  `source_status=mock` for generated rows.
- `DATA_MODE=real` does not activate real wallet activity ingestion yet; the
  adapter returns explicit mock-normalized warnings.
- No real provider calls are made by `/api/wallets/ingest/*`.
- The UI does not claim real provider ingestion, real PnL, real clustering, or
  ownership proof.
- Missing provider data must stay visible and must not be inferred.

## Verification Snapshot

Use this checklist before promoting the adapter interface branch:

- `npm run build` from `frontend/`.
- `.venv/bin/python -m pytest -q` from `backend/`.
- `.venv/bin/python -m pytest tests/test_wallet_activity_adapter.py -q` from
  `backend/`.
- `.venv/bin/python -m pytest tests/test_wallet_activity_ingestion.py -q` from
  `backend/`.
- Browser QA on desktop and mobile widths.
- Confirm UI shows `RELEASE v0.11.4 ADAPTERS`.
- Confirm Wallet Activity Ingestion Workspace still previews, runs, refreshes,
  and renders activity tables.
- Confirm source badges show mock/source status and data honesty warnings.
- Confirm no user-facing UI copy shows stale product labels such as
  `v0.11.3 INGEST UI`, `v0.11.2 MOCK INGEST`, `v0.11.1 SCHEMA`,
  `v0.11.0 PLAN`, `v0.10.7`, `v0.10.6 RC`, `v0.10.5 RC`, `v0.10.4 RC`, or
  `v0.2.1`.
- Confirm horizontal page overflow is absent on desktop/mobile.
- Confirm browser console has no runtime errors during initial dashboard load
  and after preview/run/refresh interactions.

## Known Limitations

- Full real wallet activity analysis is not implemented yet.
- The only active wallet activity adapter is deterministic mock data.
- Mock ingestion runs are not wired into legacy PnL, clustering, or exports.
- Real transaction history, DEX swaps, current TON balances, and full wallet
  behavior are not included in TonAPI wallet intelligence preview.
- Bitquery TON trade coverage remains schema/provider limited.
- Export endpoints rerun analysis instead of exporting a specific stored run id.

## Recommended Next Step

Promote this adapter interface branch after the checklist is accepted. The next
logical track is provider-specific adapter scaffolding behind status controls:

```bash
git checkout -b v0.11.5-wallet-ingestion-provider-scaffolds
```
