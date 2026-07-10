# TON Wallet Intelligence Dashboard - v0.26.0 Public Release

Public release handoff for the current TON wallet intelligence workspace.

## Public Scope

- Responsive TON wallet evidence workspace with guarded real TonAPI ingestion.
- Bounded transaction/event pagination and network-scoped identities.
- Immutable trace capture and local transaction/message BOC verification.
- Body-safe TEP-74 payload observations for recognized jetton layouts.
- Immutable native activity ledgers with explicit multi-run merge and dedup.
- Provider-free multi-asset PnL readiness over native flow, verified jetton
  observations, provider snapshot asset matches, and exact transaction fees.
- Stored-run signals, estimated PnL preview, clustering, exports, provider
  previews, and visible limitations remain separate scoped surfaces.

## Release Contract

- Product release label: `v0.26.0 MULTI-ASSET PNL READINESS`.
- Backend API `VERSION` remains `0.2.1`.
- `DATA_MODE=mock` remains the default.
- Guarded live wallet ingestion requires explicit real/TonAPI/live settings.
- Multi-asset readiness performs no provider request and never returns BOC or
  message-body contents.
- Provider snapshot matches are not local jetton-master proofs. Exact fee
  matches are not fee allocation. Real PnL remains locked.

## Known Limitations

- Selected bounded intervals and captures do not establish complete history.
- TEP-74 layouts do not alone prove successful economic execution or a trade.
- Historical trade prices, ordered acquisition lots, and fee allocation are
  not established by the multi-asset readiness contract.
- Legacy buyers and the top-level report remain separate and mock-aware.
- Bitquery TON coverage remains schema/provider limited.

## Verification Summary

Before tagging `v0.26.0`, confirm:

- `npm run build` passes from `frontend/`.
- `.venv/bin/python -m pytest -q` passes from `backend/`.
- Browser QA passes on desktop and mobile without console errors or horizontal
  overflow.
- UI shows `RELEASE v0.26.0 MULTI-ASSET PNL READINESS`.
- Real stored-run multi-asset readiness is provider-free, digest-stable, and
  fail-closed for unavailable/malformed evidence.
- Credential and prohibited-brand scans are clean.

## Next Tracks

The original v0.10.7 public baseline was followed by `v0.11.1 SCHEMA`, which
added wallet activity schema
scaffolding, `v0.11.2 MOCK INGEST` proves that schema with deterministic
mock-normalized ingestion, `v0.11.3 INGEST UI` adds the dashboard workflow, and
`v0.11.4 ADAPTERS` adds the backend wallet activity adapter interface with the
mock adapter as the default active provider. `v0.11.5 SCAFFOLDS` adds
provider-specific wallet activity scaffolds behind `WALLET_ACTIVITY_PROVIDER`
and the public provider status row. `v0.11.6 LIVE GUARDS` adds the first
guarded live wallet activity path: TonAPI account jetton balance snapshots,
enabled only with `DATA_MODE=real`, `WALLET_ACTIVITY_PROVIDER=tonapi`, and
`WALLET_ACTIVITY_LIVE_ENABLED=true`. `v0.11.7 BALANCES` expands that guarded
path to native TON balance snapshots, `v0.11.8 HISTORY` adds an ordered
account transaction-history timeline, `v0.11.9 TRANSFERS` adds TON/jetton
transfer history from account events, and `v0.12.0 SWAPS` adds DEX swaps from
account events — completing the live activity surface set — while keeping the
following deferred behind the contract in `REAL_WALLET_INGESTION_PLAN.md`:

- real wallet-level PnL and clustering inputs;
- wiring live activity into legacy buyers, exports, and reports.
