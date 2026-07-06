# TON Wallet Intelligence Dashboard — v0.15.2 HISTORICAL PRICES

A local crypto intelligence dashboard for TON wallets, provider previews, and
mock-aware wallet analytics. On top of the guarded live wallet activity path
(native TON balance, account jetton balance snapshots, transaction-history
timeline, TON/jetton transfers, and DEX swaps behind explicit real-mode flags),
run-scoped intelligence covers probabilistic multi-wallet cluster comparison,
a rule-based evidence signal layer, and an estimated PnL preview
(TON-denominated realized swap flows with Real PnL locked behind explicit
evidence requirements) — each with hedged language and JSON/CSV export where
applicable. A historical price preview (provider-reported TonAPI rate points,
explicitly not a cost-basis source yet) starts the track toward unlocking
Real PnL. Deterministic mock data remains the default executable ingestion
path.

> **v0.15.2 HISTORICAL PRICES status — provider-reported historical rate preview (not cost basis), on top of PnL preview, cluster comparison, evidence signals, and guarded TonAPI activity ingestion.**
> - Runs in `DATA_MODE=mock` (default) or `DATA_MODE=real`.
> - Provider previews are available for TonAPI account jettons, TonAPI
>   jettons-only wallet intelligence, and STON.fi pools.
> - Wallet activity ingestion now has a dashboard workspace for coverage
>   preview, persisted mock runs, run refresh, evidence, warnings, and
>   normalized activity tables.
> - Wallet activity preview/run orchestration now goes through
>   `backend/adapters/wallet_activity.py`.
> - `WALLET_ACTIVITY_PROVIDER=mock` remains the default. Explicit
>   `DATA_MODE=real`, `WALLET_ACTIVITY_PROVIDER=tonapi`, and
>   `WALLET_ACTIVITY_LIVE_ENABLED=true` enable the only live wallet activity
>   path in this release: TonAPI native TON balance snapshots, account jetton
>   balance snapshots, an ordered account transaction-history timeline,
>   TON/jetton transfer history, and DEX swaps from account events. PnL
>   remains unavailable.
> - Persisted ingestion runs can be compared pairwise (2-25 runs) as a
>   probabilistic behavioral-similarity signal with JSON/CSV export — never
>   proof of common ownership.
> - Each persisted run exposes rule-based evidence signals with confidence
>   levels and explicit insufficient-evidence records, rendered in a workspace
>   card and exportable as JSON/CSV. Signals are heuristic observations, not a
>   risk score.
> - Each persisted run exposes an estimated PnL preview (`pnl_mode`:
>   `imported_pnl` / `estimated_onchain_pnl` / `real_pnl_locked` /
>   `insufficient_data`, confidence `high`/`medium`/`low`/`unavailable`):
>   TON-denominated realized swap flows only, never labeled Real PnL. Real
>   PnL stays locked until transaction history, swap evidence, historical
>   prices, cost basis, and fee handling are all available; missing evidence
>   is listed explicitly.
> - Historical rate points can be previewed per token (`"ton"` or a jetton
>   master address) from the guarded TonAPI rates chart, with a deterministic
>   mock default and no hidden fallback on provider failure. The preview is
>   explicitly not a cost-basis source (`is_cost_basis_source: false`), so
>   Real PnL stays locked.
> - `ton_provider`, `stonfi`, `bitquery`, and TonAPI without the live guard
>   remain scaffold/limited coverage paths. They do not fetch or persist live
>   wallet activity rows.
> - Provider preview panels use shared workspace inputs and show fresh/stale,
>   ready/running/error, and scoped-data states.
> - Legacy buyers, PnL, exports, clustering, and interesting-wallet reports
>   remain mock-aware and separate from provider previews.
> - Bitquery TON coverage remains limited/unavailable in the current schema;
>   Bitquery and import tools are marked as experimental/provider-limited.
> - Every provider-limited surface avoids hidden fallback claims. Missing data
>   stays visible instead of being inferred.
> - Provider/source badges distinguish loading, error, mock/offline, live, and
>   unknown status states.
> - Provider status shows endpoint coverage and online/degraded/offline counts,
>   including the wallet activity adapter selection row, without probing
>   network providers from the status endpoint.
> - User-facing UI copy uses the `v0.15.2 HISTORICAL PRICES` product label
>   and avoids stale product version references.
> - Public release notes for the stable baseline remain in `PUBLIC_RELEASE.md`.
> - Real wallet ingestion phases remain captured in
>   `REAL_WALLET_INGESTION_PLAN.md`.
> - Wallet activity preview/run/read endpoints persist deterministic
>   mock-normalized transfers, transactions, swaps, balances, warnings, and
>   provider evidence.
> - Backend `VERSION=0.2.1` remains an API-version field; `v0.15.2 HISTORICAL
>   PRICES` is the product release label.
> - Wallet clustering is probabilistic: similarity signals only, not proof of
>   common ownership.

