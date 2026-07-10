# TON Wallet Intelligence Dashboard — v0.22.6 ACTION IDENTITY

A local crypto intelligence dashboard for TON wallets, provider previews, and
mock-aware wallet analytics. On top of the guarded live wallet activity path
(native TON balance, account jetton balance snapshots, transaction-history
timeline, TON/jetton transfers, and DEX swaps behind explicit real-mode flags),
run-scoped intelligence covers probabilistic multi-wallet cluster comparison,
a rule-based evidence signal layer, and an estimated PnL preview
(TON-denominated realized swap flows with Real PnL locked behind explicit
evidence requirements) — each with hedged language and JSON/CSV export where
applicable. A historical price preview (provider-reported TonAPI rate points) powers an
optional USD valuation of TON-side swap legs, recorded transaction fees are
netted into after-fee figures, and an in-window average-cost pass computes
realized PnL per token. Real PnL unlocks per run only when all five evidence
requirements are met, covers in-window realized swaps only, and partial
calculations are never labeled Real PnL. An optional spot snapshot uses a
deterministic fixture in mock mode or current provider-reported prices in real
mode, values remaining in-window holdings separately from realized figures,
and names the price source. Deterministic mock data remains the default
executable ingestion path.

> **v0.22.6 ACTION IDENTITY status — guarded real/live TonAPI transfer and swap rows now preserve a strict provider-scoped event/action observation coordinate: network, canonical run account, canonical event id, canonical event LT, and the original zero-based action index before filtering. The coordinate is not blockchain proof, ownership proof, or authoritative semantic activity identity, and it is not used for deduplication, cost basis, or PnL. The bounded low-level transaction and shared account-event cursor contracts from v0.22.5 remain unchanged; derived surfaces stay explicitly incomplete even when the provider page chain terminates.**
> - Runs in `DATA_MODE=mock` (default) or `DATA_MODE=real`.
> - Provider previews are available for TonAPI account jettons, TonAPI
>   jettons-only wallet intelligence, and STON.fi pools.
> - Wallet activity ingestion now has a dashboard workspace for coverage
>   preview, persisted source-labeled runs, run refresh, evidence, warnings, and
>   normalized activity tables.
> - Wallet activity preview/run orchestration now goes through
>   `backend/adapters/wallet_activity.py`.
> - `WALLET_ACTIVITY_PROVIDER=mock` remains the default. Explicit
>   `DATA_MODE=real`, `WALLET_ACTIVITY_PROVIDER=tonapi`, and
>   `WALLET_ACTIVITY_LIVE_ENABLED=true` enable the only live wallet activity
>   path in this release: TonAPI native TON balance snapshots, account jetton
>   balance snapshots, an ordered account transaction-history timeline,
>   TON/jetton transfer history, and DEX swaps from account events. Persisted
>   transactions and swaps feed the run-scoped PnL preview; Real PnL remains
>   evidence-gated and in-window only.
> - Persisted ingestion runs can be compared pairwise (2-25 runs) as a
>   probabilistic behavioral-similarity signal with JSON/CSV export — never
>   proof of common ownership.
> - Multi-run history readiness accepts an explicit target run and 2-50
>   distinct run ids for the same network-scoped canonical run-wallet identity
>   and data mode. When canonical identity is unavailable, only an exact
>   submitted-address match is accepted as a legacy diagnostic fallback. It
>   groups transactions as exact only when a coherent persisted v0.22.3 tuple
>   is present; legacy raw transaction hashes remain weak evidence. Under
>   `wallet_history_readiness_v0.22.6`, coherent TonAPI event/action coordinates
>   are grouped separately as provider-scoped observations with explicit
>   coverage and conflicts. They remain non-authoritative and cannot establish
>   semantic transfer/swap equivalence. The report also exposes observed
>   timestamp bounds, asset-address and fee hash-match coverage, and blockers.
>   Every report remains diagnostic (`is_cost_basis: false`,
>   `eligible_for_cost_basis: false`, `used_by_pnl: false`) and is never passed
>   into PnL.
> - The wallet identity contract applies only to the wallet associated with an
>   ingestion run. For valid inputs the response exposes the persisted
>   canonical identity and contract metadata; invalid or legacy placeholder
>   values never receive an inferred identity. Low-level real/live account
>   transactions use the separate contract below. Transfer and swap rows can
>   carry the narrower provider observation identity described below;
>   authoritative transfer/swap, jetton-asset, and counterparty identity remain
>   outside this release.
> - The transaction identity contract is narrower: only low-level real/live
>   TonAPI account-transaction rows with a coherent network, canonical run
>   account, LT, 32-byte hash, and matching provider provenance receive an
>   exact tuple. The original provider fields are preserved. The tuple can
>   support future deduplication, but this release does not deduplicate rows,
>   locally verify blockchain proof, prove ownership, or feed identity into
>   PnL.
> - Versioned Alembic revisions now provide a reviewable upgrade path for the
>   existing SQLAlchemy schema. Startup creates fresh databases from the
>   baseline, adopts only an exact frozen v0.22.0 legacy schema, and fails
>   closed on partial, drifted, corrupt, or unknown revisions. Retry-safe
>   revision 0003 adds and verifies transaction identity columns and indexes,
>   backfills coherent legacy live provenance, leaves mock/malformed rows
>   explicitly unavailable, and preserves
>   history-completeness, cost-basis, and PnL semantics.
>   Revision 0004 adds retry-safe `wallet_acquisition_streams` and
>   `wallet_acquisition_pages` evidence tables with cascading foreign keys and
>   unique stream/page identities. Existing runs receive zero fabricated
>   acquisition rows.
>   Revision 0005 adds retry-safe provider event/action observation fields and
>   indexes to transfers and swaps. v0.22.5 rows lack the original action index,
>   so they remain explicitly unavailable instead of receiving a guessed key.
> - Each persisted run exposes rule-based evidence signals with confidence
>   levels and explicit insufficient-evidence records, rendered in a workspace
>   card and exportable as JSON/CSV. Signals are heuristic observations, not a
>   risk score.
> - Each persisted run exposes an estimated PnL preview (`pnl_mode`:
>   `imported_pnl` / `estimated_onchain_pnl` / `real_pnl_locked` /
>   `insufficient_data` / `real_pnl`, confidence
>   `high`/`medium`/`low`/`unavailable`):
>   TON-denominated realized swap flows only, never labeled Real PnL. Real
>   PnL stays locked until transaction history, swap evidence, historical
>   prices, cost basis, and fee handling are all available; missing evidence
>   is listed explicitly.
> - Historical rate points can be previewed per token (`"ton"` or a jetton
>   master address) from the guarded TonAPI rates chart, with a deterministic
>   mock default and no hidden fallback on provider failure. The standalone
>   preview does not mutate a run (`is_cost_basis_source: false`); the PnL
>   endpoint requests the same source separately when historical enrichment
>   is explicitly enabled.
> - The PnL preview accepts `include_historical=true` to value TON-side swap
>   legs in USD at the nearest historical TON/USD point (6h tolerance). The
>   `historical_prices` requirement becomes available only when every leg
>   matches a point; unmatched legs and provider failures stay visible with
>   no hidden fallback.
> - Recorded transaction fees (`fee_ton`) are matched to used swap rows by
>   transaction hash and netted into per-token and total after-fee figures.
>   The `fee_handling` requirement becomes available only when every used
>   swap row has a recorded fee; partial coverage stays visible as a warning.
> - With historical valuation enabled, an in-window average-cost pass
>   computes realized PnL per token (fees valued in USD at the matched
>   points). The `cost_basis` requirement becomes available only when every
>   leg carries a positive token quantity and every sell is fully covered by
>   earlier in-window buys; oversold tokens stay visible as unavailable with
>   the exact reason.
> - When all five evidence requirements are met for a run, the PnL preview
>   switches to `pnl_mode: real_pnl` (in-window realized only; unrealized
>   holdings and activity outside the window are excluded). Otherwise Real
>   PnL stays locked and partial calculations are never labeled Real PnL.
> - PnL preview JSON/CSV exports accept `include_historical=true` for
>   USD/realized rows and `include_unrealized=true` for spot rows. CSV keeps
>   unavailable records separate, reports coverage counts, and emits a priced
>   subtotal only when at least one record is computed; the default export
>   stays offline and unchanged. Empty `0/0` coverage proves only that no
>   candidates were derived, not that the wallet has no holdings.
> - `include_unrealized=true` implies historical enrichment, derives remaining
>   in-window holdings from the cost-basis pass, and values them with a
>   deterministic mock fixture or real provider-reported spot prices. Derived
>   candidates name `priced_by`; candidates missing an address or usable price
>   stay visible as unavailable. If prerequisite enrichment yields no
>   candidates, the response can be empty and the UI does not claim that no
>   holdings exist. Unrealized figures never change realized PnL or the
>   five-item Real-PnL evidence checklist.
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
> - User-facing UI copy uses the `v0.22.6 ACTION IDENTITY` product label
>   and avoids stale product version references.
> - Public release notes for the stable baseline remain in `PUBLIC_RELEASE.md`.
> - Real wallet ingestion phases remain captured in
>   `REAL_WALLET_INGESTION_PLAN.md`.
> - Wallet activity preview/run/read endpoints persist deterministic
>   mock-normalized transfers, transactions, swaps, balances, warnings, and
>   provider evidence.
> - Backend `VERSION=0.2.1` remains an API-version field; `v0.22.6 ACTION
>   IDENTITY` is the product release label.
> - Wallet clustering is probabilistic: similarity signals only, not proof of
>   common ownership.

