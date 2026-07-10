# TON Wallet Intelligence Dashboard — v0.23.2 Promotion Checklist

Operational gates for capture-bound local transaction BOC verification.

## Version and migration

- Product label is `v0.23.2 LOCAL BOC VERIFICATION`; backend API version stays
  independently frozen at `0.2.1`.
- Public contract is exactly `ton_boc_trace_verification_v1`; v0.23.0 preview
  and v0.23.1 persisted graph contracts remain unchanged.
- Alembic head is `20260710_0007`, adding only
  `wallet_trace_boc_verifications` and `wallet_trace_boc_transactions`.
- Fresh, 0006 upgrade, exact empty interrupted DDL, and already-current paths
  have model parity. Drift, orphan fragments, unexpected rows/indexes/FKs,
  offline SQL, and downgrade fail closed.
- README remains frozen until v0.24.0.

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

- GET/POST use canonical run/hash paths and `Cache-Control: no-store`.
- Exact absence is 404; ineligible/corrupt state is 409; sanitized provider
  failure is 502; local verifier/storage unavailability is 503.
- The trace card automatically performs only database readback. Live preview,
  finalized capture, and local BOC verification are distinct explicit actions.
- Scope changes abort all four request classes and reject stale responses.
- The visible record shows verifier/version, counts, digests, and
  `RAW BOC HIDDEN`; it never renders raw BOC hex or message bodies.
- Desktop and narrow layouts must have no horizontal overflow, console error,
  or console warning.

## Release gates

- Full backend pytest and compileall pass.
- Full frontend Vitest, TypeScript/Vite build, and dependency audit pass.
- Live TonAPI first POST returns 201, repeat POST and GET return 200, the digest
  is stable, and SQLite integrity/foreign-key checks are clean.
- Credential/prohibited-brand scans are clean and README has no diff.
- Commit only intended files, push the dedicated release branch, open and merge
  a ready PR, then create annotated tag `v0.23.2` on the merge commit.

## Rollback

- Before merge, patch the release branch and rerun every gate.
- After merge, use a follow-up revert commit; never rewrite published history.
- Revision 0007 is forward-only. Restore the verified pre-0007 backup when a
  schema rollback is required.