---

## Tech stack

| Layer    | Stack                                   |
| -------- | --------------------------------------- |
| Backend  | FastAPI (Python), SQLite, SQLAlchemy    |
| Frontend | React + Vite + TypeScript               |
| Money    | `decimal.Decimal` for PnL math          |

The code is intentionally modular: all network-specific logic lives behind
adapters in `backend/adapters/`, so real data sources can be added later
without touching the analysis / PnL / clustering services.

---

## Project structure

```
backend/
  main.py              FastAPI app + endpoints
  config.py            Settings (DATA_MODE + providers) + ProviderResult
  .env.example         Provider configuration template
  requirements.txt
  models.py            SQLAlchemy models (AnalysisRun + wallet activity tables)
  schemas.py           Pydantic request/response schemas
  database.py          SQLite engine + session
  conftest.py          Test path setup
  routers/
    tonapi.py          TonAPI account jettons + wallet intelligence previews
    stonfi.py          STON.fi pools preview
    bitquery.py        Bitquery token trades preview/analysis
    import_trades.py   CSV/JSON trade import preview/analysis
    wallet_activity.py Mock-normalized wallet activity ingestion endpoints
    prices.py          Historical price preview endpoint (not cost basis)
  services/
    analysis.py        Orchestration + data_quality + provider status
    pnl.py             Decimal-based PnL calculations
    clustering.py      Probabilistic wallet similarity / grouping
    mock_data.py       Hand-crafted mock token/pool/wallet fixtures
    export.py          CSV / JSON serialization
    import_parser.py   CSV/JSON trade parsing
    import_analysis.py Imported-trade wallet analysis
    tonapi_wallet_intelligence.py
                         Jettons-only wallet intelligence preview builder
    wallet_activity_ingestion.py
                         Adapter-backed wallet activity ingestion persistence
    wallet_activity_clustering.py
                         Pairwise run comparison (probabilistic similarity)
    wallet_activity_signals.py
                         Rule-based evidence signals with confidence levels
    pnl_preview.py       Estimated PnL preview (Real PnL stays locked)
    historical_pricing.py
                         Historical rate point preview (not a cost-basis source)
  adapters/
    geckoterminal.py   Pool/token data — mock or real GeckoTerminal API
    wallet_activity.py Wallet activity contract + mock/scaffold adapters
    tonapi.py          TonAPI account jettons preview adapter
    stonfi.py          STON.fi pools preview adapter
    bitquery.py        DEX trades — mock/provider-limited Bitquery
    ton_provider.py    Legacy TON provider status/scaffold
  tests/               pytest suite (parser, config, data_quality, PnL,
                       clustering, wallet activity, evidence signals)

frontend/
  package.json
  vite.config.ts
  index.html
  public/
    favicon.svg       Browser favicon for clean console signoff
  src/
    main.tsx
    App.tsx
    api.ts             API client + export URLs
    types.ts           Types mirroring the backend payload
    format.ts          Display formatting helpers
    components/
      PoolUrlInput.tsx
      TimeWindowPicker.tsx
      ProviderStatus.tsx
      PreviewReadinessStrip.tsx
      PreviewFreshnessStrip.tsx
      WalletIngestionWorkspace.tsx
      TonapiWalletIntelligencePreviewPanel.tsx
      TonapiAccountJettonsPreviewPanel.tsx
      StonfiPoolsPreviewPanel.tsx
      BitqueryTokenTradesPanel.tsx
      ImportPreviewPanel.tsx
      TokenOverview.tsx
      BuyersTable.tsx
      WalletGroups.tsx
      CommonHoldings.tsx
      InterestingWallets.tsx
      ExportButtons.tsx

README.md
RELEASE_NOTES.md
RELEASE_PROMOTION.md
PUBLIC_RELEASE.md
REAL_WALLET_INGESTION_PLAN.md
```

