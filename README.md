# TON Wallet Intelligence Dashboard — v0.2

A local prototype that analyzes wallets which bought a token in a chosen time
window on a TON pool, computes realised / unrealised PnL, surfaces interesting
wallets and shared holdings, and groups wallets into **possible** behavioral
clusters.

> **v0.2 status — real data adapter layer.**
> - Runs in `DATA_MODE=mock` (default) or `DATA_MODE=real`. Mock mode is fully
>   functional and uses **realistic mock data**.
> - In `real` mode, **GeckoTerminal pool/token data can be real** (public API,
>   no key). If it fails, the app falls back to mock data and warns — it never
>   crashes.
> - **Wallet-level analysis (buyers, PnL, clustering) is still mock** in v0.2.
>   TonAPI/Toncenter and Bitquery adapters are scaffolded but not implemented;
>   without keys they return a clear `provider_not_configured` status.
> - Every analysis response carries a `data_quality` block stating exactly
>   what is real vs mock for that run.
> - Wallet clustering is **probabilistic** — similarity signals only, **not
>   proof of common ownership**.
> - The app does **not** perform real on-chain wallet analysis yet.

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
  models.py            SQLAlchemy model (AnalysisRun)
  schemas.py           Pydantic request/response schemas
  database.py          SQLite engine + session
  conftest.py          Test path setup
  services/
    analysis.py        Orchestration + data_quality + provider status
    pnl.py             Decimal-based PnL calculations
    clustering.py      Probabilistic wallet similarity / grouping
    mock_data.py       Hand-crafted mock token/pool/wallet fixtures
    export.py          CSV / JSON serialization
  adapters/
    geckoterminal.py   Pool/token data — mock or real GeckoTerminal API
    ton_provider.py    Wallet balances/transfers — mock or (later) real
    bitquery.py        DEX trades — mock or (later) real Bitquery
  tests/               pytest suite (parser, config, data_quality, PnL, clustering)

frontend/
  package.json
  vite.config.ts
  index.html
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
      TokenOverview.tsx
      BuyersTable.tsx
      WalletGroups.tsx
      CommonHoldings.tsx
      InterestingWallets.tsx
      ExportButtons.tsx

README.md
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

## Data modes & providers (v0.2)

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

What is real vs mock in v0.2:

| Data                              | mock mode | real mode                          |
| --------------------------------- | --------- | ---------------------------------- |
| Pool / token info                 | mock      | **real** GeckoTerminal (or fallback) |
| Buyers, balances, PnL, clustering | mock      | mock (real not implemented)        |

Each `/api/analyze` response includes a `data_quality` block
(`{ mode, warnings, provider_notes }`) describing the run. The UI shows a
**Data mode / Provider status** panel reflecting `GET /api/providers/status`.
A missing TON/Bitquery key yields a clear `provider_not_configured` status —
the backend never crashes.

---

## API

### `GET /api/health`
Returns service status, version, and current `data_mode`.

### `GET /api/providers/status`
Returns `data_mode` plus `{configured, available, message}` for GeckoTerminal,
the TON provider, and Bitquery.

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

## Roadmap beyond v0.2

- Implement real `adapters/ton_provider.py` against a TON indexer
  (TonAPI / Toncenter) for real wallet balances, transactions and transfers.
- Implement real `adapters/bitquery.py` for historical DEX trades, then derive
  real per-wallet buy/sell aggregates for PnL + clustering.
- Export specific stored runs by id instead of re-running an analysis.
- Richer clustering features and confidence calibration.
