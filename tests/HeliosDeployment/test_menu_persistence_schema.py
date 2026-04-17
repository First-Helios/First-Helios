"""Tests for collectors.meal_deals.menu_persistence_schema (ARCH-01).

Verifies the sidecar → target persistent shape serializer produces
FK-consistent rows with provenance, so a future migration can upsert
directly from replay bundles.
"""

from __future__ import annotations

from datetime import datetime, timezone

from collectors.meal_deals.menu_persistence_schema import (
    SCHEMA_VERSION,
    check_foreign_keys,
    serialize_sidecar,
    summarize_shape,
)
from collectors.meal_deals.menu_sidecar import (
    MenuSidecar,
    ingest_jsonld_payload,
    link_signal_to_target,
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
                "name": "Fajita platter",
                "offers": {"@type": "Offer", "price": "95.99", "priceCurrency": "USD"},
            },
            {
                "@type": "MenuItem",
                "name": "Taco Platter",
                "offers": {"@type": "Offer", "price": "54.99", "priceCurrency": "USD"},
            },
        ],
    },
}


def _fixture_sidecar() -> MenuSidecar:
    sidecar = MenuSidecar()
    ingest_jsonld_payload(
        LAPOSADA_MENU_PAYLOAD,
        page_url="https://laposadasouth.com/menu",
        sidecar=sidecar,
    )
    link_signal_to_target(
        sidecar,
        signal_ref="fajita_deal",
        page_url="https://laposadasouth.com/menu",
        context_path=["LIMITED LUNCH SPECIALS", "Family Packs"],
        primary_name="Fajita platter",
    )
    return sidecar


def test_serialize_sidecar_returns_all_row_types():
    sidecar = _fixture_sidecar()
    shape = serialize_sidecar(
        sidecar,
        restaurant_id="emp_abc123",
        source_url="https://laposadasouth.com/menu",
        source_bundle="laposadasouth_com__9e05a1a3db03.json",
    )

    assert shape["schema_version"] == SCHEMA_VERSION
    assert shape["restaurant_id"] == "emp_abc123"
    assert shape["source_url"] == "https://laposadasouth.com/menu"
    assert shape["source_bundle"] == "laposadasouth_com__9e05a1a3db03.json"

    assert len(shape["pages"]) >= 1
    assert len(shape["sections"]) >= 2
    assert len(shape["items"]) == 2
    assert len(shape["price_points"]) == 2
    assert len(shape["offer_targets"]) >= 1


def test_serialize_sidecar_rows_carry_provenance():
    sidecar = _fixture_sidecar()
    fixed_ts = datetime(2026, 4, 17, 12, 0, 0, tzinfo=timezone.utc)
    shape = serialize_sidecar(
        sidecar,
        restaurant_id="emp_abc123",
        observed_at=fixed_ts,
    )

    assert shape["observed_at"].startswith("2026-04-17T12:00:00")
    for table_key in ("pages", "sections", "items", "modifiers"):
        for row in shape[table_key]:
            assert row["restaurant_id"] == "emp_abc123"
            assert "first_seen_at" in row
            assert "last_seen_at" in row
    for pp in shape["price_points"]:
        assert pp["observed_at"].startswith("2026-04-17T12:00:00")


def test_serialize_sidecar_foreign_keys_consistent():
    sidecar = _fixture_sidecar()
    shape = serialize_sidecar(sidecar, restaurant_id="emp_abc123")
    assert check_foreign_keys(shape) == []


def test_summarize_shape_exposes_counts_and_fk_status():
    sidecar = _fixture_sidecar()
    shape = serialize_sidecar(sidecar, restaurant_id="emp_abc123")
    summary = summarize_shape(shape)
    assert summary["schema_version"] == SCHEMA_VERSION
    assert summary["counts"]["items"] == 2
    assert summary["counts"]["price_points"] == 2
    assert summary["fk_violations"] == []


def test_sidecar_ids_match_persistent_ids_roundtrip():
    """Key invariant: sidecar keys ARE the persistent IDs. If that drifts,
    future upserts become non-idempotent."""
    sidecar = _fixture_sidecar()
    shape = serialize_sidecar(sidecar)
    assert {p["id"] for p in shape["pages"]} == set(sidecar.pages.keys())
    assert {s["id"] for s in shape["sections"]} == set(sidecar.sections.keys())
    assert {i["id"] for i in shape["items"]} == set(sidecar.items.keys())
    assert {pp["id"] for pp in shape["price_points"]} == set(sidecar.price_points.keys())
    assert {t["id"] for t in shape["offer_targets"]} == set(sidecar.offer_targets.keys())
