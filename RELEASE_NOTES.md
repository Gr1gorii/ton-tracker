# GRAM Scope — v0.96.0 BACKFILL SCHEDULE

v0.96.0 converts verified backfill state into one safe operator-controlled
action. `GET /api/v1/cases/{case}/stream-checkpoints/backfill-schedule` accepts
a finite 1–10 page budget, revalidates the current `bfp_` Backfill Progress and
`cpl_` Continuation Plan, and returns a canonical `bfs_<sha256>` document. The
selection policy advances the ready stream with the fewest continuation pages,
then revisions, then provider/stream identity, preventing a repeatedly chosen
stream from silently starving a less-advanced one.

The schedule state explicitly distinguishes `ready`, `backpressured`, `empty`,
`complete`, and `blocked`. An active Case sync suppresses selection and binds
its public ID into the backpressured schedule. The run endpoint accepts only an
exact current `bfs_` plus its original page budget. Changed budgets, checkpoint
frontiers, or active work fail stale before provider I/O; successful and
ambiguous retries remain bound to one idempotency key and durable CaseSync.

Accepted runs store acquisition-plan version 5. Their content-addressed
continuation receipt v3 adds the input schedule ID while preserving the exact
input/output checkpoints, verified chains, history-cutoff after-plan, and
authorized/consumed/remaining page accounting. Receipt v1 and v2 contracts
remain unchanged. The strict client rejects shape, identity, state, selection,
budget, and provenance drift before display.

Summary now prepares a budgeted schedule, explains the server-selected stream,
runs exactly one step through the durable sync controller, surfaces
backpressure and terminal no-selection states, and exports schedule JSON.
There is no repeating background crawler, percentage, ETA, or complete-history
claim. No database migration is added; Alembic remains at `20260828_0028` and
backend API version remains `0.2.1`.

---

# GRAM Scope — v0.95.0 BACKFILL PROGRESS

v0.95.0 makes backward provider acquisition measurable without inventing a
completion percentage. The new
`GET /api/v1/cases/{case}/stream-checkpoints/backfill-progress` endpoint
recursively verifies every latest provider-stream chain and returns a canonical
`bfp_<sha256>` document bound to its checkpoint cutoff.

Each stream separates initial from continuation revisions and pages, binds its
root and tip checkpoint plus `cch_` chain identity, reports the requested
interval state, and retains root/current successful-page frontiers with page,
cursor, digest, logical-time, timestamp, and fetch-time evidence. Aggregates
show observed and actually advanced frontiers alongside ready, complete, and
blocked states. Empty Cases remain deterministic; corrupt checkpoint,
manifest, acquisition-plan, or lineage data fails closed.

The strict browser parser rejects shape, identity, total, state, and frontier
contradictions before display. Summary verifies progress only on explicit
request, visualizes root-to-current frontier movement and continuation page
counts, and exports the verified JSON. Provider cursors do not reveal a
reliable remaining-page denominator, so this release deliberately omits ETA
and percent-complete claims. Frontier evidence does not prove earliest wallet
activity or complete history. No database migration is added; Alembic remains
at `20260828_0028` and backend API version remains `0.2.1`.

---

# GRAM Scope — v0.94.0 BUDGETED CONTINUATION

v0.94.0 lets an operator advance one verified provider stream by a finite
budget of 1–10 pages. The plan-bound resume endpoint accepts a strict
`page_budget`, binds it with the exact Continuation Plan and checkpoint in a v2
idempotency fingerprint, and records acquisition-plan version 4 provenance.
Changing the budget while reusing an idempotency key fails closed.

Before provider I/O, the worker reloads and validates the stored budget along
with the existing checkpoint lineage. TonAPI transaction and account-event
pagination use the lower of the operator budget and the deployment's configured
page cap. Invalid, mismatched, boolean, string, zero, over-limit, or unbound
budgets never reach the provider.

Completed budgeted jobs publish
`wallet_case_checkpoint_continuation_receipt_v2`, which content-addresses the
authorized, consumed, and remaining page budget alongside the existing exact
checkpoint/chain/after-plan transition. Historical acquisition-plan-v3 jobs
continue to reconstruct the unchanged receipt v1 contract. The browser offers
an explicit 1–10 page selector, retains the same budget and idempotency key
across ambiguous retries, strictly validates both receipt versions, displays
budget accounting, and exports verified JSON. The operation is finite and
operator-triggered; it is not a scheduler, automatic backfill, or proof of
complete wallet history. No database migration is added; Alembic remains at
`20260828_0028` and backend API version remains `0.2.1`.

---

# GRAM Scope — v0.93.0 CONTINUATION RECEIPT

v0.93.0 makes the result of a plan-bound provider continuation independently
verifiable. The new
`GET /api/v1/cases/{case}/syncs/{sync}/continuation-receipt` endpoint returns a
canonical `ctr_<sha256>` document that binds the accepted Continuation Plan and
input checkpoint, the newly published output checkpoint and verified chain,
the exact after-plan, and the revision, page, and successful-page deltas.

The after-plan is rebuilt from the immutable provider-stream tips at the output
checkpoint's history cutoff. The first receipt therefore remains byte-for-byte
stable even after a later resume advances the live plan. Only terminal
acquisition-plan-v3 resumes are eligible; bounded, legacy-unbound, unfinished,
foreign, missing-output, and broken-lineage reads remain unavailable or fail
closed with structured errors.

The browser client strictly validates every receipt identity, scope, stream,
chain, plan, state, and delta relationship before rendering it. Summary exposes
an explicit verification action on eligible snapshots, visualizes the accepted
`cpl_/scp_` to published `scp_/cpl_` transition, and exports the verified JSON.
The receipt proves one bounded provider acquisition step, not deduplicated
semantic activity, complete wallet history, or automatic scheduling. No
database migration is added; Alembic remains at `20260828_0028` and backend API
version remains `0.2.1`.

---

# GRAM Scope — v0.92.0 PLAN-BOUND RESUME

v0.92.0 turns an explicitly verified Continuation Plan into one stale-safe
resume authorization. The new
`POST /api/v1/cases/{case}/stream-checkpoints/continuation-plan/{plan}/{checkpoint}/resume`
endpoint recomputes the current `cpl_<sha256>` document, requires the selected
`scp_<sha256>` to be its current resume-ready stream tip, and rejects a changed
plan with a structured `409 continuation_plan_stale` response containing the
new plan identity.

The plan and checkpoint IDs are bound into one versioned idempotency
fingerprint. A transport retry with the same key returns the original operation
even after successful publication advances the plan, while reuse for an
unbound or different scope fails closed. Accepted plan provenance is retained
in acquisition-plan version 3 and exposed in the sync requested scope.

Summary no longer offers an unbound resume button from the latest-checkpoint
catalog. It displays the action only inside an explicitly verified plan and
sends the exact plan/tip pair through the strict client parser and durable sync
controller. Legacy resume records remain readable and retry-compatible. The
operation is still sequential, bounded provider acquisition—not a scheduler,
automatic backfill, or proof of complete wallet history. No database migration
is added; Alembic remains at `20260828_0028` and backend API version remains
`0.2.1`.

---

# GRAM Scope — v0.91.0 CONTINUATION PLAN

v0.91.0 assembles the latest verified revision of every provider stream into
one case-level, content-addressed Continuation Plan. The new
`GET /api/v1/cases/{case}/stream-checkpoints/continuation-plan` endpoint binds a
stable checkpoint cutoff, provider/stream ordering, every root-to-tip chain
identity, aggregate revision and provider-page totals, current continuation
state, and exact next page into a canonical `cpl_<sha256>` document.

Every stream is revalidated through the existing checkpoint, source manifest,
acquisition plan, parent edge, provider contract, and 100-revision chain gates.
The plan itself is bounded to 32 latest streams and fails closed if any member
chain is corrupt or contradictory. Empty and mixed-state plans remain
content-addressed and case-scoped.

Summary verifies the plan only on an explicit action, shows ready, complete,
and blocked streams with their chain IDs and represented page totals, and
exports the strictly parsed JSON. Only one Case synchronization may run at a
time, so a ready stream is resumed explicitly and the plan must be verified
again after publication. The plan is not a scheduler, automatic backfill, or
proof of complete wallet history. No database migration is added; Alembic
remains at `20260828_0028` and backend API version remains `0.2.1`.

---

# GRAM Scope — v0.90.0 CHECKPOINT CHAIN

v0.90.0 turns one exact provider-stream checkpoint revision into a
content-addressed, root-to-tip chain document. The new case-scoped
`GET /api/v1/cases/{case}/stream-checkpoints/{checkpoint}/chain` endpoint
revalidates every checkpoint, source manifest, acquisition plan, parent edge,
provider/stream identity, and provider contract before returning any result.
The canonical document is identified by `cch_<sha256>` and binds the selected
tip, ordered revisions, aggregate page counts, current continuation state, and
next page index.

Lineage traversal now has one shared fail-closed implementation and a hard
100-revision limit. Missing, circular, future, cross-case, cross-stream,
cross-contract, or contradictory edges reject exact detail, history, and chain
reads consistently. Aggregate counts describe only the successful provider
pages captured by the verified chain; they do not imply automatic backfill or
complete wallet history.

Summary can verify a chain after selecting an exact revision, displays its
content address, root-to-tip acquisition modes, represented pages, current
state, and continuation point, and exports the strictly parsed document as
JSON. No database migration is added; Alembic remains at `20260828_0028` and
backend API version remains `0.2.1`.

