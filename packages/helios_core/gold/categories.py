"""Source-backed venue category projection and read contract (ADR-0028)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from sqlalchemy import delete, func, insert, select, text

from packages.helios_core.gold.models import VenueCategory
from packages.helios_core.identity.contracts import current_venue_record_links
from packages.helios_core.provenance.contracts import latest_record_categories

if TYPE_CHECKING:
    from collections.abc import Collection, Mapping, Sequence
    from datetime import datetime

    from sqlalchemy import ColumnElement, Select
    from sqlalchemy.orm import Session
    from sqlalchemy.orm.attributes import InstrumentedAttribute

MAPPING_VERSION = "overture-venue-v1"
# (stable key, display label, exact source tags). No suffix/keyword inference.
CATEGORY_OPTIONS: dict[str, tuple[tuple[str, str, tuple[str, ...]], ...]] = {
    "cuisine": (
        ("mexican", "Mexican", ("mexican_restaurant",)),
        ("tex_mex", "Tex-Mex", ("texmex_restaurant",)),
        ("american", "American", ("american_restaurant",)),
        ("italian", "Italian", ("italian_restaurant",)),
        ("chinese", "Chinese", ("chinese_restaurant",)),
        ("indian", "Indian", ("indian_restaurant",)),
        ("thai", "Thai", ("thai_restaurant",)),
        ("vietnamese", "Vietnamese", ("vietnamese_restaurant",)),
        ("japanese", "Japanese", ("japanese_restaurant",)),
        ("mediterranean", "Mediterranean", ("mediterranean_restaurant",)),
        ("korean", "Korean", ("korean_restaurant",)),
        ("greek", "Greek", ("greek_restaurant",)),
        ("french", "French", ("french_restaurant",)),
        ("middle_eastern", "Middle Eastern", ("middle_eastern_restaurant",)),
        ("cajun_creole", "Cajun & Creole", ("cajun_and_creole_restaurant",)),
        ("southern", "Southern", ("southern_restaurant",)),
        ("latin_american", "Latin American", ("latin_american_restaurant",)),
        ("asian_fusion", "Asian fusion", ("asian_fusion_restaurant",)),
    ),
    "specialty": (
        ("pizza", "Pizza places", ("pizza_restaurant",)),
        ("burgers", "Burger places", ("burger_restaurant",)),
        ("tacos", "Taco places", ("taco_restaurant",)),
        ("barbecue", "BBQ places", ("barbecue_restaurant",)),
        ("chicken", "Chicken places", ("chicken_restaurant",)),
        ("seafood", "Seafood places", ("seafood_restaurant",)),
        ("sushi", "Sushi places", ("sushi_restaurant",)),
        ("sandwiches", "Sandwich places", ("sandwich_shop",)),
        ("wings", "Wing places", ("chicken_wings_restaurant",)),
        ("noodles", "Noodle places", ("noodles_restaurant",)),
        ("poke", "Poke places", ("poke_restaurant",)),
        ("hot_dogs", "Hot dog places", ("hot_dog_restaurant",)),
    ),
    "place_type": (
        ("food_truck", "Food trucks", ("food_truck",)),
        ("cafe", "Cafes", ("cafe",)),
        ("coffee_shop", "Coffee shops", ("coffee_shop",)),
        ("bakery", "Bakeries", ("bakery",)),
        ("bar", "Bars", ("bar",)),
        ("pub", "Pubs", ("pub",)),
        ("brewery", "Breweries", ("brewery",)),
        ("ice_cream_shop", "Ice cream shops", ("ice_cream_shop",)),
        ("diner", "Diners", ("diner",)),
        ("deli", "Delis", ("deli",)),
        ("bistro", "Bistros", ("bistro",)),
        ("food_court", "Food courts", ("food_court",)),
        ("fast_food", "Fast food", ("fast_food_restaurant", "fast_food")),
        ("juice_bar", "Juice bars", ("smoothie_juice_bar", "juice_bar")),
    ),
}
_RESTAURANT_TAGS = tuple(
    sorted(
        {
            tag
            for options in CATEGORY_OPTIONS.values()
            for _, _, tags in options
            for tag in tags
            if tag.endswith("_restaurant")
        }
        | {"restaurant"}
    )
)
CATEGORY_OPTIONS["place_type"] += (("restaurant", "Restaurants", _RESTAURANT_TAGS),)
LABELS = {
    (group, key): label for group, options in CATEGORY_OPTIONS.items() for key, label, _ in options
}

type CategoryFilters = Mapping[str, Sequence[str]]


@dataclass(frozen=True, slots=True)
class CategoryLabel:
    group: str
    key: str
    label: str


def category_predicates(
    venue_id: ColumnElement[int] | InstrumentedAttribute[int], filters: CategoryFilters
) -> list[ColumnElement[bool]]:
    """OR within a group, AND between groups; semi-joins cannot multiply rows."""
    return [
        venue_id.in_(
            select(VenueCategory.venue_id)
            .where(VenueCategory.category_group == group, VenueCategory.category_key.in_(keys))
            .correlate(None)
        )
        for group, keys in filters.items()
        if keys
    ]


def venue_categories(
    session: Session, venue_ids: Collection[int]
) -> dict[int, list[CategoryLabel]]:
    """One indexed batch for a page; unknown scopes get no labels."""
    result: dict[int, list[CategoryLabel]] = {}
    if not venue_ids:
        return result
    rows = session.execute(
        select(VenueCategory)
        .where(VenueCategory.venue_id.in_(venue_ids))
        .order_by(VenueCategory.category_group, VenueCategory.category_key)
    ).scalars()
    for row in rows:
        label = LABELS.get((row.category_group, row.category_key))
        if label is not None:
            result.setdefault(row.venue_id, []).append(
                CategoryLabel(row.category_group, row.category_key, label)
            )
    return result


def refresh_venue_categories(session: Session, *, at: datetime, refreshed_at: datetime) -> int:
    """Full transactional replacement, including removed/empty/corrected source claims."""
    session.execute(text("SELECT pg_advisory_xact_lock(280028)"))
    links = current_venue_record_links(session, at=at)
    versions = latest_record_categories(
        session, {r for records in links.values() for r in records}, namespace="overture", at=at
    )
    rows = []
    for venue, records in links.items():
        candidates = [versions[record] for record in records if record in versions]
        if not candidates:
            continue
        winner = max(
            candidates,
            key=lambda v: (v.observed_at, -v.source_record_id, v.source_record_version_id),
        )
        tags = set(winner.categories)
        for group, options in CATEGORY_OPTIONS.items():
            for key, _, source_tags in options:
                supporting = sorted(tags.intersection(source_tags))
                if supporting:
                    rows.append(
                        {
                            "venue_id": venue,
                            "category_group": group,
                            "category_key": key,
                            "source_record_version_id": winner.source_record_version_id,
                            "source_categories": supporting,
                            "mapping_version": MAPPING_VERSION,
                            "observed_at": winner.observed_at,
                            "refreshed_at": refreshed_at,
                        }
                    )
    session.execute(delete(VenueCategory))
    if rows:
        session.execute(insert(VenueCategory), rows)
    session.flush()
    return len(rows)


@dataclass(frozen=True, slots=True)
class CategoryCount:
    group: str
    key: str
    label: str
    venue_count: int


def venue_category_facets(
    session: Session, eligible_venues: Select[tuple[int]], filters: CategoryFilters
) -> tuple[datetime | None, dict[str, list[CategoryCount]]]:
    """Counts over a caller-composed venue scope; no ORM rows leave Gold.

    Ignore each group's own selected keys, while retaining all other groups.
    The scalar scope is deliberately independent of cursor pagination.
    """
    groups: dict[str, list[CategoryCount]] = {}
    stamps: list[datetime] = []
    for group, options in CATEGORY_OPTIONS.items():
        other_groups = {key: values for key, values in filters.items() if key != group}
        rows = session.execute(
            select(
                VenueCategory.category_key,
                func.count(func.distinct(VenueCategory.venue_id)),
                func.min(VenueCategory.refreshed_at),
            )
            .where(
                VenueCategory.category_group == group,
                VenueCategory.venue_id.in_(eligible_venues),
                *category_predicates(VenueCategory.venue_id, other_groups),
            )
            .group_by(VenueCategory.category_key)
        ).all()
        by_key = {key: count for key, count, _ in rows}
        stamps.extend(stamp for _, _, stamp in rows)
        groups[group] = [
            CategoryCount(group, key, label, by_key[key])
            for key, label, _ in options
            if key in by_key
        ]
    return min(stamps) if stamps else None, groups
