from __future__ import annotations

from datetime import datetime, timezone

from flask import Flask
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from collectors.meal_deals.menu_db_writer import upsert_menu_shape
from collectors.meal_deals.menu_persistence_schema import serialize_sidecar
from collectors.meal_deals.menu_sidecar import MenuSidecar, ingest_jsonld_payload
from collectors.meal_deals.price_index_routes import price_index_bp
import collectors.meal_deals.price_index_routes as price_index_routes
from core.database import (
    Base,
    BrandGroup,
    LocalEmployer,
    MenuItem,
    MenuModifier,
    MenuPage,
    MenuPricePoint,
    MenuSection,
)


LAPOSADA_MENU_PAYLOAD = {
    "@context": "https://schema.org",
    "@type": "Menu",
    "@id": "https://www.laposadasouth.com/menu/limited-lunch-specials/#menu",
    "name": "LIMITED LUNCH SPECIALS",
    "hasMenuSection": {
        "@type": "MenuSection",
        "name": "Family Packs",
        "hasMenuItem": [
            {
                "@type": "MenuItem",
                "name": "Fajita Platter",
                "description": "Chicken or Beef Fajitas with sides",
                "offers": {"@type": "Offer", "price": "95.99", "priceCurrency": "USD"},
            },
            {
                "@type": "MenuItem",
                "name": "Taco Platter",
                "description": "12 tacos with sides",
                "offers": {"@type": "Offer", "price": "54.99", "priceCurrency": "USD"},
            },
        ],
    },
}


def _build_shape(*, restaurant_id: str = "123"):
    sidecar = MenuSidecar()
    ingest_jsonld_payload(LAPOSADA_MENU_PAYLOAD, page_url="https://laposadasouth.com/menu", sidecar=sidecar)
    return serialize_sidecar(
        sidecar,
        restaurant_id=restaurant_id,
        source_url="https://laposadasouth.com/menu",
        source_bundle="laposada_bundle.json",
        observed_at=datetime(2026, 4, 20, 18, 0, 0, tzinfo=timezone.utc),
    )


def _setup_engine():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[
            BrandGroup.__table__,
            LocalEmployer.__table__,
            MenuPage.__table__,
            MenuSection.__table__,
            MenuItem.__table__,
            MenuPricePoint.__table__,
            MenuModifier.__table__,
        ],
    )
    Session = sessionmaker(bind=engine)
    session = Session()
    session.add(BrandGroup(id=1, fingerprint="la_posada", canonical_name="La Posada", location_count=1))
    session.add(
        LocalEmployer(
            id=123,
            raw_name="La Posada South",
            name="La Posada South",
            source="manual",
            fingerprint="la_posada_south",
            brand_group_id=1,
            location_count=1,
            industry="Mexican",
            address="1200 W Lynn St, Austin TX",
            lat=30.27,
            lng=-97.74,
            region="austin_tx",
            is_active=True,
        )
    )
    session.commit()
    session.close()
    return engine


def test_upsert_menu_shape_is_idempotent_and_updates_existing_rows():
    engine = _setup_engine()
    Session = sessionmaker(bind=engine)

    session = Session()
    shape = _build_shape()
    result = upsert_menu_shape(session, shape)
    session.commit()

    assert result.skipped is False
    assert result.tables["pages"]["inserted"] == 1
    assert result.tables["items"]["inserted"] == 2
    assert session.query(MenuPricePoint).count() == 2

    updated_shape = _build_shape()
    updated_shape["price_points"][0]["price"] = 96.99
    updated_shape["price_points"][0]["confidence"] = 0.91

    result2 = upsert_menu_shape(session, updated_shape)
    session.commit()

    assert result2.tables["pages"]["updated"] == 1
    assert result2.tables["price_points"]["updated"] == 2
    assert session.query(MenuPage).count() == 1

    price_point = session.query(MenuPricePoint).filter(MenuPricePoint.price == 96.99).one()
    assert round(price_point.confidence, 2) == 0.91
    session.close()


