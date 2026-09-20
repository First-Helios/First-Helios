"""Database-backed tests for the venue read endpoints (ADR-0008).

The FastAPI ``get_session`` dependency is overridden to share the rolled-back
test transaction, so seeded rows are visible over HTTP without committing.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient

from apps.api.db import get_session
from apps.api.main import app
from apps.api.pagination import encode_cursor
from apps.api.seed import seed_sample_venues

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy.orm import Session


@pytest.fixture
def client(session: Session) -> Iterator[TestClient]:
    def _use_test_session() -> Iterator[Session]:
        yield session

    app.dependency_overrides[get_session] = _use_test_session
    try:
        with TestClient(app, raise_server_exceptions=False) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()


def test_empty_page_is_200_not_404(client: TestClient) -> None:
    # A page past the end is an empty collection: 200 with [], never 404.
    # Ordering-independent: uses a cursor beyond any real id rather than an
    # assumption that the whole table is empty.
    beyond = encode_cursor(9_223_372_036_854_775_807)
    response = client.get("/v1/venues", params={"cursor": beyond})
    assert response.status_code == 200
    assert response.json() == {"items": [], "next_cursor": None}


def test_list_returns_seeded_venues(client: TestClient, session: Session) -> None:
    ids = seed_sample_venues(session)
    session.flush()

    # Seeded ids are the newest (highest) establishments, so a page starting
    # just below the first one returns exactly them, regardless of any rows
    # other tests may have committed earlier.
    start = encode_cursor(min(ids) - 1)
    body = client.get("/v1/venues", params={"cursor": start, "limit": len(ids) + 1}).json()
    returned = [item["id"] for item in body["items"] if item["id"] in set(ids)]
    assert returned == sorted(ids)

    first = next(item for item in body["items"] if item["id"] in set(ids))
    assert set(first) == {
        "id",
        "name",
        "organization_kind",
        "address",
        "latitude",
        "longitude",
        "operating_status",
        "valid_from",
        "valid_to",
    }


def test_cursor_pagination_walks_all_pages_without_overlap(
    client: TestClient, session: Session
) -> None:
    ids = seed_sample_venues(session)
    session.flush()

    seen: list[int] = []
    cursor: str | None = encode_cursor(min(ids) - 1)
    pages = 0
    while cursor is not None:
        body = client.get("/v1/venues", params={"limit": 2, "cursor": cursor}).json()
        seen.extend(item["id"] for item in body["items"] if item["id"] in set(ids))
        pages += 1
        cursor = body["next_cursor"]
        assert pages < 100  # guard against a non-terminating cursor

    assert seen == sorted(ids)
    assert len(seen) == len(set(seen))  # no page overlap


def test_get_single_venue(client: TestClient, session: Session) -> None:
    ids = seed_sample_venues(session)
    session.flush()

    response = client.get(f"/v1/venues/{ids[0]}")
    assert response.status_code == 200
    assert response.json()["id"] == ids[0]


def test_missing_venue_is_404_with_error_contract(client: TestClient) -> None:
    response = client.get("/v1/venues/999999999")
    assert response.status_code == 404
    body = response.json()
    assert body["code"] == "not_found"
    assert set(body) == {"detail", "code", "trace_id"}
    assert body["trace_id"]


def test_invalid_cursor_is_400_with_error_contract(client: TestClient) -> None:
    response = client.get("/v1/venues", params={"cursor": "not-a-valid-cursor!!"})
    assert response.status_code == 400
    body = response.json()
    assert body["code"] == "invalid_cursor"


def test_limit_over_cap_is_rejected(client: TestClient) -> None:
    response = client.get("/v1/venues", params={"limit": 500})
    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"


def test_unknown_route_uses_error_contract(client: TestClient) -> None:
    response = client.get("/v1/does-not-exist")
    assert response.status_code == 404
    body = response.json()
    assert body["code"] == "not_found"
    assert set(body) == {"detail", "code", "trace_id"}


def test_unexpected_error_uses_error_contract(session: Session) -> None:
    def _boom() -> Session:
        raise RuntimeError("boom")

    app.dependency_overrides[get_session] = _boom
    try:
        with TestClient(app, raise_server_exceptions=False) as test_client:
            response = test_client.get("/v1/venues")
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 500
    body = response.json()
    assert body["code"] == "internal_error"
    assert body["trace_id"]
