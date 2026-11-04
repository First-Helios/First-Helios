"""Source selection, category projection and complete-scope API filtering (ADR-0028)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any
from uuid import uuid4

import pytest
from sqlalchemy import select, text

from packages.helios_core.gold.categories import refresh_venue_categories, venue_categories
from packages.helios_core.gold.models import VenueCategory
from packages.helios_core.gold.price_index import refresh_price_index
from packages.helios_core.identity import (
    admit_source_record,
    assign_source_record,
    record_subject_change,
    remap_source_record,
)
from packages.helios_core.identity.models import Establishment
from packages.helios_core.provenance.contracts import (
    BronzeObservation,
    persist_source_record_observation,
)
from test.provider_support import decision, migrate
from test.test_api_price_index_area import _at, _client, _menu, _rect, _region
from test.test_gold_price_index import _seed_located_scope

if TYPE_CHECKING:
    from collections.abc import Iterator

    from fastapi.testclient import TestClient
    from sqlalchemy.engine import Engine
    from sqlalchemy.orm import Session

AT = datetime(2026, 11, 1, tzinfo=UTC)


@pytest.fixture
def client(session: Session) -> Iterator[TestClient]:
    yield from _client(session)


def _observation(
    session: Session,
    tags: list[str],
    *,
    key: str | None = None,
    observed: datetime = AT,
    namespace: str = "overture",
    missing: bool = False,
) -> Any:
    token = uuid4().hex
    payload: dict[str, Any] = {"id": key or token}
    if not missing:
        payload |= {"primary_category": tags[0] if tags else None, "alternate_categories": tags[1:]}
    return persist_source_record_observation(
        session,
        BronzeObservation(
            source_namespace=namespace,
            source_kind="poi_snapshot",
            external_key=key or token,
            observed_at=observed,
            content_hash=f"sha256:{token}",
            source_payload=payload,
            evidence_locator="$.id",
            source_url=f"https://{token}.example.test/poi",
            capture_content_hash=f"sha256:{token}",
            bundle_path=f"fixture/{token}",
        ),
    )


def _attach(session: Session, venue: int, record: Any) -> None:
    admit_source_record(
        session,
        source_record_id=record.source_record_id,
        decision=decision(),
        evidence_ids=(record.evidence_id,),
    )
    assign_source_record(
        session,
        source_record_id=record.source_record_id,
        to_subject_id=venue,
        decision=decision(),
        evidence_ids=(record.evidence_id,),
    )


def _keys(session: Session, venue: int) -> set[tuple[str, str]]:
    return {(entry.group, entry.key) for entry in venue_categories(session, [venue]).get(venue, [])}


def test_latest_empty_and_backfilled_versions_remove_claims(session: Session) -> None:
    scope = _seed_located_scope(session, _at(_region(), "0.01", "0.01"))
    venue = scope.establishment.subject_id
    key = uuid4().hex
    first = _observation(
        session, ["mexican_restaurant", "taco_restaurant", "food_truck", "music_venue"], key=key
    )
    _attach(session, venue, first)
    refresh_venue_categories(session, at=AT, refreshed_at=AT)
    assert _keys(session, venue) == {
        ("cuisine", "mexican"),
        ("specialty", "tacos"),
        ("place_type", "restaurant"),
        ("place_type", "food_truck"),
    }
    row = session.scalar(
        select(VenueCategory).where(
            VenueCategory.venue_id == venue, VenueCategory.category_group == "cuisine"
        )
    )
    assert row is not None and row.source_record_version_id == first.source_record_version_id
    assert row.source_categories == ["mexican_restaurant"]
    _observation(session, [], key=key, observed=AT + timedelta(hours=1), missing=True)
    _observation(session, ["italian_restaurant"], key=key, observed=AT - timedelta(hours=1))
    refresh_venue_categories(session, at=AT + timedelta(hours=2), refreshed_at=AT)
    assert not _keys(session, venue)
    # A refresh at the earlier observation still deterministically selects its version.
    refresh_venue_categories(session, at=AT, refreshed_at=AT)
    assert ("cuisine", "mexican") in _keys(session, venue)


def test_source_tie_remap_and_currentness(session: Session) -> None:
    region = _region()
    first = _seed_located_scope(session, _at(region, "0.01", "0.01"))
    second = _seed_located_scope(session, _at(region, "0.02", "0.02"))
    venue = first.establishment.subject_id
    oldest = _observation(session, ["pizza_restaurant"])
    _attach(session, venue, oldest)
    newer_record = _observation(session, ["mexican_restaurant"])
    _attach(session, venue, newer_record)
    # Same observation timestamp prefers the oldest record, not insertion of a newer record.
    refresh_venue_categories(session, at=AT, refreshed_at=AT)
    assert ("specialty", "pizza") in _keys(session, venue)
    assert ("cuisine", "mexican") not in _keys(session, venue)
    remap_source_record(
        session,
        source_record_id=oldest.source_record_id,
        from_subject_id=venue,
        to_subject_id=second.establishment.subject_id,
        decision=decision(),
        evidence_ids=(oldest.evidence_id,),
    )
    refresh_venue_categories(session, at=AT, refreshed_at=AT)
    assert ("cuisine", "mexican") in _keys(session, venue)
    assert ("specialty", "pizza") in _keys(session, second.establishment.subject_id)
    closed = session.get(Establishment, second.establishment.subject_id)
    assert closed is not None
    closed.operating_status = "closed"
    session.flush()
    refresh_venue_categories(session, at=AT, refreshed_at=AT)
    assert not _keys(session, second.establishment.subject_id)
    record_subject_change(
        session,
        operation="retire",
        input_subject_ids=[first.organization.subject_id],
        output_subject_ids=[],
        decision=decision(),
        evidence_ids=[oldest.evidence_id],
    )
    refresh_venue_categories(session, at=AT, refreshed_at=AT)
    assert not _keys(session, venue)


def test_unresolved_wrong_namespace_and_unmapped_records_do_not_label(session: Session) -> None:
    scope = _seed_located_scope(session, _at(_region(), "0.01", "0.01"))
    venue = scope.establishment.subject_id
    _observation(session, ["mexican_restaurant"])
    other = _observation(session, ["mexican_restaurant"], namespace=f"other-{uuid4().hex}")
    _attach(session, venue, other)
    junk = _observation(session, ["restaurant_equipment_and_supply", "music_venue"])
    _attach(session, venue, junk)
    # An organization-scoped category is never copied to its locations.
    organization_record = _observation(session, ["italian_restaurant"])
    _attach(session, scope.organization.subject_id, organization_record)
    refresh_venue_categories(session, at=AT, refreshed_at=AT)
    assert not _keys(session, venue)


def _catalog(session: Session) -> tuple[str, list[int]]:
    corner = _region()
    ids = []
    for n, tags in enumerate(
        [
            ["mexican_restaurant", "taco_restaurant", "food_truck"],
            ["mexican_restaurant", "pizza_restaurant"],
            ["italian_restaurant", "pizza_restaurant", "food_truck"],
            [],
        ]
    ):
        scope = _seed_located_scope(session, _at(corner, f"0.0{n + 1}", "0.01"))
        venue = scope.establishment.subject_id
        record = _observation(session, tags)
        _attach(session, venue, record)
        _menu(
            session,
            (venue, "establishment"),
            record,
            [1000 + n * 100, 2000 + n * 100],
            names=["Taco", "Pizza"],
        )
        ids.append(venue)
    session.flush()
    refresh_venue_categories(session, at=AT, refreshed_at=AT)
    refresh_price_index(session, effective_instant=AT, refreshed_at=AT)
    return _rect(*corner, *_at(corner, "0.1", "0.1")), ids


def test_category_pages_or_and_facets_and_unknowns(client: TestClient, session: Session) -> None:
    boundary, ids = _catalog(session)
    params = [
        ("boundary", boundary),
        ("has_menu", "true"),
        ("cuisine", "mexican"),
        ("cuisine", "italian"),
        ("place_type", "food_truck"),
        ("limit", "1"),
    ]
    first = client.get("/v1/venues", params=params).json()
    assert [row["id"] for row in first["items"]] == [ids[0]]
    second = client.get("/v1/venues", params=params + [("cursor", first["next_cursor"])]).json()
    assert [row["id"] for row in second["items"]] == [ids[2]]
    assert second["next_cursor"] is None
    assert {row["key"] for row in first["items"][0]["categories"]} == {
        "mexican",
        "tacos",
        "restaurant",
        "food_truck",
    }
    detail = client.get(f"/v1/venues/{ids[3]}").json()
    assert detail["categories"] == []
    facets = client.get(
        "/v1/venues/category-facets",
        params={
            "boundary": boundary,
            "has_menu": True,
            "cuisine": "mexican",
            "place_type": "food_truck",
        },
    ).json()
    assert {x["key"]: x["venue_count"] for x in facets["groups"]["cuisine"]} == {
        "mexican": 1,
        "italian": 1,
    }
    assert {x["key"]: x["venue_count"] for x in facets["groups"]["specialty"]} == {"tacos": 1}
    assert {x["key"]: x["venue_count"] for x in facets["groups"]["place_type"]} == {
        "restaurant": 2,
        "food_truck": 1,
    }
    assert facets["as_of"] is not None


def test_items_filter_before_pagination_and_indexed_facets(
    client: TestClient, session: Session
) -> None:
    boundary, ids = _catalog(session)
    params = {"boundary": boundary, "cuisine": "mexican", "specialty": "tacos", "limit": 1}
    body = client.get("/v1/price-index/area/items", params=params).json()
    assert [row["venue_id"] for row in body["items"]] == [ids[0]]
    assert body["items"][0]["amount_minor"] == 1000
    next_page = client.get(
        "/v1/price-index/area/items", params={**params, "cursor": body["next_cursor"]}
    ).json()
    assert [row["amount_minor"] for row in next_page["items"]] == [2000]
    assert next_page["next_cursor"] is None
    params2 = {"boundary": boundary, "indexed_only": True, "q": "Pizza", "place_type": "food_truck"}
    matching = client.get("/v1/venues", params=params2).json()
    assert [row["id"] for row in matching["items"]] == [ids[0], ids[2]]
    facets = client.get("/v1/venues/category-facets", params=params2).json()
    assert sum(row["venue_count"] for row in facets["groups"]["cuisine"]) == 2
    missing = client.get("/v1/venues/category-facets", params={**params2, "q": "missing"}).json()
    assert missing == {"as_of": None, "groups": {"cuisine": [], "specialty": [], "place_type": []}}
    no_match = client.get("/v1/price-index/area/items", params={**params, "q": "missing"}).json()
    assert no_match["items"] == [] and no_match["next_cursor"] is None


@pytest.mark.parametrize(
    "path", ["/v1/venues", "/v1/venues/category-facets", "/v1/price-index/area/items"]
)
@pytest.mark.parametrize(
    "filters", [[("cuisine", "unknown")], [("specialty", "")], [("cuisine", "mexican")] * 21]
)
def test_invalid_category_filters_are_422(
    client: TestClient, path: str, filters: list[tuple[str, str]]
) -> None:
    response = client.get(path, params=[("boundary", "0,0;0,1;1,0"), *filters])
    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"


def test_category_filter_uses_index(session: Session) -> None:
    _catalog(session)
    session.execute(text("SET LOCAL enable_seqscan=off"))
    plan = session.execute(
        text(
            "EXPLAIN (FORMAT JSON) SELECT venue_id FROM gold.venue_category "
            "WHERE category_group='cuisine' AND category_key='mexican'"
        )
    ).scalar_one()
    assert "ix_gold_venue_category_filter" in str(plan)
    assert "Seq Scan" not in str(plan)


def test_category_migration_roundtrip(historical_database_engine: Engine) -> None:
    migrate("upgrade", "head")
    migrate("downgrade", "13081a087231")
    with historical_database_engine.connect() as conn:
        assert conn.scalar(text("SELECT to_regclass('gold.venue_category')")) is None
    migrate("upgrade", "head")
