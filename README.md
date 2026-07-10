# TON Tracker

TON Tracker is a source-aware wallet intelligence workspace for TON. It ingests
bounded wallet activity, preserves provider and local-verification evidence,
and keeps unsupported conclusions visibly unavailable.

Current product release: **v0.24.0 — Native Activity PnL Readiness**<br>
Stable backend API version: **0.2.1**

## What v0.24.0 adds

The multi-run native activity pipeline is now connected to an explicit PnL
evidence gate:

1. A finalized TonAPI trace is captured as immutable relational evidence.
2. Transaction BOCs are deserialized and checked locally against that graph.
3. Verified native TON messages become content-addressed activity rows.
4. Compatible run ledgers are merged in deterministic chronological order.
5. Repeated activity identities are resolved to one canonical occurrence while
   every suppressed source remains visible.
6. The selected native activity is reconciled into incoming, outgoing, self,
   and net TON flow.
7. Cost basis and PnL remain locked until complete history, verified trade
   semantics, jetton identity, historical prices, and fee allocation exist.

Native message value is never presented as a swap, acquisition lot, sale,
profit, ownership proof, or complete wallet history.

## Main capabilities

- Dark, responsive wallet evidence workspace.
- Mock mode for deterministic local development.
- Guarded live TonAPI wallet ingestion for transactions, provider-derived
  transfers/swaps, jetton balances, and native TON balance snapshots.
- Frozen half-open acquisition windows with explicit pagination evidence.
- Network-scoped wallet and transaction identities.
- Persisted run catalog and provider-free stored-run loading.
- Selected-run interval continuity diagnostics.
- Explicit transaction trace preview and immutable trace capture.
- Local transaction/message BOC verification with bounded parsing.
- Body-safe message evidence, native TON flow observations, native asset
  identity, and counterparty observation identity.
- Immutable native activity ledgers, multi-run merge, and cross-run dedup.
- v0.24.0 native TON flow reconciliation and fail-closed PnL readiness.
- Run-scoped evidence signals, estimated PnL preview, clustering, and exports.
- TonAPI account/jetton previews, STON.fi pool previews, Bitquery scaffolding,
  and CSV/JSON trade import tools.

## Data-honesty rules

The application deliberately separates these concepts:

- a provider observation is not locally verified chain evidence;
- a locally verified BOC is not a blockchain inclusion proof;
- a message endpoint is not an identified actor or owner;
- a native TON movement is not necessarily a trade;
- adjacent selected windows are not complete wallet history;
- net wallet flow is not PnL;
- cost basis is unavailable until acquisition lots, prices, and fees are
  sufficiently established.

Unavailable and incomplete evidence is returned in the API and rendered in the
interface instead of being silently substituted.

## Architecture

```text
frontend/                    React 18, TypeScript, Vite
backend/
  adapters/                  Provider-specific network clients
  routers/                   FastAPI routes
  services/                  Source-independent evidence and analysis logic
  migrations/versions/       Forward-only Alembic revisions
  tests/                     Backend contract, migration, and service tests
  ton_check.db               Local SQLite database, ignored by Git
```

Backend: FastAPI, SQLAlchemy, SQLite, Pydantic, Alembic.<br>
Frontend: React, TypeScript, Vite, Vitest.

The current schema head is `20260710_0008`. The application applies migrations
on backend startup.

## Requirements

- Python 3.10 or newer
- Node.js `^20.19.0` or `>=22.12.0`
- npm 10 or newer

## Quick start in mock mode

### Backend

```bash
cd backend
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env
.venv/bin/uvicorn main:app --host 127.0.0.1 --port 8000
```

### Frontend

In a second terminal:

```bash
cd frontend
npm install
npm run dev -- --host 127.0.0.1
```

