"""Container build-context and release-gate regression tests."""

import re
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
CHECKOUT_ACTION = "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1"
SETUP_PYTHON_ACTION = "actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97"
SETUP_NODE_ACTION = "actions/setup-node@820762786026740c76f36085b0efc47a31fe5020"
SETUP_QEMU_ACTION = "docker/setup-qemu-action@ce360397dd3f832beb865e1373c09c0e9f86d70a"
SETUP_BUILDX_ACTION = "docker/setup-buildx-action@bb05f3f5519dd87d3ba754cc423b652a5edd6d2c"
ATTEST_ACTION = "actions/attest@508db95dd578ae2727ebd6217d5ba78e4fbda05d"
LOGIN_ACTION = "docker/login-action@dbcb813823bdd20940b903addbd779551569679f"
METADATA_ACTION = "docker/metadata-action@dc802804100637a589fabce1cb79ff13a1411302"
BUILD_PUSH_ACTION = "docker/build-push-action@53b7df96c91f9c12dcc8a07bcb9ccacbed38856a"
PINNED_ACTION = re.compile(r"^[^@\s]+/[^@\s]+@[0-9a-f]{40}$")
PYTHON_IMAGE = "python:3.10-slim@sha256:c1e4e6c01eb489c422288b2de34b0761ca316f7a2d98e2c33f47659a73ed108a"
NODE_IMAGE = "node:22-alpine@sha256:c610fcdfb1d5b4740dd70c284ed3cb16bb857e0f7166196e36a5501df7a3aa32"
NGINX_IMAGE = "nginx:1.27-alpine@sha256:65645c7bb6a0661892a8b03b89d0743208a18dd2f3f17a54ef4b76fb8e2f2a10"
PROMETHEUS_IMAGE = "prom/prometheus:v2.54.1@sha256:f6639335d34a77d9d9db382b92eeb7fc00934be8eae81dbc03b31cfe90411a94"


