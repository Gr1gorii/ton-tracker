# GRAM Scope — v0.90.0 Promotion Checklist

Current promotion gates for content-addressed Wallet Case checkpoint chains:

- Product label is `v0.90.0 CHECKPOINT CHAIN`; backend API version stays
  independently frozen at `0.2.1`.
- Alembic reaches revision `20260828_0028` with exact model parity from fresh,
  legacy, current-0018/0019/0020/0021, and every accepted interrupted table/index
  path. Missing or changed columns, checks, foreign keys, delete actions, and
  indexes fail closed; downgrade remains unsupported. Revision 0020 versions
  proofs by trust level. Revision 0021 persists the verifier policy and exact
  application-pinned network checkpoint and covers both in the proof/catalog
  digests. Revision 0022 separates the strict proof-chain policy from prior
  checkpoint rows. The accepted policy is
  `ton_liteserver_checkpoint_strict_2026_08_v2`.
  Existing trust-level-0 rows remain preserved as `legacy_unpinned_v1`,
  noncanonical evidence and are never selected by the current policy. Existing
  `ton_liteserver_checkpoint_2026_08_v1` rows also remain noncanonical legacy
  checkpoint evidence.
- Revision 0023 adds the immutable Wallet Case Report revision table. Fresh,
  0022 upgrade, exact empty interrupted-DDL resume, same-name drift, row
  adoption, and forward-only behavior must all pass fail-closed tests.
- Revision 0024 adds retained Wallet Case lifecycle audit receipts. Fresh, 0023
  upgrade, exact empty interrupted-DDL resume, same-name drift, row adoption,
  and forward-only behavior must pass fail-closed tests. The table has no case
  foreign key and retains no wallet address, label, note, payload, or proof.
- Revision 0025 appends a positive, non-null `metadata_version` to every Wallet
  Case. Fresh, 0024 upgrade, exact interrupted-DDL resume, column drift,
  invalid existing values, model parity, and forward-only behavior must pass
  fail-closed tests.
- Revision 0026 adds a case-owned append-only Wallet Case catalog event journal. Existing
  active and archived Cases receive one deterministic visibility/position seed;
  exact empty interrupted-DDL resume, row adoption, foreign-key/index drift,
  schema parity, cascade, and forward-only behavior must pass fail-closed tests.
- Revision 0027 adds exactly one immutable acquisition manifest per published
  CaseSync. Fresh creation, 0026 upgrade, exact empty interrupted-DDL resume,
  row-adoption rejection, index/check/foreign-key parity, CaseSync cascade, and
  forward-only behavior must pass fail-closed tests.
- Revision 0028 adds immutable checkpoint revisions per published provider
  stream. Fresh creation, 0027 upgrade, exact empty interrupted-DDL resume,
  row-adoption rejection, index/check/foreign-key parity, cascade behavior, and
  forward-only behavior must pass fail-closed tests.
- Manifest canonical JSON and its `smf_<sha256>` identity bind Case/sync scope,
  provider and data mode, terminal state, snapshot/acquisition periods,
  incremental lineage, requested surfaces, sanitized streams/pages, and valid
  provider response digests. Raw payloads, provider queries/messages,
  credentials, database IDs, and internal run IDs must remain absent.
- Final publication inserts ingestion run, terminal sync state, catalog event,
  and manifest under one lease-fenced transaction. A stale owner must roll all
  of them back together. Existing usable rows without a manifest remain valid
  only with `acquisition_manifest_unavailable`.
- Sync responses expose only the compact descriptor. The case-scoped manifest
  endpoint revalidates canonical JSON, SHA-256, and Case/sync identity before
  returning the full provider-safe document; Summary loads it explicitly.
- A checkpoint may be `ready` only when a successful page and the stream
  terminal cursor agree and termination is page-cap or provider-error based.
  Complete and blocked states retain no continuation cursor.
- Resume enqueue accepts only the latest verified `ready` checkpoint for a
  supported TonAPI transaction or account-event stream. The checkpoint ID is
  bound into the idempotency fingerprint and one active Case sync remains the
  concurrency boundary.
- Before provider I/O the worker must reload and revalidate checkpoint content
  address, source manifest and sync, latest provider/stream revision, provider
  contract, original bounds, requested surfaces, cursor, and next page index.
  Stale, corrupt, blocked, complete, foreign, or incompatible state fails
  closed without provider access.
