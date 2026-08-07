# Verified production deployment

Deploy only from the three assets attached to one stable GitHub Release. The
bundle verifier checks the canonical manifest, its SHA-256 checksum, the signed
attestation, repository, signer workflow, tag ref, source commit, and runner
policy before it prints any image reference.

## Prepare one release

Start from an empty private directory and replace the example tag with the
release being deployed:

```sh
release=v0.59.0
assets=$(mktemp -d)
chmod 700 "$assets"

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
  --tag "$release"
```

The command verifies the signed bundle immediately before use, keeps a private
snapshot of the verified manifest for the entire rollout, and injects only its
two digest-pinned image references. It then runs compose validation, the
container preflight, an on-demand SQLite backup, a restore drill of that backup,
the exact image pull, service activation, and the public smoke gate in order.
No later step runs after an earlier failure. The tool discards command output
on failure so provider or container diagnostics cannot leak through the release
interface.

The periodic backup and recovery watchdogs continue after activation. A
rollout is complete only after the public smoke gate passes and backup/recovery
health is confirmed through `/api/ops/ready` and monitoring.

## Rollback

Select the previous stable tag, download its three assets into a new empty
directory, and run the same guarded command. Never retag an image or combine
backend and frontend references from different manifests. Persistent database,
backup, recovery, and Prometheus volumes are not removed by this procedure. If
the failed release changed the database schema incompatibly, restore the
pre-rollout verified backup instead of starting older code against newer data.
