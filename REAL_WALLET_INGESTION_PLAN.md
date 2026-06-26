# TON Wallet Intelligence Dashboard - v0.11.9 TRANSFERS

Planning and rollout contract for real wallet activity ingestion. The current
milestone expands the guarded TonAPI live path to TON/jetton transfer history
derived from account events, alongside the existing native TON balance, account
jetton balance snapshots, and transaction-history timeline, behind explicit
configuration controls.

## Objective

Move from scoped provider previews and mock-aware legacy analytics toward real
wallet-level activity ingestion for TON wallets.

The plan must preserve the current data honesty contract:

- missing provider data remains visible;
- scoped previews stay labeled as previews;
- mock-aware legacy analytics do not silently become "real";
- backend `VERSION=0.2.1` remains the API-version field until the API contract
  changes.

## Non-Goals For v0.11.9

- Do not calculate real wallet PnL yet.
- Do not connect live balance, transaction-history, or transfer rows to
  clustering yet.
- Do not replace legacy mock-aware buyers, exports, or interesting-wallet
  reports yet.
- Do not infer DEX swaps or ownership proof from balance snapshots, the
  transaction-history timeline, or transfer rows.
- Do not claim transfer rows are DEX swap reconstruction or complete wallet
  intelligence; transfer direction is best-effort from event addresses.
- Do not wire ingestion rows into legacy PnL, clustering, or exports.
- Do not remove TonAPI/STON.fi/Bitquery provider limitation messaging.

## Data To Ingest

Planned wallet activity surfaces:

| Surface | Purpose | Current status |
| --- | --- | --- |
| Wallet transfers | Incoming/outgoing TON and jetton movements | Mock-normalized in v0.11.2; TonAPI live guarded in v0.11.9 |
| Transaction history | Ordered account activity timeline | Mock-normalized in v0.11.2; TonAPI live guarded in v0.11.8 |
| DEX swaps | Swap-side activity for wallet-level behavior | Mock-normalized in v0.11.2; live deferred |
| Current TON balance | Wallet-level native TON balance | TonAPI live guarded in v0.11.7 |
| Jetton balances | Current token holdings | TonAPI live guarded in v0.11.6; expanded with native balance in v0.11.7 |
| Provider evidence | Source, mode, warnings, freshness, errors | Required |

## Storage Scaffold

Use explicit, source-aware entities rather than a single opaque JSON blob.
`v0.11.1` scaffolds these entities in SQLAlchemy, `v0.11.2` persists
deterministic mock-normalized rows into them, `v0.11.6` persists guarded TonAPI
live jetton balance snapshots, `v0.11.7` adds guarded native TON balance
snapshots into `WalletBalanceSnapshot`, `v0.11.8` persists guarded live
transaction-history rows into `WalletTransaction`, and `v0.11.9` persists
guarded live TON/jetton transfer rows into `WalletTransfer`:

- `WalletIngestionRun`: run id, wallet address, requested window, data mode,
  provider summary, unavailable surfaces, status, timestamps.
- `WalletTransfer`: run id, tx hash, logical time or timestamp, asset, amount,
  direction, counterparty, provider, source status.
- `WalletTransaction`: run id, tx hash, timestamp, fee, success/error state,
  raw provider refs.
- `WalletSwap`: run id, tx hash, dex/source, token in/out, amount in/out,
  estimated USD values when available.
- `WalletBalanceSnapshot`: run id, asset, balance, source, timestamp, raw
  provider payload, and exact normalized live balance strings where available.
- `WalletIngestionWarning`: run id, severity, provider, message, evidence key.

Each record must preserve provenance so the UI can show what is known,
provider-limited, stale, unavailable, or mock-aware.

## API Contract Direction

`v0.11.2` implements these endpoints with deterministic mock-normalized data.
`v0.11.3` adds a dashboard workspace that uses them. `v0.11.4` routes preview
and run orchestration through the backend wallet activity adapter interface.
`v0.11.5` adds explicit provider scaffold selection through
`WALLET_ACTIVITY_PROVIDER`. `v0.11.6` adds the first guarded live TonAPI path:
account jetton balance snapshots. `v0.11.7` expands the same guard to native
TON balance snapshots for requested `balances`. `v0.11.8` expands it again to an
ordered account transaction-history timeline for requested `transactions`.
`v0.11.9` expands it again to TON/jetton transfer history (from account events)
for requested `transfers`.

- `POST /api/wallets/ingest/preview`
  - validates wallet address, window, and requested surfaces;
  - returns estimated provider coverage and unavailable surfaces;
  - returns live TonAPI provider evidence only when all live guard flags are
    enabled;
  - does not persist a run.
- `POST /api/wallets/ingest`
  - persists deterministic mock-normalized rows by default;
  - persists scaffold-only warning/evidence runs when an explicit non-live
    provider scaffold is selected;
  - persists live TonAPI native TON balance snapshots when the v0.11.7 live
    guard is enabled and `balances` is requested;
  - persists live TonAPI account jetton balance snapshots when the live guard
    is enabled and `jettons` is requested;
  - persists live TonAPI ordered transaction-history rows when the v0.11.8 live
    guard is enabled and `transactions` is requested;
  - persists live TonAPI TON/jetton transfer rows when the v0.11.9 live guard
    is enabled and `transfers` is requested;
  - returns run id, status, provider evidence, unavailable surfaces, normalized
    rows, and warnings.