- Resume UI actions appear only for `ready` checkpoints and use the durable
  sync polling/reconnect/cancel path. Resume snapshots expose base and source
  checkpoint lineage and retain the explicit not-full-history limitation.
- Checkpoint history must freeze its newest revision cutoff on the first page,
  authenticate every continuation against Case/cutoff/keyset position, reject
  duplicate or unsupported query parameters, and expire cursors after process
  restart rather than accepting an unauthenticated continuation.
- Exact and history reads must recursively revalidate content address, source
  manifest, acquisition plan, parent ordering, base snapshot, provider/stream
  identity, and provider contract. Summary must preserve a frozen loaded set,
  reject cutoff drift or duplicate revisions, and state that the journal does
  not prove complete wallet history.
- Exact, history, and chain reads share the same fail-closed root-to-tip
  traversal and reject a lineage deeper than 100 revisions. A chain document
  must preserve ordered parent/base linkage and recompute its `cch_<sha256>`
  identity from canonical JSON before it is accepted by either server or
  client.
- Chain page totals must equal the represented immutable checkpoint revisions,
  while the current state and next page must come from the selected tip.
  Summary loads the chain only on an explicit action and exports the strictly
  parsed document without describing it as automatic backfill or complete
  wallet history.
- Incremental enqueue requires the latest usable base snapshot, identical
  surfaces, and a forward request time. It persists a composed snapshot period,
  a 15-minute acquisition overlap, the actual provider bounds, and the base
  snapshot public ID. Mode participates in idempotency.
- Workers acquire only the persisted incremental bounds. Activity validates
  runs and live rows against each source acquisition interval, composes sources
  up to the pinned snapshot, and deduplicates overlap observations.
- Incremental responses expose their mode, base, overlap, and acquisition
  interval, remain partial with respect to the composed coverage claim, and
  disclose that compact Summary counts describe only the latest acquisition.
- Case catalog search matches label, note, display address, and canonical wallet
  key case-insensitively while treating `%`, `_`, and `\\` as literal text.
  Network and data-environment filters are exact, optional, and independently
  echoed in every response.
- Catalog cursor version 3 authenticates the normalized discovery filter digest
  together with owner scope, lifecycle state, frozen cutoff, and keyset
  position. Reusing a cursor after any filter change must fail closed.
- The `/cases` URL round-trips lifecycle, applied search, network, and
  demo/live state. Refresh and back/forward restore that state; ambiguous,
  duplicate, noncanonical, and unsupported parameters resolve to not found.
- Evidence is bound to one owner-scoped case, usable pinned snapshot, exact
  source synchronization, and a revalidated provider-observed transaction.
  Demo fixtures, transfers, swaps, unknown linkage, and mismatched source scope
  never enter the proof job.
- POST persists a queued job before proof I/O. UUID idempotency replay returns
  the same job, a reused key with another fingerprint fails closed, and one
  case/snapshot/Activity/policy selection has at most one active verification.
- Claiming is lease-fenced and heartbeat-protected. Restart recovery resumes
  from the last revalidated immutable artifact; bounded retry distinguishes
  transient provider failures from permanent protocol/scope conflicts.
- Cancellation is immediate while queued and cooperatively polled while proof
  work is running. Inclusion cancellation becomes observable after at most the
  current whole-operation subprocess deadline plus its bounded terminate/kill
  grace. Stale workers cannot publish progress or terminal state after losing
  their lease.
- TonAPI and liteserver calls hold no application database connection. The
  complete liteserver operation, including config acquisition, startup, proof
  work, and shutdown, runs in a child process behind one hard deadline; timeout
  first terminates and then force-kills it after a bounded grace. Source
  coordinates and every returned candidate are reloaded and revalidated before
  immutable persistence or Case-job progress is committed.
- Trace capture remains normalized evidence and local BOC verification raises
  the level only to locally verified. `chain-inclusion-proven` additionally
  requires every block proof to have been captured at trust level 0 from the
  exact current application-pinned checkpoint for its TON network. The persisted
  policy/checkpoint binding must reproduce the proof and catalog digests.
  Canonicality is asserted at capture under that policy, not recreated by an
  offline BOC replay. Trust level 1 and legacy unpinned trust-0 evidence cannot
  satisfy current-policy promotion; without a complete current set the job stops
  as a disclosed noncanonical partial. A partial job exposes only artifacts
  that still bind to the pinned selection and includes an explicit limitation.
