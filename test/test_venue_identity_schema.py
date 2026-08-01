"""One failing case per constraint in the venue-identity schema.

ROADMAP Phase 1 requires that "every constraint has at least one failing-test
case", and it is the right bar: a `CHECK` nobody has ever seen reject a row is
indistinguishable from a `CHECK` that was never applied.

Two deliberate choices here:

- **Cascades are tested with raw SQL, not `session.delete()`.** The ORM's
  `cascade="all, delete-orphan"` would delete children in Python and the test
  would pass even if the database had no `ON DELETE` rule at all. Issuing the
  `DELETE` directly tests the constraint that actually protects the data.
- **Blank-string checks matter as much as NOT NULL.** Scraped and geocoded
  data arrives as `""` far more often than as `NULL`, and an empty fingerprint
  would silently collide with every other empty fingerprint.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from packages.helios_core.db.models import (
    Brand,
    SiteIdentity,
    Venue,
    VenueAlias,
    VenueSite,
    VenueSource,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


def _venue(session: Session, name: str = "Test Venue", **overrides: Any) -> Venue:
    """Persist a minimally valid venue."""
    venue = Venue(name=name, **overrides)
    session.add(venue)
    session.commit()
    return venue


def _brand(session: Session, **overrides: Any) -> Brand:
    defaults: dict[str, Any] = {"name": "Test Brand", "name_fingerprint": "test brand"}
    brand = Brand(**{**defaults, **overrides})
    session.add(brand)
    session.commit()
    return brand


def _site(session: Session, **overrides: Any) -> SiteIdentity:
    defaults: dict[str, Any] = {"url_canonical": "https://example.com"}
    site = SiteIdentity(**{**defaults, **overrides})
    session.add(site)
    session.commit()
    return site


def _assert_rejects(session: Session, obj: Any) -> None:
    """Adding `obj` must violate a database constraint."""
    session.add(obj)
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


# --- brand ------------------------------------------------------------------


def test_brand_name_fingerprint_is_unique(session: Session) -> None:
    _brand(session, name="H-E-B", name_fingerprint="heb")
    _assert_rejects(session, Brand(name="HEB Grocery", name_fingerprint="heb"))


def test_brand_name_cannot_be_blank(session: Session) -> None:
    _assert_rejects(session, Brand(name="   ", name_fingerprint="something"))


def test_brand_fingerprint_cannot_be_blank(session: Session) -> None:
    _assert_rejects(session, Brand(name="Real Name", name_fingerprint=""))


# --- venue ------------------------------------------------------------------


def test_venue_status_rejects_unknown_value(session: Session) -> None:
    # Deliberately short: a longer bogus value trips the varchar(16) length
    # limit first and raises DataError, which would test the wrong thing.
    _assert_rejects(session, Venue(name="Somewhere", status="trading"))


@pytest.mark.parametrize("status", ["open", "closed", "unknown"])
def test_venue_status_accepts_allowed_values(session: Session, status: str) -> None:
    _venue(session, status=status)


def test_venue_name_cannot_be_blank(session: Session) -> None:
    _assert_rejects(session, Venue(name="  "))


@pytest.mark.parametrize("lat", [91.0, -91.0])
def test_venue_latitude_must_be_in_range(session: Session, lat: float) -> None:
    _assert_rejects(session, Venue(name="Off Earth", lat=lat, lng=0.0))


@pytest.mark.parametrize("lng", [181.0, -181.0])
def test_venue_longitude_must_be_in_range(session: Session, lng: float) -> None:
    _assert_rejects(session, Venue(name="Off Earth", lat=0.0, lng=lng))


@pytest.mark.parametrize(
    ("lat", "lng"),
    [(30.26, None), (None, -97.74)],
)
def test_venue_rejects_half_a_coordinate(
    session: Session, lat: float | None, lng: float | None
) -> None:
    """A venue with a latitude but no longitude is a bug, not a state."""
    _assert_rejects(session, Venue(name="Half Located", lat=lat, lng=lng))


def test_venue_allows_no_coordinates_at_all(session: Session) -> None:
    """Un-geocoded is a legitimate state -- discovery runs before geocoding."""
    venue = _venue(session)
    assert venue.lat is None
    assert venue.lng is None


def test_deleting_a_brand_keeps_its_venues(session: Session) -> None:
    """ON DELETE SET NULL: the restaurant outlives our knowledge of the chain."""
    brand = _brand(session)
    venue = _venue(session, brand_id=brand.id)
    venue_id = venue.id

    session.execute(text("DELETE FROM canonical.brand WHERE id = :id"), {"id": brand.id})
    session.commit()
    session.expire_all()

    survivor = session.get(Venue, venue_id)
    assert survivor is not None
    assert survivor.brand_id is None


# --- venue_alias ------------------------------------------------------------


def test_venue_alias_fingerprint_is_unique_per_venue(session: Session) -> None:
    venue = _venue(session)
    session.add(VenueAlias(venue_id=venue.id, alias="Torchy's", alias_fingerprint="torchys"))
    session.commit()
    _assert_rejects(
        session,
        VenueAlias(venue_id=venue.id, alias="TORCHYS", alias_fingerprint="torchys"),
    )


def test_same_alias_fingerprint_allowed_across_different_venues(session: Session) -> None:
    first = _venue(session)
    second = _venue(session, name="Second Venue")
    session.add(VenueAlias(venue_id=first.id, alias="Torchy's", alias_fingerprint="torchys"))
    session.add(VenueAlias(venue_id=second.id, alias="Torchy's", alias_fingerprint="torchys"))
    session.commit()


def test_venue_alias_cannot_be_blank(session: Session) -> None:
    venue = _venue(session)
    _assert_rejects(session, VenueAlias(venue_id=venue.id, alias="", alias_fingerprint="x"))


def test_venue_alias_rejects_unknown_source_kind(session: Session) -> None:
    """Same vocabulary as `venue_source.source`, and pinned for the same reason."""
    venue = _venue(session)
    _assert_rejects(
        session,
        VenueAlias(venue_id=venue.id, alias="Torchy's", alias_fingerprint="t", source="yelp"),
    )


def test_venue_alias_source_may_be_unrecorded(session: Session) -> None:
    """NULL passes the CHECK -- an alias may predate knowing its origin."""
    venue = _venue(session)
    session.add(VenueAlias(venue_id=venue.id, alias="Torchy's", alias_fingerprint="t"))
    session.commit()


def test_deleting_a_venue_cascades_to_aliases(session: Session) -> None:
    venue = _venue(session)
    session.add(VenueAlias(venue_id=venue.id, alias="Alias", alias_fingerprint="alias"))
    session.commit()

    session.execute(text("DELETE FROM canonical.venue WHERE id = :id"), {"id": venue.id})
    session.commit()

    remaining = session.execute(text("SELECT count(*) FROM canonical.venue_alias")).scalar_one()
    assert remaining == 0


# --- venue_source -----------------------------------------------------------


def test_external_record_maps_to_exactly_one_venue(session: Session) -> None:
    """The constraint that makes re-ingesting an Overture snapshot idempotent."""
    first = _venue(session)
    second = _venue(session, name="Second Venue")
    session.add(VenueSource(venue_id=first.id, source="overture", external_id="abc123"))
    session.commit()
    _assert_rejects(
        session,
        VenueSource(venue_id=second.id, source="overture", external_id="abc123"),
    )


def test_same_external_id_allowed_across_different_sources(session: Session) -> None:
    venue = _venue(session)
    session.add(VenueSource(venue_id=venue.id, source="overture", external_id="123"))
    session.add(VenueSource(venue_id=venue.id, source="osm", external_id="123"))
    session.commit()


def test_venue_source_rejects_unknown_source_kind(session: Session) -> None:
    venue = _venue(session)
    _assert_rejects(session, VenueSource(venue_id=venue.id, source="yelp", external_id="1"))


def test_venue_source_external_id_cannot_be_blank(session: Session) -> None:
    venue = _venue(session)
    _assert_rejects(session, VenueSource(venue_id=venue.id, source="manual", external_id=" "))


def test_venue_source_stores_raw_identity_as_jsonb(session: Session) -> None:
    venue = _venue(session)
    payload = {"names": {"primary": "Torchy's Tacos"}, "confidence": 0.94}
    session.add(
        VenueSource(venue_id=venue.id, source="overture", external_id="ovt-1", raw_identity=payload)
    )
    session.commit()
    session.expire_all()

    stored = session.execute(
        text("SELECT raw_identity FROM canonical.venue_source WHERE external_id = 'ovt-1'")
    ).scalar_one()
    assert stored == payload


def test_deleting_a_venue_cascades_to_sources(session: Session) -> None:
    venue = _venue(session)
    session.add(VenueSource(venue_id=venue.id, source="osm", external_id="node/1"))
    session.commit()

    session.execute(text("DELETE FROM canonical.venue WHERE id = :id"), {"id": venue.id})
    session.commit()

    remaining = session.execute(text("SELECT count(*) FROM canonical.venue_source")).scalar_one()
    assert remaining == 0


# --- site_identity ----------------------------------------------------------


def test_canonical_url_is_unique(session: Session) -> None:
    _site(session, url_canonical="https://torchystacos.com")
    _assert_rejects(session, SiteIdentity(url_canonical="https://torchystacos.com"))


def test_site_rejects_unknown_liveness_status(session: Session) -> None:
    _assert_rejects(
        session, SiteIdentity(url_canonical="https://a.example", liveness_status="maybe")
    )


def test_site_url_cannot_be_blank(session: Session) -> None:
    _assert_rejects(session, SiteIdentity(url_canonical="   "))


def test_site_liveness_defaults_to_unknown(session: Session) -> None:
    site = _site(session)
    session.refresh(site)
    assert site.liveness_status == "unknown"


# --- venue_site -------------------------------------------------------------


def test_one_site_can_serve_many_venues(session: Session) -> None:
    """The chain case RFC-0001 D2 calls for: one brand site, many locations."""
    site = _site(session, url_canonical="https://mcdonalds.com")
    first = _venue(session, name="McDonald's Congress")
    second = _venue(session, name="McDonald's Riverside")

    session.add(
        VenueSite(venue_id=first.id, site_identity_id=site.id, resolution_method="overture_website")
    )
    session.add(
        VenueSite(venue_id=second.id, site_identity_id=site.id, resolution_method="osm_tag")
    )
    session.commit()

    linked = session.execute(text("SELECT count(*) FROM canonical.venue_site")).scalar_one()
    assert linked == 2


def test_venue_site_pair_cannot_repeat(session: Session) -> None:
    site = _site(session)
    venue = _venue(session)
    session.add(VenueSite(venue_id=venue.id, site_identity_id=site.id, resolution_method="manual"))
    session.commit()
    _assert_rejects(
        session,
        VenueSite(venue_id=venue.id, site_identity_id=site.id, resolution_method="osm_tag"),
    )


def test_venue_site_rejects_unknown_resolution_method(session: Session) -> None:
    site = _site(session)
    venue = _venue(session)
    _assert_rejects(
        session,
        VenueSite(venue_id=venue.id, site_identity_id=site.id, resolution_method="google_places"),
    )


def test_deleting_a_site_cascades_to_links_but_not_venues(session: Session) -> None:
    site = _site(session)
    venue = _venue(session)
    venue_id = venue.id
    session.add(VenueSite(venue_id=venue.id, site_identity_id=site.id, resolution_method="manual"))
    session.commit()

    session.execute(text("DELETE FROM canonical.site_identity WHERE id = :id"), {"id": site.id})
    session.commit()

    links = session.execute(text("SELECT count(*) FROM canonical.venue_site")).scalar_one()
    assert links == 0
    assert session.get(Venue, venue_id) is not None


def test_deleting_a_venue_cascades_to_links_but_not_sites(session: Session) -> None:
    site = _site(session)
    venue = _venue(session)
    site_id = site.id
    session.add(VenueSite(venue_id=venue.id, site_identity_id=site.id, resolution_method="manual"))
    session.commit()

    session.execute(text("DELETE FROM canonical.venue WHERE id = :id"), {"id": venue.id})
    session.commit()

    links = session.execute(text("SELECT count(*) FROM canonical.venue_site")).scalar_one()
    assert links == 0
    assert session.get(SiteIdentity, site_id) is not None
