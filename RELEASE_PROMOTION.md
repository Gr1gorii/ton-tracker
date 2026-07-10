# TON Wallet Intelligence Dashboard — v0.23.1 Promotion Checklist

Operational gates for the finalized-only persisted low-level trace evidence
contract. The v0.23.0 live preview remains a separate read-only operation.

## Version contract

- Product label: `v0.23.1 PERSISTED TRACE EVIDENCE`.
- Backend API version remains independently frozen at `0.2.1`.
- New public persistence contract:
  `tonapi_low_level_trace_evidence_v1`.
- Existing `tonapi_transaction_trace_preview_v1`, transaction identity,
  acquisition, readiness, interval, and PnL contracts remain unchanged.
- README is intentionally frozen until the planned v0.24.0 final release.

## Migration gates

- Alembic head is `20260710_0006`.
- New tables are exactly `wallet_trace_evidence_captures`,
  `wallet_trace_evidence_nodes`, and `wallet_trace_evidence_messages`.
- Capture, node, self-parent, message, run, and transaction foreign keys have
  the declared cascade behavior.
- `(run_id, capture_slot)` is unique and the runtime accepts only slots 0-15.
- Message observation identity is indexed but deliberately non-unique across
  captures and runs; no global deduplication is inferred.
- Fresh, 0005 upgrade, exact empty interrupted fragments, and already-current
  paths reach the same reflected schema.
- Drift, unexpected indexes/constraints/rows, wrong foreign-key options,
  offline generation, and downgrade fail closed.
- No v0.23.0 preview or legacy row is backfilled as persisted evidence.

## Endpoint gates

- `GET .../trace-evidence` retains its one-call, no-write preview semantics.
- `GET .../trace-evidence/persisted` is provider-free and mutation-free.
- `POST .../trace-evidence/persisted` is the only capture operation.
- Canonical run/hash validation returns 422 before settings, provider, or DML.
- Missing run/transaction/record returns the exact 404 contract.
- Ineligible configuration, pending trace, capacity, or corrupt stored graph
  returns 409; provider/protocol/anchor failure returns sanitized 502; storage
  unavailability returns sanitized 503.
- Every handled success and error returns `Cache-Control: no-store`; browser
  requests also use `cache: no-store`.
- First capture performs exactly one provider trace GET. Existing capture
  readback and idempotent POST perform zero provider calls and zero writes.

## Graph and atomicity gates

- A candidate is non-emulated and finalized before persistence.
- Limits are 256 nodes, depth 32, 2,048 remaining outgoing messages, 2,304
  total persisted message observations, and 16 captures per run.
- Transaction hashes and account+LT coordinates are unique per capture.
- Nodes form strict DFS preorder; every non-root parent is the active node at
  depth-1 and every depth step is coherent.
- Every child has exactly one internal inbound message whose source and
  destination match parent and child accounts.
- Root inbound and remaining outbound roles accept only compatible message
  types; finalized graphs retain no internal outgoing message.
- Message role/ordinal identities and provider observation keys re-derive
  exactly. Cross-run reuse does not become a dedup identity.
- The canonical digest covers graph, counts, network, run, capture slot,
  capture timestamp, and the exact persisted anchor used for capture.
- Full relational graph and digest revalidation occurs after flush but before
  commit. Any mismatch rolls capture, nodes, and messages back to zero rows.
- Every read performs the same structural and digest revalidation and never
  falls back to a provider when stored data is corrupt.
- Raw provider JSON, BOCs, bodies, decoded data, interfaces, actions,
  presentation metadata, authorization headers, and credentials are absent
  from all three tables and public responses.

## UI gates

- Selecting a real eligible transaction automatically issues only the
  database GET; mock/empty states remain network-silent.
- Live preview and finalized capture are separate explicit actions.
- Pending preview cannot enable capture.
- Scope identity includes run, mode, account, LT, and hash. Scope changes abort
  read, preview, and capture and ignore late results.
- Read, preview, and capture errors remain distinct. A failed provider request
  never removes the last confirmed persisted record.
- Saved state says `FINALIZED AT CAPTURE`, not fresh/current chain state.
- Permanent labels keep stored evidence separate from blockchain proof,
  authoritative activity, ownership, cost basis, and PnL.
- Desktop and narrow viewport have no horizontal overflow, console warning, or
  console error.

## Verification gates

- Full backend pytest passes.
- Python compileall passes.
- Full frontend Vitest passes.
- TypeScript and Vite production build pass.
- Frontend dependency audit reports zero vulnerabilities.
- Alembic current is 0006; SQLite integrity check is `ok`; foreign-key check is
  empty; pre-existing domain table counts are unchanged by migration.
- A guarded live TonAPI capture succeeds on an eligible stored transaction,
  then exact GET and repeated POST are provider-free and stable.
- Database counts and digest remain unchanged across provider-free readback.
- Credential and prohibited-brand scans are clean; README has no diff.

## Promotion

After all gates pass, commit only the intended v0.23.1 files, push a dedicated
branch, open and merge a ready PR, then create annotated tag `v0.23.1` on the
merge commit. Never rewrite published history.

## Rollback

- Before merge, patch the release branch and rerun every gate.
- After merge, use a follow-up revert commit; do not force-push.
- Revision 0006 is forward-only because downgrade would discard evidence.
  Restore a verified pre-0006 backup when schema rollback is required.