- Production configuration supplies
  `TON_LITECLIENT_CACHE_DIRECTORY=/data/liteclient` on the writable persistent
  data volume. Cache creation and reuse are lock-serialized; inability to
  create/write the directory or an unsafe path fails the applicable gate.
- Public catalog/job responses contain only non-sequential case identifiers,
  sanitized provenance, factual progress, safe messages, and evidence digests.
  Raw BOCs/provider payloads, compatibility run IDs, database IDs, lease data,
  idempotency keys, worker lifecycle checkpoint state, SQL diagnostics, and
  credentials are absent.
- Runtime readiness is factual: a disabled or dead local Evidence runner makes
  the action unavailable and publishes a machine-readable limitation instead
  of allowing a deterministic failing POST.
- Summary, Activity, Findings, Evidence, and Reports routes survive direct navigation, refresh,
  back/forward, transient transport failures, and active-job polling. Keyboard
  focus, cancellation confirmation, narrow layouts, and both themes pass.
- The report is pinned to one immutable CaseSync snapshot, content-addressed by
  its exact public payload projection, and rebuilt deterministically from
  Activity plus revalidated persisted Evidence. Observed, normalized, and
  partially verified revisions remain useful and exportable. Canonical requires
  every published hard gate; one failed proof does not destroy the report.
- Report history is populated only through an explicit capture. The same exact
  content replays idempotently, saved documents are revalidated on every read,
  and catalog pagination freezes a revision cutoff with a case-bound signed
  cursor. Process-local cursor lifetime and the absence of automatic capture of
  intermediate Evidence states remain disclosed limitations.
- Report comparison revalidates both immutable stored documents and requires
  one owner-scoped case and public subject identity. Its `rcmp_…` document binds
  ordered baseline and target summaries, exact directional deltas, comparison
  limitations, and the distinction between same- and cross-snapshot scope.
  It never interprets a delta as causality or reconstructs uncaptured states.
- DELETE requires the local owner scope and no queued/running CaseSync or
  Evidence job. The transaction removes only case-owned syncs, unique ingestion
  runs and their normalized/proof artifacts, Evidence jobs, and Report
  revisions; unrelated cases and unscoped legacy runs remain. The UI requires
  exact typed confirmation and validates the returned case-bound receipt.
- PATCH accepts only a bounded label and/or note plus the exact positive
  `expected_metadata_version`. The owner-scoped conditional update increments
  the version exactly once, returns safe structured conflict detail for a stale
  editor, and cannot mutate canonical identity or revive an archived Case.
- GET `/api/v1/cases` remains owner-scoped and accepts one canonical limit from
  1 through 50, one explicit `active|archived` state, and one optional signed
  continuation. The cursor binds the owner, lifecycle state, frozen event
  cutoff, and keyset position. The `/cases` UI appends bounded pages, rejects
  duplicate, overlapping, cross-state, contradictory, or stalled continuations,
  aborts obsolete reads, and preserves loaded pages on failure.
- POST archive requires the local owner scope and no queued/running CaseSync or
  Evidence job. It appends an invisible catalog event and retains every
  case-owned snapshot, normalized row, proof artifact, note, and Report revision.
  POST restore appends a visible event and returns the Case as the newest active
  catalog entry. Both transitions are response-bound and idempotent.
- The workspace distinguishes reversible archive from permanent typed-confirmation
  deletion. The Library exposes accessible Active and Archived tabs, truthful
  state-specific empty/error/loading views, paged archive history, stale-snapshot
  guards, and restore only after a strictly validated case-bound response.
- Report output always includes assurance, coverage, gaps, limitations,
  unverified claims, Activity/Evidence revision digests, and fixed false
  boundaries for complete history, cost basis, PnL, raw payload inclusion, and
  provider-free whole-report revalidation. It never exposes run/source IDs or
  raw proof/provider data.
- Findings are rebuilt from exactly one pinned Activity revision and its
  revalidated Evidence catalog. Canonical asset identity is the sole asset
  grouping key; symbol collisions remain separate. Every published rule is
  versioned, deterministic, content-addressed, and either links public Activity
  support or names a revision-level gap/conflict basis.
- Findings never claim an opaque risk score, safe or illicit status, ownership,
  actor identity, full history, cost basis, cross-asset comparability, or PnL.
  An empty finding set retains the explicit not-safe limitation.