---

## Tech stack

| Layer    | Stack                                   |
| -------- | --------------------------------------- |
| Backend  | FastAPI (Python), SQLite, SQLAlchemy, Alembic |
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
  alembic.ini          Alembic configuration
  requirements.txt
  models.py            SQLAlchemy models (AnalysisRun + wallet activity tables)
  schemas.py           Pydantic request/response schemas
  database.py          SQLAlchemy engine + session + migration startup
  conftest.py          Test path setup
  migrations/
    env.py             Metadata, URL, and shared-connection wiring
    legacy_baseline.py Frozen v0.22.0 schema compatibility manifest
    versions/
      20260710_0001_baseline.py
                       Frozen v0.22.0-compatible schema baseline
      20260710_0002_wallet_identity.py
                       Additive run-wallet identity fields + backfill
      20260710_0003_transaction_identity.py
                       Retry-safe low-level transaction identity fields + indexes
      20260710_0004_acquisition_evidence.py
                       Durable acquisition stream/page evidence foundation
      20260710_0005_event_action_identity.py
                       Provider-scoped event/action observation identity
  routers/
    tonapi.py          TonAPI account jettons + wallet intelligence previews
    stonfi.py          STON.fi pools preview
    bitquery.py        Bitquery token trades preview/analysis
    import_trades.py   CSV/JSON trade import preview/analysis
    wallet_activity.py Adapter-backed wallet activity and run intelligence endpoints
    prices.py          Standalone historical price inspection endpoint
  services/
    analysis.py        Orchestration + data_quality + provider status
    database_migrations.py
                       Fail-closed fresh/legacy migration runner
    ton_address_identity.py
                       Strict TON address parsing + canonical run-wallet identity
    ton_transaction_identity.py
                       Strict low-level TON account-transaction tuple
    ton_event_action_identity.py
                       Strict TonAPI event/action observation coordinate
    wallet_acquisition_bounds.py
                       Immutable half-open UTC interval resolution
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
    wallet_history_readiness.py
                         Read-only multi-run overlap and coverage diagnostics
    wallet_activity_signals.py
                         Rule-based evidence signals with confidence levels
    pnl_preview.py       Evidence-gated run-scoped PnL preview
    pnl_usd_valuation.py USD valuation of swap legs via historical prices
    pnl_unrealized.py    Optional spot valuation of remaining in-window holdings
    historical_pricing.py
                         Historical rate source for preview and PnL enrichment
  adapters/
    geckoterminal.py   Pool/token data — mock or real GeckoTerminal API
    wallet_activity.py Wallet activity contract + mock/scaffold adapters
    tonapi.py          TonAPI account jettons preview adapter
    stonfi.py          STON.fi pools preview adapter
    bitquery.py        DEX trades — mock/provider-limited Bitquery
    ton_provider.py    Legacy TON provider status/scaffold
  tests/               pytest suite (parser, config, data_quality, migrations,
                       PnL, wallet activity, readiness, evidence signals)

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
Startup automatically runs the checked-in migration path. A fresh database is
built from the baseline. An unversioned database is adopted only when its full
domain schema exactly matches the frozen v0.22.0 manifest and SQLite integrity
checks pass; otherwise startup stops without guessing or calling
`create_all()`. Existing application rows are preserved.

