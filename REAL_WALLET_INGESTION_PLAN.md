# TON Wallet Intelligence Dashboard - v0.11.0 PLAN

Planning contract for real wallet activity ingestion. This milestone defines
what should be built next; it does not implement real full-wallet analysis yet.

## Objective

Move from scoped provider previews and mock-aware legacy analytics toward real
wallet-level activity ingestion for TON wallets.

The plan must preserve the current data honesty contract:

- missing provider data remains visible;
- scoped previews stay labeled as previews;
- mock-aware legacy analytics do not silently become "real";
- backend `VERSION=0.2.1` remains the API-version field until the API contract
  changes.

## Non-Goals For v0.11.0

- Do not calculate real wallet PnL yet.
- Do not connect real wallet activity to clustering yet.
- Do not replace legacy mock-aware buyers, exports, or interesting-wallet
  reports yet.
- Do not infer missing swaps, balances, or transfers from partial provider data.
- Do not remove TonAPI/STON.fi/Bitquery provider limitation messaging.

## Data To Ingest

Planned wallet activity surfaces:

| Surface | Purpose | Initial status |
| --- | --- | --- |
| Wallet transfers | Incoming/outgoing TON and jetton movements | Planned |
| Transaction history | Ordered account activity timeline | Planned |
| DEX swaps | Swap-side activity for wallet-level behavior | Planned |
| Current TON balance | Wallet-level native TON balance | Planned |
| Jetton balances | Current token holdings | Partially previewed via TonAPI |
| Provider evidence | Source, mode, warnings, freshness, errors | Required |

## Proposed Storage Direction

Use explicit, source-aware entities rather than a single opaque JSON blob:

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

## Proposed API Direction

Plan these endpoints before implementation:

- `POST /api/wallets/ingest/preview`
  - validates wallet address, window, and requested surfaces;
  - returns estimated provider coverage and unavailable surfaces;
  - does not persist a run.
- `POST /api/wallets/ingest`
  - starts or performs a source-aware wallet ingestion run;
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
   - Add persisted run/activity models and tests.
   - Add response schemas without provider calls.

2. Mock-normalized ingestion
   - Add deterministic mock wallet activity fixtures.
   - Prove tables, states, and warnings with stable data.

3. Provider adapter integration
   - Add real provider calls behind feature/data-mode controls.
   - Keep partial provider coverage visible.

4. UI wallet ingestion workspace
   - Add preview/run workflow and activity tables.
   - Keep legacy analytics separate.

5. Analytics integration
   - Connect real wallet activity to PnL, clustering, and exports only after
     ingestion quality is measurable.

## Verification Gates

Before moving from planning to schema scaffold:

- `npm run build` passes.
- `.venv/bin/python -m pytest -q` passes.
- UI shows `RELEASE v0.11.0 PLAN`.
- README, `RELEASE_NOTES.md`, `RELEASE_PROMOTION.md`, and this document all
  describe the same planning scope.
- No user-facing UI claims real full-wallet analysis exists yet.

## Next Branch

```bash
git checkout -b v0.11.1-wallet-activity-schema-scaffold
```