def test_docker_context_excludes_local_state_and_credentials():
    patterns = {
        line.strip()
        for line in (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
        if line.strip()
    }
    assert {
        "backend/.env",
        "backend/.env.*",
        "backend/.venv/",
        "backend/*.db",
        "backend/*.sqlite*",
        "frontend/.env",
        "frontend/.env.*",
        "frontend/dist/",
        "frontend/node_modules/",
        "**/*.key",
        "**/*.p12",
        "**/*.pem",
    } <= patterns
    assert "!backend/**" in patterns
    assert "!frontend/**" in patterns
    assert "!ops/**" in patterns


def test_dockerfiles_copy_only_required_application_trees():
    backend = (ROOT / "backend/Dockerfile").read_text(encoding="utf-8")
    frontend = (ROOT / "frontend/Dockerfile").read_text(encoding="utf-8")
    assert "COPY . " not in backend
    assert "COPY . " not in frontend
    assert "COPY backend/ /app/backend/" in backend
    assert "COPY ops/ /app/ops/" in backend
    assert "RUN mkdir -p /data /backups /recovery" in backend
    assert "chown -R tontracker:tontracker /app /data /backups /recovery" in backend
    assert "COPY frontend/ ./" in frontend
    assert f"FROM {PYTHON_IMAGE} AS runtime" in backend
    assert f"FROM --platform=$BUILDPLATFORM {NODE_IMAGE} AS build" in frontend
    assert f"FROM {NGINX_IMAGE} AS runtime" in frontend
    assert (
        "COPY backend/requirements.runtime.txt backend/requirements.runtime.lock ./"
        in backend
    )
    assert (
        "pip install --no-cache-dir --require-hashes -r requirements.runtime.lock"
        in backend
    )


def test_backend_dependency_lock_is_complete_and_used_by_ci():
    lock = (ROOT / "backend/requirements.lock").read_text(encoding="utf-8")
    runtime_lock = (ROOT / "backend/requirements.runtime.lock").read_text(
        encoding="utf-8"
    )
    requirement_lines = [
        line
        for line in lock.splitlines()
        if line and not line.startswith((" ", "#"))
    ]
    runtime_requirement_lines = [
        line
        for line in runtime_lock.splitlines()
        if line and not line.startswith((" ", "#"))
    ]
    assert len(requirement_lines) >= 40
    for lines in (requirement_lines, runtime_requirement_lines):
        assert all(
            line.endswith(" " + chr(92))
            and re.fullmatch(r"[a-z0-9][a-z0-9._-]*==\S+", line[:-2])
            for line in lines
        )
    assert lock.count("--hash=sha256:") >= len(requirement_lines)
    assert runtime_lock.count("--hash=sha256:") >= len(runtime_requirement_lines)
    for requirement in (
        "fastapi==0.141.1",
        "pydantic==2.13.4",
        "sqlalchemy==2.0.51",
        "greenlet==3.5.4",
        "pytoniq-core==0.1.46",
        "pytoniq==0.1.43",
    ):
        assert any(line.startswith(f"{requirement} ") for line in requirement_lines)
        assert any(
            line.startswith(f"{requirement} ") for line in runtime_requirement_lines
        )
    runtime_packages = {line.split("==", 1)[0] for line in runtime_requirement_lines}
    assert {
        "pytest",
        "httpx",
        "httpcore",
        "pluggy",
        "iniconfig",
        "pygments",
    }.isdisjoint(runtime_packages)
    assert len(runtime_requirement_lines) < len(requirement_lines)

    workflow = yaml.safe_load(
        (ROOT / ".github/workflows/release-gate.yml").read_text(encoding="utf-8")
    )
    backend = workflow["jobs"]["backend"]
    commands = "\n".join(str(step.get("run", "")) for step in backend["steps"])
    assert "pip install --require-hashes -r backend/requirements.lock" in commands
    assert "pip install --upgrade pip" not in commands
    setup = next(step for step in backend["steps"] if step.get("uses") == SETUP_PYTHON_ACTION)
    assert setup["with"]["cache-dependency-path"] == (
        "backend/requirements.txt\nbackend/requirements.lock\n"
    )


def test_release_gate_covers_tests_builds_preflight_and_compose():
    workflow = yaml.safe_load(
        (ROOT / ".github/workflows/release-gate.yml").read_text(encoding="utf-8")
    )
    jobs = workflow["jobs"]
    assert set(jobs) == {"backend", "frontend", "production"}
    actions = [
        step["uses"]
        for job in jobs.values()
        for step in job["steps"]
        if "uses" in step
    ]
    assert all(PINNED_ACTION.fullmatch(action) for action in actions)
    assert set(actions) == {
        CHECKOUT_ACTION,
        SETUP_NODE_ACTION,
        SETUP_PYTHON_ACTION,
    }
    checkout_steps = [
        step
        for job in jobs.values()
        for step in job["steps"]
        if step.get("uses") == CHECKOUT_ACTION
    ]
    assert len(checkout_steps) == len(jobs)
    assert all(step["with"]["persist-credentials"] is False for step in checkout_steps)
    commands = "\n".join(
        str(step.get("run", ""))
        for job in jobs.values()
        for step in job["steps"]
    )
    assert "python -m pytest -q" in commands
    assert "npm test" in commands
    assert "npm run build" in commands
    assert "npm audit --omit=dev" in commands
    assert "python ops/production_preflight.py" in commands
    assert "docker compose -f compose.production.yml config --quiet" in commands
    assert "backend/Dockerfile" in commands
    assert "frontend/Dockerfile" in commands
    assert "--entrypoint /bin/promtool" in commands
    assert "check config /etc/prometheus/prometheus.yml" in commands
    assert "up --detach --no-build --wait --wait-timeout 120 frontend" in commands
    assert "--smoke-url" in commands
    assert "--expected-public-url" in commands
    production_environment = jobs["production"]["env"]
    assert production_environment["BACKEND_IMAGE"] == (
        "ghcr.io/gr1gorii/ton-tracker-backend@sha256:" + "a" * 64
    )
    assert production_environment["FRONTEND_IMAGE"] == (
        "ghcr.io/gr1gorii/ton-tracker-frontend@sha256:" + "b" * 64
    )
    assert production_environment["APP_PULL_POLICY"] == "never"
    assert production_environment["DEPLOYMENT_MANIFEST_FILE"] == (
        "${{ github.workspace }}/.release-gate-deployment.json"
    )
    assert "python ops/create_release_manifest.py" in commands
    assert "--tag v0.63.0" in commands
    assert '--output "$DEPLOYMENT_MANIFEST_FILE"' in commands
    compose = yaml.safe_load(
        (ROOT / "compose.production.yml").read_text(encoding="utf-8")
    )
    preflight = compose["services"]["production-preflight"]
    assert preflight["environment"]["DEPLOYMENT_MANIFEST_FILE"] == (
        "/app/deployment-manifest.json"
    )
    assert preflight["volumes"] == [
        "${DEPLOYMENT_MANIFEST_FILE:?DEPLOYMENT_MANIFEST_FILE is required}:/app/deployment-manifest.json:ro"
    ]
    backup_now = compose["services"]["backup-now"]
    assert backup_now["profiles"] == ["deployment"]
    assert backup_now["command"] == ["python", "/app/ops/backup_sqlite.py"]
    assert backup_now["volumes"] == [
        "ton_tracker_data:/data:ro",
        "ton_tracker_backups:/backups",
    ]
    assert compose["services"]["backup"]["healthcheck"]["start_interval"] == "10s"
    assert compose["services"]["restore-drill"]["profiles"] == [
        "recovery",
        "deployment",
    ]
    assert compose["services"]["recovery-watchdog"]["healthcheck"][
        "start_interval"
    ] == "10s"
    assert "--profile deployment run --rm backup-now" in commands
    assert "--profile deployment run --rm restore-drill" in commands
    assert (
        "up --detach --no-build --wait --wait-timeout 180 \\\n"
        "  frontend prometheus backup recovery-watchdog"
    ) in commands
    assert "/etc/nginx/conf.d" in compose["services"]["frontend"]["tmpfs"]
    assert compose["services"]["prometheus"]["image"] == PROMETHEUS_IMAGE
    assert PROMETHEUS_IMAGE in commands


def test_tagged_release_publishes_bounded_ghcr_images_for_compose():
    workflow_path = ROOT / ".github/workflows/publish-images.yml"
    workflow = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))
    assert workflow["permissions"] == {"contents": "read"}
    assert set(workflow["jobs"]) == {"publish", "verify"}
    job = workflow["jobs"]["publish"]
    assert job["permissions"] == {
        "contents": "read",
        "packages": "write",
        "id-token": "write",
        "attestations": "write",
        "artifact-metadata": "write",
    }
    matrix = job["strategy"]["matrix"]["include"]
    assert matrix == [
        {
            "component": "backend",
            "image": "ghcr.io/gr1gorii/ton-tracker-backend",
            "dockerfile": "backend/Dockerfile",
        },
        {
            "component": "frontend",
            "image": "ghcr.io/gr1gorii/ton-tracker-frontend",
            "dockerfile": "frontend/Dockerfile",
        },
    ]
    actions = {step["uses"] for step in job["steps"] if "uses" in step}
    assert all(PINNED_ACTION.fullmatch(action) for action in actions)
    assert actions == {
        CHECKOUT_ACTION,
        SETUP_QEMU_ACTION,
        SETUP_BUILDX_ACTION,
        ATTEST_ACTION,
        LOGIN_ACTION,
        METADATA_ACTION,
        BUILD_PUSH_ACTION,
    }
    qemu = next(
        step for step in job["steps"] if step.get("uses") == SETUP_QEMU_ACTION
    )
    assert qemu["with"] == {"platforms": "arm64"}
    publisher = next(
        step for step in job["steps"] if step.get("uses") == BUILD_PUSH_ACTION
    )
    assert publisher["with"]["push"] is True
    assert publisher["with"]["platforms"] == "linux/amd64,linux/arm64"
    assert publisher["with"]["provenance"] == "mode=max"
    assert publisher["with"]["sbom"] is True
    assert publisher["id"] == "build"
    attester = next(
        step for step in job["steps"] if step.get("uses") == ATTEST_ACTION
    )
    assert attester["with"] == {
        "subject-name": "${{ matrix.image }}",
        "subject-digest": "${{ steps.build.outputs.digest }}",
        "subject-version": "${{ github.ref_name }}",
        "push-to-registry": True,
    }
    validator = next(
        step for step in job["steps"] if step.get("name") == "Validate stable release tag"
    )
    assert "grep -Eq" in validator["run"]
    assert validator["env"]["RELEASE_TAG"] == "${{ github.ref_name }}"
    metadata = next(
        step for step in job["steps"] if step.get("uses") == METADATA_ACTION
    )
    assert "type=raw,value=latest" not in metadata["with"]["tags"]

    compose = yaml.safe_load(
        (ROOT / "compose.production.yml").read_text(encoding="utf-8")
    )
    backend_image = "${BACKEND_IMAGE:?BACKEND_IMAGE is required}"
    for service_name in (
        "production-preflight",
        "backend",
        "backup",
        "backup-now",
        "restore-drill",
        "recovery-watchdog",
    ):
        assert compose["services"][service_name]["image"] == backend_image
        assert compose["services"][service_name]["pull_policy"] == (
            "${APP_PULL_POLICY:-always}"
        )
    assert compose["services"]["frontend"]["image"] == (
        "${FRONTEND_IMAGE:?FRONTEND_IMAGE is required}"
    )
    assert compose["services"]["frontend"]["pull_policy"] == (
        "${APP_PULL_POLICY:-always}"
    )
    assert ":latest" not in (ROOT / "compose.production.yml").read_text(encoding="utf-8")

    verifier = workflow["jobs"]["verify"]
    assert verifier["needs"] == "publish"
    assert verifier["permissions"] == {
        "contents": "write",
        "packages": "read",
        "id-token": "write",
        "attestations": "write",
        "artifact-metadata": "write",
    }
    verifier_actions = {
        step["uses"] for step in verifier["steps"] if "uses" in step
    }
    assert verifier_actions == {CHECKOUT_ACTION, LOGIN_ACTION, ATTEST_ACTION}
    assert all(PINNED_ACTION.fullmatch(action) for action in verifier_actions)
    manifest_attester = next(
        step
        for step in verifier["steps"]
        if step.get("id") == "attest-deployment-manifest"
    )
    assert manifest_attester["uses"] == ATTEST_ACTION
    assert manifest_attester["with"] == {
        "subject-path": "${{ env.DEPLOYMENT_MANIFEST }}"
    }
    verifier_commands = "\n".join(
        str(step.get("run", "")) for step in verifier["steps"]
    )
    assert "docker buildx imagetools inspect" in verifier_commands
    assert "--format '{{json .Manifest}}'" in verifier_commands
    assert "BACKEND_DIGEST=$digest" in verifier_commands
    assert "FRONTEND_DIGEST=$digest" in verifier_commands
    assert '("linux", "amd64")' in verifier_commands
    assert '("linux", "arm64")' in verifier_commands
    assert 'gh attestation verify "oci://${image}"' in verifier_commands
    assert '--signer-workflow "github.com/$GITHUB_REPOSITORY/.github/workflows/publish-images.yml"' in verifier_commands
    assert 'https://github.com/$GITHUB_REPOSITORY/.github/workflows/' not in (
        verifier_commands
    )
    assert '--source-ref "$GITHUB_REF"' in verifier_commands
    assert '--source-digest "$GITHUB_SHA"' in verifier_commands
    assert "--deny-self-hosted-runners" in verifier_commands
    assert "BACKEND_IMAGE=ghcr.io/gr1gorii/ton-tracker-backend:${release}" in (
        verifier_commands
    )
    assert "FRONTEND_IMAGE=ghcr.io/gr1gorii/ton-tracker-frontend:${release}" in (
        verifier_commands
    )
    assert "pull backend frontend" in verifier_commands
    assert "up --detach --no-build --wait --wait-timeout 120 frontend" in (
        verifier_commands
    )
    assert "--profile deployment run --rm backup-now" in verifier_commands
    assert "--profile deployment run --rm restore-drill" in verifier_commands
    assert (
        "up --detach --no-build --wait --wait-timeout 180 \\\n"
        "  frontend prometheus backup recovery-watchdog"
    ) in verifier_commands
    assert "--smoke-url" in verifier_commands
    assert "python ops/create_release_manifest.py" in verifier_commands
    assert "DEPLOYMENT_MANIFEST_FILE=$manifest" in verifier_commands
    assert "sha256sum" in verifier_commands
    assert 'gh release view "$RELEASE_TAG"' in verifier_commands
    assert 'gh release download "$RELEASE_TAG"' in verifier_commands
    assert 'gh release create "$RELEASE_TAG"' in verifier_commands
    assert "python ops/verify_release_bundle.py" in verifier_commands
    assert '--manifest "$DEPLOYMENT_MANIFEST"' in verifier_commands
    assert '--checksum "$DEPLOYMENT_CHECKSUM"' in verifier_commands
    assert '--attestation-bundle "$bundle"' in verifier_commands
    assert '--tag "$RELEASE_TAG"' in verifier_commands
    assert "--verify-tag" in verifier_commands
    assert "cmp \"$DEPLOYMENT_MANIFEST\"" in verifier_commands
    step_names = [step.get("name") for step in verifier["steps"]]
    assert step_names.index("Pull and smoke-test exact release images") < (
        step_names.index("Publish verified deployment bundle")
    )


def test_dependabot_tracks_every_release_dependency_surface():
    config = yaml.safe_load(
        (ROOT / ".github/dependabot.yml").read_text(encoding="utf-8")
    )
    assert config["version"] == 2
    updates = {
        (entry["package-ecosystem"], entry["directory"]): entry
        for entry in config["updates"]
    }
    assert set(updates) == {
        ("github-actions", "/"),
        ("pip", "/backend"),
        ("npm", "/frontend"),
        ("docker", "/backend"),
        ("docker", "/frontend"),
        ("docker-compose", "/"),
    }
    for entry in updates.values():
        assert entry["schedule"]["interval"] == "weekly"
        assert entry["schedule"]["timezone"] == "Europe/Rome"
        expected_limit = (
            3
            if entry["package-ecosystem"] in {"docker", "docker-compose"}
            else 5
        )
        assert entry["open-pull-requests-limit"] == expected_limit