---

# GRAM Scope — v0.89.0 CHECKPOINT HISTORY

v0.89.0 makes every immutable provider-stream checkpoint revision auditable,
instead of exposing only the latest revision for each provider/stream pair.
`GET /api/v1/cases/{case}/stream-checkpoints/history` returns a bounded,
newest-first catalog frozen at the first page's revision cutoff. Continuations
use a canonical, process-local HMAC-authenticated cursor bound to the Case,
cutoff, and keyset position; malformed, changed, foreign, unavailable, and
noncanonical cursors fail closed.

Each history item revalidates its checkpoint canonical JSON, SHA-256 content
address, database identity, Case and source sync, source manifest, provider
contract, acquisition period, page totals, and continuation state. Resume
lineage is then followed recursively to a bounded or incremental root. Every
parent must be older, case-local, content-valid, and identical in provider,
stream, and contract, while each resume base snapshot must be the direct
parent's source sync. Missing, circular, future, cross-stream, or contradictory
lineage returns an integrity error for the whole read.

`GET /api/v1/cases/{case}/stream-checkpoints/{checkpoint}` exposes one exact
verified document with its base snapshot, direct parent, and chain depth.
Summary loads the revision journal only with acquisition inspection, supports
frozen `Load older revisions` traversal, and can inspect the exact source sync,
source manifest, parent, depth, and continuation state. Client controllers
reject cutoff drift and repeated revisions across pages.

The release also closes the v0.88.0 resume-evidence compatibility gap: public
manifest and checkpoint schemas plus the strict frontend parsers now accept and
validate `acquisition_mode=resume`. No database migration is added; Alembic
remains at `20260828_0028` and backend API version remains `0.2.1`. Checkpoint
history is an explicit revision journal, not automatic backfill and not proof
of complete wallet history.

---

# GRAM Scope — v0.88.0 CHECKPOINT RESUME

v0.88.0 turns the conservative `ready` checkpoint state from v0.87.0 into one
explicit durable continuation operation. A caller posts a canonical checkpoint
ID with one UUIDv4 idempotency key; the queued CaseSync records versioned resume
lineage containing the source checkpoint and sync, original acquisition bounds,
provider stream key, cursor, and next page index.

Only the latest verified checkpoint for a supported TonAPI transaction or
account-event stream can run. Enqueue verifies the content address and source
manifest, and the worker repeats the integrity, latest-revision, provider
contract, source-sync, surface, bound, cursor, and page-index checks immediately
before provider I/O. Blocked, complete, stale, corrupt, foreign, and unsupported
records fail closed. Ambiguous client transport retries reuse the same
idempotency key; active-job recovery, polling, cancellation, lease fencing, and
terminal publication continue through the existing sync machinery.

Summary now offers `Resume stream` only for `ready` checkpoints. Complete and
blocked records remain informational. A resumed snapshot names both its base
snapshot and source checkpoint and always carries an explicit limitation: one
continued bounded stream is not automatic backfill and does not prove complete
wallet history. No database migration is added; Alembic remains at
`20260828_0028` and backend API version remains `0.2.1`.

---

# GRAM Scope — v0.87.0 STREAM CHECKPOINTS

v0.87.0 turns the sanitized stream/page evidence introduced in v0.86.0 into
separate durable continuation records. Every provider stream in a published
sync produces an immutable `scp_<sha256>` checkpoint bound to the Case, source
sync, source manifest, provider contract, requested period, successful page
count, last response digest, and conservative continuation decision.

Continuation is `ready` only after at least one successful page when the last
response cursor exactly matches the stream terminal cursor and acquisition
ended at a page cap or transient provider error. Completed streams retain no
cursor. Preview-only, legacy-unbounded, protocol-error, in-progress event,
missing-cursor, and cursor-mismatch states are explicitly blocked. Raw provider
payloads, queries, headers, credentials, database IDs, and error messages never
enter checkpoint JSON.

Revision `20260828_0028` adds the append-only checkpoint table with exact
content-address, page-count, continuation-state, uniqueness, foreign-key, and
index constraints. The worker inserts all checkpoints in the same lease-fenced
transaction as the ingestion run, terminal CaseSync state, catalog event, and
acquisition manifest; stale publication rolls everything back.

`GET /api/v1/cases/{case}/stream-checkpoints` returns the latest verified
revision for each provider/stream pair and revalidates canonical JSON, SHA-256,
Case, source sync, source manifest, provider contract, page totals, and cursor
state. Summary shows ready/complete/blocked totals and stream-level boundaries.
This release persists resume-ready state but does not yet execute a resumed
provider crawl or claim full-history backfill.

---

# GRAM Scope — v0.86.0 ACQUISITION MANIFESTS

v0.86.0 gives every newly published Wallet Case ingestion run an immutable,
content-addressed acquisition manifest. The canonical JSON binds the Case and
sync public IDs, network and observed provider, terminal state, composed
snapshot period, actual acquisition period, incremental base and overlap,
requested surfaces, sanitized stream checkpoints, page cursors and counts, and
valid provider response SHA-256 digests. It excludes raw responses, provider
queries, headers, credentials, database/run IDs, and provider error messages.

The worker builds and inserts the manifest in the same lease-fenced database
transaction that publishes the ingestion run and terminal CaseSync state. A
stale worker therefore rolls back the run and manifest together. Revision
`20260827_0027` adds the one-to-one manifest table with content-address identity,
contract, payload, foreign-key, and unique-sync constraints; exact empty
interrupted DDL can resume, incompatible or populated pre-revision tables fail
closed, CaseSync deletion cascades, and downgrade is intentionally unsupported.

Sync responses include a compact descriptor with manifest ID, content hash,
stream/page/digest counts, and creation time. The case-scoped
`GET /api/v1/cases/{case}/syncs/{sync}/manifest` endpoint verifies canonical JSON,
SHA-256, and Case/sync identity before returning the provider-safe document.
Summary displays the descriptor and loads the verified details only on request.
Older usable snapshots without manifests remain available with an explicit
`acquisition_manifest_unavailable` limitation. Demo manifests truthfully have
zero provider streams and response digests. The stored checkpoints prepare a
future resume/backfill slice; v0.86.0 does not claim provider-crawl resume.

---

# GRAM Scope — v0.85.0 INCREMENTAL REFRESH

v0.85.0 adds an explicit forward-refresh path for an existing usable Wallet
Case snapshot. The first synchronization remains a bounded 24-hour acquisition.
Every later Summary refresh can request `mode=incremental`; the backend anchors
the new snapshot to the latest usable snapshot, acquires only from 15 minutes
before its end through the new request time, and records the base snapshot ID,
actual acquisition interval, and overlap in durable lineage.

Incremental jobs require exactly the same activity surfaces as their base and
reject missing, active, mismatched, or already-current baselines without
persisting speculative work. The idempotency fingerprint binds the mode. The
worker uses the narrower acquisition interval while the resulting snapshot
retains the composed start and new end; Activity revalidates every source
against its own acquisition interval and deterministically deduplicates overlap
observations.

The strict frontend contract independently validates mode, bounds, overlap,
base identity, surfaces, coverage, and the explicit composite-history
limitation. Summary changes from `Sync last 24 hours` to
`Refresh incrementally` only after a usable snapshot exists, preserves that
snapshot during the job, and displays both snapshot and acquisition intervals.
The compact Summary still reflects only the latest acquisition run; Activity is
the composed cross-sync view. Neither mode claims complete wallet history.

No database migration is added. Alembic remains at `20260827_0026`; the private
versioned acquisition plan is stored inside the existing sync coverage record
and is removed from public coverage output. Older rows without a plan remain
valid bounded snapshots.

---

# GRAM Scope — v0.84.0 CASE DISCOVERY

v0.84.0 makes a growing local Wallet Case catalog discoverable without
weakening its bounded pagination contract. `GET /api/v1/cases` accepts an
optional case-insensitive `q` over label, note, display address, and canonical
wallet key, plus exact `network=ton-mainnet|ton-testnet` and
`data_environment=demo|live` filters. Search wildcard characters are matched
literally, unknown and duplicate parameters fail closed, and every response
echoes the normalized filter scope.

The signed catalog cursor is upgraded to version 3 and binds a digest of the
normalized search, network, and data-environment filters in addition to owner
scope, lifecycle state, event cutoff, and keyset position. A continuation
cannot be replayed with broader or different discovery conditions. Existing
event-cutoff behavior continues to freeze ordering and lifecycle membership;
new or moved Cases appear on a fresh first page.

The Case Library now provides accessible search, network, and demo/live
controls for both Active and Archived catalogs. Its canonical `/cases` URL
stores the applied discovery state, so refresh and browser back/forward restore
the same catalog instead of silently returning to defaults. Every filter change
abandons the old cursor snapshot, aborts stale work, and begins a new bounded
traversal. Filtered empty results are distinct from a genuinely empty library
and can be cleared directly.

No database migration is added. Alembic remains at `20260827_0026`; v0.84.0
uses the existing append-only catalog event journal and owner-scoped Case
metadata. Wallet Cases and their catalog remain direct-loopback only until
authentication derives a hosted owner scope.

---

# GRAM Scope — v0.83.0 CASE ARCHIVE

