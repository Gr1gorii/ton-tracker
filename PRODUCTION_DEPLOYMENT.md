# Verified production deployment

Deploy only from the three assets attached to one stable GitHub Release. The
bundle verifier checks the canonical manifest, its SHA-256 checksum, the signed
attestation, repository, signer workflow, tag ref, source commit, and runner
policy before it prints any image reference.

## Prepare one release

Start from an empty private directory and replace the example tag with the
release being deployed:

```sh
release=v0.58.0
assets=$(mktemp -d)
chmod 700 "$assets"

gh release download "$release" \
  --repo Gr1gorii/ton-tracker \
  --pattern "gram-scope-${release}-deployment*" \
  --dir "$assets"

umask 077
python ops/verify_release_bundle.py \
  --manifest "$assets/gram-scope-${release}-deployment.json" \
  --checksum "$assets/gram-scope-${release}-deployment.json.sha256" \
  --attestation-bundle "$assets/gram-scope-${release}-deployment.intoto.jsonl" \
  --tag "$release" > "$assets/images.env"

set -a
. "$assets/images.env"
set +a
export DEPLOYMENT_MANIFEST_FILE="$assets/gram-scope-${release}-deployment.json"
```

The verifier writes errors only to stderr and exits with status `2`. Its stdout
contains exactly `BACKEND_IMAGE` and `FRONTEND_IMAGE`, both pinned to canonical
SHA-256 digests. Do not continue if verification fails or produces an empty
environment file.

## Preflight and start

Load the remaining production variables from the host secret store, then run
both the host and containerized configuration gates before changing services:

```sh
python ops/production_preflight.py
docker compose --file compose.production.yml --profile ops run --rm production-preflight
docker compose --file compose.production.yml pull backend frontend
docker compose --file compose.production.yml up --detach --no-build --wait \
  frontend prometheus backup recovery-watchdog
python ops/production_preflight.py \
  --smoke-url "$PUBLIC_APP_URL" \
  --expected-public-url "$PUBLIC_APP_URL"
```

The compose preflight mounts the same verified manifest read-only and rejects
an image pair that does not belong to it. A rollout is complete only after the
public smoke gate passes and backup/recovery health is visible through
`/api/ready` and monitoring.

## Rollback

Select the previous stable tag, download its three assets into a new empty
directory, and repeat the full verification and preflight sequence. Never
retag an image or combine backend and frontend references from different
manifests. Persistent database, backup, recovery, and Prometheus volumes are
not removed by this procedure.
