# TON Wallet Intelligence Dashboard — v0.23.7 Promotion Checklist

Operational gates for the immutable native TON activity ledger.

## Version and migration

- Product label is `v0.23.7 IMMUTABLE NATIVE ACTIVITY LEDGER`; backend API version stays
  independently frozen at `0.2.1`.
- New public contract is `ton_native_activity_ledger_v1`; all prior evidence,
  flow, asset, and counterparty contracts remain unchanged.
- Alembic head is `20260710_0008`, adding native activity ledgers and rows on
  top of the unchanged 0007 BOC tables.
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
- Scope changes abort all four request classes and reject stale responses.
- The visible record shows verifier/version, counts, digests, and
  `RAW BOC HIDDEN`; it never renders raw BOC hex or message bodies.
- Desktop and narrow layouts must have no horizontal overflow, console error,
  or console warning.

## Release gates

- Full backend pytest and compileall pass.
- Full frontend Vitest, TypeScript/Vite build, and dependency audit pass.
- Live run 32 materializes one outgoing 3 TON semantic row, then provider-free
  readback returns the same digest and relational counts.
- Credential/prohibited-brand scans are clean and README has no diff.
- Commit only intended files, push the dedicated release branch, open and merge
  a ready PR, then create annotated tag `v0.23.7` on the merge commit.

## Rollback

- Before merge, patch the release branch and rerun every gate.
- After merge, use a follow-up revert commit; never rewrite published history.
- Revisions 0007-0008 are forward-only. Restore the verified pre-upgrade backup when a
  schema rollback is required.