v0.83.0 adds a reversible Wallet Case lifecycle between active work and
permanent deletion. `POST /api/v1/cases/{case}/archive` removes an idle Case
from active workflows without deleting its snapshots, normalized Activity,
Evidence jobs, Findings inputs, notes, or saved Report revisions. A queued or
running synchronization or Evidence verification blocks archival with a safe
structured conflict. `POST /api/v1/cases/{case}/restore` returns the retained
Case to active workflows. Repeating either accepted transition is idempotent.

`GET /api/v1/cases` now accepts the explicit `state=active|archived` contract.
Its process-local signed cursor binds the owner scope, frozen event cutoff,
lifecycle state, and keyset position, so an archived continuation cannot be
replayed against the active library. Archive and restore events freeze both
membership and order for an in-progress traversal while a fresh first page
sees the current lifecycle state.

The Case workspace presents archival as a reversible action distinct from the
typed-confirmation permanent delete flow. The Case Library adds accessible
Active and Archived tabs, independent loading/empty/error states, paged archive
history, and a restore action that refreshes the archive snapshot only after a
strict case-bound response. A Case transitioned after page one is labelled as
stale snapshot state instead of being opened under a false lifecycle assumption.

No database migration is added. Alembic remains at `20260827_0026`; its
append-only visibility journal already records the active/archive transitions.
Wallet Cases remain direct-loopback only until authentication derives a hosted
owner scope. Archive is retention, not erasure; permanent deletion remains a
separate guarded action.

---

# GRAM Scope — v0.82.0 PAGED CASE LIBRARY

v0.82.0 removes the 50-Case visibility ceiling from the local Wallet Case
library. `GET /api/v1/cases` now accepts an optional authenticated continuation
cursor and returns `next_cursor` whenever another bounded page exists. The UI
loads pages of 12 into the current library without replacing prior cards, and
keeps the loaded catalog available when a continuation fails.

Catalog order is frozen at the first page. Revision `20260827_0026` adds an
case-owned append-only Case catalog event journal and seeds every existing Case with its
current visibility and update position. A signed cursor binds the local owner
scope, frozen event cutoff, and last returned keyset position. New, updated, or
reopened Cases after page one do not jump into that traversal; opening a fresh
first page sees the new order. Deletion can shorten an in-progress traversal
but cannot expose a foreign owner or duplicate a surviving Case. Permanent
Case deletion also removes its internal catalog events.

The API rejects unknown or duplicate query parameters, malformed, tampered,
cross-scope, noncanonical, and oversized cursors with a safe structured 422.
The frontend independently enforces page size, uniqueness, full-page
continuations, cursor/truncation agreement, non-overlap across pages, cursor
advancement, stale-response fencing, and abort on unmount. Cursor signing is
intentionally process-local: after a backend restart the user starts a fresh
catalog traversal.

---

# GRAM Scope — v0.81.0 CASE LIBRARY

v0.81.0 completes the missing return path into durable Wallet Cases. The new
refresh-safe `/cases` route reads the existing owner-scoped local catalog and
lets a user reopen a Case without pasting its TON address again. The landing
page and every Case route link to the library, and permanent deletion returns
to the remaining catalog instead of an unrelated workspace.

Each Case card keeps canonical identity and display metadata separate while
showing the network, demo/live environment, optional note, latest sync or
snapshot state, bounded Activity count, and update time. Loading, empty,
storage-error, retry, and narrow-screen states are explicit. The initial page
is limited to 12 Cases and can expand to the API maximum of 50; a larger local
catalog remains honestly disclosed as truncated.

The frontend treats the catalog as a strict contract. Requested page sizes
must be safe integers from 1 through 50, the response must echo that exact
limit, cases must be unique and fit the page, and a truncated page must be
full. Superseded loads are aborted and cannot publish stale state. The library
is a separate lazy chunk so the primary landing path does not eagerly load its
catalog UI.

No database migration is added in v0.81.0; Alembic remains at
`20260710_0025`. The catalog retains the existing direct-loopback and local
owner-scope boundary. It is not exposed as an anonymous hosted case index.

---

# GRAM Scope — v0.80.0 CASE DETAILS

v0.80.0 makes the human context on a Wallet Case editable without weakening
its canonical identity. The owner-scoped local API adds
`PATCH /api/v1/cases/{case_public_id}` for bounded labels and notes. Empty
values are normalized to `null`; the route cannot change the case wallet,
network, data environment, creation time, sync history, Evidence, Findings, or
Report revisions.

Metadata writes use explicit optimistic concurrency. Every Case carries a
positive `metadata_version`, and a write succeeds only when its
`expected_metadata_version` is current. A successful update increments the
version atomically. A stale editor receives a structured `409` with the safe
current version, while a deleted or foreign case remains indistinguishable as
`404`. This prevents two browser tabs from silently overwriting each other's
notes.

The shared Case shell now displays a bounded multiline note and opens an
accessible details editor from every Case view. The editor canonicalizes
whitespace, publishes only a response bound to the unchanged Case identity and
the next version, preserves the user's draft after a conflict, blocks dismissal
during a save, aborts obsolete requests, and prevents a stale shell reload from
overwriting the accepted update.

Revision `20260710_0025` appends the non-null `metadata_version` column with a
default of `1`. Fresh install, 0024 upgrade, exact interrupted-DDL resume,
schema drift, invalid existing rows, model parity, and forward-only downgrade
behavior are covered by migration tests. Wallet Cases remain direct-loopback
only until authentication supplies a hosted owner scope.

---

# GRAM Scope — v0.79.0 CASE LIFECYCLE

v0.79.0 completes the first permanent data-lifecycle action for Wallet Cases.
The owner-scoped local API now exposes
`DELETE /api/v1/cases/{case_public_id}` and returns a strict deletion receipt
with the public case ID, a non-sequential audit-event ID, deletion time, and
bounded counts of removed syncs, ingestion runs, Evidence verifications, and
saved Report revisions.

Deletion is transactional and fail-closed. A case with a queued or running
CaseSync or Evidence verification returns a structured `409` instead of racing
the worker. Once all work is terminal, the service removes the case-owned
syncs, revisions, normalized activity, provider acquisition evidence, and proof
artifacts in dependency order. Unrelated cases and unscoped legacy ingestion
runs remain untouched. A failed cascade rolls the whole operation back.

Revision `20260710_0024` adds a forward-only lifecycle-event table that remains
after the case row is gone. Its audit receipt intentionally stores only owner
scope, public case/event IDs, event time, and aggregate removal counts; wallet
address, label, note, provider payloads, proof material, worker state, and
credentials are not retained. Fresh, 0023 upgrade, exact interrupted-DDL
resume, drift, row-adoption, and downgrade paths are tested fail-closed.

Every Case view now exposes a guarded deletion action. The modal names the data
that will disappear, explains the retained audit boundary, requires the exact
text `DELETE`, disables dismissal while the request is active, preserves safe
active-job errors for retry, and returns to the home route only after a
case-bound receipt is validated. Wallet Cases remain direct-loopback only until
authentication supplies a hosted owner scope.

---

# GRAM Scope — v0.78.0 REPORT COMPARE

v0.78.0 adds a deterministic comparison view for two immutable Wallet Case
Report revisions. A user can designate any saved revision as the baseline,
select another saved revision as the target, and inspect directional changes
without exporting documents or treating capture order as causality.

The owner-scoped local API adds
`GET /api/v1/cases/{case}/reports/{baseline}/compare/{target}`. Both stored
documents are revalidated against their content addresses, persisted metadata,
case, snapshot, and public subject identity before comparison. The strict
`wallet_case_report_revision_comparison_v1` response is itself content-addressed
as `rcmp_…` and exposes only public revision summaries and bounded deltas. It
does not expose database/run/source IDs, provider payloads, proof BOCs, worker
state, or credentials.

Comparison covers assurance, Activity and Evidence digests and counts, observed
period and coverage change flags, canonical eligibility and gate changes, plus
added, resolved, or modified gap, limitation, and unverified-claim codes. The
direction is exactly baseline to target. Comparing across different snapshots
is explicitly labelled because those counts can represent different bounded
observation scopes; no delta is presented as proof of why a value changed.

The Reports route now persists `baseline` alongside the pinned target snapshot
and revision in strict URL state. It survives refresh and back/forward
navigation, rejects malformed or partial comparison state before requesting,
aborts stale comparisons, and moves keyboard focus to the newly validated diff.
Responsive comparison cards retain the explicit-capture, incomplete-history,
cost-basis, PnL, and non-causality boundaries.

No database migration is added in v0.78.0; Alembic remains at
`20260710_0023`. Comparisons are read models over two explicit immutable
captures and do not reconstruct missing intermediate states or automatically
select Evidence targets. Wallet Cases remain direct-loopback only until
authentication supplies an owner scope.

---

# GRAM Scope — v0.77.0 REPORT HISTORY

v0.77.0 adds durable, content-addressed Wallet Case Report revisions. A user
can explicitly save the current report for one pinned usable snapshot, browse
the case's saved revision history, reopen an exact revision, and export the
stored validated JSON document. Repeating the same capture is idempotent: it
returns the existing `rpt_…` revision instead of creating duplicate history.

The new owner-scoped local API exposes a signed, snapshot-stable report catalog,
an explicit capture endpoint, exact revision detail, and exact saved export.
Catalog cursors bind the case, revision cutoff, and keyset position. They are
opaque and tamper-evident, but intentionally live only for the current backend
process. Public responses expose no sequential database IDs, source run IDs,
provider payloads, proof BOCs, idempotency material, or cursor signing secret.

