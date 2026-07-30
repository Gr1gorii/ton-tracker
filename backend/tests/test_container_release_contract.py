"""Container build-context and release-gate regression tests."""

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]


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
    compose = yaml.safe_load(
        (ROOT / "compose.production.yml").read_text(encoding="utf-8")
    )
    assert "/etc/nginx/conf.d" in compose["services"]["frontend"]["tmpfs"]


def test_tagged_release_publishes_bounded_ghcr_images_for_compose():
    workflow_path = ROOT / ".github/workflows/publish-images.yml"
    workflow = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))
    assert workflow["permissions"] == {"contents": "read", "packages": "write"}
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
    actions = {step.get("uses") for step in job["steps"]}
    assert "docker/setup-buildx-action@v3" in actions
    assert "docker/login-action@v3" in actions
    assert "docker/metadata-action@v5" in actions
    assert "docker/build-push-action@v6" in actions
    publisher = next(
        step for step in job["steps"] if step.get("uses") == "docker/build-push-action@v6"
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
        step for step in job["steps"] if step.get("uses") == "docker/metadata-action@v5"
    )
    assert "type=raw,value=latest" not in metadata["with"]["tags"]

    compose = yaml.safe_load(
        (ROOT / "compose.production.yml").read_text(encoding="utf-8")
    )
    backend_image = "${BACKEND_IMAGE:-ghcr.io/gr1gorii/ton-tracker-backend:latest}"
    for service_name in (
        "production-preflight",
        "backend",
        "backup",
        "restore-drill",
        "recovery-watchdog",
    ):
        assert compose["services"][service_name]["image"] == backend_image
    assert compose["services"]["frontend"]["image"] == (
        "${FRONTEND_IMAGE:-ghcr.io/gr1gorii/ton-tracker-frontend:latest}"
    )
