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
ALERTMANAGER_IMAGE = "prom/alertmanager:v0.33.1@sha256:9e082985f56f4c8c9f724e18f2288c6708f472e56a5286b8863d080434ea065d"


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
    nginx = (ROOT / "frontend/nginx.conf").read_text(encoding="utf-8")
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
    assert '"--no-proxy-headers"' in backend
    assert "--forwarded-allow-ips" not in backend
    assert "X-Forwarded-For $remote_addr" in nginx
    assert "$proxy_add_x_forwarded_for" not in nginx


def test_gateway_and_container_bound_every_liteclient_child():
    from services.ton_liteclient_process import (
        MAX_PROCESS_DEADLINE_SECONDS,
        PROCESS_KILL_GRACE_SECONDS,
        PROCESS_TERMINATE_GRACE_SECONDS,
    )

    nginx = (ROOT / "frontend/nginx.conf").read_text(encoding="utf-8")
    timeout = re.search(r"proxy_read_timeout\s+([0-9]+)s;", nginx)
    assert timeout is not None
    gateway_seconds = int(timeout.group(1))
    assert gateway_seconds > (
        MAX_PROCESS_DEADLINE_SECONDS
        + PROCESS_TERMINATE_GRACE_SECONDS
        + PROCESS_KILL_GRACE_SECONDS
        + 5
    )

    backend = yaml.safe_load(
        (ROOT / "compose.production.yml").read_text(encoding="utf-8")
    )["services"]["backend"]
    assert backend["mem_limit"] == "${BACKEND_MEMORY_LIMIT:-2g}"
    assert backend["pids_limit"] == "${BACKEND_PIDS_LIMIT:-256}"


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
    production_commands = "\n".join(
        str(step.get("run", "")) for step in jobs["production"]["steps"]
    )
    assert (
        "python -m pip install --require-hashes "
        "-r backend/requirements.runtime.lock"
    ) in production_commands
    assert "docker compose -f compose.production.yml config --quiet" in commands
    assert "backend/Dockerfile" in commands
    assert "frontend/Dockerfile" in commands
    assert "--entrypoint /bin/promtool" in commands
    assert "check config /etc/prometheus/prometheus.yml" in commands
    assert "--profile ops run --rm alertmanager-config-check" in commands
    assert "--profile deployment run --rm monitoring-smoke" in commands
    assert "--profile deployment run --rm notification-drill" in commands
    assert "--profile deployment run --rm recovery-point-now" in commands
    assert "rehearse_database_bootstrap.py --mode resume" in commands
    assert (
        "--profile test up --detach --no-build --wait "
        "notification-receiver-fixture"
    ) in commands
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
    assert "--tag v0.75.0" in commands
    assert '--output "$DEPLOYMENT_MANIFEST_FILE"' in commands
    assert "python ops/inspect_deployment_state.py" in commands
    assert "DEPLOYMENT_STATE_DIRECTORY=$state" in commands
    assert "DEPLOYMENT_STATE_UID=$(id -u)" in commands
    assert "DEPLOYMENT_STATE_GID=$(id -g)" in commands
    assert "ALERTMANAGER_CONFIG_FILE=$alertmanager_config" in commands
    assert "ALERTMANAGER_DATA_DIRECTORY=$alertmanager_data" in commands
    assert "DISASTER_RECOVERY_DIRECTORY=$recovery_points" in commands
    compose = yaml.safe_load(
        (ROOT / "compose.production.yml").read_text(encoding="utf-8")
    )
    preflight = compose["services"]["production-preflight"]
    assert compose["services"]["backend"]["environment"][
        "WALLET_CASE_JOB_RUNNER"
    ] == "disabled"
    assert compose["services"]["backend"]["environment"][
        "WALLET_CASE_EVIDENCE_RUNNER"
    ] == "disabled"
    assert compose["services"]["backend"]["environment"][
        "TON_LITECLIENT_TRUST_LEVEL"
    ] == "0"
    assert preflight["environment"]["DEPLOYMENT_MANIFEST_FILE"] == (
        "/app/deployment-manifest.json"
    )
    assert preflight["environment"]["DEPLOYMENT_STATE_DIRECTORY"] == (
        "${DEPLOYMENT_STATE_DIRECTORY:?DEPLOYMENT_STATE_DIRECTORY is required}"
    )
    assert preflight["environment"]["DEPLOYMENT_STATE_UID"] == (
        "${DEPLOYMENT_STATE_UID:?DEPLOYMENT_STATE_UID is required}"
    )
    assert preflight["environment"]["DEPLOYMENT_STATE_GID"] == (
        "${DEPLOYMENT_STATE_GID:?DEPLOYMENT_STATE_GID is required}"
    )
    assert preflight["environment"]["ALERTMANAGER_CONFIG_FILE"] == (
        "/run/alertmanager/alertmanager.yml"
    )
    assert preflight["environment"]["ALERTMANAGER_DATA_DIRECTORY"] == (
        "/alertmanager"
    )
    assert preflight["environment"]["DISASTER_RECOVERY_DIRECTORY"] == (
        "/recovery-points"
    )
    assert preflight["environment"]["RECOVERY_POINT_RETENTION"] == (
        "${RECOVERY_POINT_RETENTION:-14}"
    )
    assert preflight["environment"]["RECOVERY_POINT_INTERVAL_SECONDS"] == (
        "${RECOVERY_POINT_INTERVAL_SECONDS:-86400}"
    )
    assert preflight["environment"]["RECOVERY_POINT_RETRY_SECONDS"] == (
        "${RECOVERY_POINT_RETRY_SECONDS:-300}"
    )
    assert preflight["environment"]["RECOVERY_POINT_HEALTH_MAX_AGE_SECONDS"] == (
        "${RECOVERY_POINT_HEALTH_MAX_AGE_SECONDS:-172800}"
    )
    assert preflight["user"] == (
        "${DEPLOYMENT_STATE_UID:?DEPLOYMENT_STATE_UID is required}:"
        "${DEPLOYMENT_STATE_GID:?DEPLOYMENT_STATE_GID is required}"
    )
    assert preflight["volumes"] == [
        "${DEPLOYMENT_MANIFEST_FILE:?DEPLOYMENT_MANIFEST_FILE is required}:/app/deployment-manifest.json:ro",
        {
            "type": "bind",
            "source": (
                "${ALERTMANAGER_CONFIG_FILE:?ALERTMANAGER_CONFIG_FILE is required}"
            ),
            "target": "/run/alertmanager/alertmanager.yml",
            "read_only": True,
        },
        {
            "type": "bind",
            "source": (
                "${ALERTMANAGER_DATA_DIRECTORY:?ALERTMANAGER_DATA_DIRECTORY is required}"
            ),
            "target": "/alertmanager",
            "read_only": True,
        },
        {
            "type": "bind",
            "source": (
                "${DISASTER_RECOVERY_DIRECTORY:?DISASTER_RECOVERY_DIRECTORY is required}"
            ),
            "target": "/recovery-points",
            "read_only": True,
        },
    ]
    backup_now = compose["services"]["backup-now"]
    assert backup_now["profiles"] == ["deployment"]
    assert backup_now["command"] == ["python", "/app/ops/backup_sqlite.py"]
    assert backup_now["volumes"] == [
        "ton_tracker_data:/data:ro",
        "ton_tracker_backups:/backups",
    ]
    database_bootstrap = compose["services"]["database-bootstrap"]
    assert database_bootstrap["profiles"] == ["deployment"]
    assert database_bootstrap["command"] == [
        "python",
        "/app/ops/rehearse_database_bootstrap.py",
        "--mode",
        "fresh",
    ]
    assert database_bootstrap["environment"] == {
        "BACKUP_RETENTION": "${BACKUP_RETENTION:-14}"
    }
    assert database_bootstrap["volumes"] == [
        "ton_tracker_data:/data:ro",
        "ton_tracker_backups:/backups",
    ]
    assert database_bootstrap["cap_drop"] == ["ALL"]
    assert database_bootstrap["read_only"] is True
    assert compose["services"]["backup"]["healthcheck"]["start_interval"] == "10s"
    assert compose["services"]["restore-drill"]["profiles"] == [
        "recovery",
        "deployment",
    ]
    recovery_point = compose["services"]["recovery-point-now"]
    assert recovery_point["profiles"] == ["deployment"]
    assert recovery_point["user"] == (
        "${DEPLOYMENT_STATE_UID:?DEPLOYMENT_STATE_UID is required}:"
        "${DEPLOYMENT_STATE_GID:?DEPLOYMENT_STATE_GID is required}"
    )
    assert recovery_point["command"] == [
        "python",
        "/app/ops/recovery_point.py",
        "create",
        "--heartbeat",
        "/backups/.backup-health.json",
        "--deployment-manifest",
        "/app/deployment-manifest.json",
        "--destination-directory",
        "/recovery-points",
        "--retention",
        "${RECOVERY_POINT_RETENTION:-14}",
    ]
    assert recovery_point["environment"] == {
        "RECOVERY_POINT_HEALTH_MAX_AGE_SECONDS": (
            "${RECOVERY_POINT_HEALTH_MAX_AGE_SECONDS:-172800}"
        )
    }
    assert recovery_point["volumes"] == [
        "ton_tracker_backups:/backups:ro",
        "${DEPLOYMENT_MANIFEST_FILE:?DEPLOYMENT_MANIFEST_FILE is required}:/app/deployment-manifest.json:ro",
        {
            "type": "bind",
            "source": (
                "${DISASTER_RECOVERY_DIRECTORY:?DISASTER_RECOVERY_DIRECTORY is required}"
            ),
            "target": "/recovery-points",
        },
    ]
    assert recovery_point["cap_drop"] == ["ALL"]
    assert recovery_point["read_only"] is True
    recovery_exporter = compose["services"]["recovery-point-exporter"]
    assert recovery_exporter["command"] == [
        "python",
        "/app/ops/recovery_point.py",
        "loop",
        "--heartbeat",
        "/backups/.backup-health.json",
        "--destination-directory",
        "/recovery-points",
        "--retention",
        "${RECOVERY_POINT_RETENTION:-14}",
    ]
    assert recovery_exporter["depends_on"] == {
        "backup": {"condition": "service_healthy"}
    }
    assert recovery_exporter["healthcheck"]["start_interval"] == "10s"
    assert recovery_exporter["healthcheck"]["timeout"] == "15m"
    assert recovery_exporter["cap_drop"] == ["ALL"]
    assert recovery_exporter["read_only"] is True
    migration_rehearsal = compose["services"]["migration-rehearsal"]
    assert migration_rehearsal["profiles"] == ["deployment"]
    assert migration_rehearsal["entrypoint"] == ["/bin/sh", "-ec"]
    rehearsal_command = migration_rehearsal["command"][0]
    assert "/app/ops/rehearse_database_migration.py" in rehearsal_command
    assert "/app/ops/restore_sqlite.py" in rehearsal_command
    assert "python -m services.database_migrations" in rehearsal_command
    assert "/app/ops/backup_sqlite.py" in rehearsal_command
    assert migration_rehearsal["environment"] == {
        "TON_CHECK_DB_URL": "sqlite:////tmp/rehearsal.sqlite3"
    }
    assert migration_rehearsal["volumes"] == [
        "ton_tracker_backups:/backups:ro"
    ]
    assert migration_rehearsal["cap_drop"] == ["ALL"]
    assert migration_rehearsal["read_only"] is True
    assert compose["services"]["recovery-watchdog"]["healthcheck"][
        "start_interval"
    ] == "10s"
    deployment_monitor = compose["services"]["deployment-monitor"]
    assert deployment_monitor["user"] == (
        "${DEPLOYMENT_STATE_UID:?DEPLOYMENT_STATE_UID is required}:"
        "${DEPLOYMENT_STATE_GID:?DEPLOYMENT_STATE_GID is required}"
    )
    assert deployment_monitor["volumes"] == [
        {
            "type": "bind",
            "source": (
                "${DEPLOYMENT_STATE_DIRECTORY:?DEPLOYMENT_STATE_DIRECTORY is required}"
            ),
            "target": "/deployment-state",
        }
    ]
    assert deployment_monitor["cap_drop"] == ["ALL"]
    assert deployment_monitor["read_only"] is True
    assert deployment_monitor["healthcheck"]["start_interval"] == "2s"
    assert compose["services"]["prometheus"]["depends_on"][
        "deployment-monitor"
    ]["condition"] == "service_healthy"
    assert compose["services"]["prometheus"]["depends_on"]["alertmanager"][
        "condition"
    ] == "service_healthy"
    assert "--profile deployment run --rm backup-now" in commands
    assert "--profile deployment run --rm restore-drill" in commands
    assert "--profile deployment run --rm migration-rehearsal" in commands
    assert "--profile deployment run --rm recovery-point-now" in commands
    assert "recovery-watchdog recovery-point-exporter" in commands
    assert "deployment-monitor alertmanager" in commands
    assert "/etc/nginx/conf.d" in compose["services"]["frontend"]["tmpfs"]
    assert compose["services"]["prometheus"]["image"] == PROMETHEUS_IMAGE
    assert PROMETHEUS_IMAGE in commands

    alertmanager = compose["services"]["alertmanager"]
    assert alertmanager["image"] == ALERTMANAGER_IMAGE
    assert alertmanager["user"] == (
        "${DEPLOYMENT_STATE_UID:?DEPLOYMENT_STATE_UID is required}:"
        "${DEPLOYMENT_STATE_GID:?DEPLOYMENT_STATE_GID is required}"
    )
    assert "ports" not in alertmanager
    assert alertmanager["expose"] == ["9093"]
    assert alertmanager["cap_drop"] == ["ALL"]
    assert alertmanager["read_only"] is True
    assert alertmanager["command"][-2:] == [
        "--cluster.listen-address=",
        "--enable-feature=receiver-name-in-metrics",
    ]
    assert alertmanager["volumes"] == [
        {
            "type": "bind",
            "source": (
                "${ALERTMANAGER_CONFIG_FILE:?ALERTMANAGER_CONFIG_FILE is required}"
            ),
            "target": "/etc/alertmanager/alertmanager.yml",
            "read_only": True,
        },
        {
            "type": "bind",
            "source": (
                "${ALERTMANAGER_DATA_DIRECTORY:?ALERTMANAGER_DATA_DIRECTORY is required}"
            ),
            "target": "/alertmanager",
        },
    ]
    config_check = compose["services"]["alertmanager-config-check"]
    assert config_check["image"] == ALERTMANAGER_IMAGE
    assert config_check["profiles"] == ["ops", "deployment"]
    assert config_check["entrypoint"] == ["/bin/amtool"]
    assert config_check["command"] == [
        "check-config",
        "/etc/alertmanager/alertmanager.yml",
    ]
    monitoring_smoke = compose["services"]["monitoring-smoke"]
    assert monitoring_smoke["profiles"] == ["deployment"]
    assert monitoring_smoke["command"] == [
        "python",
        "/app/ops/check_alert_delivery.py",
    ]
    assert monitoring_smoke["depends_on"] == {
        "prometheus": {"condition": "service_healthy"},
        "alertmanager": {"condition": "service_healthy"},
    }
    notification_drill = compose["services"]["notification-drill"]
    assert notification_drill["profiles"] == ["deployment"]
    assert notification_drill["command"] == [
        "python",
        "/app/ops/check_alert_notification.py",
    ]
    assert notification_drill["depends_on"] == {
        "alertmanager": {"condition": "service_healthy"}
    }
    fixture = compose["services"]["notification-receiver-fixture"]
    assert fixture["profiles"] == ["test"]
    assert fixture["expose"] == ["9199"]
    assert fixture["command"][-1] == "9199"
    assert fixture["read_only"] is True
    assert fixture["cap_drop"] == ["ALL"]