Each stored revision preserves the complete validated `wallet_case_report_v1`
envelope and revalidates its public ID, content hash, case, snapshot, assurance,
and digest bindings on every read. A saved revision is immutable; the current
report can still change when new Evidence is captured, and it is not silently
added to history. History is therefore a record of explicit captures, not a
claim that every intermediate report state was reconstructed or retained.

The case shell now provides Summary, Activity, Findings, Evidence, and Reports.
The Reports route pins snapshot and selected revision in strict URL state,
survives refresh/back/forward navigation, appends non-overlapping cursor pages,
and keeps keyboard focus on the opened revision or its returning history link.
The view distinguishes the current reproducible report from saved history and
keeps all incomplete-history, cost-basis, PnL, coverage, and canonical-gate
limitations visible.

Schema revision `20260710_0023` adds the durable revision catalog with exact
case/snapshot ownership, content-hash uniqueness, stored-document integrity,
and restart-safe forward-only migration checks. Wallet Cases remain
direct-loopback only until authentication supplies an owner scope.

---

# GRAM Scope — v0.76.0 CASE FINDINGS

v0.76.0 adds a deterministic Findings and Flows view over one pinned Wallet
Case Activity revision. It groups observed asset movement only by canonical
network-scoped asset identity, keeps same-symbol jettons separate, and publishes
bounded counterparty and recognized-protocol groups without treating display
labels as identity.

Each `wallet_case_findings_v1` document is content-addressed by an exact
SHA-256 public projection and binds the case, snapshot, subject, Activity
aggregate, observed period, Evidence revision, flow groups, findings, gaps,
limitations, and fixed truth boundaries. Rebuilding the same revision produces
the same `fset_…` identifier. The endpoint is read-only, uses the existing
local owner scope, pins the newest usable snapshot when one is not supplied,
and exposes no compatibility run IDs, source-row IDs, raw provider payloads,
proof BOCs, or credentials.

Published findings use named versioned rules rather than an opaque risk score.
Every row-supported finding links back to its public Activity records and is
labelled by the weakest revalidated support level. Coverage and identity
conflicts remain revision-level diagnostics. An empty finding set explicitly
does not mean a wallet is safe, and the document does not establish ownership,
illicit status, complete history, cost basis, cross-asset comparability, or PnL.

The case shell now provides Summary, Activity, Findings, and Evidence routes.
The Findings URL survives refresh and back/forward navigation, pins its
snapshot in history, rejects malformed or duplicated query state before a
request, fails case/environment drift closed, and opens supporting Activity
details through real links with keyboard-safe route focus. Desktop flow cards
collapse to a bounded mobile layout without hiding interpretation limits.

The local API adds `GET /api/v1/cases/{case}/findings`. No database migration is
added in v0.76.0; the Alembic head remains `20260710_0022`. Findings are a
bounded read model and do not replace the content-addressed Case Report or
silently promote Evidence. Wallet Cases remain direct-loopback only until an
authenticated owner scope is implemented.

---

# GRAM Scope — v0.75.0 CASE REPORT

v0.75.0 adds the first Wallet Case Report over one immutable, pinned Activity
snapshot. A synchronized case now always has a useful report revision: demo
fixtures produce `observed`, live normalized observations produce `normalized`,
and locally revalidated Evidence can raise the revision to
`partially_verified`. `canonical` remains a distinct hard-gated assurance state
and cannot be published while coverage, history, identity conflicts, Activity
gaps, bounded Evidence history, transaction inclusion, or native-ledger
requirements remain unmet.

Each report is a strict `wallet_case_report_v1` document with a SHA-256 content
hash and matching opaque `rpt_…` public ID. It binds the case and snapshot,
subject identity, Activity aggregate and observed period, the returned
revalidated Evidence window, coverage, gaps, limitations, unverified claims,
and fixed truth boundaries. Rebuilding the same data revision produces the
same bytes and hash; new Evidence produces a new content-addressed revision
without mutating an exported prior document. The bounded facade deliberately
does not expose compatibility run IDs, source row IDs, raw provider payloads,
proof BOCs, worker state, or credentials.

The local-only case API adds `GET /api/v1/cases/{case}/report` and an exact JSON
export at `GET /api/v1/cases/{case}/report/export.json`. Both accept one
optional snapshot UUID, pin the newest usable snapshot when omitted, use
`Cache-Control: no-store`, enforce the existing owner scope, and fail closed on
snapshot or Evidence conflicts. The export is the complete validated public
envelope, not the legacy run-scoped report surface.

Evidence now shows the report assurance, report and content hashes, Activity
and Evidence counts, canonical gate status, and every remaining unverified
claim. The report refreshes after terminal Evidence updates, survives direct
snapshot URLs, and never renders a prior snapshot's report while a new scope is
loading or failing. JSON export remains available for observed, normalized,
and partially verified revisions instead of blocking all noncanonical output.

No database migration is added in v0.75.0. The Alembic head remains
`20260710_0022`; report revisions are deterministic read models over immutable
CaseSync snapshots plus revalidated persisted Evidence. The server does not yet
maintain a historical report-revision catalog, auto-select proof targets, prove
complete wallet history, establish cost basis, or feed PnL. Those remain
explicit limitations rather than inferred claims. Wallet Cases, Evidence, and
Case Reports remain direct-loopback only until authenticated owner scopes are
available.

---

# GRAM Scope — v0.74.0 CASE EVIDENCE

v0.74.0 adds a durable Wallet Case evidence-verification workflow for one
transaction selected from a pinned Activity snapshot. Eligible live,
provider-observed transactions can enter one explicit pipeline that captures a
finalized trace and verifies persisted transaction BOCs locally. It promotes
block inclusion and the selected native-TON evidence artifact only when every
inclusion proof was captured at liteserver trust level 0 from the exact
application-pinned checkpoint for that TON network under verifier policy
`ton_liteserver_checkpoint_strict_2026_08_v2`. The policy and checkpoint are persisted
with each proof and covered by its evidence and catalog digests.
`chain_inclusion_proven` therefore means canonical under that policy at capture
time; it does not claim that a later offline BOC replay re-establishes the live
canonical chain. Demo fixtures, transfers, swaps, unavailable identities, and
transactions without a self-linked canonical hash remain explicitly
ineligible.

Pre-strict `ton_liteserver_checkpoint_2026_08_v1` rows are preserved only as
noncanonical legacy checkpoint evidence. Revision `20260710_0022` activates the
strict policy and prevents older blockstore state from becoming its trust root.

Verification is stored as an owner-scoped job before proof work starts. A UUID
idempotency key and semantic request fingerprint prevent duplicate work; one
selection has at most one active verification. Fenced leases, heartbeats,
bounded retry, restart recovery, stage checkpoints, and cooperative
cancellation preserve completed immutable artifacts without changing the
usable Case synchronization that supplied the transaction. Provider and
liteserver calls run without holding an application database connection. The
whole liteserver operation runs in a child process behind one hard deadline;
expiry requests termination and escalates to a forced kill after a bounded
grace period. Running cancellation remains cooperative, but an active
liteserver child cannot make it unbounded: the same deadline and bounded stop
path limit that wait. Every persisted artifact is revalidated before progress
or a terminal result is published.

Schema revision `20260710_0019` adds the durable Evidence job and its exact
scope, lifecycle, lease, retry, artifact-prefix, and ownership constraints.
Revision `20260710_0020` preserves existing inclusion proofs while versioning
their identity by `(BOC transaction, trust level)`. Revision
`20260710_0021` adds immutable verifier-policy and exact network-checkpoint
provenance to transaction-inclusion proofs and their digests. Revision
`20260710_0022` is the Alembic head and separates strict proof-link verification
from pre-strict checkpoint rows. Existing trust-level-0 rows are preserved under
`legacy_unpinned_v1`, but are noncanonical and cannot be promoted or selected
by the current policy. A prior legacy or trust-level-1 proof can coexist with a
current policy proof; only a complete set bound to the current pinned
checkpoint is canonical at capture.

The public case facade adds a snapshot-pinned Evidence catalog plus enqueue,
poll, and cancel endpoints. Responses expose non-sequential case, snapshot,
Activity, synchronization, and verification identifiers; sanitized transaction
provenance; factual stage progress; safe retry/error state; SHA-256 evidence
digests; and explicit normalized, locally verified, or chain-inclusion-proven
levels. `chain_inclusion_proven` therefore never means only “a liteserver named
this block.” Responses do not expose compatibility run IDs, database row IDs,
raw BOCs, provider payloads, lease tokens, idempotency keys, worker lifecycle
checkpoint state, or credentials.

The case shell now has Summary, Activity, and Evidence views. An eligible
Activity transaction links to a refresh-safe Evidence URL where the user can
review eligibility, start or resume the durable job, follow all four stages,
cancel at a safe boundary, inspect preserved partial evidence, and reopen
snapshot history. Demo and unavailable-runtime states remain disabled with a
machine-readable explanation. Direct URLs, refresh, back/forward navigation,
keyboard focus, narrow layouts, and both themes are covered by the new flow.

