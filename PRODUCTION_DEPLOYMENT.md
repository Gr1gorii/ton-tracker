# Verified production deployment

Deploy only from the three assets attached to one stable GitHub Release. The
bundle verifier checks the canonical manifest, its SHA-256 checksum, the signed
attestation, repository, signer workflow, tag ref, source commit, and runner
policy before it prints any image reference.

## Prepare one release

Start from an empty private directory and replace the example tag with the
release being deployed:

```sh
release=v0.63.0
assets=$(mktemp -d)
chmod 700 "$assets"
state="$HOME/.local/state/gram-scope"

gh release download "$release" \
  --repo Gr1gorii/ton-tracker \
  --pattern "gram-scope-${release}-deployment*" \
  --dir "$assets"
```

## Preflight and start

Load the production variables from the host secret store, then run the guarded
rollout as one command:

```sh
python ops/deploy_release.py \
  --manifest "$assets/gram-scope-${release}-deployment.json" \
  --checksum "$assets/gram-scope-${release}-deployment.json.sha256" \
  --attestation-bundle "$assets/gram-scope-${release}-deployment.intoto.jsonl" \
  --tag "$release" \
  --state-directory "$state"
```

The command first acquires a non-blocking exclusive lock in the private,
operator-owned state directory. A concurrent rollout fails before bundle
verification or any container action. While holding that lock, the command
verifies the signed bundle immediately before use, keeps a private snapshot of
the verified manifest for the entire rollout, and injects only its two
digest-pinned image references. After authorization and before any compose or
container action, it atomically writes `pending-deployment.json` with a random
attempt id, operation, start time, exact target identity, and active base
identity. It then runs compose validation, the container preflight, an on-demand
SQLite backup, a restore drill of that backup, the exact image pull, service
activation, and the public smoke gate in order. No later step runs after an
earlier failure. The tool discards command output on failure so provider or
container diagnostics cannot leak through the release interface.

Only after every gate succeeds, the command atomically publishes a private event
under `deployment-events/`, then atomically writes `current-deployment.json`.
Each event records its sequence, exact base and target identities, operation,
journal attempt id, completion time, rollback predecessor, and the SHA-256 digest
of the preceding event. Its canonical bytes are bound to the digest in its file
name. Receipt schema v4 records the verified ledger sequence and head digest in
addition to the active and immediately previous release identities. Existing v1,
v2, and v3 receipts remain accepted and start the ledger on the next success.

The complete event chain and its receipt binding are validated before bundle
verification or container work. A changed, removed, reordered, linked, public,
or malformed event fails closed. The ledger is a local tamper-evident operational
record, not an externally anchored signature: preserve the entire private state
directory on durable access-controlled storage and include it in host backups.

The command durably publishes the event and success receipt before removing the
matching pending journal. A failed or interrupted rollout never replaces the
last successful receipt and deliberately leaves its journal in place. Missing
privacy, corrupt state, or a busy deployment lock fails closed before rollout.

A normal deployment may repeat the exact active identity or move to a strictly
newer stable SemVer release. It cannot silently downgrade or replace one tag
with a different source or manifest identity.

Keep the state directory on durable host storage and do not share it between
unrelated installations. It contains no provider credential, but it is an
operational integrity boundary and must remain owned by the deployment account
with no group or world permissions.

The periodic backup and recovery watchdogs continue after activation. A
rollout is complete only after the public smoke gate passes and backup/recovery
health is confirmed through `/api/ops/ready` and monitoring.

## Resume an interrupted rollout

Do not edit or delete `pending-deployment.json`. Reuse the same three release
assets, tag, state directory, and operation, then add `--resume` to the guarded
command:

```sh
python ops/deploy_release.py \
  --manifest "$assets/gram-scope-${release}-deployment.json" \
  --checksum "$assets/gram-scope-${release}-deployment.json.sha256" \
  --attestation-bundle "$assets/gram-scope-${release}-deployment.intoto.jsonl" \
  --tag "$release" \
  --state-directory "$state" \
  --resume
```

The signed bundle, deployment or rollback operation, target identity, and base
receipt must exactly match the journal. Otherwise the command fails before any
compose action. A valid resume repeats the complete guarded rollout. If the
success event was already durably published, the matching ledger attempt id
proves that every rollout gate passed. `--resume` binds or confirms the v4 receipt
and clears the stale journal without touching containers. To resume a rollback,
pass both `--rollback` and `--resume`.

## Rollback

Select the previous stable tag, download its three assets into a new empty
directory, confirm its identity against `previous_release` in the current
receipt, and run the same guarded command with the same state directory plus
`--rollback`. The command verifies the signed bundle first, then requires its
tag, source commit, and manifest digest to exactly equal `previous_release`
before any compose action. A missing previous identity, an arbitrary older
release, or a same-tag identity conflict fails closed.

```sh
python ops/deploy_release.py \
  --manifest "$assets/gram-scope-${release}-deployment.json" \
  --checksum "$assets/gram-scope-${release}-deployment.json.sha256" \
  --attestation-bundle "$assets/gram-scope-${release}-deployment.intoto.jsonl" \
  --tag "$release" \
  --state-directory "$state" \
  --rollback
```

Never retag an image or combine backend and frontend references from different
manifests. Persistent database, backup, recovery, and Prometheus volumes are not
removed by this procedure. Receipt authorization does not claim database schema
compatibility. If the failed release changed the database schema incompatibly,
restore the pre-rollout verified backup instead of starting older code against
newer data.