---

## Setup

### Backend

```bash
cd backend
python -m venv .venv

# Activate the virtualenv:
#   macOS / Linux:
source .venv/bin/activate
#   Windows (PowerShell):
.\.venv\Scripts\Activate.ps1
#   Windows (cmd):
.\.venv\Scripts\activate.bat

pip install -r requirements.txt
uvicorn main:app --reload
```

The API serves on `http://localhost:8000`. Interactive docs: `http://localhost:8000/docs`.

### Frontend

```bash
cd frontend
npm install
npm run dev
```

The dashboard serves on `http://localhost:5173` and calls the backend at
`http://localhost:8000` by default. Override the API base by setting
`VITE_API_BASE` (e.g. in `frontend/.env`):

```
VITE_API_BASE=http://localhost:8000
```

---

## Data modes & providers (v0.15.2 HISTORICAL PRICES)

Configure providers via environment variables (copy `backend/.env.example` to
`backend/.env`):

| Variable                 | Purpose                                            |
| ------------------------ | -------------------------------------------------- |
| `DATA_MODE`              | `mock` (default) or `real`                         |
| `GECKOTERMINAL_BASE_URL` | GeckoTerminal v2 API base (public, no key)         |
| `TON_API_BASE_URL`       | TON indexer base URL (real TON data)               |
| `TON_API_KEY`            | TON indexer API key                                |
| `BITQUERY_API_URL`       | Bitquery endpoint (real DEX trades)                |
| `BITQUERY_API_KEY`       | Bitquery API key                                   |
| `STONFI_BASE_URL`        | STON.fi API base for pool previews                 |
| `TONAPI_BASE_URL`        | TonAPI API base for account balance and jetton previews |
| `TONAPI_API_KEY`         | Optional TonAPI API key                            |
| `WALLET_ACTIVITY_PROVIDER` | `mock`, `tonapi`, `ton_provider`, `stonfi`, or `bitquery` |
| `WALLET_ACTIVITY_LIVE_ENABLED` | `false` by default; enables the guarded TonAPI live path only when `DATA_MODE=real` and `WALLET_ACTIVITY_PROVIDER=tonapi` |
| `WALLET_ACTIVITY_LIVE_JETTON_LIMIT` | TonAPI live jetton snapshot limit, clamped to `1..500` |
| `WALLET_ACTIVITY_LIVE_TX_LIMIT` | TonAPI live transaction-history page size, clamped to `1..1000` |
| `WALLET_ACTIVITY_LIVE_TRANSFER_LIMIT` | TonAPI live transfer-history (account events) page size, clamped to `1..1000` |
| `WALLET_ACTIVITY_LIVE_SWAP_LIMIT` | TonAPI live DEX-swap (account events) page size, clamped to `1..1000` |

What is real, preview-only, mock-aware, planned, and scaffolded in this
milestone:

