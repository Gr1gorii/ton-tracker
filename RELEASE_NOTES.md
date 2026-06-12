# TON Wallet Intelligence Dashboard - v0.11.2 MOCK INGEST

Mock-normalized wallet activity ingestion handoff for the current wallet
intelligence workspace.

## Release Scope

- Dark matrix-style TON wallet intelligence dashboard.
- Shared provider preview workspace for TonAPI wallet intelligence, TonAPI
  account jettons, and STON.fi pools.
- Provider status panel with endpoint coverage and online/degraded/offline
  counts.
- Evidence and data honesty cards for unavailable provider data, scoped
  previews, mock-aware legacy analytics, and provider limitations.
- Wallet activity SQLAlchemy models and Pydantic response contracts from
  `v0.11.1` are now exercised by mock-normalized ingestion endpoints.
- `POST /api/wallets/ingest/preview` returns deterministic provider coverage
  for requested wallet activity surfaces.
- `POST /api/wallets/ingest` persists a deterministic mock ingestion run with
  normalized transfers, transactions, swaps, balances, warnings, and provider
  evidence.
- `GET /api/wallets/ingest/{run_id}` returns a persisted ingestion run by id.
- Version contract clarified: backend `VERSION=0.2.1` remains the API-version
  field; `v0.11.2 MOCK INGEST` is the product release label.
- Real wallet ingestion phases, non-goals, data model, and rollout gates remain
  captured in `REAL_WALLET_INGESTION_PLAN.md`.
- Public release baseline remains documented in `PUBLIC_RELEASE.md`.
- Legacy mock-aware token/wallet report with buyers, PnL, clustering, common
  holdings, interesting wallets, and exports remains separate from ingestion.
- Experimental Bitquery and CSV/JSON import tools remain explicitly
  provider-limited.

## Current Data Contract

- Product label: `v0.11.2 MOCK INGEST`.
- Backend API `VERSION` remains `0.2.1` and is documented as a separate
  API-version field.
- `DATA_MODE=mock` remains the default.
- The new wallet activity ingestion endpoints return `data_mode=mock` and
  `source_status=mock` for their generated rows.
- Mock-normalized ingestion does not call real providers.
- TonAPI wallet intelligence preview is jettons-only, not full wallet
  intelligence.
- STON.fi preview covers STON.fi pools only, not all TON DeFi.
- Bitquery TON coverage may be unavailable/provider-limited.
- Legacy buyers, PnL, clustering, and exports remain mock-aware or deferred.
- Missing provider data must stay visible and must not be inferred.
- No real provider ingestion or analytics wiring is implemented in this
  milestone.

## Verification Snapshot

Use this checklist before promoting the mock ingestion branch:

- `npm run build` from `frontend/`.
- `.venv/bin/python -m pytest -q` from `backend/`.
- `.venv/bin/python -m pytest tests/test_wallet_activity_ingestion.py -q` from
  `backend/`.
- `.venv/bin/python -m pytest tests/test_wallet_activity_schema.py -q` from
  `backend/`.
- Browser QA on desktop and mobile widths.
- Confirm UI shows `RELEASE v0.11.2 MOCK INGEST`.
- Confirm preview/run/read wallet ingestion endpoints return deterministic
  mock-normalized responses with explicit warnings.
- Confirm persisted ingestion runs can be read back by id.
- Confirm `RELEASE_PROMOTION.md` lists the promotion gates, commands, and
  rollback notes.
- Confirm Provider Status can show `Endpoint coverage` and `5/5 providers`
  when the backend is running.
- Confirm provider/source badges distinguish loading, error, mock/offline,
  live, and unknown states.
- Confirm no user-facing UI copy shows stale product labels such as
  `v0.11.1 SCHEMA`, `v0.11.0 PLAN`, `v0.10.7`, `v0.10.6 RC`, `v0.10.5 RC`,
  `v0.10.4 RC`, or `v0.2.1`.
- Confirm horizontal page overflow is absent on desktop/mobile.
- Confirm browser console has no runtime errors during initial dashboard load.

## Known Limitations

- Full real wallet activity analysis is not implemented yet.
- The ingestion endpoints use deterministic mock fixtures only.
- Real transaction history, DEX swaps, current TON balances, and full wallet
  behavior are not included in TonAPI wallet intelligence preview.
- Legacy PnL/clustering surfaces are mock-aware, not real on-chain analytics.
- Mock ingestion runs are not wired into legacy PnL, clustering, or exports.
- Bitquery TON trade coverage remains schema/provider limited.
- Export endpoints rerun analysis instead of exporting a specific stored run id.

## Recommended Next Step

Promote this mock ingestion branch after the checklist is accepted. The next
logical track is a dedicated wallet ingestion UI workspace:

```bash
git checkout -b v0.11.3-wallet-ingestion-ui-workspace
```