The native TON artifact is deliberately labelled as selected evidence only. It
is not the authoritative general Activity ledger, does not establish complete
wallet history, is not eligible for cost basis, and is not consumed by PnL.
v0.74.0 also keeps the Case report unavailable: a reproducible versioned report
over pinned observed and verified evidence is the next Roadmap 1 slice. Wallet
Cases and their proof worker remain direct-loopback only until authenticated
owner scopes replace the local single-user boundary.

---

# GRAM Scope — v0.73.0 CASE ACTIVITY

v0.73.0 adds the first canonical Wallet Case Activity facade and replaces the
case workflow's former Activity dead end with a refresh-safe, filterable
timeline. Activity is pinned to one usable case snapshot revision and combines
only eligible partial/succeeded syncs up to that revision. Overlapping source
rows collapse only when their persisted transaction or provider event-action
identity fully revalidates; observations without a trustworthy identity remain
separate, and conflicting semantics fail closed with an explicit data gap.

The public API exposes opaque activity and asset identifiers, stable keyset
pagination, server-side filters, bounded aggregates, requested and observed
periods, stream coverage, gaps, and sanitized provenance. Cursors bind the
case, snapshot, normalized filters, ordering, and position so a later sync
cannot change an in-progress traversal. Public responses contain no sequential
database IDs, compatibility run IDs, raw provider payloads, worker lease data,
or unsupported chain-proof claims.

TON is identified as the network-scoped native asset. Jettons receive an asset
identity only from a canonical `(network, contract address)` pair; symbol and
name remain display metadata, so two contracts sharing a symbol never merge.
Transactions are normalized provider observations. Transfer and swap actions
remain mutable provider-derived display observations unless a future evidence
pipeline proves a stronger relationship. Demo fixtures are visibly separated
from live provider observations.

The case UI now shares one wallet header and Summary/Activity navigation.
Activity filters, sort, pinned snapshot, and selected record survive direct
URLs, refresh, back, and forward navigation. Desktop rows become compact mobile
cards, expanded details preserve keyboard focus, and unavailable coverage or
partial data stays visible instead of being rendered as zero or complete
history.

This release intentionally leaves the compact Summary on the case's latest
usable-run basis while Activity publishes its own cross-sync deduplicated
aggregate at an explicit pinned revision. The views label those different
snapshot semantics and make no count-equivalence claim.
Native proof ledgers are not silently mixed into the general timeline because
they are still a separately initiated subset. Per-page ingestion resume,
unified Summary aggregates, automated evidence verification, authenticated
hosted owner scopes, Findings, and Evidence screens remain later Roadmap 1
slices.

---

# GRAM Scope — v0.72.0 DURABLE CASE SYNC

v0.72.0 turns every Wallet Case synchronization into a persisted background
job before provider work begins. The create-sync request returns immediately
with a non-sequential sync identifier; case and job reads expose factual stage,
progress, retry-attempt, cancellation, and timestamp state without publishing
the compatibility ingestion-run identifier.

Each job has a client idempotency key and canonical request fingerprint. One
case can have only one active sync, duplicate submissions with the same key
return the same job, and a reused key with different scope fails closed. A
single local runner claims jobs with a fenced lease, maintains an independent
heartbeat while the existing ingestion builder performs provider work, and
atomically publishes the final ingestion run and terminal sync result.
Expired work is recovered after restart instead of remaining permanently
running. Retryable network/provider failures use a bounded deterministic
backoff; invalid scope and protocol failures are not retried. Queued work can
be cancelled immediately, while running work observes cancellation before or
after the current monolithic provider crawl and discards unpublished results
safely.

The case response now separates the latest attempt, the active sync, and the
latest usable partial/succeeded snapshot. A queued, cancelled, or failed
attempt therefore cannot erase or impersonate the provenance of the last
useful Summary. The Summary route resumes polling after refresh, avoids
overlapping requests, shows real persisted progress and retry state, supports
safe cancellation, and displays `Not available` before the first usable
snapshot. The old case-to-legacy-Activity escape hatch is removed; a canonical
Activity route remains the next vertical slice.

This release deliberately reuses the existing monolithic ingestion builder.
The lease heartbeat and bounded stage checkpoint are durable, but accepted
provider pages are not yet committed incrementally: a crash during provider
I/O repeats the bounded crawl, and cancellation waits for the current bounded
crawl boundary. Per-page checkpoint/resume and canonical cross-sync Activity
deduplication remain subsequent Roadmap 1 work. Wallet Cases are still
direct-loopback only until authenticated owner scopes are implemented.

---

# GRAM Scope — v0.71.0 WALLET CASE FOUNDATION

v0.71.0 introduces the first product-facing Wallet Case vertical slice. A
network-scoped TON address now creates or reopens one durable owner-scoped case
with a non-sequential public URL. The new case facade exposes bounded syncs,
coverage, compact activity and portfolio summaries, and explicit limitations
without publishing the compatibility ingestion-run identifier.

The first case sync reuses the existing ingestion implementation atomically:
the case sync and its source run are committed together, and wallet identity,
network, and demo/live mode are checked before persistence. Demo cases always
use deterministic fixture evidence. Live cases require the guarded TonAPI
runtime and reject mock fallback data. Mainnet, testnet, demo, and live cases
remain distinct identities.

The frontend now has a refresh-safe `/cases/:caseId/summary` route that bypasses
the legacy multi-panel workspace. Its primary flow is create/open case, then an
explicit 24-hour bounded sync. Runtime configuration, persisted case
environment, bounded coverage, missing surfaces, snapshot semantics, and the
fact that full history is not proven remain visible. GRAM Scope is the product
brand; TON remains the blockchain and native asset throughout technical data
and user-facing labels.

Migration `20260710_0015` adds `wallet_cases` and `wallet_case_syncs`, and
`20260710_0016` adds compact persisted case summaries/messages, without
rewriting legacy evidence. Existing runs are intentionally not backfilled in
this release because older records may lack a trustworthy canonical network or
the exact resolved acquisition bounds. Sync execution is still synchronous;
durable workers, retry/cancel, cross-sync activity deduplication, and the final
four-screen replacement of legacy diagnostics remain subsequent Roadmap 1
slices. Until authenticated owner scopes land, the facade accepts only direct
loopback clients; hosted production access is disabled rather than exposing the
shared local owner scope.

---

# GRAM Scope — v0.70.0 EXTERNAL RECOVERY POINT

v0.70.0 closes the single-host backup gap. Every guarded deployment and
rollback now creates a new post-activation SQLite backup, restores and verifies
it, and atomically publishes a release-bound recovery point to a required
private host directory before monitoring, notification, public smoke, or the
deployment receipt can succeed. The destination is intended to be a separately
mounted and independently replicated failure domain, never the application
Docker volumes.

After that gate, a read-only-root periodic exporter reuses the latest embedded
release binding and writes a new point from the newest verified backup every 24
hours by default. A private non-blocking filesystem lock serializes scheduled
and deployment exports. Its bounded age healthcheck fails when the last point
is stale or invalid, while configurable retry, maximum-age, and retention
windows are validated together by production preflight. Freshness covers both
point publication time and the source backup's bound completion time, so a new
wrapper around stale data cannot report healthy.

Each recovery point contains only a restored database, the exact verified
deployment manifest, and a canonical integrity manifest. SHA-256 bindings cover
the database, source backup, deployment manifest, release tag, and source
commit. Publication is directory-atomic, the latest health pointer is atomic,
retention removes only fully verified recognized points, and links, public
permissions, hard links, unknown files, corruption, revision drift, or a
mismatched signed release fail closed. The recovery command requires the
original checksum and signed attestation and never overwrites an existing
database. Backup names now include microseconds to prevent concurrent
deployment and sidecar backups from colliding while legacy names remain valid.

---

# GRAM Scope — v0.69.0 SAFE FIRST DEPLOYMENT

v0.69.0 adds a dedicated fail-closed path for the first production deployment.
An installation with no active deployment receipt no longer attempts to back up
a database that does not exist. Instead, the exact target backend image proves
that the named data and backup volumes are empty, builds and validates the
current schema in private ephemeral storage, and records a durable bootstrap
checkpoint before any application service can start.

The application is activated separately, followed immediately by a verified
backup, restore drill, and target-image migration verification. Only then are
the backup, recovery, monitoring, and alert-delivery services activated. A
non-empty volume without the checkpoint is rejected as unmanaged state. An
explicit resume after the checkpoint accepts only two still-empty volumes or
the exact SQLite database, known sidecars, and verified backup artifacts created
by the interrupted attempt. An existing database is backed up and rehearsed
before activation is retried.
Upgrade and rollback sequencing remains unchanged.

---

# GRAM Scope — v0.68.0 TARGET DATABASE MIGRATION REHEARSAL

v0.68.0 adds a fail-closed schema compatibility gate before production service
activation. After the pre-rollout backup and restore checks, the exact target
backend image restores a second private copy, runs the same Alembic bootstrap
used at application startup, validates the resulting model schema and SQLite
integrity, checks source/target revision coherence, and destroys the copy.

The live database and retained backup remain read-only. Unknown future
revisions, partial or drifted schemas, failed migrations, integrity errors, and
inconsistent results stop both deployments and explicit rollbacks before the
target services can start. Release CI and published-image verification execute
the same container gate.

---

# GRAM Scope — v0.67.0 ACTIVE NOTIFICATION DRILL

v0.67.0 closes the automated production alert-delivery path. Every guarded
deployment now creates a unique synthetic Alertmanager API v2 alert after the
passive Prometheus/Alertmanager smoke gate, confirms that the live route marks
it active, and requires every selected receiver integration to record a
successful downstream request before the deployment receipt can be committed.