| Surface                                      | mock mode       | real mode / provider mode                         |
| -------------------------------------------- | --------------- | ------------------------------------------------- |
| Pool / token info for legacy analysis        | mock            | GeckoTerminal when available, with fallback notes |
| TonAPI account jettons preview               | mock/offline    | TonAPI/public API when available                  |
| TonAPI wallet intelligence preview           | jettons-only    | jettons-only; not full wallet intelligence        |
| STON.fi pools preview                        | mock/offline    | STON.fi pools only                                |
| Bitquery token trades preview/analysis       | provider-limited | limited by current TON schema coverage            |
| Imported CSV/JSON trade preview/analysis     | local input     | local input                                       |
| Legacy buyers, PnL, exports, clustering      | mock-aware      | mock-aware / deferred                             |
| Full wallet transfers/history/swaps/balances | mock-normalized | mock by default; explicit TonAPI live guard returns native TON balance, jetton balance snapshots, an ordered transaction-history timeline, TON/jetton transfer history, and DEX swaps (all from TonAPI); PnL remains unavailable; cluster comparison and evidence signals run separately over persisted runs |

Each `/api/analyze` response includes a `data_quality` block
(`{ mode, warnings, provider_notes }`) describing the run. The UI shows a
**Data mode / Provider status** panel reflecting `GET /api/providers/status`,
plus release-readiness and evidence cards that state current limitations.
Missing provider coverage is displayed as unavailable/provider-limited instead
of being silently inferred.

---

## API

### `GET /api/health`
Returns service status, backend API version, and current `data_mode`.

Note: the backend `version` field remains `0.2.1` by design. It is the backend
API-version field, while `v0.15.2 HISTORICAL PRICES` is the current
user-facing product release label.

### `GET /api/providers/status`
Returns `data_mode` plus provider status for GeckoTerminal, legacy TON
provider, Bitquery, STON.fi, TonAPI, and the selected wallet activity adapter.

### `POST /api/analyze`
Request body:

```json
{
  "pool_url": "https://www.geckoterminal.com/ton/pools/<pool_address>",
  "time_window": "24h",            // "24h" | "3d" | "7d" | "custom"
  "custom_start": "2026-05-01T00:00:00Z",  // required only when "custom"
  "custom_end": "2026-05-08T00:00:00Z"     // required only when "custom"
}
```

Returns token info, pool info, the analyzed window, per-wallet PnL + flags,
candidate clusters, common holdings, interesting wallets, a summary, the
`data_quality` block, and the `providers` status.

### `GET /api/export/csv` and `GET /api/export/json`
Download placeholders. They run a fresh mock analysis and stream it back as a
downloadable CSV (wallet table) or JSON (full payload). Optional query params:
`pool_url`, `time_window`.

### `GET /api/tonapi/account-jettons/preview`
Returns a scoped TonAPI account jettons preview for `account_address` and
`limit`. This is account jetton data only.

### `GET /api/tonapi/wallet-intelligence/preview`
Builds a jettons-only wallet intelligence preview from TonAPI account jetton
data. It does not include full transaction history, PnL, DEX swaps, current TON
balance, or full on-chain behavior.

### `GET /api/stonfi/pools/preview`
Returns a scoped STON.fi pools preview for `limit`. It covers STON.fi DEX pools
only, not all TON DeFi.

### `POST /api/wallets/ingest/preview`
Returns provider coverage for a wallet activity ingestion request. The default
mock path is deterministic. Since v0.12.0 the explicit TonAPI live guard can
call TonAPI for native TON balance, account jetton balance, account
transaction-history, TON/jetton transfer, and DEX swap coverage; PnL remains
unavailable.

### `POST /api/wallets/ingest`
Persists one adapter-backed wallet activity run and returns run id, status,
provider evidence, normalized rows, unavailable surfaces, and warnings. The
default path persists deterministic mock-normalized rows. The TonAPI
live guard persists native TON balance snapshots, account jetton balance
snapshots, ordered transaction-history rows, TON/jetton transfer rows, and DEX
swap rows only.

### `GET /api/wallets/ingest/{run_id}`
Returns one persisted wallet activity run by id, including provider evidence,
unavailable surfaces, normalized rows, and warnings.

