"""Tests for the API's health/readiness endpoints."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from apps.api.main import app
from packages.helios_core.config import get_settings


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


def test_healthz_ok(client: TestClient) -> None:
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readyz_unavailable_when_db_unreachable(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    class _BrokenEngine:
        def connect(self) -> None:
            raise RuntimeError("simulated connection failure")

    monkeypatch.setattr("apps.api.main.get_engine", lambda: _BrokenEngine())

    response = client.get("/readyz")
    assert response.status_code == 503
    assert response.json() == {"status": "unavailable"}


def test_readyz_ok_when_db_reachable(client: TestClient) -> None:
    try:
        with create_engine(get_settings().database_url).connect():
            pass
    except Exception as exc:  # pragma: no cover - environment dependent
        pytest.skip(f"database unreachable: {exc}")

    response = client.get("/readyz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
