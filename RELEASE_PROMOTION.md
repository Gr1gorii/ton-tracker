# TON Wallet Intelligence Dashboard — v0.22.6 ACTION IDENTITY Promotion Checklist

Operational gates for promoting provider-scoped TonAPI event/action observation
identity while preserving bounded acquisition and non-authoritative semantics.

## Version contract

- Product label is `v0.22.6 ACTION IDENTITY`.
- Backend `VERSION=0.2.1` remains the independent API-version field.
- `wallet_history_readiness_v0.22.6` is the diagnostic analysis contract.
- `tonapi_event_action_obs_v1` is the provider observation identity contract.
- Historical v0.22.3 transaction identity and v0.22.5 pagination references
  remain valid and are not relabeled as authoritative activity identity.

## Schema gates

- Alembic head is `20260710_0005`.
- Fresh databases create the baseline plus revisions 0002 through 0005.
- Exact legacy databases preserve every existing domain and acquisition row.
- Existing v0.22.5 transfer/swap rows remain event-action identity
  `unavailable`; no action index is inferred from row order, payload, type, or
  timestamp.
- Existing versioned databases upgrade without `create_all()` repair.
- Retry accepts only exact safe SQLite schema fragments; malformed columns,
  indexes, partial ordering, or unexpected identity values fail closed before
  further DDL.
- Both activity tables contain the complete event-action identity field set.
- Identity keys are unique within each run/table, and migration validation
  rejects a duplicate provider coordinate across transfers and swaps.
- Existing acquisition stream/page uniqueness and cascading foreign keys remain
  intact.
- Runtime SQLite connections report `PRAGMA foreign_keys=1`.
- Downgrade from revision 0005 is rejected with backup-restore guidance.

## Provider observation identity gates

- Identity is created only for coherent guarded real/live TonAPI rows.
- The key contains contract version, provider, network, canonical run account,
  canonical event id, canonical event LT, and original zero-based action index.
- Event id is canonical lowercase 32-byte hex and event LT is a positive uint64.
- Action index is a strict non-negative integer from the complete provider
  action array before filtering; bool, float, string, negative, and oversized
  values fail closed.
- Raw and normalized provider/source/surface/event/action fields remain
  coherent with the run wallet and network.
- Transfer and swap persistence claims identities from one combined namespace.
- `action_type` and activity surface are audit fields, not key fields; retyping
  one coordinate exposes a conflict.
- Mock, malformed, incomplete-provenance, tampered, and legacy rows expose an
  explicit unavailable or invalid identity state.
- Readback and JSON/CSV export preserve the coordinate and all honesty flags.

## Acquisition and protocol gates

- Every request retains one frozen half-open UTC interval `[start, end)`.
- Low-level transaction pagination and the shared account-event page chain keep
  strict descending LT, bounded page caps, local interval filtering, durable
  evidence, and terminal/start-cross completion rules.
- Requesting transfers and swaps together still follows exactly one event
  cursor chain and materializes both surfaces from the same accepted events.
- In-progress events are excluded and prevent event-stream completion.
- A TonAPI response body larger than 16 MiB is rejected as protocol evidence.
- Parsed JSON depth is limited to 64 and total nodes to 200,000 with an
  iterative structural walk.
- Numeric tokens are limited to 128 characters; non-standard and non-finite
  numeric values fail as protocol evidence.
- Malformed JSON, invalid UTF-8, non-byte bodies, excessive structure, and
  parser resource failures are classified as sanitized provider protocol
  errors; transport/read failures retain provider/network classification.
- Keyed TonAPI bases require HTTPS and authorization is not forwarded on
  redirects. Lossy boolean/float cursor values remain protocol errors.

## Data-honesty gates

- The event-action key is described only as provider-scoped observation
  identity, never as blockchain proof or authoritative activity identity.
- `is_provider_observation_identity` can be true only for a coherent row.
- `is_blockchain_proof_verified`,
  `is_authoritative_activity_identity`, `is_ownership_proof`,
  `eligible_for_cost_basis`, `deduplication_applied`, and `used_by_pnl` remain
  false for this contract.