Manual verification from `backend/`:

```bash
python -m services.database_migrations
alembic -c alembic.ini current
```

The Python command uses the same safe fresh/legacy state machine as startup.
Use raw Alembic commands only after the database has a revision marker; they
do not perform frozen legacy-schema adoption on their own.

Baseline downgrade is intentionally blocked because it would destroy persisted
data. Restore a verified database backup instead of downgrading the baseline.

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

## Data modes & providers (v0.22.6 ACTION IDENTITY)

Configure providers via environment variables (copy `backend/.env.example` to
`backend/.env`):

| Variable                 | Purpose                                            |
| ------------------------ | -------------------------------------------------- |
| `DATA_MODE`              | `mock` (default) or `real`                         |
| `TON_CHECK_DB_URL`       | Optional SQLite SQLAlchemy URL; defaults locally  |
| `TON_NETWORK`            | `mainnet` (default) or `testnet`; scopes raw run-wallet and low-level transaction identities plus the guarded live path |
| `GECKOTERMINAL_BASE_URL` | GeckoTerminal v2 API base (public, no key)         |
| `TON_API_BASE_URL`       | TON indexer base URL (real TON data)               |
| `TON_API_KEY`            | TON indexer API key                                |
| `BITQUERY_API_URL`       | Bitquery endpoint (real DEX trades)                |
| `BITQUERY_API_KEY`       | Bitquery API key                                   |
| `STONFI_BASE_URL`        | STON.fi API base for pool previews                 |
| `TONAPI_BASE_URL`        | Optional TonAPI base; empty selects the official host for `TON_NETWORK`, and explicit official hosts must match it |
| `TONAPI_API_KEY`         | Optional TonAPI API key                            |
| `WALLET_ACTIVITY_PROVIDER` | `mock`, `tonapi`, `ton_provider`, `stonfi`, or `bitquery` |
| `WALLET_ACTIVITY_LIVE_ENABLED` | `false` by default; enables the guarded TonAPI live path only when `DATA_MODE=real` and `WALLET_ACTIVITY_PROVIDER=tonapi` |
| `WALLET_ACTIVITY_LIVE_JETTON_LIMIT` | TonAPI live jetton snapshot limit, clamped to `1..500` |
| `WALLET_ACTIVITY_LIVE_TX_LIMIT` | TonAPI live transaction-history page size, clamped to `1..1000` |
| `WALLET_ACTIVITY_LIVE_TX_MAX_PAGES` | Maximum bounded transaction pages per ingest run, clamped to `1..100`; reaching it remains incomplete |
| `WALLET_ACTIVITY_LIVE_EVENT_LIMIT` | Shared TonAPI account-event page size for derived transfers/swaps, clamped to `1..100` |
| `WALLET_ACTIVITY_LIVE_EVENT_MAX_PAGES` | Maximum shared bounded account-event pages per ingest run, clamped to `1..100`; reaching it remains incomplete |

