from datetime import datetime, timezone

from collectors.meal_deals.routes import _materialization_specificity_score, _sort_materialized_deals
from core.database import DealMaterialization


def _build_materialization(
    materialization_id: int,
    *,
    deal_name: str,
    verified_at: datetime,
    price: float | None = None,
    discount_percentage: float | None = None,
    deal_value_score: float | None = None,
    signal_quality: float | None = None,
    sub_deals: list[dict] | None = None,
) -> DealMaterialization:
    return DealMaterialization(
        id=materialization_id,
        observation_id=materialization_id,
        applicability_id=materialization_id,
        canonical_venue_id=1,
        local_employer_id=1,
        brand_group_id=1,
        restaurant_name="Test Venue",
        address="1 Main St, Austin, TX",
        lat=30.0,
        lng=-97.0,
        region="austin_tx",
        applicability_scope="venue",
        is_chain_template=False,
        deal_name=deal_name,
        deal_description=None,
        deal_type="happy_hour",
        price=price,
        discount_percentage=discount_percentage,
        source="website_scrape",
        source_url="https://example.com/deals",
        source_observation_key=f"obs-{materialization_id}",
        verified_at=verified_at,
        signal_quality=signal_quality,
        deal_value_score=deal_value_score,
        sub_deals=sub_deals,
        resolver_method="test",
        review_state="accepted",
        is_active=True,
    )


def test_sort_materialized_deals_prefers_specific_offer_rows_over_summary_rows():
    broad_summary = _build_materialization(
        1,
        deal_name="Happy Hour",
        verified_at=datetime(2026, 4, 18, 12, 0, 0, tzinfo=timezone.utc),
        deal_value_score=0.35,
        signal_quality=0.95,
    )
    specific_offer = _build_materialization(
        2,
        deal_name="$6 Margarita Happy Hour",
        verified_at=datetime(2026, 4, 17, 12, 0, 0, tzinfo=timezone.utc),
        price=6.0,
        deal_value_score=0.72,
        signal_quality=0.8,
        sub_deals=[{"item": "House Margarita", "price": 6.0}],
    )

    ordered = _sort_materialized_deals([broad_summary, specific_offer])

    assert _materialization_specificity_score(specific_offer) > _materialization_specificity_score(broad_summary)
    assert [deal.id for deal in ordered] == [2, 1]
