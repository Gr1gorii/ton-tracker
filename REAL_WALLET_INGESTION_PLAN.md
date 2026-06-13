# TON Wallet Intelligence Dashboard - v0.11.3 INGEST UI

Planning and rollout contract for real wallet activity ingestion. The current
milestone adds the dashboard workspace for deterministic mock-normalized
ingestion; it does not implement real full-wallet analysis yet.

## Objective

Move from scoped provider previews and mock-aware legacy analytics toward real
wallet-level activity ingestion for TON wallets.

The plan must preserve the current data honesty contract:

- missing provider data remains visible;
- scoped previews stay labeled as previews;
- mock-aware legacy analytics do not silently become "real";
- backend `VERSION=0.2.1` remains the API-version field until the API contract
  changes.

## Non-Goals For v0.11.3

- Do not calculate real wallet PnL yet.
- Do not connect real wallet activity to clustering yet.
- Do not replace legacy mock-aware buyers, exports, or interesting-wallet
  reports yet.
- Do not infer missing swaps, balances, or transfers from partial provider data.
- Do not claim the mock ingestion rows are real provider data.
- Do not wire mock ingestion rows into legacy PnL, clustering, or exports.
- Do not remove TonAPI/STON.fi/Bitquery provider limitation messaging.

## Data To Ingest

Planned wallet activity surfaces:

| Surface | Purpose | Initial status |
| --- | --- | --- |
| Wallet transfers | Incoming/outgoing TON and jetton movements | Mock-normalized in v0.11.2 |
| Transaction history | Ordered account activity timeline | Mock-normalized in v0.11.2 |
| DEX swaps | Swap-side activity for wallet-level behavior | Mock-normalized in v0.11.2 |
| Current TON balance | Wallet-level native TON balance | Mock-normalized in v0.11.2 |
| Jetton balances | Current token holdings | Mock-normalized in v0.11.2; partially previewed via TonAPI |
| Provider evidence | Source, mode, warnings, freshness, errors | Required |

## Storage Scaffold

Use explicit, source-aware entities rather than a single opaque JSON blob.
`v0.11.1` scaffolds these entities in SQLAlchemy and `v0.11.2` persists
deterministic mock-normalized rows into them:

- `WalletIngestionRun`: run id, wallet address, requested window, data mode,
  provider summary, status, timestamps.
- `WalletTransfer`: run id, tx hash, logical time or timestamp, asset, amount,
  direction, counterparty, provider, source status.
- `WalletTransaction`: run id, tx hash, timestamp, fee, success/error state,
  raw provider refs.
- `WalletSwap`: run id, tx hash, dex/source, token in/out, amount in/out,
  estimated USD values when available.
- `WalletBalanceSnapshot`: run id, asset, balance, source, timestamp.
- `WalletIngestionWarning`: run id, severity, provider, message, evidence key.

Each record should preserve provenance so the UI can show what is known,
provider-limited, stale, unavailable, or mock-aware.

## API Contract Direction

`v0.11.2` implements these endpoints with deterministic mock-normalized data.
`v0.11.3` adds a dashboard workspace that uses them. They do not call real
providers:

- `POST /api/wallets/ingest/preview`
  - validates wallet address, window, and requested surfaces;
  - returns estimated provider coverage and unavailable surfaces;
  - does not persist a run.
- `POST /api/wallets/ingest`
  - persists a deterministic mock-normalized wallet ingestion run;
  - returns run id, status, provider coverage, and warnings.
- `GET /api/wallets/ingest/{run_id}`
  - returns normalized transfers, transactions, swaps, balances, warnings, and
    provider evidence for one run.

Do not wire these outputs into PnL/clustering until the ingestion contract is
tested independently.

## Provider Strategy

Start with adapters that can report partial success clearly:

- TonAPI for account jettons and future wallet activity where available.
- TON provider adapter for wallet transfer/history scaffolding.
- STON.fi only for DEX pool/swap scope where the provider supports it.
- Bitquery only when TON schema coverage is confirmed.

Every adapter response must include:

- provider name;
- data mode;
- source status: live, mock, offline, limited, unavailable, or error;
- warnings;
- freshness timestamp when available;
- raw count and normalized count.

## UI Direction

Add a dedicated wallet ingestion workspace before changing legacy analytics:

- Wallet address input and window selector.
- Surface toggles for transfers, transactions, swaps, balances, jettons.
- Provider coverage matrix before running ingestion.
- Run status with ready/running/success/error/stale states.
- Data honesty cards for unavailable surfaces.
- Activity tables separated by surface.
- Clear message that PnL/clustering are not yet real unless explicitly wired.

## Rollout Phases

1. Schema scaffold
   - Add persisted run/activity models and tests. Done in `v0.11.1`.
   - Add response schemas without provider calls. Done in `v0.11.1`.

2. Mock-normalized ingestion
   - Add deterministic mock wallet activity fixtures. Done in `v0.11.2`.
   - Prove tables, states, and warnings with stable data. Done in `v0.11.2`.

3. UI wallet ingestion workspace
   - Add preview/run workflow and activity tables. Done in `v0.11.3`.
   - Keep legacy analytics separate. Done in `v0.11.3`.

4. Provider adapter integration
   - Add real provider calls behind feature/data-mode controls.
   - Keep partial provider coverage visible.

5. Analytics integration
   - Connect real wallet activity to PnL, clustering, and exports only after
     ingestion quality is measurable.

## Verification Gates

Before promoting wallet ingestion UI:

- `npm run build` passes.
- `.venv/bin/python -m pytest -q` passes.
- `.venv/bin/python -m pytest tests/test_wallet_activity_ingestion.py -q`
  passes.
- `.venv/bin/python -m pytest tests/test_wallet_activity_schema.py -q` passes.
- UI shows `RELEASE v0.11.3 INGEST UI`.
- `/api/wallets/ingest/preview`, `/api/wallets/ingest`, and
  `/api/wallets/ingest/{run_id}` return source-aware mock data.
- Wallet Activity Ingestion Workspace can preview coverage, persist a mock run,
  refresh the stored run, and render activity tables.
- README, `RELEASE_NOTES.md`, `RELEASE_PROMOTION.md`, and this document all
  describe the same ingestion UI scope.
- No user-facing UI claims real full-wallet analysis exists yet.

## Next Branch

```bash
git checkout -b v0.11.4-wallet-ingestion-adapter-interfaces
```