def test_upsert_menu_shape_filters_non_positive_price_points():
    engine = _setup_engine()
    Session = sessionmaker(bind=engine)

    session = Session()
    shape = _build_shape()
    shape["price_points"][0]["price"] = 0.0
    result = upsert_menu_shape(session, shape)
    session.commit()

    assert result.skipped is False
    assert result.filtered["price_points_non_positive"] == 1
    assert session.query(MenuPricePoint).count() == 1
    assert session.query(MenuPricePoint).filter(MenuPricePoint.price <= 0).count() == 0
    session.close()


def test_upsert_menu_shape_prunes_stale_price_points_for_replayed_scope():
    engine = _setup_engine()
    Session = sessionmaker(bind=engine)

    session = Session()
    shape = _build_shape()
    first_result = upsert_menu_shape(session, shape)
    session.commit()

    assert first_result.skipped is False
    assert session.query(MenuPricePoint).count() == 2

    updated_shape = _build_shape()
    updated_shape["price_points"][0]["id"] = "pp_repriced"
    updated_shape["price_points"][0]["price"] = 96.99
    updated_shape["price_points"][0]["evidence"] = "updated replay"

    second_result = upsert_menu_shape(session, updated_shape)
    session.commit()

    assert second_result.skipped is False
    assert session.query(MenuPricePoint).count() == 2
    assert session.query(MenuPricePoint).filter(MenuPricePoint.price == 95.99).count() == 0
    repriced = session.query(MenuPricePoint).filter(MenuPricePoint.id == "pp_repriced").one()
    assert repriced.price == 96.99
    assert repriced.evidence == "updated replay"
    session.close()


def test_price_index_endpoint_returns_filtered_menu_rows(monkeypatch):
    engine = _setup_engine()
    Session = sessionmaker(bind=engine)
    session = Session()
    session.add_all([])
    result = upsert_menu_shape(session, _build_shape())
    session.commit()
    assert result.skipped is False
    session.close()

    app = Flask(__name__)
    app.register_blueprint(price_index_bp)
    monkeypatch.setattr(price_index_routes, "_engine", engine)

    client = app.test_client()
    resp = client.get("/api/price-index", query_string={"region": "austin_tx", "limit": 5})
    assert resp.status_code == 200
    payload = resp.get_json()
    assert payload["total"] == 2
    assert len(payload["items"]) == 2
    first = payload["items"][0]
    assert first["restaurant_name"] == "La Posada South"
    assert first["section_name"] == "Family Packs"
    assert first["brand_fingerprint"] == "la_posada"
    assert first["source_url"] == "https://laposadasouth.com/menu"

    taco_resp = client.get(
        "/api/price-index",
        query_string={"region": "austin_tx", "q": "taco", "limit": 5},
    )
    taco_payload = taco_resp.get_json()
    assert taco_payload["total"] == 1
    assert taco_payload["items"][0]["item_name"] == "Taco Platter"