### `GET /api/wallets/ingest/{run_id}/export.json` and `.../export.csv`
Download one persisted run as JSON, or as flattened one-row-per-activity CSV.

### `GET /api/wallets/ingest/{run_id}/signals`
Returns rule-based evidence signals for one persisted run: signal codes,
confidence levels, observations, per-signal evidence, and explicit
insufficient-evidence records. Heuristic observations only — not a risk score
or a verdict.

### `GET /api/wallets/ingest/{run_id}/signals/export.json` and `.../export.csv`
Download the evidence signals for one persisted run as JSON, or as flattened
CSV with one row per signal or insufficient-evidence record.

### `GET /api/wallets/ingest/{run_id}/pnl-preview`
Returns an estimated PnL preview for one persisted run: `pnl_mode`,
confidence, TON-denominated realized swap flows per token, swap rows
used/excluded, the Real-PnL evidence requirement checklist, missing-evidence
reasons, and warnings. Estimate only — never Real PnL; Real PnL stays locked
until transaction history, swap evidence, historical prices, cost basis, and
fee handling are all available. Imported-trade analysis responses are tagged
`pnl_mode: imported_pnl` with their own confidence and note.

### `GET /api/prices/historical/preview`
Returns provider-reported historical rate points for one `token` (`"ton"` or
a jetton master address) between `start` and `end` (ISO datetimes, window
capped at 90 days). Mock mode returns deterministic points without querying
TonAPI; real mode queries the TonAPI rates chart. Provider failures are
reported as `source_status: unavailable` with no hidden fallback. Preview
only — `is_cost_basis_source` stays `false` and Real PnL stays locked.

### `POST /api/wallets/cluster/compare`
Compares 2-25 persisted runs pairwise and returns a probabilistic
behavioral-similarity signal (scores, bands, shared tokens) — never proof of
common ownership.

### `GET /api/wallets/cluster/compare/export.json` and `.../export.csv`
Download a cluster comparison for the given `run_ids` as JSON or flattened
pair CSV.

### `POST /api/bitquery/token-trades/preview`
Returns a Bitquery token-trades preview when provider coverage is available.
Current TON coverage may be unavailable/provider-limited.

### `POST /api/bitquery/token-trades/analyze`
Runs imported-trade-style wallet analysis from fetched Bitquery DEX trades.
It does not fetch wallet balances, current holdings, or full on-chain history.

### `POST /api/import/trades/preview`
Parses local CSV/JSON trade input and returns validation summary plus preview
rows.

### `POST /api/import/trades/analyze`
Parses local CSV/JSON trade input and returns a simple per-wallet imported
trade analysis.

---

## How the analysis works

### PnL (`services/pnl.py`)
Average-cost basis, computed with `Decimal`. From the normalized inputs
`total_bought_qty/usd`, `total_sold_qty/usd`, `current_holding` and
`current_price_usd` it derives:

- `avg_buy_price_usd`, `avg_sell_price_usd`
- `realised_pnl_usd` / `%` — sale proceeds minus cost basis of sold quantity
- `unrealised_pnl_usd` / `%` — market value minus cost basis of remaining holding
- `total_pnl_usd` / `%`
- `status`: `holder` | `partial_seller` | `full_exit` | `unknown`

A wallet is a **partial seller** when `total_sold_qty > 0`,
`current_holding > 0`, and `total_sold_qty < total_bought_qty`.

### Clustering (`services/clustering.py`)
Pairwise behavioral similarity (0–100) across: buy time, entry price, held
tokens, partial-sell behavior, TON balance, and portfolio value. Score bands:

| Score   | Meaning                                   |
| ------- | ----------------------------------------- |
| 0–25    | weak / no signal                          |
| 26–50   | weak similarity                           |
| 51–70   | possible cluster                          |
| 71–85   | likely related behavior                   |
| 86–100  | very high similarity, **still not proof** |

