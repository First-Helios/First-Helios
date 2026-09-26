"""Tests for the API's health/readiness endpoints."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient

from apps.api.main import app

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy.engine import Engine


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
    body = response.json()
    # The standard error envelope (R44), not the ad hoc {"status": ...} body:
    # a caller already knows how to parse every other error from this API.
    assert body["code"] == "service_unavailable"
    assert set(body) == {"detail", "code", "trace_id"}
    assert body["trace_id"]


def test_readyz_ok_when_db_reachable(client: TestClient, database_engine: Engine) -> None:
    response = client.get("/readyz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readyz_failure_is_logged(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    class _BrokenEngine:
        def connect(self) -> None:
            raise RuntimeError("simulated connection failure")

    monkeypatch.setattr("apps.api.main.get_engine", lambda: _BrokenEngine())

    with caplog.at_level("ERROR"):
        client.get("/readyz")

    assert any("readyz_failed" in record.getMessage() for record in caplog.records)