The drill compares receiver-scoped request and failure counters from the pinned
Alertmanager v0.33.1 runtime, fails closed on suppression, metric drift,
timeouts, or partial receiver failure, and always posts a matching resolved
alert after a successful injection. The release gate uses a private bounded
webhook fixture; production uses only the operator-owned receiver configuration.
Receiver endpoints, credentials, provider diagnostics, response bodies, and
drill identifiers are never printed by the rollout interface.

---

# TON Wallet Intelligence Dashboard — v0.26.0 MULTI-ASSET PNL READINESS

v0.26.0 adds provider-free POST
`/api/wallets/ingest/{target_run_id}/multi-asset-pnl-readiness`. The
`ton_multi_asset_pnl_readiness_v1` contract revalidates the unchanged native
dedup chain and every selected verified BOC capture, content-deduplicates
recognized TEP-74 observations, matches only canonical observed contracts to
persisted live TonAPI jetton snapshots, and links exact stored transaction fees
by canonical hash. Counts and source run provenance remain digest-bound.

TonAPI nested jetton-wallet records are now normalized to the canonical address
instead of a stringified object. Legacy malformed snapshot addresses remain
invalid and are never guessed. Provider snapshot matches are not local
jetton-master proofs, transaction fees are not allocated to lots, and complete
history, trade semantics, historical prices, cost basis, and Real PnL remain
explicitly blocked. The workspace renders native flow, jetton dedup, asset and
fee matches, all requirement reasons, and the calculation lock.

---

# TON Wallet Intelligence Dashboard — v0.25.0 VERIFIED JETTON PAYLOADS

v0.25.0 adds provider-free GET
`.../boc-verification/jetton-payloads` and an explicit trace-card action. The
`ton_jetton_payload_observations_v1` contract reparses the already verified
transaction BOCs, strictly decodes recognized TEP-74 transfer, notification,
burn, excess, internal-transfer, and burn-notification layouts, and binds every
observation to transaction, message, body hash, opcode, query id, and a digest.
Raw bodies and payload contents are never returned. Unknown opcodes remain
counted, malformed recognized payloads fail closed, and jetton-wallet role,
master, asset, ownership, cost-basis, and PnL claims remain explicitly limited.
The decoder follows the active TEP-74 contract:
https://github.com/ton-blockchain/TEPs/blob/master/text/0074-jettons-standard.md

---

# TON Wallet Intelligence Dashboard — v0.24.0 NATIVE ACTIVITY PNL READINESS

v0.24.0 adds provider-free POST
`/api/wallets/ingest/{target_run_id}/native-activity-pnl-readiness`. It consumes
the v0.23.9 canonical dedup result, reconciles exact incoming, outgoing, self,
and net native TON flows, and digest-binds a seven-item PnL evidence checklist.
Verified native value is not promoted to a trade, acquisition lot, price, fee,
cost basis, or profit. The workspace exposes selected-run reconciliation,
suppressed-repeat counts, flow totals, and every blocking prerequisite. On the
two real stored runs used for release verification, the contract reconciles two
canonical outgoing activities totaling 3.34 TON and correctly keeps Real PnL
locked.

---

# TON Wallet Intelligence Dashboard — v0.23.9 CROSS-RUN NATIVE ACTIVITY DEDUP

v0.23.9 adds explicit POST
`/api/wallets/ingest/{target_run_id}/native-activity-dedup` on top of the
unchanged v0.23.8 deterministic merge. Repeated content-addressed activity
identities collapse to the first canonical merge occurrence while every source
occurrence and suppression decision remains visible and digest-bound. A reused
identity with different verified semantics fails closed. The selected runs are
still bounded evidence, so complete history, cost basis, and PnL remain locked.

---

# TON Wallet Intelligence Dashboard — v0.23.8 MULTI-RUN NATIVE ACTIVITY MERGE

v0.23.8 adds explicit POST
`/api/wallets/ingest/{target_run_id}/native-activity-merge` for 2–50 unique
selected run ids. Every selected run must share the target wallet/network and
contain at least one fully revalidated v0.23.7 ledger. Source rows are merged in
deterministic chronological order with canonical merge indexes and a digest.
Repeated activity identities are reported as duplicate groups but every
occurrence remains present. The merge therefore does not deduplicate, establish
complete wallet history, unlock cost basis, or feed PnL.

---

# TON Wallet Intelligence Dashboard — v0.23.7 IMMUTABLE NATIVE ACTIVITY LEDGER

v0.23.7 adds forward-only Alembic revision `20260710_0008`, capture-bound
`wallet_native_activity_ledgers` and `wallet_native_activity_rows`, plus
provider-free GET/POST `.../native-activity-ledger`. The first POST materializes
verified native TON flows with canonical asset and counterparty observation
keys; repeated POST and GET re-derive the BOC-backed source, every row, totals,
and canonical digest before returning. Semantic reconstruction is now explicit
for native message transfers, but the ledger remains trace-scoped,
non-authoritative, unmerged across runs, ineligible for cost basis, and unused
by PnL.

---

# TON Wallet Intelligence Dashboard — v0.23.6 COUNTERPARTY OBSERVATION IDENTITY

v0.23.6 adds provider-free `GET .../boc-verification/counterparties`.
Observed native-flow endpoints are grouped by
`ton_counterparty_account_obs_v1|{network}|{canonical_account}` with exact
workchain/account-id decomposition, bound flow identities, directions, and
nanoton totals. The canonical digest covers the upstream message evidence and
sorted groups. This is observation identity only, never actor, owner,
beneficiary, intent, cost-basis, or PnL identity.

---

# TON Wallet Intelligence Dashboard — v0.23.5 NATIVE TON ASSET IDENTITY

v0.23.5 adds provider-free
`GET .../boc-verification/native-ton-asset`. Every verified native TON flow is
bound to `ton_native_asset_v1|{network}`, fixed `TON`/`Toncoin` metadata, nine
decimals, and `nanoton` base units. The binding list and upstream message digest
produce a canonical SHA-256 record. Symbols are display metadata, not identity.
Jetton assets, counterparties, activity merge/deduplication, cost basis, and PnL
remain explicitly outside this contract.

---

# TON Wallet Intelligence Dashboard — v0.23.4 NATIVE TON FLOW OBSERVATIONS

v0.23.4 adds provider-free
`GET .../boc-verification/native-ton-flows`. Verified internal-message headers
that involve the stored run account are classified as incoming, outgoing, or
self. Each row carries a deterministic `ton_native_message_flow_obs_v1`
identity, nanotons, message/transaction binding, observed counterparty endpoint,
body hash, opcode prefix, and bounce state. Totals are recomputed from rows.
This is native TON header evidence only: payload semantic decoding,
authoritative transfer/counterparty identity, activity merge, deduplication,
ownership, cost basis, and PnL remain false.

---

# TON Wallet Intelligence Dashboard — v0.23.3 MESSAGE BODY EVIDENCE

v0.23.3 adds provider-free
`GET .../trace-evidence/boc-verification/messages`. It reparses the immutable
v0.23.2 BOCs and returns one body-safe row per unique persisted message:
transaction preorder/hash, trace role/ordinal, provider and raw cell hashes,
hash convention, verified header fields, body hash, bit/ref count, and an
optional 32-bit opcode prefix. The response is digest-bound to the complete
v0.23.2 verification, uses `Cache-Control: no-store`, and never returns the raw
BOC or message body. Semantic reconstruction, authoritative identity, ownership,
cost basis, and PnL remain explicitly false.

---

# TON Wallet Intelligence Dashboard — v0.23.2 LOCAL BOC VERIFICATION

v0.23.2 adds a separate `ton_boc_trace_verification_v1` record on top of an
existing finalized v0.23.1 trace capture. The first explicit verification
performs exactly one TonAPI trace request, persists each bounded transaction
BOC, and locally deserializes it with pinned `pytoniq-core==0.1.46`. Existing
verification GET and idempotent POST are provider-free and reparse every BOC.

- Transaction root cell hash, account hash, LT, unix time, aborted state, and
  out-message count must match the immutable trace node.
- Internal and external message types, normalized external-in hashes, direct
  cell hashes, canonical endpoints, amounts, fees, flags, and timestamps must
  match the persisted message graph.
- Parent outgoing messages must partition exactly into child inbound edges and
  remaining outbound messages. Body hashes and available 32-bit opcode prefixes
  are derived locally without semantic promotion.
- Raw BOCs are capped at 1 MiB each and 8 MiB per verification, stored only in
  the database, covered by canonical SHA-256 digests, and never returned to the
  browser. Message bodies are also never returned.
- Alembic `20260710_0007` adds `wallet_trace_boc_verifications` and
  `wallet_trace_boc_transactions`; the migration repairs only exact empty
  interrupted DDL and otherwise fails closed.
- The trace card automatically reads the local verification record after the
  persisted graph. Verification remains an explicit action and is clearly
  separated from blockchain inclusion proof, semantic reconstruction,
  authoritative identity, ownership, merge/deduplication, cost basis, and PnL.

---

# TON Wallet Intelligence Dashboard — v0.23.1 PERSISTED TRACE EVIDENCE

