# GRAM Scope - v0.73.0 Public Release

Public release handoff for the current TON wallet intelligence workspace.

## Public Scope

- Durable Wallet Cases keyed by canonical TON identity, network, and demo/live
  environment.
- Persisted, idempotent bounded sync jobs with polling, factual progress,
  bounded retry, cooperative cancellation, lease fencing, and restart recovery.
- Refresh-safe case Summary URLs that resume active-job status and preserve the
  latest usable partial/succeeded snapshot with explicit sync provenance.
- A snapshot-pinned Wallet Case Activity facade with cross-sync identity
  revalidation, overlap deduplication, stable cursor pagination, server-side
  filters, bounded aggregates, coverage gaps, and sanitized provenance.
- A shared Summary/Activity case shell with refresh-safe filters, sorting,
  selected-record details, keyboard focus management, and responsive cards.
- Compact case activity, portfolio snapshot, coverage, and limitation summaries
  that keep internal compatibility run IDs out of the primary workflow.
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

- Product release label: `v0.73.0 CASE ACTIVITY`.
- Backend API `VERSION` remains `0.2.1`.
- `DATA_MODE=mock` remains the default.
- Guarded live wallet ingestion requires explicit real/TonAPI/live settings.
- Demo syncs are deterministic fixtures; live syncs reject mock fallback
  evidence and network/identity mismatches before persistence.
- Wallet Cases are direct-loopback only in this pre-authentication slice.
  Hosted production access remains disabled until authentication derives the
  owner scope.
- Multi-asset readiness performs no provider request and never returns BOC or
  message-body contents.
- Provider snapshot matches are not local jetton-master proofs. Exact fee
  matches are not fee allocation. Real PnL remains locked.

## Known Limitations

- Selected bounded intervals and captures do not establish complete history.
- Activity combines only usable case syncs up to its pinned revision. Rows
  without a fully revalidated identity are intentionally not deduplicated, and
  semantic identity conflicts are published as gaps rather than guessed.
- The compact Summary remains based on the case's latest usable run while
  Activity publishes a separately labelled cross-sync aggregate at an explicit
  pinned revision. The counts are not claimed to be equivalent; unified
  Summary aggregation is deferred.
- Native proof ledgers remain a separate manually initiated evidence subset and
  are not presented as the complete or authoritative general timeline.
- The local worker replays the whole bounded crawl after an in-flight crash;
  accepted provider pages are not yet committed as resumable checkpoints.
- Cancellation is immediate while queued and cooperative around the current
  monolithic bounded provider crawl while running.
- Legacy ingestion runs are not automatically backfilled into cases when their
  canonical identity or exact acquisition bounds cannot be proven.
- Hosted Wallet Cases are a release blocker, not an accepted anonymous mode.
- TEP-74 layouts do not alone prove successful economic execution or a trade.
- Historical trade prices, ordered acquisition lots, and fee allocation are
  not established by the multi-asset readiness contract.
- Legacy buyers and the top-level report remain separate and mock-aware.
- Bitquery TON coverage remains schema/provider limited.

## Verification Summary

Before tagging `v0.73.0`, confirm:

- `npm run build` passes from `frontend/`.
- `.venv/bin/python -m pytest -q` passes from `backend/`.
- Browser QA passes on desktop and mobile without console errors or horizontal
  overflow.
- UI shows `v0.73.0` and keeps GRAM Scope branding distinct from TON asset and
  blockchain terminology.
- Create/open case, enqueue/idempotency, polling, retry/cancel, restart
  recovery, snapshot preservation, and direct URL restoration pass the
  frontend and backend vertical-slice tests.
- Activity overlap deduplication, unavailable-identity separation, semantic
  conflict gaps, token-symbol collision, snapshot-stable cursors, filters,
  direct URL restoration, and sanitized-detail tests pass.
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
