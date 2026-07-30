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