Every group includes a name, type, wallet list, shared tokens, average
connected score, a reason summary, and a Russian conclusion (**Вывод**). The
wording is deliberately hedged: these are *similarity signals*, never claims of
common ownership.

### Mock data (`services/mock_data.py`)
14 wallets covering holders, partial sellers, full exits, whales (TON > 500),
ИНТЕРЕСНО wallets (a position worth > $5,000), three candidate clusters, shared
holdings, a negative realised-PnL wallet, and a large unrealised-PnL wallet.

---

## Live guard checklist

The `v0.12.0` wallet ingestion DEX-swaps milestone was considered ready when:

- the frontend builds with `npm run build`;
- final browser QA confirms `RELEASE v0.12.0 SWAPS` on desktop and mobile
  without console errors or horizontal page overflow;
- release promotion gates and commands are documented in
  `RELEASE_PROMOTION.md`;
- wallet activity schema tests and ingestion endpoint tests pass;
- backend `VERSION=0.2.1` is treated as the API-version field, not as the
  user-facing product release label;
- `POST /api/wallets/ingest/preview`, `POST /api/wallets/ingest`, and
  `GET /api/wallets/ingest/{run_id}` return data-honest mock-normalized
  responses;
- wallet activity adapter contract tests pass and prove preview/run behavior
  behind `backend/adapters/wallet_activity.py`;
- explicit `WALLET_ACTIVITY_PROVIDER` scaffold tests prove TON provider,
  STON.fi, Bitquery, and unguarded TonAPI selections return limited/unavailable
  coverage without real provider calls;
- live guard tests prove `DATA_MODE=real`, `WALLET_ACTIVITY_PROVIDER=tonapi`,
  and `WALLET_ACTIVITY_LIVE_ENABLED=true` can fetch and persist TonAPI native
  TON balance snapshots, account jetton balance snapshots, ordered
  transaction-history rows, TON/jetton transfer rows, and DEX swap rows only;
  PnL and clustering remain unavailable;
- the Wallet Activity Ingestion Workspace can preview coverage, run mock
  ingestion, refresh a stored run, and render transfers, transactions, swaps,
  balances, warnings, and provider evidence;
- provider status, TonAPI previews, STON.fi preview, Bitquery/import tools, and
  legacy mock-aware analysis render without layout overflow on desktop/mobile;
- provider preview panels show ready/running/error/fresh/stale states honestly;
- unavailable provider data stays visible and is not inferred;
- provider/source badges clearly distinguish loading, error, mock/offline,
  live, and unknown states;
- provider status endpoint coverage displays all six expected provider
  surfaces when available: GeckoTerminal, STON.fi, TonAPI, wallet activity,
  Bitquery, and TON provider;
- user-facing UI copy does not show stale product-version labels;
- accessibility pass remains intact for navigation, segmented controls, status
  strips, loading states, and dashboard sections;
- README, `RELEASE_NOTES.md`, `RELEASE_PROMOTION.md`,
  `REAL_WALLET_INGESTION_PLAN.md`, and UI release labels all identified the
  product milestone as `v0.12.0 SWAPS` at that time; the UI release label now
  tracks the current release (`v0.15.2 HISTORICAL PRICES`).

## Roadmap beyond v0.15.2 HISTORICAL PRICES

- Wire the historical price preview into cost-basis math so the
  `historical_prices` Real-PnL requirement can honestly become available
  (points exist as preview-only today; Real PnL stays locked).
- Wire the live activity surfaces (balances, transactions, transfers, swaps)
  into Real PnL instead of mock-aware legacy analysis, once historical prices
  exist and ingestion quality is measurable.
- Keep backend `VERSION` as an API-version field until the backend API contract
  changes.
- Connect real wallet activity to buyers and stored-run reports instead of
  re-running mock analysis.
- Expand Bitquery or alternate DEX coverage for TON trade history.
- Broaden the evidence-signal rule set and calibrate cluster-comparison
  confidence with richer features and clearer uncertainty bands.