def test_price_index_endpoint_cleans_dirty_rows_and_supports_zip_and_dietary_filters(monkeypatch):
    engine = _setup_engine()
    Session = sessionmaker(bind=engine)
    session = Session()
    result = upsert_menu_shape(session, _build_shape())
    assert result.skipped is False

    timestamp = datetime(2026, 4, 20, 18, 0, 0, tzinfo=timezone.utc)
    base_page = session.query(MenuPage).filter(MenuPage.url == "https://laposadasouth.com/menu").one()

    taco_item = session.query(MenuItem).filter(MenuItem.name == "Taco Platter").one()
    taco_item.name = "Taco Platter <vegan>VG</vegan>"
    taco_item.dietary_tags = []

    session.add(MenuSection(
        id="section_side",
        page_id=base_page.id,
        restaurant_id=123,
        name="Side of Rice (White or Brown)",
        path=["Side of Rice (White or Brown)"],
        service_period=None,
        course="side",
        source="dom",
        first_seen_at=timestamp,
        last_seen_at=timestamp,
    ))
    session.add(MenuItem(
        id="item_side",
        section_id="section_side",
        restaurant_id=123,
        name="8 Oz",
        description=None,
        course="side",
        calories=None,
        dietary_tags=[],
        source="dom",
        first_seen_at=timestamp,
        last_seen_at=timestamp,
    ))
    session.add(MenuPricePoint(
        id="pp_side",
        item_id="item_side",
        section_id="section_side",
        restaurant_id=123,
        price=2.0,
        currency="USD",
        variant=None,
        confidence=0.6,
        source="dom",
        evidence="8 Oz",
        observed_at=timestamp,
    ))

    session.add(MenuSection(
        id="section_unnamed",
        page_id=base_page.id,
        restaurant_id=123,
        name="(unnamed)",
        path=["(unnamed)"],
        service_period=None,
        course="appetizer",
        source="jsonld",
        first_seen_at=timestamp,
        last_seen_at=timestamp,
    ))
    session.add(MenuItem(
        id="item_queso",
        section_id="section_unnamed",
        restaurant_id=123,
        name="Chile con Queso",
        description=None,
        course="appetizer",
        calories=None,
        dietary_tags=[],
        source="jsonld",
        first_seen_at=timestamp,
        last_seen_at=timestamp,
    ))
    session.add(MenuPricePoint(
        id="pp_queso",
        item_id="item_queso",
        section_id="section_unnamed",
        restaurant_id=123,
        price=5.0,
        currency="USD",
        variant=None,
        confidence=0.9,
        source="jsonld",
        evidence="Regular",
        observed_at=timestamp,
    ))

    session.add(MenuPage(
        id="page_specials",
        restaurant_id=123,
        url="https://abels.com/specials",
        source="dom",
        renderer="static_html",
        source_bundle="abels_specials.json",
        first_seen_at=timestamp,
        last_seen_at=timestamp,
    ))
    session.add(MenuSection(
        id="section_specials",
        page_id="page_specials",
        restaurant_id=123,
        name="Daily Specials",
        path=["Daily Specials"],
        service_period="happy_hour",
        course="drink",
        source="dom",
        first_seen_at=timestamp,
        last_seen_at=timestamp,
    ))
    session.add(MenuItem(
        id="item_specials",
        section_id="section_specials",
        restaurant_id=123,
        name="off drafts",
        description=None,
        course="drink",
        calories=None,
        dietary_tags=[],
        source="dom",
        first_seen_at=timestamp,
        last_seen_at=timestamp,
    ))
    session.add(MenuPricePoint(
        id="pp_specials",
        item_id="item_specials",
        section_id="section_specials",
        restaurant_id=123,
        price=1.0,
        currency="USD",
        variant=None,
        confidence=0.6,
        source="dom",
        evidence="$1 off drafts",
        observed_at=timestamp,
    ))

    session.commit()
    session.close()

    app = Flask(__name__)
    app.register_blueprint(price_index_bp)
    monkeypatch.setattr(price_index_routes, "_engine", engine)
    monkeypatch.setattr(price_index_routes, "_resolve_zip_coordinates", lambda zip_code: (30.27, -97.74))

    client = app.test_client()

    base_resp = client.get("/api/price-index", query_string={"region": "austin_tx", "limit": 10})
    assert base_resp.status_code == 200
    base_payload = base_resp.get_json()
    assert base_payload["total"] == 4
    assert all(item["distance_mi"] is None for item in base_payload["items"])
    assert all(item["item_name"] != "off drafts" for item in base_payload["items"])

    taco_row = next(item for item in base_payload["items"] if item["item_name"] == "Taco Platter")
    assert taco_row["dietary_tags"] == ["vegan"]

    rice_row = next(item for item in base_payload["items"] if item["item_name"] == "Side of Rice (White or Brown)")
    assert rice_row["variant"] == "8 Oz"

    queso_row = next(item for item in base_payload["items"] if item["item_name"] == "Chile con Queso")
    assert queso_row["section_name"] is None
    assert queso_row["variant"] == "Regular"

    dietary_resp = client.get(
        "/api/price-index",
        query_string=[("region", "austin_tx"), ("dietary", "vegan")],
    )
    dietary_payload = dietary_resp.get_json()
    assert dietary_payload["total"] == 1
    assert dietary_payload["items"][0]["item_name"] == "Taco Platter"

    zip_resp = client.get(
        "/api/price-index",
        query_string={"region": "austin_tx", "zip_code": "78701", "limit": 10},
    )
    zip_payload = zip_resp.get_json()
    assert zip_payload["items"][0]["distance_mi"] is not None

    facet_resp = client.get("/api/price-index/facets", query_string={"region": "austin_tx"})
    facet_payload = facet_resp.get_json()
    assert any(tag["key"] == "vegan" for tag in facet_payload["dietary_tags"])