Open [http://127.0.0.1:5173/](http://127.0.0.1:5173/). API health and generated
OpenAPI documentation are available at
[http://127.0.0.1:8000/api/health](http://127.0.0.1:8000/api/health) and
[http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs).

## Guarded live TonAPI mode

Keep credentials only in `backend/.env`, which is ignored by Git:

```dotenv
TONAPI_API_KEY=your_key_here
```

Start live ingestion with the guards set explicitly for that process:

```bash
cd backend
DATA_MODE=real \
WALLET_ACTIVITY_PROVIDER=tonapi \
WALLET_ACTIVITY_LIVE_ENABLED=true \
TON_NETWORK=mainnet \
.venv/bin/uvicorn main:app --host 127.0.0.1 --port 8000
```

Use `TON_NETWORK=testnet` only with testnet addresses and the matching official
TonAPI host. Keyed requests require HTTPS, do not follow authorization through
redirects, and return sanitized provider errors.

Never place provider keys in frontend variables, URLs, fixtures, logs, commits,
screenshots, or issue text. Rotate any key that has been exposed outside the
local ignored environment file.

## Wallet workflow

1. Open **Wallet Activity Ingestion Workspace**.
2. Enter a TON address, select a bounded window and requested surfaces.
3. Preview first, then persist the run when the evidence scope is acceptable.
4. Reopen stored runs from the recent-run catalog without contacting a provider.
5. For a real low-level transaction, explicitly inspect the trace, capture the
   finalized trace, and perform local BOC verification.
6. Build the immutable native activity ledger for verified captures.
7. In **Native activity PnL readiness**, enter one or more other compatible run
   IDs. The target run is included automatically.
8. Review canonical activity count, suppressed repeats, native TON flow, and
   every available or blocked PnL requirement.

The v0.24.0 readiness request is provider-free. It revalidates persisted
ledgers, merge and dedup evidence on every call and performs no hidden price or
provider lookup.

## Core wallet API

| Method | Endpoint | Purpose |
| --- | --- | --- |
| `POST` | `/api/wallets/ingest/preview` | Preview one bounded ingestion request |
| `POST` | `/api/wallets/ingest` | Persist one accepted ingestion run |
| `GET` | `/api/wallets/ingest?limit=8` | Read the bounded newest-run catalog |
| `GET` | `/api/wallets/ingest/{run_id}` | Load one persisted run provider-free |
| `POST` | `/api/wallets/history/readiness` | Inspect selected-run evidence and interval continuity |
| `GET` | `/api/wallets/ingest/{run_id}/transactions/{hash}/trace-evidence` | Explicit provider trace preview |
| `POST` | `/api/wallets/ingest/{run_id}/transactions/{hash}/trace-evidence/persisted` | Persist finalized trace evidence |
| `POST` | `/api/wallets/ingest/{run_id}/transactions/{hash}/trace-evidence/boc-verification` | Persist locally verified BOCs |
| `GET` | `.../boc-verification/messages` | Read body-safe verified message evidence |
| `GET` | `.../boc-verification/native-ton-flows` | Read account-relative native TON observations |
| `GET` | `.../boc-verification/native-ton-asset` | Read canonical native asset binding |
| `GET` | `.../boc-verification/counterparties` | Read counterparty observation groups |
| `POST` | `.../native-activity-ledger` | Build an immutable verified native ledger |
| `POST` | `/api/wallets/ingest/{target_run_id}/native-activity-merge` | Merge 2–50 compatible ledgers |
| `POST` | `/api/wallets/ingest/{target_run_id}/native-activity-dedup` | Resolve repeated native activity identities |
| `POST` | `/api/wallets/ingest/{target_run_id}/native-activity-pnl-readiness` | Reconcile native flow and evaluate PnL prerequisites |
| `GET` | `/api/wallets/ingest/{run_id}/pnl-preview` | Read the separate run-scoped estimated PnL preview |
| `GET` | `/api/wallets/ingest/{run_id}/signals` | Read rule-based evidence signals |

The `...` paths continue from
`/api/wallets/ingest/{run_id}/transactions/{hash}/trace-evidence`.

## v0.24.0 PnL-readiness contract

Request:

```http
POST /api/wallets/ingest/33/native-activity-pnl-readiness
Content-Type: application/json

{"run_ids":[32,33]}
```

Important response fields:

- `contract_version`: `ton_native_activity_pnl_readiness_v1`
- `source_dedup_digest_sha256` and `analysis_digest_sha256`
- `flow_summary`: exact native counts and nanoton/TON totals
- `requirements`: seven explicit evidence gates
- `blocked_requirement_codes`: every unavailable prerequisite
- `native_activity_used_by_pnl_readiness: true`
- `native_activity_used_by_pnl_calculation: false`
- `eligible_for_cost_basis: false`
- `is_real_pnl: false`
- `real_pnl_locked: true`

The endpoint returns `409` when selected runs, wallet/network identity, ledger
evidence, or duplicate semantics are incompatible. Storage failures return a
sanitized `503`.

## Testing

Backend:

```bash
cd backend
.venv/bin/python -m pytest -q
.venv/bin/python -m compileall -q main.py config.py database.py models.py schemas.py adapters services routers tests
```

Frontend:

```bash
cd frontend
npm test -- --run
npm run build
npm audit --audit-level=moderate
```

Release gates also include migration parity, credential/prohibited-brand scans,
live local contract checks, and responsive browser QA.

The v0.24.0 release candidate passed 966 backend tests, 99 frontend tests, the
production build, Python compilation, and the dependency audit with zero
reported vulnerabilities. The live local two-run check reconciled two canonical
outgoing activities totaling 3.34 TON, kept PnL locked, and the desktop browser
check reported no horizontal overflow or error/warning log entries.

## Current limitations

- Complete wallet history is not established outside explicitly verified
  selected intervals and captures.
- TonAPI event actions remain presentation-oriented provider evidence, not
  authoritative protocol semantics.
- Local BOC verification checks internal consistency with captured evidence; it
  is not a chain inclusion or ownership proof.
- The immutable semantic ledger currently covers native TON message transfers,
  not locally verified jetton trade actions.
- v0.24.0 reconciles native wallet flow but intentionally does not calculate
  cost basis, realized PnL, or unrealized PnL from that flow.
- The older run-scoped PnL preview is a separate estimate path and may unlock
  only when all of its own transaction, swap, price, basis, and fee requirements
  are satisfied.

## Documentation

- [Real wallet ingestion plan](REAL_WALLET_INGESTION_PLAN.md)
- [Release notes](RELEASE_NOTES.md)
- [Release promotion checklist](RELEASE_PROMOTION.md)
- [Public release history](PUBLIC_RELEASE.md)

## License

No license file is currently included. Treat the repository as all rights
reserved until a license is added.