When `TONAPI_BASE_URL` is empty, the backend selects `https://tonapi.io` for
mainnet or `https://testnet.tonapi.io` for testnet. A configured official host
that conflicts with `TON_NETWORK` is rejected before any live provider call.
When `TONAPI_API_KEY` is present, the base URL must use HTTPS and the
authorization header is marked non-forwardable so redirects cannot carry it to
another request origin.

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
| Wallet transfers/history/swaps/balances | mock-normalized | mock by default; the explicit TonAPI live guard paginates bounded low-level transactions plus one shared account-event display stream, and coherent derived transfer/swap rows preserve provider-scoped event/action coordinates; balances remain snapshots, derived actions remain semantically incomplete, and the observation identity is not consumed by PnL |

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
API-version field, while `v0.22.6 ACTION IDENTITY` is the current
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
transaction-history, TON/jetton transfer, and DEX swap coverage. This coverage
preview does not calculate PnL. Every request resolves one immutable
half-open UTC interval `[start, end)`. A live transaction or shared account-event
preview fetches exactly one page and reports `completion_state: preview_only`;
it does not follow the cursor or persist a run and cannot verify interval
completeness.

### `POST /api/wallets/ingest`
Persists one adapter-backed wallet activity run and returns run id, status,
provider evidence, normalized rows, unavailable surfaces, and warnings. The
default path persists deterministic mock-normalized rows. The TonAPI
live guard persists native TON balance snapshots, account jetton balance
snapshots, ordered transaction-history rows, TON/jetton transfer rows, and DEX
swap rows only. The submitted `wallet_address` remains unchanged for audit,
and `wallet_identity` exposes the persisted identity status, contract version,
TON network, canonical raw address, workchain, account id, submitted format,
and friendly-address flags. Identity metadata describes address syntax and
network scope only; `is_account_existence_proof` and `is_ownership_proof`
remain `false`. Eligible low-level real/live TonAPI transaction rows also expose
`transaction_identity`: a persisted `ton_account_tx_v1` tuple of network,
canonical run account, canonical LT, and canonical 32-byte hash. The original
`tx_hash` and `logical_time` fields remain unchanged.

