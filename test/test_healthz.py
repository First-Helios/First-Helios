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
    assert response.json() == {"status": "unavailable"}


def test_readyz_ok_when_db_reachable(client: TestClient, database_engine: Engine) -> None:
    response = client.get("/readyz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
