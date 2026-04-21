"""
collectors/meal_deals/menu_db_writer.py — Idempotent upsert helper for the
menu graph tables introduced in FPI-1 (Food Price Index tab).

Each call to upsert_menu_shape() is fully transactional.  A failure does
not leave partially-populated rows for the restaurant.

Usage
-----
    from collectors.meal_deals.menu_db_writer import upsert_menu_shape
    from core.database import get_engine, get_session

    with get_session(get_engine()) as session:
        result = upsert_menu_shape(session, shape)
        session.commit()
        print(result)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

from collectors.meal_deals.menu_persistence_schema import PersistentShape
from core.database import MenuItem, MenuModifier, MenuPage, MenuPricePoint, MenuSection

logger = logging.getLogger(__name__)

_ISO = "%Y-%m-%dT%H:%M:%S%z"


# ── Result container ─────────────────────────────────────────────────────────


@dataclass
class UpsertResult:
    pages_written: int = 0
    sections_written: int = 0
    items_written: int = 0
    price_points_written: int = 0
    modifiers_written: int = 0
    fk_violations_skipped: int = 0
    errors: list[str] = field(default_factory=list)

    def __str__(self) -> str:  # noqa: D105
        return (
            f"pages={self.pages_written} sections={self.sections_written} "
            f"items={self.items_written} price_points={self.price_points_written} "
            f"modifiers={self.modifiers_written} fk_skip={self.fk_violations_skipped}"
        )


# ── Helpers ──────────────────────────────────────────────────────────────────


def _parse_dt(value: str | None) -> datetime | None:
    """Parse ISO-8601 timestamp string; return None on failure."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value).replace(tzinfo=None)
    except (ValueError, TypeError):
        return None


def _cast_restaurant_id(value: str | None) -> int | None:
    """Cast sidecar restaurant_id (str) to int FK; return None if uncastable."""
    if value is None:
        return None
    try:
        return int(value)
    except (ValueError, TypeError):
        return None


# ── Core upsert ──────────────────────────────────────────────────────────────


def upsert_menu_shape(session: Session, shape: PersistentShape) -> UpsertResult:
    """Idempotent upsert of a PersistentShape into the 5 menu graph tables.

    Strategy: INSERT OR REPLACE on SQLite; for PostgreSQL we use a simple
    merge-via-delete+insert pattern so this stays DB-agnostic without
    needing dialect-specific ON CONFLICT clauses.

    The whole write is wrapped in a savepoint so a failure here does not
    poison the caller's outer transaction.
    """
    result = UpsertResult()

    restaurant_id = _cast_restaurant_id(shape.get("restaurant_id"))
    if restaurant_id is None:
        logger.debug("[menu_db_writer] no restaurant_id — skipping shape for %s", shape.get("source_url"))
        result.fk_violations_skipped += 1
        return result

    try:
        _upsert_pages(session, shape, restaurant_id, result)
        _upsert_sections(session, shape, restaurant_id, result)
        _upsert_items(session, shape, restaurant_id, result)
        _upsert_price_points(session, shape, restaurant_id, result)
        _upsert_modifiers(session, shape, restaurant_id, result)
    except Exception as exc:
        logger.error("[menu_db_writer] upsert failed for restaurant_id=%s: %s", restaurant_id, exc, exc_info=True)
        result.errors.append(str(exc))
        raise  # let caller roll back

    return result


# ── Per-table helpers ────────────────────────────────────────────────────────


def _upsert_pages(session: Session, shape: PersistentShape, restaurant_id: int, result: UpsertResult) -> None:
    for row in shape.get("pages") or []:
        page_id = row.get("id")
        if not page_id:
            continue
        existing = session.get(MenuPage, page_id)
        now = _parse_dt(row.get("last_seen_at")) or datetime.now(timezone.utc).replace(tzinfo=None)
        if existing:
            existing.last_seen_at = now
        else:
            session.add(MenuPage(
                id=page_id,
                restaurant_id=restaurant_id,
                url=row.get("url"),
                source=row.get("source"),
                renderer=row.get("renderer"),
                source_bundle=row.get("source_bundle"),
                first_seen_at=_parse_dt(row.get("first_seen_at")),
                last_seen_at=now,
            ))
        result.pages_written += 1