Low-level `transactions` pages use `WALLET_ACTIVITY_LIVE_TX_LIMIT` and
`WALLET_ACTIVITY_LIVE_TX_MAX_PAGES`. Derived `transfers` and `swaps` now share
one account-event chain using `WALLET_ACTIVITY_LIVE_EVENT_LIMIT` and
`WALLET_ACTIVITY_LIVE_EVENT_MAX_PAGES`; requesting both surfaces does not make
two provider traversals. Every page and aggregate stream record is persisted
through migration 0004, including request/response cursors, counts, LT/time
extrema, response digest, bounds, termination reason, and sanitized failure
evidence. A bounded stream becomes `complete` only after a terminal empty page
or an ordered, verified crossing below the requested start. Page-cap exhaustion,
provider failure, malformed protocol data, a stalled/non-descending cursor, or
an in-progress event remains `incomplete` or `error`.

`account_events` uses `scope_kind: provider_display_events`. Its completion
means only that the recorded TonAPI page chain terminated for the bounded
query. TonAPI event actions can change, so derived transfer and swap surfaces
remain in `incomplete_surfaces` and the run remains partial/limited. The event
chain does not establish authoritative transfer history, full DEX history,
ownership, cost basis, or PnL. Jettons and balances remain snapshot surfaces.

For coherent guarded real/live actions, each transfer or swap also exposes
`event_action_identity` under contract `tonapi_event_action_obs_v1`. Its key is
the provider + TON network + canonical run account + canonical event id +
canonical event LT + original zero-based action index from the full provider
action array. Surface and action type are not key fields, so retyping one
coordinate is a conflict instead of a second identity. This is provider
observation identity only: `is_blockchain_proof_verified`,
`is_authoritative_activity_identity`, `is_ownership_proof`,
`eligible_for_cost_basis`, `deduplication_applied`, and `used_by_pnl` remain
false. Mock or incoherent rows expose `unavailable`.