- The native-TON artifact remains selected evidence only: it is not
  authoritative general Activity, does not establish complete history or cost
  basis, and is not used by PnL. The report does not inflate that artifact.
- The pre-authentication facade and Evidence runner are direct-loopback only.
  Hosted access remains disabled until authentication supplies an owner scope;
  v0.90.0 must not be promoted as a hosted Wallet Case release.
- Backend, frontend, migration rehearsal, production contract, browser, live
  provider, credential, and prohibited-brand checks pass before tagging.

---

## Historical v0.26.0 evidence checklist

Operational gates for multi-asset PnL-readiness evidence.

## Version and migration

- Product label is `v0.26.0 MULTI-ASSET PNL READINESS`; backend API version stays
  independently frozen at `0.2.1`.
- New public contract is `ton_multi_asset_pnl_readiness_v1`; payload, BOC,
  native readiness, dedup, merge, and all persisted contracts remain unchanged.
- Alembic head is `20260710_0008`, adding native activity ledgers and rows on
  top of the unchanged 0007 BOC tables.
- Fresh, 0006 upgrade, exact empty interrupted DDL, and already-current paths
  have model parity. Drift, orphan fragments, unexpected rows/indexes/FKs,
  offline SQL, and downgrade fail closed.
- No migration is added. README and release operations describe the exact
  v0.26.0 evidence and non-authority boundaries.

## Verification contract

- Verification requires an eligible real/live TonAPI transaction inside an
  existing finalized persisted trace capture.
- First POST performs exactly one `GET /v2/traces/{hash}`. GET and repeated POST
  are provider-free, mutation-free, and reparse all stored BOCs.
- The verifier is pinned to `pytoniq-core==0.1.46`; an absent or different
  version fails closed.
- Each BOC is lowercase even hex, at most 1 MiB; aggregate storage is at most
  8 MiB. Exactly one BOC root and no unconsumed transaction root data are
  accepted.
- Transaction cell hash, account hash, LT, unix time, aborted state, and raw
  outgoing count match the immutable trace node.
- Internal and external message hash conventions, headers, values, fees,
  flags, timestamps, endpoints, and body hashes are locally re-derived.
- External-in provider hashes use the official normalized message-cell layout;
  internal and external-out messages use direct cell hashes.
- Parent outgoing messages partition exactly into child inbound edges plus
  remaining outbound observations.
- Canonical per-transaction and verification SHA-256 digests cover raw BOCs,
  derived evidence, pinned verifier, capture digest, network, and timestamp.
- Raw BOCs and message bodies remain database-only and are absent from every
  response. No semantic transfer/swap, authority, ownership, merge,
  deduplication, cost-basis, or PnL flag is promoted.

## Endpoint and UI

- POST `.../{target_run_id}/multi-asset-pnl-readiness` is provider-free and
  first revalidates the unchanged native PnL-readiness chain.
- Every selected trace capture with BOC verification is fully reparsed through
  the v0.25.0 payload contract. Payload identities are content-deduplicated;
  conflicting semantics under one identity fail closed.
- Observed wallet/master contract roles match only strict canonical addresses
  from persisted real/live TonAPI jetton snapshots. Ambiguous master or decimal
  evidence fails closed; malformed legacy wallet-object strings stay invalid.
- Exact persisted transaction fees match by network-scoped canonical hash and
  conserve TON/nanoton. They remain unallocated evidence and never become lot
  costs.
- The nine-item gate may mark verified payload, provider snapshot, or exact fee
  evidence available, while complete history, authoritative trades, historical
  prices, fee allocation, acquisition lots, cost basis, and Real PnL remain
  unavailable.
- The UI shows native flow, payload dedup, asset and fee matches, bounded rows,
  every requirement reason, digest, and the permanent PnL lock.
- GET `.../boc-verification/jetton-payloads` is provider-free and first performs
  full BOC/message revalidation before a separate local body reparse.
- Active TEP-74 transfer, notification, burn, and excess layouts are decoded;
  suggested internal-transfer and burn-notification layouts are marked
  separately. Unknown opcodes remain counted.
- Recognized malformed bodies, ambiguous message coordinates, changed body
  hashes/opcodes, trailing fixed-layout data, and non-canonical addresses fail
  closed with 409.
- The trace card exposes one explicit decode/revalidate action, recognized and
  unknown counts, bounded operation fields, observation roles, and the digest.
  Raw bodies, forward/custom payload contents, master identity, and token
  metadata are absent.