- Provider-chain completion does not establish complete transfer logic, full
  DEX history, global wallet history, or ownership.
- History readiness reports provider observation identity coverage, groups,
  and changed-payload/conflicting-coordinate blockers without performing
  cross-run deduplication.
- `history_complete`, `deduplication_applied`, `is_cost_basis`,
  `eligible_for_cost_basis`, and `used_by_pnl` remain false in every readiness
  response.
- Jettons and native TON balances remain point-in-time snapshots.
- Persisted query/error evidence contains no authorization header, API key,
  raw credential, or credential-bearing URL.
- Mock remains the default executable mode; live calls require every explicit
  guard setting.

## Automated verification

Run from `backend/`:

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m pytest -q tests/test_database_migrations.py
.venv/bin/python -m pytest -q tests/test_tonapi_adapter.py tests/test_tonapi_event_pages.py
.venv/bin/python -m pytest -q tests/test_ton_event_action_identity.py
.venv/bin/python -m pytest -q tests/test_event_action_identity_persistence.py
.venv/bin/python -m pytest -q tests/test_wallet_activity_ingestion.py
.venv/bin/python -m pytest -q tests/test_wallet_history_readiness.py
.venv/bin/python -m compileall -q .
```

Run from `frontend/`:

```bash
npm run build
```

Run repository hygiene checks before staging:

```bash
git diff --check
git status --short
```

## Migration verification

Before upgrading a working database, create and verify a backup. Then confirm:

- Alembic reports `20260710_0005`;
- transfer, swap, acquisition-stream, and acquisition-page counts are unchanged;
- all pre-v0.22.6 activity rows without original action indexes are unavailable;
- no identity key appears in both transfer and swap tables for one run;
- all expected indexes exist and SQLite integrity/foreign-key checks pass;
- retrying startup performs no additional DDL or data mutation.

## Guarded live verification

Use a valid network-matching wallet and the configured server-side TonAPI key
without printing it. Use small event page limits where practical and verify:

- original provider action indexes survive normalization without renumbering;
- persisted transfer and swap identities use canonical network/account/event/LT
  values and remain stable on readback;
- two actions in one event receive distinct keys by original index;
- a repeated or retyped transfer/swap coordinate is rejected;
- CSV and JSON expose provider-scoped semantics and every false proof/use flag;
- bounded page evidence and partial/incomplete surface semantics are unchanged;
- readiness reports identity coverage/groups and keeps global history,
  deduplication, cost-basis, and PnL flags false;
- oversized, malformed, or excessively nested responses fail as sanitized
  protocol errors;
- no credential appears in source, database, backup, logs, warnings, errors, or
  exports.

## UI and documentation gates

- Dashboard label reads `v0.22.6 ACTION IDENTITY` on desktop and mobile.
- Transfer and swap tables identify the provider observation coordinate and
  event reference without implying authoritative semantics.
- The workspace states that the identity is not blockchain proof, ownership
  proof, a deduplication result, a cost-basis input, or a PnL key.
- Legacy unavailable identity remains clear and does not render as a valid key.
- No horizontal overflow or console error is introduced.
- README, release notes, ingestion plan, and this checklist describe the same
  contract and limits.
- `PUBLIC_RELEASE.md` remains the explicitly labeled v0.10.7 stable-baseline
  handoff and is not rewritten as the current development release.

## Promotion commands

After every gate passes:

```bash
git checkout main
git merge --no-ff codex/v0.22.6-event-action-identity
git tag -a v0.22.6 -m "v0.22.6 ACTION IDENTITY"
git push origin main
git push origin v0.22.6
```

## Rollback

- Before push, patch the release branch and rerun all gates.
- After push, use a follow-up revert commit; do not rewrite published history.
- v0.22.6 adds migration 0005. Restore a verified pre-upgrade database backup
  when schema rollback is required; do not run a destructive downgrade.
