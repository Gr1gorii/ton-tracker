# TON Wallet Intelligence Dashboard — v0.1

A local prototype that analyzes wallets which bought a token in a chosen time
window on a TON pool, computes realised / unrealised PnL, surfaces interesting
wallets and shared holdings, and groups wallets into **possible** behavioral
clusters.

> **v0.1 status — this is a prototype.**
> - All analysis runs on **realistic mock data**. No real APIs are connected.
> - GeckoTerminal, TonAPI, Toncenter and Bitquery are **not** integrated yet.
> - Wallet clustering is **probabilistic** — similarity signals only, **not
>   proof of common ownership**.
> - PnL is calculated by real functions over mock, normalized trade data.
> - The app does **not** perform real on-chain analysis yet.

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
  requirements.txt
  models.py            SQLAlchemy model (AnalysisRun)
  schemas.py           Pydantic request/response schemas
  database.py          SQLite engine + session
  services/
    analysis.py        Orchestrates the full analysis payload
    pnl.py             Decimal-based PnL calculations
    clustering.py      Probabilistic wallet similarity / grouping
    mock_data.py       Hand-crafted mock token/pool/wallet fixtures
    export.py          CSV / JSON serialization
  adapters/
    geckoterminal.py   Token/pool data adapter (mock-backed)
    ton_provider.py    On-chain wallet/trade adapter (mock-backed)

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

## API

### `GET /api/health`
Returns service status and version.

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
candidate clusters, common holdings, interesting wallets, and a summary.

### `GET /api/export/csv` and `GET /api/export/json`
Download placeholders. They run a fresh mock analysis and stream it back as a
downloadable CSV (wallet table) or JSON (full payload). Optional query params:
`pool_url`, `time_window`.

---

## How the analysis works (v0.1)

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

## Roadmap beyond v0.1

- Implement `adapters/geckoterminal.py` against the real GeckoTerminal API.
- Implement `adapters/ton_provider.py` against a real TON indexer
  (TonAPI / Toncenter / Bitquery) to fetch real buyers, trades and balances.
- Export specific stored runs by id instead of re-running a mock analysis.
- Richer clustering features and confidence calibration.
