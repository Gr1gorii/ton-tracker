"""Container build-context and release-gate regression tests."""

import re
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
CHECKOUT_ACTION = "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1"
SETUP_PYTHON_ACTION = "actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97"
SETUP_NODE_ACTION = "actions/setup-node@820762786026740c76f36085b0efc47a31fe5020"
SETUP_BUILDX_ACTION = "docker/setup-buildx-action@bb05f3f5519dd87d3ba754cc423b652a5edd6d2c"
LOGIN_ACTION = "docker/login-action@dbcb813823bdd20940b903addbd779551569679f"
METADATA_ACTION = "docker/metadata-action@dc802804100637a589fabce1cb79ff13a1411302"
BUILD_PUSH_ACTION = "docker/build-push-action@53b7df96c91f9c12dcc8a07bcb9ccacbed38856a"
PINNED_ACTION = re.compile(r"^[^@\s]+/[^@\s]+@[0-9a-f]{40}$")


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
    assert "COPY frontend/ ./" in frontend


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
        "ghcr.io/gr1gorii/ton-tracker-backend:0.49.0"
    )
    assert production_environment["FRONTEND_IMAGE"] == (
        "ghcr.io/gr1gorii/ton-tracker-frontend:0.49.0"
    )
    assert production_environment["APP_PULL_POLICY"] == "never"
    compose = yaml.safe_load(
        (ROOT / "compose.production.yml").read_text(encoding="utf-8")
    )
    assert "/etc/nginx/conf.d" in compose["services"]["frontend"]["tmpfs"]


def test_tagged_release_publishes_bounded_ghcr_images_for_compose():
    workflow_path = ROOT / ".github/workflows/publish-images.yml"
    workflow = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))
    assert workflow["permissions"] == {"contents": "read", "packages": "write"}
    assert set(workflow["jobs"]) == {"publish", "verify"}
    job = workflow["jobs"]["publish"]
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
        SETUP_BUILDX_ACTION,
        LOGIN_ACTION,
        METADATA_ACTION,
        BUILD_PUSH_ACTION,
    }
    publisher = next(
        step for step in job["steps"] if step.get("uses") == BUILD_PUSH_ACTION
    )
    assert publisher["with"]["push"] is True
    assert publisher["with"]["platforms"] == "linux/amd64"
    assert publisher["with"]["provenance"] == "mode=max"
    assert publisher["with"]["sbom"] is True
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
    assert verifier["permissions"] == {"contents": "read", "packages": "read"}
    verifier_actions = {
        step["uses"] for step in verifier["steps"] if "uses" in step
    }
    assert verifier_actions == {CHECKOUT_ACTION, LOGIN_ACTION}
    assert all(PINNED_ACTION.fullmatch(action) for action in verifier_actions)
    verifier_commands = "\n".join(
        str(step.get("run", "")) for step in verifier["steps"]
    )
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
    assert "--smoke-url" in verifier_commands


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
    }
    for entry in updates.values():
        assert entry["schedule"]["interval"] == "weekly"
        assert entry["schedule"]["timezone"] == "Europe/Rome"
        assert entry["open-pull-requests-limit"] == 5
