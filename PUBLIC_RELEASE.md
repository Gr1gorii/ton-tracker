# GRAM Scope - v0.75.0 Public Release

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
- A durable, idempotent selected-transaction Evidence pipeline with trace
  capture, local BOC verification, TON block-inclusion proof captured at
  liteserver trust level 0 from the exact application-pinned checkpoint for its
  network, native-TON semantics, fenced leases, bounded retry, restart recovery,
  and cooperative cancellation.
- A content-addressed Wallet Case Report bound to one pinned Activity snapshot,
  its coverage and gaps, and the returned revalidated Evidence window. Useful
  observed, normalized, and partially verified revisions remain exportable;
  canonical assurance is separately hard-gated.
- A shared Summary/Activity/Evidence case shell with refresh-safe filters,
  selected-record details, verification progress, keyboard focus management,
  responsive cards, report assurance, canonical gates, and exact JSON export.
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

- Product release label: `v0.75.0 CASE REPORT`.
- Backend API `VERSION` remains `0.2.1`.
- Alembic head is `20260710_0022`: 0019 adds durable Case Evidence jobs, 0020
  versions immutable transaction-inclusion proofs by trust level, and 0021
  persists the verifier policy plus exact per-network application checkpoint
  and binds them into proof and catalog digests. Revision 0022 activates the
  application-owned strict proof-link policy without relabeling older rows.
- Current verifier policy `ton_liteserver_checkpoint_strict_2026_08_v2` pins these
  masterchain checkpoint tuples as
  `(workchain, shard, seqno, root hash, file hash)`:

  - `ton-mainnet`: workchain `-1`, shard `-9223372036854775808`, seqno
    `46894135`, root
    `3048e69a12cf946ebc99b4cf9ca61c3ff4b3fcc88c4015763ac01204ecc1bf9f`,
    file
    `bbdac0b4543e9141449ceb37c3c63ba6e9cc4e2c904d77f56d17e44acf1d1bed`.
  - `ton-testnet`: workchain `-1`, shard `-9223372036854775808`, seqno
    `58834988`, root
    `8c711614c06a513e026dd1456f2f01a3b5b412f5a99ff1b050e23e9b103231d9`,
    file
    `898c25a4599a33bea0b442e80ec3877461eaac824b497ebbbc670f7d077925d7`.

  Every current-policy proof persists its network-scoped tuple. Rows migrated
  as `legacy_unpinned_v1` have no checkpoint tuple and remain noncanonical.
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
- Case Report contract `wallet_case_report_v1` is a deterministic read model;
  its `rpt_…` ID is the SHA-256 of the exact public payload projection. It adds
  no migration, so the Alembic head remains `20260710_0022`.

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
- Evidence verification is available only for an explicitly selected live,
  provider-observed, network-scoped transaction. Demo fixtures and derived
  transfer/swap actions remain ineligible.
- The Evidence runtime requires liteserver trust level 0 under the current
  application-owned checkpoint policy. `chain_inclusion_proven` is canonical at
  capture under that exact persisted policy and checkpoint; local replay still
  validates the stored transaction/block commitment but does not independently
  re-establish later chain canonicality.
- Existing trust-level-0 proofs without the current verifier-policy and exact
  checkpoint binding remain immutable legacy evidence. They are noncanonical
  and cannot be selected, promoted, or combined with current-policy proofs.
- The selected native-TON artifact and the Case Report do not establish
  complete wallet history, cost basis, or PnL eligibility. Noncanonical report
  assurance and every unmet hard gate remain visible.
- The service recomputes the content-addressed revision from its pinned snapshot
  and persisted Evidence. Exported documents remain independently identifiable,
  but the server does not yet keep a browsable historical report-revision
  catalog or automatically select proof targets.
- The local worker replays the whole bounded crawl after an in-flight crash;
  accepted provider pages are not yet committed as resumable checkpoints.
- Case-sync cancellation is immediate while queued and cooperative around the
  current monolithic bounded provider crawl while running. Evidence cancellation
  is cooperatively polled while running; during inclusion, its wait cannot exceed
  the whole-operation child-process deadline plus the bounded terminate/kill
  grace.
- The liteserver child process covers config acquisition, startup, proof work,
  and shutdown under one hard deadline. Deadline expiry terminates the child and
  escalates to a forced kill instead of leaving an unbounded worker behind.
- A production Evidence worker requires
  `TON_LITECLIENT_CACHE_DIRECTORY=/data/liteclient` on a writable, persistent,
  lock-serialized volume; ephemeral or read-only cache paths are unsupported.
- Legacy ingestion runs are not automatically backfilled into cases when their
  canonical identity or exact acquisition bounds cannot be proven.
- Hosted Wallet Cases are a release blocker, not an accepted anonymous mode.
- TEP-74 layouts do not alone prove successful economic execution or a trade.
- Historical trade prices, ordered acquisition lots, and fee allocation are
  not established by the multi-asset readiness contract.
- Legacy buyers and the top-level report remain separate and mock-aware.
- Bitquery TON coverage remains schema/provider limited.

## Verification Summary

Before tagging `v0.75.0`, confirm:

- `npm run build` passes from `frontend/`.
- `.venv/bin/python -m pytest -q` passes from `backend/`.
- Browser QA passes on desktop and mobile without console errors or horizontal
  overflow.
- UI shows `v0.75.0` and keeps GRAM Scope branding distinct from TON asset and
  blockchain terminology.
- Create/open case, enqueue/idempotency, polling, retry/cancel, restart
  recovery, snapshot preservation, and direct URL restoration pass the
  frontend and backend vertical-slice tests.
- Activity overlap deduplication, unavailable-identity separation, semantic
  conflict gaps, token-symbol collision, snapshot-stable cursors, filters,
  direct URL restoration, and sanitized-detail tests pass.
- Evidence eligibility, enqueue/idempotency, stage persistence, lease fencing,
  retry/cancel/restart, partial-result preservation, snapshot provenance,
  response redaction, direct URL restoration, and runner-availability tests
  pass.
- Case Report reproducibility, content-ID binding, snapshot/Evidence scope,
  assurance transitions, canonical negative gates, response redaction, export,
  refresh invalidation, and cross-snapshot race tests pass.
- Migration 0021, current-policy selection, legacy trust-0 rejection,
  checkpoint/digest binding, whole-operation timeout, terminate/kill cleanup,
  cancellation bound, and locked persistent-cache tests pass.
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
