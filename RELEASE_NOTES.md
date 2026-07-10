# TON Wallet Intelligence Dashboard — v0.22.6 ACTION IDENTITY

This release adds a strict provider-scoped observation identity for transfer
and swap rows derived from TonAPI account-event actions. The identity preserves
the exact event/action coordinate returned by the provider; it does not promote
mutable high-level actions to authoritative activity, blockchain proof, or
ownership proof.

## Release scope

- Every guarded real/live TonAPI transfer or swap action is evaluated against
  `tonapi_event_action_obs_v1` before its identity is persisted.
- The coordinate contains provider, TON network, canonical run account,
  canonical event id, canonical event LT, and the original zero-based action
  index from the complete provider action array.
- Filtering unsupported action types never renumbers supported actions.
- Transfer and swap surfaces share one identity namespace, so the same provider
  coordinate cannot be accepted twice or retyped into a second activity row.
- Mock, malformed, incoherent, and legacy rows remain explicitly
  `unavailable`.
- Bounded transaction and shared account-event pagination from v0.22.5 remain
  unchanged.

## Provider observation identity contract

The persisted key is derived from:

```text
tonapi_event_action_obs_v1
| tonapi
| network
| canonical_account
| canonical_event_id
| canonical_event_lt
| original_action_index
```

The event id is canonical lowercase 32-byte hex, event LT is a positive uint64,
and the action index is a strict non-negative integer captured before surface
filtering. Network, run wallet, provider provenance, event fields, and action
type must remain coherent with the raw provider observation.

`action_type` and activity surface are audit fields, not key fields. This is
intentional: changing the interpretation of one provider coordinate must expose
a conflict instead of creating a new identity.

The identity is provider-scoped observation evidence only:

- `is_provider_observation_identity` can be true for a coherent live row;
- `is_blockchain_proof_verified` is false;
- `is_authoritative_activity_identity` is false;
- `is_ownership_proof` is false;
- `eligible_for_cost_basis` is false;
- `deduplication_applied` is false;
- `used_by_pnl` is false.

It therefore does not establish semantic transfer or swap equivalence across
provider revisions, verified chain execution, ownership, acquisition cost
basis, or PnL.

## Migration and legacy behavior

Alembic revision `20260710_0005` adds the event-action observation fields and
indexes to both `wallet_transfers` and `wallet_swaps`. It enforces per-table
identity uniqueness and validates the shared transfer/swap namespace before
creating indexes.

Rows written by v0.22.5 do not contain the original action index. The migration
does not infer that index from row order, payload shape, timestamp, or action
type, so those rows remain `event_action_identity_status: unavailable`.
Migration retry accepts only an exact, safe schema state; downgrade remains
unsupported.

## History readiness v0.22.6

`analysis_version: wallet_history_readiness_v0.22.6` validates provider action
identities independently of low-level transaction identity. It reports
event-action identity coverage, provider-scoped groups, and conflicts across
the selected runs. A repeated identity with changed semantic payload is a
conflict, not a second valid observation.

Provider-scoped groups do not prove global activity continuity or authorize
cross-run deduplication. `history_complete`, `deduplication_applied`,
`is_cost_basis`, `eligible_for_cost_basis`, and `used_by_pnl` remain false.

## TonAPI response hardening

- A response body larger than 16 MiB is rejected as protocol evidence.
- Parsed JSON is limited to depth 64 and 200,000 nodes.
- JSON numeric tokens are limited to 128 characters; non-standard and
  non-finite numeric values are rejected.
- Validation uses a bounded iterative walk, so deeply nested input does not
  escape as an uncaught recursion failure.
- Malformed JSON, invalid UTF-8, non-byte bodies, excessive structure, and
  parser resource failures are reported as provider protocol errors; transport
  failures retain provider/network error classification.
- Existing keyed-request HTTPS and non-forwarded redirect authorization rules
  remain enforced.

## Explicitly unchanged

- No authoritative transfer, swap-action, jetton-asset, or counterparty
  identity is introduced.
- No cross-run merge, interval stitching, semantic deduplication, or complete
  pre-run acquisition history is established.
- Existing realized/unrealized calculations and Real-PnL gates are unchanged.
- Backend `VERSION=0.2.1` remains the API-version field; `v0.22.6 ACTION
  IDENTITY` is the product label.

## Verification

```bash
cd backend
.venv/bin/python -m pytest -q

cd ../frontend
npm run build
```

Guarded live verification must confirm that original action indexes survive
normalization, persistence, readback, and export; transfer and swap observations
share one identity namespace; malformed or conflicting coordinates fail closed;
legacy rows remain unavailable; readiness remains diagnostic; and no credential
appears in logs, warnings, persisted evidence, errors, or exports.
