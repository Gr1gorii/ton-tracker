# Verified production deployment

Deploy only from the three assets attached to one stable GitHub Release. The
bundle verifier checks the canonical manifest, its SHA-256 checksum, the signed
attestation, repository, signer workflow, tag ref, source commit, and runner
policy before it prints any image reference.

## Prepare one release

Start from an empty private directory and replace the example tag with the
release being deployed:

```sh
release=v0.69.0
assets=$(mktemp -d)
chmod 700 "$assets"
state="$HOME/.local/state/gram-scope"

gh release download "$release" \
  --repo Gr1gorii/ton-tracker \
  --pattern "gram-scope-${release}-deployment*" \
  --dir "$assets"
```

## Configure alert delivery

Create the Alertmanager configuration outside the repository and keep it in the
deployment account's private configuration directory:

```sh
install -d -m 700 "$HOME/.config/gram-scope"
alertmanager_config="$HOME/.config/gram-scope/alertmanager.yml"
${EDITOR:?Set EDITOR first} "$alertmanager_config"
chmod 600 "$alertmanager_config"
export ALERTMANAGER_CONFIG_FILE="$alertmanager_config"
export ALERTMANAGER_RETENTION=120h
```

The minimum routed configuration has one real notification integration. Replace
the example endpoint with the production incident receiver before deployment:

```yaml
route:
  receiver: operations
  group_by: [alertname]
  group_wait: 30s
  group_interval: 5m
  repeat_interval: 4h
receivers:
  - name: operations
    webhook_configs:
      - url: https://alerts.example.invalid/gram-scope
        send_resolved: true
```

Do not commit this file: receiver URLs and credentials are secrets. The guarded
rollout accepts only a regular, non-symlink file owned by the deployment account,
with no group or world permissions, bounded size, no YAML aliases, a bounded
route tree, and a configured integration for every routed receiver. The same
configuration must also pass the Alertmanager v0.33.1 `amtool` validator.

Alertmanager state is not supplied manually. The rollout creates a private
durable sibling of the deployment state directory. For the example above it is
`$HOME/.local/state/gram-scope-alertmanager`; it must remain owned by the same
account with mode `0700` and be included in host backups.

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
attempt id, operation, start time, exact target identity, active base identity,
and rollout phase.

For an upgrade or rollback with an active receipt, it then runs compose
validation, the container preflight, the upstream Alertmanager configuration
validator, an on-demand SQLite backup, a restore drill of that backup, the exact
image pull, a target-image migration rehearsal on a second private restored
copy, service activation, an internal Prometheus-to-Alertmanager delivery smoke
gate, an active downstream notification drill, and the public smoke gate in
order.

For a first deployment with no active receipt, the exact images are pulled and
the target backend first requires genuinely empty database and backup volumes.
It creates the full current schema only in private ephemeral storage, validates
the schema revision and SQLite integrity, destroys that copy, and durably
checkpoints the successful empty-volume gate before any application activation.
The backend and frontend then start, followed immediately by an on-demand
backup, restore drill, and target-image migration verification. The periodic
backup, recovery, monitoring, and alert-delivery services start only after
those database gates pass. A non-empty volume before that checkpoint is treated
as unmanaged state and fails closed; it is never silently adopted.

No later step runs after an earlier failure. The tool discards command output
on failure so provider or container diagnostics cannot leak through the release
interface.

The migration rehearsal runs the target backend image against an ephemeral copy
of the heartbeat-selected verified backup. It applies the same fail-closed
Alembic bootstrap used at application startup, validates the resulting model
schema and SQLite integrity, confirms the observed source and target revisions,
and then destroys the copy. The live database and retained backup stay
read-only to this gate. An unknown future revision, schema drift, failed
migration, integrity error, or inconsistent revision stops the rollout before
service activation. The same rule applies to an explicit rollback, preventing
older code from opening a newer schema it cannot recognize.
Rollback targets created before v0.68.0 use the equivalent restore, migration,
and post-migration verification commands already present in that signed target
image, so the compatibility gate remains available for the immediate previous
release.

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

The periodic backup and recovery watchdogs continue after activation. A rollout
is complete only after the internal delivery and public smoke gates pass and
backup/recovery health is confirmed through `/api/ops/ready` and monitoring.

The rollout command also passes the absolute state directory and the operator's
numeric uid/gid to Compose. The internal `deployment-monitor` and Alertmanager
containers run as that same host identity. Alertmanager mounts only its private
configuration and durable state, exposes port 9093 only to the Compose network,
and runs with clustering disabled for this single-node topology. The deployment
monitor mounts only the state directory plus its read-only image filesystem and
exposes port 9101 only to the Compose network. Do not start either service under
a different uid or copy the deployment records into a second monitoring
directory: both choices would break the validated ownership boundaries.

