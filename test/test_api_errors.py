"""DB-free tests for the API's error envelope, headers, and request ids.

These complement test_api_venues.py's DB-backed tests. Per R49, every error
test there needs a live database (the ``client`` fixture takes ``session``)
even for paths that never touch one -- a bad path/query value, a routing
failure, or an unhandled exception all fail before or without a query. Here,
``get_session`` is overridden with a stand-in that must never actually be
queried, so these run under plain ``make test`` with no PostgreSQL at all.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient

from apps.api.db import get_session
from apps.api.main import app
from apps.api.pagination import BIGINT_MAX, encode_cursor

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy.orm import Session


class _UnreachableSession:
    """A ``get_session()`` stand-in for tests that must fail before querying."""

    def execute(self, *args: object, **kwargs: object) -> None:
        raise AssertionError("test reached the database unexpectedly")


@pytest.fixture
def no_db_client() -> Iterator[TestClient]:
    def _stub_session() -> Iterator[Session]:
        yield _UnreachableSession()  # type: ignore[misc]

    app.dependency_overrides[get_session] = _stub_session
    try:
        with TestClient(app, raise_server_exceptions=False) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()


def test_method_not_allowed_reports_code_and_allow_header() -> None:
    # Routing rejects the method before any dependency runs, so this needs no
    # override either -- it never touches the database (R43).
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post("/v1/venues")

    assert response.status_code == 405
    body = response.json()
    assert body["code"] == "method_not_allowed"
    assert set(body) == {"detail", "code", "trace_id"}
    assert response.headers["allow"] == "GET"


def test_huge_venue_id_is_422_not_500(no_db_client: TestClient) -> None:
    response = no_db_client.get(f"/v1/venues/{BIGINT_MAX + 1}")

    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"


def test_huge_cursor_is_400_not_500(no_db_client: TestClient) -> None:
    response = no_db_client.get("/v1/venues", params={"cursor": encode_cursor(BIGINT_MAX + 1)})

    assert response.status_code == 400
    assert response.json()["code"] == "invalid_cursor"


def test_limit_over_cap_is_422_without_a_database(no_db_client: TestClient) -> None:
    response = no_db_client.get("/v1/venues", params={"limit": 500})

    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"


def test_unexpected_error_carries_request_id_and_cors_headers() -> None:
    def _boom() -> Session:
        raise RuntimeError("boom")

    app.dependency_overrides[get_session] = _boom
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.get("/v1/venues", headers={"Origin": "http://localhost:5173"})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 500
    body = response.json()
    assert body["code"] == "internal_error"
    assert response.headers["x-request-id"]
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_unsafe_request_id_is_replaced_not_echoed(no_db_client: TestClient) -> None:
    response = no_db_client.get("/healthz", headers={"X-Request-ID": "a" * 300})

    assert response.headers["x-request-id"] != "a" * 300
    assert len(response.headers["x-request-id"]) <= 64


def test_request_id_with_control_characters_is_replaced(no_db_client: TestClient) -> None:
    response = no_db_client.get("/healthz", headers={"X-Request-ID": "abc\r\nSet-Cookie: evil"})

    assert "\r" not in response.headers["x-request-id"]
    assert "evil" not in response.headers["x-request-id"]


def test_safe_request_id_is_echoed_verbatim(no_db_client: TestClient) -> None:
    response = no_db_client.get("/healthz", headers={"X-Request-ID": "abc-123.def_456"})

    assert response.headers["x-request-id"] == "abc-123.def_456"
