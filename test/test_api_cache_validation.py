"""Exercise validators through HTTP, including a publication changing underneath a client."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import APIRouter, FastAPI, HTTPException
from fastapi.testclient import TestClient

from apps.api.cache_validation import ValidatedRoute
from apps.api.db import get_session
from apps.api.main import app as production_app


@pytest.fixture
def published() -> dict[str, Any]:
    return {
        "as_of": "2026-10-27T03:38:50Z",
        "menus": [
            {
                "source_url": "https://example.org/lunch",
                "prices": [
                    {
                        "id": "opaque-one",
                        "amount_minor": 1200,
                        "channel": "dine_in",
                        "service_period": "lunch",
                        "observed_at": "2026-10-02T00:00:00Z",
                        "age_seconds": 10,
                    }
                ],
            }
        ],
    }


@pytest.fixture
def client(published: dict[str, Any]) -> TestClient:
    app = FastAPI()
    router = APIRouter(route_class=ValidatedRoute)

    @router.get("/v1/venues/18/menu")
    @router.get("/v1/items/opaque-one/price-history")
    def response() -> dict[str, Any]:
        return published

    @router.get("/v1/missing")
    def missing() -> None:
        raise HTTPException(404)

    app.include_router(router)
    return TestClient(app)


def test_conditional_read_is_bodyless_and_preserves_age_clock(
    client: TestClient, published: dict[str, Any]
) -> None:
    first = client.get("/v1/venues/18/menu")
    assert first.status_code == 200
    tag = first.headers["etag"]
    assert tag.startswith('W/"')
    assert first.headers["cache-control"] == "public, no-cache"
    published["menus"][0]["prices"][0]["age_seconds"] = 9999
    validated = client.get("/v1/venues/18/menu", headers={"If-None-Match": tag})
    assert validated.status_code == 304
    assert validated.content == b""
    assert "content-length" not in validated.headers
    assert "content-type" not in validated.headers
    assert validated.headers["etag"] == tag
    assert validated.headers["cache-control"] == "public, no-cache"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("amount_minor", 900),
        ("id", "different-node"),
        ("channel", "takeaway"),
        ("service_period", "dinner"),
        ("observed_at", "2026-10-03T00:00:00Z"),
    ],
)
def test_corrections_and_context_change_validator(
    client: TestClient, published: dict[str, Any], field: str, value: object
) -> None:
    tag = client.get("/v1/venues/18/menu").headers["etag"]
    published["menus"][0]["prices"][0][field] = value
    response = client.get("/v1/venues/18/menu", headers={"If-None-Match": tag})
    assert response.status_code == 200
    assert response.headers["etag"] != tag


def test_withdrawal_last_row_and_restore_never_hide_behind_refresh_minimum(
    client: TestClient, published: dict[str, Any]
) -> None:
    first = client.get("/v1/venues/18/menu")
    tag = first.headers["etag"]
    old_menus = published["menus"]
    published["menus"] = []
    # The minimum refresh time is deliberately unchanged: it is not a revision.
    empty = client.get("/v1/venues/18/menu", headers={"If-None-Match": tag})
    assert empty.status_code == 200
    assert empty.json()["menus"] == []
    published["menus"] = old_menus
    restored = client.get("/v1/venues/18/menu", headers={"If-None-Match": empty.headers["etag"]})
    assert restored.status_code == 200
    assert restored.headers["etag"] == tag


def test_source_correction_changes_validator(client: TestClient, published: dict[str, Any]) -> None:
    tag = client.get("/v1/venues/18/menu").headers["etag"]
    published["menus"][0]["source_url"] = "https://example.org/dinner"
    response = client.get("/v1/venues/18/menu", headers={"If-None-Match": tag})
    assert response.status_code == 200


def test_history_request_clock_is_ignored_but_menu_publication_clock_is_not(
    client: TestClient, published: dict[str, Any]
) -> None:
    history_tag = client.get("/v1/items/opaque-one/price-history").headers["etag"]
    menu_tag = client.get("/v1/venues/18/menu").headers["etag"]
    published["as_of"] = "2026-10-28T00:00:00Z"
    assert (
        client.get(
            "/v1/items/opaque-one/price-history", headers={"If-None-Match": history_tag}
        ).status_code
        == 304
    )
    assert client.get("/v1/venues/18/menu", headers={"If-None-Match": menu_tag}).status_code == 200


@pytest.mark.parametrize("prefix", ["", "W/"])
def test_conditional_lists_weak_comparison_and_quoted_commas(
    client: TestClient, prefix: str
) -> None:
    tag = client.get("/v1/venues/18/menu").headers["etag"].removeprefix("W/")
    response = client.get(
        "/v1/venues/18/menu", headers={"If-None-Match": f'"different,tag", {prefix}{tag}'}
    )
    assert response.status_code == 304


def test_wildcard_does_not_turn_missing_resource_into_304(client: TestClient) -> None:
    assert client.get("/v1/venues/18/menu", headers={"If-None-Match": "*"}).status_code == 304
    assert client.get("/v1/missing", headers={"If-None-Match": "*"}).status_code == 404


def test_query_order_is_canonical_but_all_parameters_shape_key(client: TestClient) -> None:
    tag = client.get("/v1/venues/18/menu?currency=USD&cursor=one").headers["etag"]
    assert (
        client.get(
            "/v1/venues/18/menu?cursor=one&currency=USD", headers={"If-None-Match": tag}
        ).status_code
        == 304
    )
    assert (
        client.get(
            "/v1/venues/18/menu?currency=USD&cursor=two", headers={"If-None-Match": tag}
        ).status_code
        == 200
    )


def test_production_errors_are_not_cached_and_success_headers_are_cors_visible() -> None:
    production_app.dependency_overrides[get_session] = lambda: None
    try:
        with TestClient(production_app) as client:
            response = client.get(
                "/v1/venues/not-an-id", headers={"Origin": "http://localhost:5173"}
            )
    finally:
        production_app.dependency_overrides.clear()
    assert response.status_code == 422
    assert response.headers["cache-control"] == "no-store"
    assert "etag" not in response.headers
    assert response.headers["x-request-id"]
    assert "etag" in response.headers["access-control-expose-headers"].lower()
