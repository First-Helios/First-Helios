"""
collectors/meal_deals/models.py — DealSignal dataclass.

Normalized container that all meal deal collectors produce before DB write.
Mirrors the pattern of ScraperSignal (collectors/base.py) and
EventSignal (events/ingest.py).
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class DealSignal:
    """A single meal deal observation from any source.

    Every deal collector produces a list[DealSignal].  The ingest pipeline
    converts these into meal_deals rows, handling dedup, geocoding, and
    brand_group fan-out.
    """

    # ── Restaurant identification ─────────────────────────────────────────────
    restaurant_name: str                          # display name
    address: str | None = None                    # street address for matching
    lat: float | None = None
    lng: float | None = None

    # ── Brand matching (for chain-wide deals) ─────────────────────────────────
    brand_fingerprint: str | None = None          # fingerprint from brand_groups
    brand_group_id: int | None = None             # resolved FK (set by ingest)
    local_employer_id: int | None = None          # resolved FK (set by ingest)

    # ── Deal detail ───────────────────────────────────────────────────────────
    deal_name: str = ""
    deal_description: str | None = None
    deal_type: str = "combo"
    # lunch_special | combo | bogo | happy_hour | kids_eat_free | daily_special

    # ── Pricing ───────────────────────────────────────────────────────────────
    price: float | None = None
    original_price: float | None = None
    menu_avg_price: float | None = None           # avg entrée price on same menu

    # ── Nutrition ─────────────────────────────────────────────────────────────
    calories: int | None = None                   # kcal for the deal item
    calorie_price_ratio: float | None = None      # kcal per dollar (calories/price)

    # ── Validity window ───────────────────────────────────────────────────────
    valid_days: str | None = None                 # "Mon-Fri" or "Tuesday"
    valid_start_time: str | None = None           # "11:00"
    valid_end_time: str | None = None             # "14:00"
    is_recurring: bool = True
    start_date: datetime | None = None
    end_date: datetime | None = None

    # ── Source provenance ─────────────────────────────────────────────────────
    source: str = "chain_website"
    source_url: str | None = None
    region: str = "austin_tx"

    # ── Extras ────────────────────────────────────────────────────────────────
    metadata: dict[str, Any] = field(default_factory=dict)
    observed_at: datetime = field(default_factory=datetime.utcnow)