v0.23.1 adds an explicit finalized-only persistence boundary for one bounded
TonAPI low-level trace graph. The existing v0.23.0 live preview remains
read-only and unchanged. A persisted graph is provider-indexed structural
evidence only: it is not blockchain proof, semantic transfer/trade
reconstruction, activity identity, cost basis, ownership proof, or PnL input.

## v0.23.1 scope

- `GET .../trace-evidence/persisted` reads one stored graph and performs no
  provider call. Absence is 404; malformed stored identity or graph is 409.
- `POST .../trace-evidence/persisted` is the only capture operation. The first
  eligible capture makes exactly one `GET /v2/traces/{transaction_hash}` call;
  an already stored graph returns provider-free and mutation-free.
- Only a non-emulated `finalized` trace is persisted. A `pending` trace remains
  preview-only and returns 409 without a database write.
- Capture is atomic: all nodes, parent links, message roles, counts, identities,
  capture context, and the evidence digest are revalidated before commit.
- Each run has 16 database-enforced capture slots. The lowest free slot is used;
  a unique `(run_id, capture_slot)` index prevents concurrent overflow.
- The normalized graph is strict DFS preorder with at most 256 transactions,
  depth 32, 2,048 remaining outgoing messages, and 2,304 total persisted
  message observations.
- Every non-root node has one coherent internal inbound edge from its current
  DFS parent. Root inbound and remaining outbound roles accept only their
  contract-compatible message types.
- Provider names, icons, interfaces, decoded bodies, semantic actions, raw
  transaction/message JSON, BOCs, message bodies, credentials, and headers are
  excluded from persistence.
- The digest covers the canonical graph plus run id, capture slot, exact
  persisted transaction anchor, and capture timestamp. Readback reconstructs
  and re-hashes that document before returning `persisted_graph_revalidated`.
- Every success and handled failure uses `Cache-Control: no-store`.

## v0.23.1 schema

Alembic revision `20260710_0006` adds three forward-only tables:

1. `wallet_trace_evidence_captures` — immutable finalized capture metadata,
   strict per-run slot, aggregate counts, anchor relationship, and digest;
2. `wallet_trace_evidence_nodes` — unique capture preorder/hash/account+LT
   transaction observations with explicit parent linkage;
3. `wallet_trace_evidence_messages` — role/ordinal-scoped sanitized message
   headers and provider-observation identities.

The migration is online-validation-only, repairs only exact empty interrupted
fragments, rejects schema drift or pre-revision rows, performs no legacy
backfill, and refuses downgrade. Foreign keys cascade capture → node → message.
Message observation keys are deliberately non-unique across captures/runs; this
release does not introduce hidden global or cross-run deduplication.

## v0.23.1 workspace

The trace card automatically performs only the database readback for the
selected eligible anchor. Live preview and finalized capture remain separate
manual actions. Scope, abort, and monotonic sequence guards include run, mode,
account, LT, and hash. Read, preview, and capture errors are independent; a
failed live request never removes a previously confirmed immutable record.

---

# TON Wallet Intelligence Dashboard — v0.23.0 TRACE EVIDENCE PREVIEW

This release adds one explicit, read-only trace evidence preview for an eligible
low-level transaction already stored in a real wallet-ingestion run. The user
selects a coherent transaction anchor and requests one sanitized TonAPI trace
summary manually. No trace is fetched automatically, persisted, merged into
activity, reconstructed into transfer/trade semantics, or passed to PnL.

## Release scope

- `GET /api/wallets/ingest/{run_id}/transactions/{transaction_hash}/trace-evidence`
  is the only new public endpoint.
- `run_id` is a canonical positive signed-64-bit decimal. `transaction_hash` is
  a canonical lowercase 64-character hexadecimal hash. Noncanonical path values
  return 422 before provider access.
- Missing runs or transactions return 404. An ineligible guard, network, run, or
  stored identity returns 409 before provider access. Provider transport or
  protocol failure and any trace/stored-anchor mismatch return a
  credential-sanitized 502.
- An eligible request performs exactly one TonAPI
  `GET /v2/traces/{transaction_hash}` call with no query or request body. There
  is no account-trace discovery call, pagination, retry loop, hidden fallback,
  or automatic refresh.
- Success and error responses use `Cache-Control: no-store`; the browser request
  also uses `no-store`.
- The endpoint reads existing run/transaction identity only and performs no DML,
  DDL, commit, ingestion, run mutation, or trace persistence.

## Eligibility and exact stored anchor

Before the provider can be contacted, all of the following must hold:

1. the current configuration is `DATA_MODE=real`, selects `tonapi`, enables the
   wallet-activity live guard, and has a valid network-matching base URL;
2. the persisted run exists, is real, and matches the configured TON network;
3. exactly one stored row matches the requested transaction hash;
4. provider/source/raw provenance and the complete persisted
   `ton_account_tx_v1` tuple re-derive coherently;
5. the re-derived canonical hash equals the lowercase path hash.

The returned provider tree must then contain the requested hash exactly once,
and that node's canonical transaction hash, unsigned-64-bit LT, and canonical
raw account must exactly equal the three persisted identity fields. A missing
anchor or a mismatch is a 502 provider-evidence failure, not a partial success.

## Bounded trace normalization and sanitized allowlist

TonAPI's official `GET /v2/traces/{trace_id}` operation can resolve a trace id or
the hash of a transaction in that trace. v0.23.0 deliberately narrows this to a
canonical hash already stored under the selected run. It traverses the recursive
provider response iteratively with trace-specific caps of 256 transaction nodes,
depth 32, and 2,048 outgoing messages, in addition to the existing generic JSON
transport limits. Interfaces must be a bounded list of non-empty strings, with
at most 128 entries per node and 128 characters per value, but interfaces are
never returned.

Each accepted node requires a non-emulated state, canonical 32-byte transaction
hash, canonical raw account, unsigned-64-bit LT, nonnegative signed-64-bit
timestamp, boolean success/aborted fields, list-shaped outgoing messages with
known types, and list-shaped children. Transaction hashes cannot repeat, and one
canonical account + LT coordinate cannot change hash.

The strict response contract is `tonapi_transaction_trace_preview_v1`. Its
allowlist contains only contract/run/provider metadata, `trace_state`, the exact
stored anchor, a structural summary, permanent safety flags, and one bounded
message. The summary contains root hash, transaction count, maximum depth,
outgoing and pending-internal message counts, successful/failed/aborted counts,
and unique-account count. Raw messages, BOCs, decoded bodies, interfaces,
actions, display metadata, and the provider's recursive tree are omitted.

`is_provider_indexed_low_level_trace` is true. Every promotion flag remains
false: `is_blockchain_proof_verified`,
`is_authoritative_activity_identity`, `semantic_reconstruction_applied`,
`activity_merge_applied`, `deduplication_applied`,
`eligible_for_cost_basis`, `used_by_pnl`, and `is_ownership_proof`.

## Finalized and pending semantics

- `finalized` means the accepted non-emulated provider response contains no
  remaining internal outgoing message anywhere in the trace tree.
- `pending` means at least one such internal outgoing message remains.
- An emulated node is rejected instead of being labeled finalized or pending.
- Finalization does not mean every transaction succeeded. Successful, failed,
  and aborted counts remain separate and visible.
- Neither state is locally verified blockchain proof, authoritative semantic
  activity, complete history, ownership proof, cost-basis evidence, or PnL
  eligibility. A later explicit request may observe a provider transition from
  pending to finalized; no background polling occurs.

## Trace evidence UI

- The card renders only for a persisted run and selects only coherent live
  TonAPI transaction identities; duplicate hashes are suppressed in the
  selector.
- Mock runs, runs with no transactions, and runs without an eligible identity
  remain network-silent with a disabled inspect action.
- The initial state says an explicit request is required. Inspecting and
  refreshing have separate accessible running labels; finalized and pending
  results are visually distinct.
- A request-specific abort controller and monotonic sequence guard prevent stale
  responses from replacing the selected anchor. Changing the anchor clears its
  prior result; loading a different run remounts and aborts run-scoped state.
- A failed first request shows an unavailable state. A failed explicit retry
  preserves the last successful result and exposes retry without promoting it to
  fresh evidence.
- The browser revalidates the exact response keys, counts, stored hash + LT +
  account anchor, trace-state coherence, and every permanent false flag before
  rendering the result.

## Retained recent-run catalog

- `GET /api/wallets/ingest?limit=8` returns the newest persisted-run summaries;
  the default catalog limit is `8`.
- `limit` must be one canonical ASCII positive decimal from `1` through `50`.
  Leading zeros, signs, whitespace, decimals, booleans, empty values, duplicate
  `limit` parameters, unknown parameters, and out-of-range values return 422.
- The catalog is fixed to descending persisted run id. It exposes no offset,
  cursor, filter, client-selected sort, or total count; `truncated` reports only
  whether an older run exists beyond the returned newest page.
- Catalog run ids are canonical positive signed-64-bit decimal strings, up to
  `9223372036854775807`, so transport does not round them through a JSON number.
- `GET /api/wallets/ingest/{run_id}` remains the only full stored-run read
  endpoint. Existing, missing, and invalid path ids retain the v0.22.8
  200/404/422 behavior and exact stored timestamp restoration.
- Wallet input is now bounded to 128 characters in backend validation and the
  browser control.

## Minimal catalog response

The top-level response contains exactly `runs`, `limit`, and `truncated`. Each
run summary contains exactly six fields:

