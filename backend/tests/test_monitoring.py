"""Production readiness and Prometheus metric tests."""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

import database
from database import get_session
from main import app
from services.database_migrations import run_database_migrations
from services.monitoring import observe_http_request, render_prometheus_metrics


def test_prometheus_renderer_uses_bounded_route_labels():
    observe_http_request("GET", "/api/health", 200, 0.125)
    metrics = render_prometheus_metrics(version="0.2.1", database_ready=True)
    assert 'ton_tracker_build_info{version="0.2.1"} 1' in metrics
    assert "ton_tracker_database_ready 1" in metrics
    assert 'route="/api/health",status="200"' in metrics
    assert "ton_tracker_http_request_duration_seconds_sum" in metrics


def test_readiness_and_metrics_endpoints(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    run_database_migrations(engine)
    testing_session = sessionmaker(bind=engine)

    def override_session():
        session = testing_session()
        try:
            yield session
        finally:
            session.close()

    monkeypatch.setattr(database, "engine", engine)
    app.dependency_overrides[get_session] = override_session
    try:
        with TestClient(app) as client:
            ready = client.get("/api/ready")
            metrics = client.get("/metrics")
        assert ready.status_code == 200
        assert ready.json()["database"] == "ready"
        assert ready.headers["cache-control"] == "no-store"
        assert metrics.status_code == 200
        assert "ton_tracker_database_ready 1" in metrics.text
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