- POST `.../{target_run_id}/native-activity-pnl-readiness` consumes the
  canonical dedup result provider-free and reconciles incoming, outgoing, self,
  and net native TON flow.
- A seven-item checklist exposes dedup availability and every missing complete-
  history, trade-semantic, jetton-identity, historical-price, fee-linkage, and
  acquisition-basis prerequisite. Calculation values remain null and Real PnL
  remains locked.
- The wallet workspace accepts 1–49 other selected run ids, shows canonical and
  suppressed counts, exact native flow, the calculation lock, and all
  requirement reasons on desktop and narrow layouts.
- POST `.../{target_run_id}/native-activity-dedup` runs the unchanged merge,
  chooses the first deterministic occurrence per identity, and preserves every
  winner/suppressed coordinate in digest-bound resolution evidence.
- A duplicate identity with conflicting verified semantics returns 409. The
  contract does not establish complete history, cost basis, or PnL eligibility.
- POST `.../{target_run_id}/native-activity-merge` accepts 2–50 unique selected
  ids including the target; every run must share wallet/network identity.
- Every source ledger is fully revalidated. Rows receive deterministic
  chronological merge indexes and the full result is digest-bound.
- Duplicate identity groups are reported and retained; deduplication and
  completeness/cost-basis/PnL claims remain false.
- GET/POST `.../native-activity-ledger` are provider-free. First POST creates
  one immutable capture-bound ledger; repeated POST and GET perform no writes.
- Every read re-derives source flows, asset/counterparty keys, rows, totals, and
  digest. Relational or source drift returns 409.
- `GET .../boc-verification/counterparties` groups only verified flow endpoints
  by canonical network/account and recomputes directional totals.
- Keys explicitly identify observations, never actors, owners, beneficiaries,
  intent, or authority.
- `GET .../boc-verification/native-ton-asset` binds every upstream flow identity
  to `ton_native_asset_v1|{network}`, nine decimals, and nanoton base units.
- Binding count, asset key, upstream digest, and canonical binding digest must
  re-derive exactly; symbols alone never become identity.
- `GET .../boc-verification/native-ton-flows` is provider-free and includes
  only verified internal messages involving the stored run account.
- Direction, nanotons, counterparty endpoint, totals, and deterministic
  observation identity re-derive exactly. Non-authority/PnL flags stay false.
- `GET .../boc-verification/messages` is provider-free and reparses every stored
  BOC before returning message evidence.
- Each row exposes only transaction binding, trace role, verified hashes and
  header fields, body hash, bit/ref counts, and optional 32-bit opcode prefix.
- The response digest is bound to the v0.23.2 verification digest and the exact
  canonical message list. Raw BOCs and message bodies are absent.
- GET/POST use canonical run/hash paths and `Cache-Control: no-store`.
- Exact absence is 404; ineligible/corrupt state is 409; sanitized provider
  failure is 502; local verifier/storage unavailability is 503.
- The trace card automatically performs only database readback. Live preview,
  finalized capture, and local BOC verification are distinct explicit actions.
- Scope changes and component unmount abort payload requests and reject stale
  responses.
- The visible record shows verifier/version, counts, digests, and
  `RAW BOC HIDDEN`; it never renders raw BOC hex or message bodies.
- Desktop and narrow layouts must have no horizontal overflow, console error,
  or console warning.

## Release gates

- Full backend pytest and compileall pass.
- Full frontend Vitest, TypeScript/Vite build, and dependency audit pass.
- Deterministic fixtures cover every supported opcode, inline/reference
  payload boundaries, malformed recognized bodies, unknown opcodes, response
  validation and stable digests, plus flow reconciliation and stable analysis digest,
  response validation, ordering, duplicate grouping, canonical
  winner selection, complete suppression provenance, semantic-conflict
  rejection, response validation, incompatible-wallet rejection, canonical
  snapshot validation, payload dedup, asset/fee binding, exact nanoton
  conversion, legacy snapshot rejection, and dynamic readiness gates.
- Credential/prohibited-brand scans are clean and README matches the release.
- Commit only intended files, push the dedicated release branch, open and merge
  a ready PR, then create annotated tag `v0.26.0` on the merge commit.

## Rollback

- Before merge, patch the release branch and rerun every gate.
- After merge, use a follow-up revert commit; never rewrite published history.
- Revisions 0007-0008 are forward-only. Restore the verified pre-upgrade backup when a
  schema rollback is required.
