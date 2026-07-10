# TON Tracker

TON Tracker is a source-aware wallet intelligence workspace for TON. It ingests
bounded wallet activity, preserves provider and local-verification evidence,
and keeps unsupported conclusions visibly unavailable.

Current product release: **v0.26.0 — Multi-Asset PnL Readiness**<br>
Stable backend API version: **0.2.1**

## What v0.26.0 adds

The selected-run PnL evidence gate now reconciles four independent layers in
one provider-free, digest-bound response:

- the unchanged cross-run native TON dedup and exact native flow;
- locally verified and content-deduplicated TEP-74 payload observations;
- exact canonical contract matches against persisted live TonAPI jetton
  balance snapshots;
- exact transaction-hash fee matches with nanoton/TON conservation.

Provider snapshot matches remain provider-scoped observations, not locally
verified jetton-master proofs. Transaction fees remain unallocated evidence,
not acquisition/disposal lot costs. Complete history, authoritative trade
semantics, historical trade prices, cost basis, and Real PnL stay locked.

Fresh TonAPI ingestion now normalizes nested jetton wallet records to the exact
canonical contract address. Legacy stringified records are rejected instead of
being guessed or repaired during readiness analysis.

## v0.25.0 verified-payload foundation

An explicit provider-free trace-card action now decodes recognized TEP-74
jetton message layouts from the already verified transaction BOCs. It returns
only bounded semantic fields and hashes; raw message bodies, custom payloads,
forward payload contents, and token metadata remain hidden.

- Active layouts: transfer, transfer notification, burn, and excesses.
- Suggested layouts are separately labeled: internal transfer and burn
  notification.
- Unknown opcodes remain counted without inferred semantics.
- Malformed recognized layouts and changed BOC/message coordinates fail closed.
- Jetton-wallet/master contract roles remain observations, not asset identity.

The decoder follows the active
[TEP-74 Jetton standard](https://github.com/ton-blockchain/TEPs/blob/master/text/0074-jettons-standard.md).

## v0.24.0 native PnL-readiness foundation

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
- v0.25.0 provider-free verified TEP-74 payload observations.
- v0.26.0 multi-run jetton asset/fee evidence reconciliation with locked PnL.
- Run-scoped evidence signals, estimated PnL preview, clustering, and exports.
- TonAPI account/jetton previews, STON.fi pool previews, Bitquery scaffolding,
  and CSV/JSON trade import tools.

## Data-honesty rules

The application deliberately separates these concepts:

- a provider observation is not locally verified chain evidence;
- a locally verified BOC is not a blockchain inclusion proof;
- a message endpoint is not an identified actor or owner;
- a native TON movement is not necessarily a trade;
- a provider jetton snapshot match is not a locally verified master proof;
- an exact transaction fee match is not fee allocation;
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
7. Use **Decode TEP-74 payloads** to inspect recognized jetton layouts without
   returning body contents or assigning an asset identity.
8. In **Multi-asset PnL readiness**, enter one or more other compatible run
   IDs. The target run is included automatically.
9. Review canonical native flow, deduplicated jetton observations, provider
   snapshot matches, exact fee evidence, and every blocked PnL requirement.

Both readiness requests are provider-free. v0.26.0 revalidates the v0.24.0
native chain plus every selected BOC capture, snapshot match, and fee record on
every call. It performs no hidden price or provider lookup.

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
| `GET` | `.../boc-verification/jetton-payloads` | Decode recognized TEP-74 layouts provider-free |
| `GET` | `.../boc-verification/native-ton-flows` | Read account-relative native TON observations |
| `GET` | `.../boc-verification/native-ton-asset` | Read canonical native asset binding |
| `GET` | `.../boc-verification/counterparties` | Read counterparty observation groups |
| `POST` | `.../native-activity-ledger` | Build an immutable verified native ledger |
| `POST` | `/api/wallets/ingest/{target_run_id}/native-activity-merge` | Merge 2–50 compatible ledgers |
| `POST` | `/api/wallets/ingest/{target_run_id}/native-activity-dedup` | Resolve repeated native activity identities |
| `POST` | `/api/wallets/ingest/{target_run_id}/native-activity-pnl-readiness` | Reconcile native flow and evaluate PnL prerequisites |
| `POST` | `/api/wallets/ingest/{target_run_id}/multi-asset-pnl-readiness` | Reconcile native, verified jetton, snapshot asset, and fee evidence |
| `GET` | `/api/wallets/ingest/{run_id}/pnl-preview` | Read the separate run-scoped estimated PnL preview |
| `GET` | `/api/wallets/ingest/{run_id}/signals` | Read rule-based evidence signals |

The `...` paths continue from
`/api/wallets/ingest/{run_id}/transactions/{hash}/trace-evidence`.

## v0.26.0 multi-asset PnL-readiness contract

Request:

```http
POST /api/wallets/ingest/33/multi-asset-pnl-readiness
Content-Type: application/json

{"run_ids":[32,33]}
```

Important response fields:

- `contract_version`: `ton_multi_asset_pnl_readiness_v1`
- `source_native_analysis_digest_sha256` and `analysis_digest_sha256`
- `native_flow_summary`: exact native counts and nanoton/TON totals
- `jetton_evidence_summary`: capture/message, payload dedup, asset-match, and
  fee-match conservation counts
- `evidence`: bounded content-deduplicated payload rows with provider-scoped
  asset and exact transaction-fee evidence
- `requirements`: nine explicit evidence gates
- `blocked_requirement_codes`: every unavailable prerequisite
- `provider_requests_performed: false`
- `provider_snapshot_asset_identity_is_authoritative: false`
- `transaction_fee_allocation_applied: false`
- `used_by_pnl_calculation: false`
- `eligible_for_cost_basis: false`
- `is_real_pnl: false`
- `real_pnl_locked: true`

The endpoint returns `409` when selected runs, wallet/network identity, ledger,
BOC, duplicate payload, snapshot, or fee evidence is incompatible. Storage
failures return a sanitized `503`.

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

The v0.26.0 release candidate passed 986 backend tests, 101 frontend tests, the
production build, Python compilation, and the dependency audit with zero
reported vulnerabilities. Live checks covered stable provider-free analysis on
runs 32+33 and a fresh keyed TonAPI ingestion with 100/100 canonical jetton
wallet-contract snapshot addresses.

## Current limitations

- Complete wallet history is not established outside explicitly verified
  selected intervals and captures.
- TonAPI event actions remain presentation-oriented provider evidence, not
  authoritative protocol semantics.
- Local BOC verification checks internal consistency with captured evidence; it
  is not a chain inclusion or ownership proof.
- The immutable semantic ledger currently covers native TON message transfers,
  while v0.25.0 exposes verified jetton payload observations separately. A
  recognized payload does not prove successful economic execution.
- Jetton master and cross-wallet asset identity are not derived from payload
  layout alone. v0.26.0 can expose an exact provider snapshot match, but that
  match is not a locally verified master-contract proof.
- Exact stored transaction fees are linked by canonical hash but are not
  allocated to acquisitions or disposals.
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