TonAPI response handling is bounded to 16 MiB, JSON depth 64, 200,000 parsed
nodes, and 128 characters per numeric token. Oversized, excessively nested,
malformed, non-finite, or invalidly encoded JSON is reported as sanitized
provider protocol evidence rather than an uncaught parser/resource failure.

### `GET /api/wallets/ingest/{run_id}`
Returns one persisted wallet activity run by id, including provider evidence,
unavailable surfaces, normalized rows, warnings, the original submitted
`wallet_address`, and its persisted `wallet_identity`. Valid bounceable and
non-bounceable friendly forms can share one network-scoped canonical identity;
mainnet and testnet identities remain distinct. Invalid or legacy placeholder
values return explicit unavailable identity metadata instead of an inferred
address. Each transaction includes its persisted `transaction_identity`.
`is_deduplication_identity` becomes true only when the stored tuple and source
provenance remain coherent; `is_blockchain_proof_verified`,
`is_ownership_proof`, `deduplication_applied`, and `used_by_pnl` always remain
false. Pre-v0.22.3 live rows are backfilled only when their stored provenance
passes the same strict contract; mock, malformed, or inconsistent transaction
rows stay explicitly `unavailable`.

Each transfer and swap includes its persisted `event_action_identity`. Rows
written before migration 0005 do not contain the original action index, so
readback leaves them `unavailable`; it never derives an index from row order,
payload, timestamp, or type. Persisted identity fields are validated against the
run and raw provider observation before the public validity flag can be true.

The run response also returns persisted `acquisition_streams` and per-page
evidence for low-level transaction pagination and the shared account-
event display stream. Runs created before migration 0004 have no synthesized
stream or page records; their pagination state remains unavailable rather than
inferred.

### `GET /api/wallets/ingest/{run_id}/export.json` and `.../export.csv`
Download one persisted run as JSON, or as flattened one-row-per-activity CSV.
Transaction exports preserve original hash/LT fields and include the persisted
identity status, version, canonical tuple fields, and identity key. Export does
not apply deduplication or change PnL. Transfer and swap exports likewise carry
the provider event/action coordinate and all non-authoritative proof/use flags;
exporting the key does not make it a cost-basis or PnL input.

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

Token flows carry `fee_ton` and `net_ton_flow_after_fees` (plus
`total_fees_ton` and a total after-fee figure): recorded transaction fees
matched to used swap rows by transaction hash. The `fee_handling`
requirement becomes available only at full fee coverage of used swap rows.

With `include_historical=true` the response additionally values TON-side
swap legs in USD at the nearest historical TON/USD point (6h tolerance):
`usd_flows`, USD totals, and a `historical_pricing` evidence block
(source status, points fetched, matched/unmatched legs). The
`historical_prices` requirement becomes available only at full match
coverage; unmatched legs stay visible and no fallback data is substituted.
The default (parameter omitted) response is unchanged and stays offline.

The same enriched response carries `realized_pnl`: per-token in-window
average-cost results (proceeds, cost basis, realized PnL, remaining
quantity, or an explicit unavailable status with the reason) plus
`total_realized_pnl_usd`. When every evidence requirement is available the
response switches to `pnl_mode: real_pnl` with `is_real_pnl: true` —
in-window realized only; otherwise Real PnL stays locked.

With `include_unrealized=true` the endpoint also derives remaining in-window
holdings and values them with a deterministic mock fixture or current
provider-reported spot prices in real mode (`include_historical` is implied).
Each derived `unrealized` record reports its status, remaining quantity and
cost, spot price, `priced_by`, market value, and unrealized PnL, or an explicit
reason why that candidate is unavailable. If prerequisite enrichment produces
no candidates, the array can be empty. `total_unrealized_pnl_usd` is a subtotal
of computed records only; unavailable records are excluded. Spot figures are
informational and never affect realized results, `pnl_mode`, confidence, or the
Real-PnL evidence checklist.