def test_deployment_state_monitor_is_scraped_and_alerted_fail_closed():
    prometheus = yaml.safe_load(
        (ROOT / "monitoring/prometheus.yml").read_text(encoding="utf-8")
    )
    scrape_jobs = {
        entry["job_name"]: entry for entry in prometheus["scrape_configs"]
    }
    assert scrape_jobs["ton-tracker-deployment"] == {
        "job_name": "ton-tracker-deployment",
        "metrics_path": "/metrics",
        "static_configs": [{"targets": ["deployment-monitor:9101"]}],
    }
    assert scrape_jobs["ton-tracker-alertmanager"] == {
        "job_name": "ton-tracker-alertmanager",
        "metrics_path": "/metrics",
        "static_configs": [{"targets": ["alertmanager:9093"]}],
    }
    assert prometheus["alerting"] == {
        "alertmanagers": [
            {
                "scheme": "http",
                "static_configs": [{"targets": ["alertmanager:9093"]}],
            }
        ]
    }

    alert_groups = yaml.safe_load(
        (ROOT / "monitoring/alerts.yml").read_text(encoding="utf-8")
    )["groups"]
    rules = {
        rule["alert"]: rule
        for group in alert_groups
        for rule in group["rules"]
    }
    assert rules["TonTrackerDeploymentMonitorDown"]["expr"] == (
        'up{job="ton-tracker-deployment"} == 0'
    )
    assert rules["TonTrackerDeploymentStateInvalid"]["expr"] == (
        "ton_tracker_deployment_audit_valid == 0 and "
        "ton_tracker_deployment_lock_busy == 0"
    )
    assert rules["TonTrackerDeploymentInterrupted"]["expr"] == (
        "ton_tracker_deployment_pending_attempt == 1"
    )
    assert rules["TonTrackerDeploymentReceiptUnbound"]["expr"] == (
        "ton_tracker_deployment_ledger_events > 0 and "
        "ton_tracker_deployment_receipt_bound == 0"
    )
    assert rules["TonTrackerDeploymentStateEmpty"]["for"] == "30m"
    assert rules["TonTrackerDeploymentLockStuck"]["for"] == "45m"
    assert rules["TonTrackerAlertmanagerDown"]["expr"] == (
        'up{job="ton-tracker-alertmanager"} == 0'
    )
    assert rules["TonTrackerAlertNotificationFailures"]["expr"] == (
        "sum(rate(alertmanager_notifications_failed_total[5m])) > 0"
    )
    assert rules["TonTrackerPrometheusAlertDeliveryFailures"]["expr"] == (
        "sum(rate(prometheus_notifications_errors_total[5m])) > 0"
    )
    assert all(
        rule["labels"]["severity"] in {"warning", "critical"}
        for name, rule in rules.items()
        if name.startswith("TonTrackerDeployment")
    )


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
        "migration-rehearsal",
        "recovery-point-now",
        "recovery-point-exporter",
        "recovery-watchdog",
        "deployment-monitor",
        "monitoring-smoke",
        "notification-drill",
        "notification-receiver-fixture",
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
    assert verifier_actions == {
        CHECKOUT_ACTION,
        SETUP_PYTHON_ACTION,
        LOGIN_ACTION,
        ATTEST_ACTION,
    }
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
    assert (
        "python -m pip install --require-hashes "
        "-r backend/requirements.runtime.lock"
    ) in verifier_commands
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
    assert "python ops/inspect_deployment_state.py" in verifier_commands
    assert "DEPLOYMENT_STATE_DIRECTORY=$state" in verifier_commands
    assert "DEPLOYMENT_STATE_UID=$(id -u)" in verifier_commands
    assert "DEPLOYMENT_STATE_GID=$(id -g)" in verifier_commands
    assert "ALERTMANAGER_CONFIG_FILE=$alertmanager_config" in verifier_commands
    assert "ALERTMANAGER_DATA_DIRECTORY=$alertmanager_data" in verifier_commands
    assert "DISASTER_RECOVERY_DIRECTORY=$recovery_points" in verifier_commands
    assert "pull backend frontend alertmanager" in verifier_commands
    assert "--profile ops run --rm alertmanager-config-check" in verifier_commands
    assert "--profile deployment run --rm monitoring-smoke" in verifier_commands
    assert "--profile deployment run --rm notification-drill" in verifier_commands
    assert (
        "--profile test up --detach --no-build --wait "
        "notification-receiver-fixture"
    ) in verifier_commands
    assert "up --detach --no-build --wait --wait-timeout 120 frontend" in (
        verifier_commands
    )
    assert "--profile deployment run --rm backup-now" in verifier_commands
    assert "--profile deployment run --rm restore-drill" in verifier_commands
    assert "--profile deployment run --rm migration-rehearsal" in verifier_commands
    assert "--profile deployment run --rm recovery-point-now" in verifier_commands
    assert "recovery-watchdog recovery-point-exporter" in verifier_commands
    assert "deployment-monitor alertmanager" in verifier_commands
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