1. `run_id`;
2. `wallet_hint`;
3. `time_window`;
4. `created_at`;
5. `status`;
6. `data_mode`.

`wallet_hint` is bounded to at most 11 characters: values at least 16 characters
use the first six and last four submitted characters separated by one ellipsis,
while shorter legacy values use the non-reconstructing `stored…run` sentinel. The full
submitted address, canonical account identity, custom bounds, requested
surfaces, provider evidence, activity rows and counts, warnings, and messages
are deliberately absent.

The backend issues one projected SELECT against `wallet_ingestion_runs`, orders
by id descending, and reads at most `limit + 1` rows. It does not load child
tables, parse stored provider metadata, load settings, construct an adapter,
contact a provider, insert, update, delete, commit, or otherwise mutate the
database. The response sends `Cache-Control: no-store`; the browser request also
uses `no-store`.

## Catalog UI and request races

- The workspace requests eight recent summaries and shows the newest three in
  its collapsed state; the user can expand to all eight.
- Initial load, manual refresh, and retry use a catalog-specific abort
  controller and monotonic request sequence. A stale or aborted request cannot
  overwrite a newer catalog or interfere with preview, ingestion, refresh, or
  full stored-run loading.
- A refresh error keeps the last successful catalog visible and presents a
  retry action. An empty successful catalog remains distinct from an error.
- Successful ingestion refreshes the catalog after the new run is committed.
- Selecting a catalog row passes its id directly to the existing full-run
  loader. A failed row open keeps the prior selected run and catalog current.
- Signed-64-bit ids outside the JavaScript safe-integer range remain visible as
  exact decimal strings, but their open action is disabled rather than rounded
  to another run.

## Atomic full-run workspace state

- A successful load validates the response id and stored request metadata, then
  restores wallet, time window, exact custom bounds, requested surfaces,
  request snapshot, and displayed run as one state transition.
- Preview and persisted-run results are mutually exclusive. A newly loaded or
  ingested run cannot silently shadow a later preview, and preview state cannot
  leak into a stored run.
- A 404, 422, network error, stale response, or incoherent response leaves the
  previously selected run and its rendered results intact.
- Run-scoped evidence, PnL, signal, and interval cards are keyed by selected run
  id and remount when a different stored run is loaded.
- Request signatures canonicalize datetime values before comparison, so a
  restored custom range is not marked stale merely because the form displays a
  local datetime while the API stores UTC.
- Loaded custom bounds keep the exact canonical UTC values for signatures and
  subsequent preview/run payloads until the corresponding date input is edited.
  Local `datetime-local` presentation therefore cannot shift a DST-fold
  instant or truncate persisted microseconds behind a fresh-state label.

## Retained interval-coverage contract

- `analysis_version: wallet_history_readiness_v0.22.7` continues to expose
  `bounded_interval_coverage` under the unchanged
  `wallet_multi_run_interval_coverage_v1` contract.
- The request still requires one explicit target run and 2-50 distinct run ids
  for the same wallet identity and data mode.
- Every selected run is classified independently in each coverage layer as
  `included`, `excluded`, or `not_requested`, with its recorded evidence state
  and rejection reason preserved.
- Accepted intervals use exact half-open UTC semantics: `[start, end)`.
- Durations are calculated with integer microseconds and serialized as
  canonical decimal strings. No floating-point, browser safe-integer, or
  whole-second rounding can hide a one-microsecond gap.
- A deterministic boundary sweep reports accepted intervals, their union,
  adjacency, overlap segments and depth, and internal gap segments.
- Time before the earliest eligible start and at or after the latest eligible
  end remains `unknown`.

## Strict evidence revalidation

Coverage is not derived from stored start/end fields alone. History readiness
first revalidates every selected run's persisted stream and page evidence:

- low-level transaction coverage accepts only one coherent bounded
  `transactions` stream in validated `complete` state;
- provider-display coverage accepts only one coherent bounded `account_events`
  stream in validated `provider_stream_complete` state;
- stream contract, provider, scope, query filters, sort order, page sequence,
  cursors, counts, digests, bounds, completion reason, errors, and run scope must
  satisfy the existing fail-closed page-evidence validators;
- missing, ambiguous, malformed, incomplete, preview-only, legacy, or otherwise
  ineligible evidence is excluded rather than repaired or inferred;
- a surface that was not requested is reported separately as `not_requested`
  and is never silently counted as an excluded or covered interval.

## Two separate coverage layers

The contract contains two layers that are never combined:

1. `low_level_transactions` measures validated low-level transaction-query
   intervals.
2. `provider_display_events` measures validated TonAPI account-event display
   intervals.

`cross_stream_union_applied` is always false. A gap in one layer cannot be
filled by evidence from the other layer, and overlap between the layers has no
coverage meaning. TonAPI event actions remain mutable, display-only provider
interpretations; even contiguous `provider_display_events` coverage is not
authoritative transfer, swap, or activity history.

## Interval semantics

For each layer, the response exposes:

- accepted per-run intervals and the normalized union;
- a selected span from the earliest eligible start to the latest eligible end;
- exact covered, gap, overlap, and span durations as canonical decimal
  microsecond strings;
- overlap segments with contributing run ids and coverage depth;
- internal gap segments with the eligible run ids on each side;
- included, excluded, and not-requested run ids plus per-run evidence reasons;
- `contiguous_selected_span`, `gapped_selected_span`, or
  `no_validated_intervals` state.

Touching half-open intervals are adjacent and form one contiguous union.
Overlapping intervals contribute coverage only once to the union, while their
overlap duration and maximum depth remain visible. Gaps are reported only
inside the earliest-to-latest eligible span; the contract makes no statement
about time outside it.

## Retained catalog, loader, and interval UI

The wallet workspace retains the recent catalog inside the stored-run loader,
with independent loading, refresh, retry, empty, truncated, expanded, current,
opening, and unsafe-id states. A successful full read restores the saved
controls and makes that run current; a failed read reports its own error without
hiding or replacing the previous run. When the id changes, run-scoped cards
remount against the new target. The selected-run history-readiness card still
accepts the remaining run ids for a total of 2-50 distinct runs and keeps
transaction and provider-display interval summaries separate.

## Migration and compatibility

v0.23.0 adds no database migration. Alembic head remains
`20260710_0005`. The v0.22.6 provider event/action observation identity
contract `tonapi_event_action_obs_v1`, transaction identity, and persisted
acquisition evidence remain unchanged. Trace previews are not stored. Backend
`VERSION=0.2.1` remains the independent API-version field;
`wallet_history_readiness_v0.22.7` and
`wallet_multi_run_interval_coverage_v1` are unchanged.

Legacy or malformed stream evidence is not synthesized into interval coverage.
It is represented through explicit per-layer exclusion or not-requested state.

## Explicitly unchanged

- No transaction or event rows are merged across runs.
- No trace response, summary, pending/finalized state, message, or semantic row
  is persisted.
- No automatic provider request, polling, account-trace discovery, retry, or
  ingestion traversal is introduced.
- No trace-derived transfer, swap, jetton-asset, counterparty, or activity
  identity is created.
- No cross-run or semantic deduplication is applied.
- No complete pre-run, global, or full wallet history is established.
- No acquisition cost basis or PnL input is created.
- Provider-display event actions remain non-authoritative.
- `full_pre_run_history_established`, `complete_wallet_history_established`,
  `is_global_history_coverage`, `is_authoritative_activity_coverage`,
  `activity_rows_merged`, `deduplication_applied`, `is_cost_basis`,
  `eligible_for_cost_basis`, and `used_by_pnl` remain false.
- Backend `VERSION=0.2.1` remains the API-version field; `v0.23.0 TRACE EVIDENCE
  PREVIEW` is the product label.

## Verification

```bash
cd backend
.venv/bin/python -m pytest -q

cd ../frontend
npm test
npm run build
npm audit
```

The frontend test/build toolchain is Vitest 4 with Vite 8, and the checked-in
dependency graph reports zero `npm audit` vulnerabilities. Verification covers
the exact explicit trace endpoint, canonical paths, eligibility-before-provider
ordering, one provider GET, exact stored hash + LT + account matching, iterative
node/depth/message limits, malformed and emulated trace rejection, coherent
finalized/pending states, strict sanitized allowlists, 404/409/502 mapping,
credential redaction, no-store, database non-mutation, network-silent mock and
initial UI states, explicit inspection, abort/sequence handling, anchor/run
reset, and last-success preservation. Existing verification continues to cover
canonical `limit` values and rejection of duplicate or unknown query input,
exact six-field summaries, masked bounded wallet hints, decimal-string signed-
64-bit ids, newest-first ordering and truncation, one projected SELECT,
provider-free and mutation-free reads, no-store behavior, the collapsed three-
of-eight UI, refresh/retry preservation, stale-request suppression, and unsafe-
id disabling. It also continues to cover the full-run frontend
safe-integer gate, 200/404/422 behavior, exact persisted timestamp restoration,
atomic state replacement, failed-load preservation, run-card remounting,
strict stream/page revalidation, 2-50 selected runs, exact interval math,
independent layers, and unchanged false merge/history/cost/PnL flags. No
credential may appear in logs, warnings, persisted evidence, errors, exports,
or UI copy.

Vite 8 and the React plugin require Node.js `^20.19.0 || >=22.12.0`; npm 10 or
newer is required. These prerequisites are declared in `frontend/package.json`
instead of relying on an implicit local toolchain.