### `GET /api/wallets/ingest/{run_id}/pnl-preview/export.json` and `.../export.csv`
Download the PnL preview as JSON, or as flattened CSV with one row per token
flow, USD flow, realized cost-basis record, spot-based unrealized record, or
Real-PnL requirement (tagged by `record_type`). Both accept
`include_historical=true` for USD/realized enrichment and
`include_unrealized=true` for unrealized rows (`include_historical` implied).
CSV preserves unavailable records, adds a coverage row, and emits a numeric
`unrealized_subtotal` row only when at least one record is computed; that
subtotal excludes unavailable records. An empty `0/0` coverage row means no
candidates were derived and does not prove that the wallet has no holdings.
The default export stays offline.
Whether figures amount to Real PnL is decided solely by requirement rows.

### `POST /api/wallets/history/readiness`

Inspects an explicit set of 2-50 persisted runs for one network-scoped
canonical run-wallet identity and data mode against a target run. Runs with
different submitted bounceable/non-bounceable representations can be grouped
when their persisted canonical identity and TON network match. If any run lacks
complete canonical identity, all runs must use the exact same submitted
`wallet_address`; that fallback stays visible as a legacy diagnostic blocker.
The response preserves each submitted address, exposes wallet identity at the
target and per-run scope, and reports observed bounds, transaction identity
coverage, overlaps, conflicts, asset-address and fee hash-match coverage, and
blockers under `analysis_version: wallet_history_readiness_v0.22.6`. An exact
transaction group requires a coherent persisted network + canonical account +
LT + 32-byte-hash tuple and matching real/live TonAPI provenance. A legacy raw
transaction hash is classified only as weak evidence. Coherent transfer and
swap event/action coordinates are grouped as `provider_scoped` observations,
with explicit coverage and changed-payload/conflicting-coordinate blockers.
They are not exact semantic swap or transfer identity. The diagnostic reports
validated per-run bounded transaction pagination and separately validates the
persisted `account_events` provider chain. Even `provider_stream_complete`
describes only TonAPI display acquisition; derived transfers/swaps, jettons,
balances, interval continuity across runs, and wallet history before the
selected runs remain unverified.
Diagnostic only: the endpoint does not apply cross-run deduplication, merge
activity, prove complete wallet history, establish cost basis, or change any
PnL result; `history_complete`,
`deduplication_applied`, `is_cost_basis`, `eligible_for_cost_basis`, and
`used_by_pnl` remain `false`.

### `GET /api/prices/historical/preview`
Returns provider-reported historical rate points for one `token` (`"ton"` or
a jetton master address) between `start` and `end` (ISO datetimes, window
capped at 90 days). Mock mode returns deterministic points without querying
TonAPI; real mode queries the TonAPI rates chart. Provider failures are
reported as `source_status: unavailable` with no hidden fallback. Preview
only — `is_cost_basis_source` stays `false` because this standalone request
does not alter a run. The PnL endpoint performs its own explicitly requested
historical enrichment against the same source.

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
  PnL and clustering were not yet available at that milestone;
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
  tracks the current release (`v0.22.6 ACTION IDENTITY`).

## Roadmap beyond v0.22.6 ACTION IDENTITY

- Add authoritative low-level transfer/trade acquisition or trace-backed
  reconstruction before treating derived transfer or swap actions as complete.
  The TonAPI event chain and v0.22.6 action coordinates remain provider
  observation evidence.
- Define appropriate temporal evidence contracts for jetton-balance and native-
  balance snapshots without mislabeling point-in-time state as history.
- Add authoritative semantic transfer/trade reconstruction plus jetton-asset
  and counterparty identity contracts, then explicit cross-run interval
  continuity and deduplication. The provider observation coordinate is not a
  substitute for semantic identity.
  One bounded low-level transaction stream cannot make multi-run data complete
  wallet history or a cost-basis source.
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
