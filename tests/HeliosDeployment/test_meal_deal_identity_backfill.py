from sqlalchemy.orm import Session

from core.database import (
    BrandGroup,
    CanonicalVenue,
    CanonicalVenueAlias,
    LocalEmployer,
    RestaurantURL,
    SiteAssignment,
    SiteIdentity,
)
from core.normalizer import make_fingerprint
from scripts.backfills.backfill_meal_deal_identity import rebuild_meal_deal_identity


def _build_employer(
    employer_id: int,
    *,
    name: str,
    address: str,
    brand_group_id: int | None,
    lat: float,
    lng: float,
) -> LocalEmployer:
    return LocalEmployer(
        id=employer_id,
        raw_name=name,
        name=name,
        fingerprint=make_fingerprint(name),
        address=address,
        brand_group_id=brand_group_id,
        lat=lat,
        lng=lng,
        region="austin_tx",
        industry="food_full_service",
        source="manual",
        is_active=True,
    )


def test_rebuild_meal_deal_identity_collapses_shared_url_aliases(engine):
    with Session(engine) as session:
        session.add_all(
            [
                BrandGroup(id=38677, fingerprint="polvos-bratton", canonical_name="Polvos Bratton", location_count=1),
                BrandGroup(id=41201, fingerprint="polvos-north", canonical_name="Polvos Mexican Restaurant North", location_count=1),
                _build_employer(
                    38677,
                    name="Polvos Bratton",
                    address="14735 Bratton Ln, Austin, TX",
                    brand_group_id=38677,
                    lat=30.44599,
                    lng=-97.68572,
                ),
                _build_employer(
                    41201,
                    name="Polvos Mexican Restaurant North",
                    address="14735 Bratton Ln #205, Austin, TX",
                    brand_group_id=41201,
                    lat=30.44906,
                    lng=-97.68265,
                ),
                RestaurantURL(
                    local_employer_id=38677,
                    brand_group_id=38677,
                    url="https://polvosaustin.com/austin-barton-creek-mall-polvos-barton-creek-locations",
                    source="google_places",
                    confidence=0.95,
                    is_active=True,
                ),
                RestaurantURL(
                    local_employer_id=41201,
                    brand_group_id=41201,
                    url="https://polvosaustin.com/austin-barton-creek-mall-polvos-barton-creek-locations",
                    source="google_places",
                    confidence=0.95,
                    is_active=True,
                ),
            ]
        )
        session.commit()

        stats = rebuild_meal_deal_identity(session, region="austin_tx")
        session.commit()

        assert stats["canonical_venues"] == 1
        assert stats["venue_aliases"] == 2
        assert stats["site_identities"] == 1
        assert stats["site_assignments"] == 1

        venue = session.query(CanonicalVenue).one()
        assert venue.site_status == "shared_site"

        aliases = session.query(CanonicalVenueAlias).order_by(CanonicalVenueAlias.local_employer_id).all()
        assert len(aliases) == 2
        assert {alias.canonical_venue_id for alias in aliases} == {venue.id}
        assert {alias.alias_role for alias in aliases} == {"primary", "alias"}

        site = session.query(SiteIdentity).one()
        assert site.ownership_scope == "venue"
        assert site.conflict_state == "clear"

        assignment = session.query(SiteAssignment).one()
        assert assignment.assignment_scope == "venue"
        assert assignment.canonical_venue_id == venue.id