- `GET /api/wallets/ingest/{run_id}`
  - returns normalized transfers, transactions, swaps, balances, warnings,
    unavailable surfaces, and provider evidence for one run.

Do not wire these outputs into PnL/clustering until the ingestion contract is
tested independently.

## Provider Strategy

Start with adapters that can report partial success clearly:

- TonAPI for native account balance, account jettons, and future wallet
  activity where available.
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

`v0.11.9` keeps the `TonapiWalletActivityLiveAdapter` guarded by:

- `DATA_MODE=real`;
- `WALLET_ACTIVITY_PROVIDER=tonapi`;
- `WALLET_ACTIVITY_LIVE_ENABLED=true`;
- `WALLET_ACTIVITY_LIVE_JETTON_LIMIT`, clamped to `1..500`;
- `WALLET_ACTIVITY_LIVE_TX_LIMIT`, clamped to `1..1000`;
- `WALLET_ACTIVITY_LIVE_TRANSFER_LIMIT`, clamped to `1..1000`.

Supported live surfaces in v0.11.9:

- `balances`: one native TON balance snapshot from TonAPI account data.
- `jettons`: account jetton balance snapshots from TonAPI account jetton data.
- `transactions`: ordered account transaction-history rows from TonAPI
  blockchain account-transactions data (`hash`, `lt`, `utime`, `total_fees`,
  `success`).
- `transfers`: TON/jetton transfer rows parsed from TonAPI account events
  (`TonTransfer`/`JettonTransfer` actions) with best-effort direction.

Unsupported live surfaces in v0.11.9:

- `swaps`
- PnL inputs
- clustering inputs
- ownership proof

## UI Direction

Keep the dedicated wallet ingestion workspace before changing legacy analytics:

- Wallet address input and window selector.
- Surface toggles for transfers, transactions, swaps, balances, jettons.
- Provider coverage matrix before running ingestion.
- Run status with ready/running/success/error/stale states.
- Data honesty cards for unavailable surfaces.
- Activity tables separated by surface.
- Clear message that PnL/clustering are not yet real unless explicitly wired.
- Release-readiness copy that states v0.11.9 is live only for native TON
  balance snapshots, account jetton balance snapshots, account
  transaction-history rows, and TON/jetton transfer rows.

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
   - Add adapter protocol and mock adapter boundary. Done in `v0.11.4`.
   - Add provider-specific scaffolds behind feature/data-mode controls. Done in
     `v0.11.5`.
   - Add first guarded live TonAPI jetton balance snapshot path. Done in
     `v0.11.6`.
   - Add guarded live native TON balance snapshot path. Done in `v0.11.7`.
   - Keep partial provider coverage visible.

5. Activity history exploration
   - Add guarded transaction-history coverage (ordered account timeline). Done
     in `v0.11.8`.
   - Add guarded transfer-level coverage (event/action parsing). Done in
     `v0.11.9`.
   - Add guarded DEX swap reconstruction only after provider rate-limit
     behavior, freshness, and field reliability are understood.
   - Keep balance snapshots separate from activity/history rows.

6. Analytics integration
   - Connect real wallet activity to PnL, clustering, and exports only after
     ingestion quality is measurable.

## Verification Gates

Before promoting wallet ingestion transfer-history coverage:

- `npm run build` passes.
- `.venv/bin/python -m pytest -q` passes.
- `.venv/bin/python -m pytest tests/test_tonapi_adapter.py -q` passes.
- `.venv/bin/python -m pytest tests/test_wallet_activity_adapter.py -q`
  passes.
- `.venv/bin/python -m pytest tests/test_wallet_activity_ingestion.py -q`
  passes.
- `.venv/bin/python -m pytest tests/test_wallet_activity_provider_status.py -q`
  passes.
- UI shows `RELEASE v0.11.9 TRANSFERS`.
- `/api/wallets/ingest/preview`, `/api/wallets/ingest`, and
  `/api/wallets/ingest/{run_id}` return source-aware mock data by default.
- `DATA_MODE=real` without `WALLET_ACTIVITY_LIVE_ENABLED=true` still returns
  honest mock/scaffold warnings instead of live rows.
- Guarded TonAPI live mode persists only native TON balance snapshots, account
  jetton balance snapshots, ordered transaction-history rows, and TON/jetton
  transfer rows.
- Unsupported surfaces (swaps) remain visible in `unavailable_surfaces`.
- `/api/providers/status` includes the selected wallet activity adapter row.
- Wallet Activity Ingestion Workspace can preview coverage, persist a run,
  refresh the stored run, and render activity tables.
- README, `RELEASE_NOTES.md`, `RELEASE_PROMOTION.md`, and this document all
  describe the same transfer-history-coverage scope.
- No user-facing UI claims real full-wallet analysis exists yet.

## Next Branch

```bash
git checkout -b v0.12.0-wallet-ingestion-dex-swaps
```