## Audit deployment state

Validate the complete state boundary without changing the receipt, journal, or
ledger events:

```sh
python ops/inspect_deployment_state.py --state-directory "$state"
```

The command acquires the same non-blocking lock as a rollout and emits one
compact `gram_scope_deployment_audit_v2` JSON object. It reports the active and
previous signed release identities, receipt metadata, ledger event count and
head digest, receipt binding, and any exact pending attempt. It contains no
provider credential or command output. Use the exit code as a monitoring
contract:

- `0`: the state is valid and either `ready` or `empty`;
- `2`: the state is valid but an interrupted attempt requires inspection and an
  explicit matching `--resume`; the pending record includes its durable rollout
  phase;
- `3`: the state is corrupt, unsafe, or otherwise fails validation;
- `4`: another deployment currently holds the lock;
- `64`: the audit command arguments are invalid.

An audit never clears a stale journal or binds an awaiting receipt, even when a
published ledger event proves that the rollout gates passed. Only the explicit
resume path performs that reconciliation.

## Monitor deployment state

Prometheus scrapes `deployment-monitor:9101/metrics` every 15 seconds. Each
scrape acquires the same non-blocking lock and runs the complete state audit;
it never returns a release tag, source commit, manifest digest, attempt id,
credential, command output, or free-form error. The bounded metric contract is:

- `ton_tracker_deployment_audit_valid` for a complete successful validation;
- `ton_tracker_deployment_state_ready` for an active receipt with no pending
  attempt;
- `ton_tracker_deployment_lock_busy` while a rollout owns the lock;
- `ton_tracker_deployment_pending_attempt` for interrupted work;
- `ton_tracker_deployment_ledger_events` and
  `ton_tracker_deployment_receipt_bound` for ledger/receipt continuity;
- `ton_tracker_deployment_state_info` with one fixed status label from
  `ready`, `empty`, `interrupted`, `busy`, or `invalid`.

A busy result is expected during a guarded rollout, so it becomes critical only
after 45 minutes. Invalid state, an interrupted attempt, an unbound ledger head,
an empty production state, and an unavailable monitor have separate alert
rules. `/healthz` checks only that the internal exporter is serving; corrupt
state remains scrapeable and therefore visible as metrics instead of causing a
restart loop.

Prometheus sends evaluated alerts to the internal Alertmanager API and scrapes
Alertmanager metrics. Alertmanager is not published on a host port. Every
rollout confirms Prometheus and Alertmanager readiness and requires Prometheus
to report exactly `alertmanager:9093` as its active, non-dropped notification
target. Separate critical rules detect an unavailable Alertmanager, failed
Prometheus delivery, and failed downstream notifications. These rules diagnose
the delivery chain.

Every guarded rollout also submits one uniquely labelled
`GramScopeNotificationDrill` through Alertmanager API v2. It requires the alert
to become active, discovers every receiver selected by the live routing tree,
and waits for each receiver integration to record at least one successful
notification request. Receiver-name metrics are enabled only on Alertmanager's
private Compose network. The drill then resolves the exact alert even when the
delivery gate fails. A receiver error, silence, inhibition, missing route,
counter reset, ambiguous metric series, or delivery taking longer than 120
seconds fails the rollout and preserves the pending deployment journal.

The external incident destination will therefore receive a firing test message
whose summary says `GRAM Scope production notification drill`; no operator
action is required. Keep the applicable `group_wait` comfortably below 120
seconds and ensure organization-wide silences or inhibition rules do not match
the drill label. The rollout proves delivery as observed by Alertmanager; keep
the organization's independent incident-response drills as a separate human
acknowledgement check.

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
compose action. A valid upgrade or rollback resume repeats the complete guarded
rollout.

For an interrupted first deployment, a journal still in the `prepared` phase
repeats the strict empty-volume gate, so retrying cannot bypass rejection of an
unmanaged database. After the durable `initial_bootstrap_verified` checkpoint,
resume accepts either both still-empty volumes or exactly `ton_check.db` with
its known SQLite journal/WAL sidecars and only recognized, verified retained
backups. A backup without its database is treated as possible data loss and
requires manual inspection. If the database exists, the target image
creates and rehearses a verified backup before application activation is
retried. Any other
entry, link, non-regular file, corrupt database, unknown revision, or schema
drift fails closed.

If the success event was already durably published, the matching ledger attempt
id proves that every rollout gate passed. `--resume` binds or confirms the v4
receipt and clears the stale journal without touching containers. To resume a
rollback, pass both `--rollback` and `--resume`.

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