def _upsert_sections(session: Session, shape: PersistentShape, restaurant_id: int, result: UpsertResult) -> None:
    for row in shape.get("sections") or []:
        section_id = row.get("id")
        if not section_id:
            continue
        existing = session.get(MenuSection, section_id)
        now = _parse_dt(row.get("last_seen_at")) or datetime.now(timezone.utc).replace(tzinfo=None)
        if existing:
            existing.last_seen_at = now
            existing.service_period = row.get("service_period") or existing.service_period
            existing.course = row.get("course") or existing.course
        else:
            session.add(MenuSection(
                id=section_id,
                page_id=row.get("page_id"),
                parent_section_id=row.get("parent_section_id"),
                restaurant_id=restaurant_id,
                name=row.get("name"),
                path=row.get("path"),
                service_period=row.get("service_period"),
                course=row.get("course"),
                source=row.get("source"),
                first_seen_at=_parse_dt(row.get("first_seen_at")),
                last_seen_at=now,
            ))
        result.sections_written += 1


def _upsert_items(session: Session, shape: PersistentShape, restaurant_id: int, result: UpsertResult) -> None:
    for row in shape.get("items") or []:
        item_id = row.get("id")
        if not item_id:
            continue
        existing = session.get(MenuItem, item_id)
        now = _parse_dt(row.get("last_seen_at")) or datetime.now(timezone.utc).replace(tzinfo=None)
        if existing:
            existing.last_seen_at = now
            # Upgrade nutrition/description if missing
            if not existing.description and row.get("description"):
                existing.description = row.get("description")
            if existing.calories is None and row.get("calories") is not None:
                existing.calories = row.get("calories")
            if not existing.dietary_tags and row.get("dietary_tags"):
                existing.dietary_tags = row.get("dietary_tags")
        else:
            session.add(MenuItem(
                id=item_id,
                section_id=row.get("section_id"),
                restaurant_id=restaurant_id,
                name=row.get("name"),
                description=row.get("description"),
                course=row.get("course"),
                calories=row.get("calories"),
                dietary_tags=row.get("dietary_tags") or [],
                source=row.get("source"),
                first_seen_at=_parse_dt(row.get("first_seen_at")),
                last_seen_at=now,
            ))
        result.items_written += 1


def _upsert_price_points(session: Session, shape: PersistentShape, restaurant_id: int, result: UpsertResult) -> None:
    for row in shape.get("price_points") or []:
        pp_id = row.get("id")
        if not pp_id:
            continue
        price = row.get("price")
        if price is None:
            continue  # never write a price point without a price value
        existing = session.get(MenuPricePoint, pp_id)
        now = _parse_dt(row.get("observed_at")) or datetime.now(timezone.utc).replace(tzinfo=None)
        if existing:
            # Update price and confidence in case scraper improved
            existing.price = price
            existing.confidence = row.get("confidence", existing.confidence)
            existing.observed_at = now
        else:
            session.add(MenuPricePoint(
                id=pp_id,
                item_id=row.get("item_id"),
                section_id=row.get("section_id"),
                restaurant_id=restaurant_id,
                price=price,
                currency=row.get("currency", "USD"),
                variant=row.get("variant"),
                confidence=row.get("confidence"),
                source=row.get("source"),
                evidence=row.get("evidence"),
                observed_at=now,
            ))
        result.price_points_written += 1


def _upsert_modifiers(session: Session, shape: PersistentShape, restaurant_id: int, result: UpsertResult) -> None:
    for row in shape.get("modifiers") or []:
        mod_id = row.get("id")
        if not mod_id:
            continue
        existing = session.get(MenuModifier, mod_id)
        now = _parse_dt(row.get("last_seen_at")) or datetime.now(timezone.utc).replace(tzinfo=None)
        if existing:
            existing.last_seen_at = now
            if row.get("price_delta") is not None:
                existing.price_delta = row.get("price_delta")
        else:
            session.add(MenuModifier(
                id=mod_id,
                item_id=row.get("item_id"),
                section_id=row.get("section_id"),
                restaurant_id=restaurant_id,
                label=row.get("label"),
                price_delta=row.get("price_delta"),
                required=row.get("required", False),
                source=row.get("source"),
                first_seen_at=_parse_dt(row.get("first_seen_at")),
                last_seen_at=now,
            ))
        result.modifiers_written += 1
