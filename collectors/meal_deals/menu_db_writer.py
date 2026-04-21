"""Persist menu sidecar shapes into the menu graph tables."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import delete, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from collectors.meal_deals.menu_persistence_schema import PersistentShape, check_foreign_keys
from core.database import LocalEmployer, MenuItem, MenuModifier, MenuPage, MenuPricePoint, MenuSection

_ISO_FORMAT = "%Y-%m-%dT%H:%M:%S%z"


@dataclass
class UpsertResult:
    restaurant_id: int | None
    skipped: bool = False
    skip_reason: str | None = None
    fk_violations: list[str] = field(default_factory=list)
    filtered: dict[str, int] = field(default_factory=lambda: {
        "price_points_non_positive": 0,
    })
    tables: dict[str, dict[str, int]] = field(default_factory=lambda: {
        "pages": {"inserted": 0, "updated": 0},
        "sections": {"inserted": 0, "updated": 0},
        "items": {"inserted": 0, "updated": 0},
        "price_points": {"inserted": 0, "updated": 0},
        "modifiers": {"inserted": 0, "updated": 0},
    })

    def record(self, table_name: str, *, inserted: int, updated: int) -> None:
        self.tables[table_name]["inserted"] += inserted
        self.tables[table_name]["updated"] += updated

    def inserted_total(self) -> int:
        return sum(counts["inserted"] for counts in self.tables.values())

    def updated_total(self) -> int:
        return sum(counts["updated"] for counts in self.tables.values())


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.strptime(value, _ISO_FORMAT)
    except ValueError:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.astimezone(timezone.utc)


def _coerce_restaurant_id(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _menu_pages(shape: PersistentShape, restaurant_id: int) -> list[dict[str, Any]]:
    return [
        {
            "id": row["id"],
            "restaurant_id": restaurant_id,
            "url": row["url"],
            "source": row["source"],
            "renderer": row["renderer"],
            "source_bundle": row["source_bundle"],
            "first_seen_at": _parse_dt(row["first_seen_at"]),
            "last_seen_at": _parse_dt(row["last_seen_at"]),
        }
        for row in shape["pages"]
    ]


def _menu_sections(shape: PersistentShape, restaurant_id: int) -> list[dict[str, Any]]:
    return [
        {
            "id": row["id"],
            "page_id": row["page_id"],
            "parent_section_id": row["parent_section_id"],
            "restaurant_id": restaurant_id,
            "name": row["name"],
            "path": list(row["path"]),
            "service_period": row["service_period"],
            "course": row["course"],
            "source": row["source"],
            "first_seen_at": _parse_dt(row["first_seen_at"]),
            "last_seen_at": _parse_dt(row["last_seen_at"]),
        }
        for row in shape["sections"]
    ]


def _menu_items(shape: PersistentShape, restaurant_id: int) -> list[dict[str, Any]]:
    return [
        {
            "id": row["id"],
            "section_id": row["section_id"],
            "restaurant_id": restaurant_id,
            "name": row["name"],
            "description": row["description"],
            "course": row["course"],
            "calories": row["calories"],
            "dietary_tags": list(row["dietary_tags"]),
            "source": row["source"],
            "first_seen_at": _parse_dt(row["first_seen_at"]),
            "last_seen_at": _parse_dt(row["last_seen_at"]),
        }
        for row in shape["items"]
    ]


def _menu_price_points(
    shape: PersistentShape,
    restaurant_id: int,
    *,
    result: UpsertResult | None = None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in shape["price_points"]:
        price = row.get("price")
        try:
            price_value = float(price) if price is not None else None
        except (TypeError, ValueError):
            price_value = None
        if price_value is None or price_value <= 0:
            if result is not None:
                result.filtered["price_points_non_positive"] = result.filtered.get("price_points_non_positive", 0) + 1
            continue
        rows.append({
            "id": row["id"],
            "item_id": row["item_id"],
            "section_id": row["section_id"],
            "restaurant_id": restaurant_id,
            "price": price_value,
            "currency": row["currency"],
            "variant": row["variant"],
            "confidence": row["confidence"],
            "source": row["source"],
            "evidence": row["evidence"],
            "observed_at": _parse_dt(row["observed_at"]),
        })
    return rows


def _menu_modifiers(shape: PersistentShape, restaurant_id: int) -> list[dict[str, Any]]:
    return [
        {
            "id": row["id"],
            "item_id": row["item_id"],
            "section_id": row["section_id"],
            "restaurant_id": restaurant_id,
            "label": row["label"],
            "price_delta": row["price_delta"],
            "required": row["required"],
            "source": row["source"],
            "first_seen_at": _parse_dt(row["first_seen_at"]),
            "last_seen_at": _parse_dt(row["last_seen_at"]),
        }
        for row in shape["modifiers"]
    ]


def _select_existing_ids(session: Session, model: Any, rows: list[dict[str, Any]]) -> set[str]:
    ids = [row["id"] for row in rows]
    if not ids:
        return set()
    return set(session.scalars(select(model.id).where(model.id.in_(ids))).all())


def _insert_stmt(session: Session, model: Any):
    dialect_name = session.get_bind().dialect.name
    if dialect_name == "postgresql":
        return pg_insert(model)
    if dialect_name == "sqlite":
        return sqlite_insert(model)
    raise NotImplementedError(f"menu_db_writer does not support dialect {dialect_name!r}")


def _upsert_rows(
    session: Session,
    model: Any,
    rows: list[dict[str, Any]],
    *,
    update_columns: tuple[str, ...],
) -> tuple[int, int]:
    if not rows:
        return 0, 0

    existing_ids = _select_existing_ids(session, model, rows)
    stmt = _insert_stmt(session, model).values(rows)
    set_map = {column: getattr(stmt.excluded, column) for column in update_columns}
    session.execute(
        stmt.on_conflict_do_update(
            index_elements=[model.id],
            set_=set_map,
        )
    )
    inserted = len(rows) - len(existing_ids)
    updated = len(existing_ids)
    return inserted, updated


def _select_scoped_ids(
    session: Session,
    model: Any,
    *,
    restaurant_id: int,
    filters: list[Any],
) -> set[str]:
    if not filters:
        return set()
    stmt = select(model.id).where(model.restaurant_id == restaurant_id, *filters)
    return set(session.scalars(stmt).all())


def _delete_stale_rows(
    session: Session,
    model: Any,
    *,
    restaurant_id: int,
    filters: list[Any],
    keep_ids: set[str],
) -> None:
    if not filters:
        return
    stmt = delete(model).where(model.restaurant_id == restaurant_id, *filters)
    if keep_ids:
        stmt = stmt.where(model.id.not_in(keep_ids))
    session.execute(stmt)


def _prune_stale_menu_scope(
    session: Session,
    *,
    restaurant_id: int,
    rows_by_table: dict[str, list[dict[str, Any]]],
) -> None:
    page_rows = rows_by_table["pages"]
    section_rows = rows_by_table["sections"]
    item_rows = rows_by_table["items"]
    price_rows = rows_by_table["price_points"]
    modifier_rows = rows_by_table["modifiers"]

    current_page_ids = {row["id"] for row in page_rows}
    current_section_ids = {row["id"] for row in section_rows}
    current_item_ids = {row["id"] for row in item_rows}
    current_price_ids = {row["id"] for row in price_rows}
    current_modifier_ids = {row["id"] for row in modifier_rows}

    source_bundles = {row.get("source_bundle") for row in page_rows if row.get("source_bundle")}
    if len(source_bundles) == 1:
        existing_page_ids = _select_scoped_ids(
            session,
            MenuPage,
            restaurant_id=restaurant_id,
            filters=[MenuPage.source_bundle == next(iter(source_bundles))],
        )
    else:
        existing_page_ids = set(current_page_ids)

    relevant_page_ids = existing_page_ids | current_page_ids
    if not relevant_page_ids:
        return

    existing_section_ids = _select_scoped_ids(
        session,
        MenuSection,
        restaurant_id=restaurant_id,
        filters=[MenuSection.page_id.in_(relevant_page_ids)],
    )
    relevant_section_ids = existing_section_ids | current_section_ids

    existing_item_ids = _select_scoped_ids(
        session,
        MenuItem,
        restaurant_id=restaurant_id,
        filters=[MenuItem.section_id.in_(relevant_section_ids)] if relevant_section_ids else [],
    )
    relevant_item_ids = existing_item_ids | current_item_ids

    modifier_filters: list[Any] = []
    if relevant_item_ids:
        modifier_filters.append(MenuModifier.item_id.in_(relevant_item_ids))
    if relevant_section_ids:
        modifier_filters.append(MenuModifier.section_id.in_(relevant_section_ids))
    if modifier_filters:
        _delete_stale_rows(
            session,
            MenuModifier,
            restaurant_id=restaurant_id,
            filters=[or_(*modifier_filters)],
            keep_ids=current_modifier_ids,
        )

    price_filters: list[Any] = []
    if relevant_item_ids:
        price_filters.append(MenuPricePoint.item_id.in_(relevant_item_ids))
    if relevant_section_ids:
        price_filters.append(MenuPricePoint.section_id.in_(relevant_section_ids))
    if price_filters:
        _delete_stale_rows(
            session,
            MenuPricePoint,
            restaurant_id=restaurant_id,
            filters=[or_(*price_filters)],
            keep_ids=current_price_ids,
        )

    if relevant_section_ids:
        _delete_stale_rows(
            session,
            MenuItem,
            restaurant_id=restaurant_id,
            filters=[MenuItem.section_id.in_(relevant_section_ids)],
            keep_ids=current_item_ids,
        )

    _delete_stale_rows(
        session,
        MenuSection,
        restaurant_id=restaurant_id,
        filters=[MenuSection.page_id.in_(relevant_page_ids)],
        keep_ids=current_section_ids,
    )

    if len(source_bundles) == 1:
        _delete_stale_rows(
            session,
            MenuPage,
            restaurant_id=restaurant_id,
            filters=[MenuPage.source_bundle == next(iter(source_bundles))],
            keep_ids=current_page_ids,
        )


def upsert_menu_shape(session: Session, shape: PersistentShape) -> UpsertResult:
    """Idempotent upsert from a PersistentShape into menu graph tables."""
    restaurant_id = _coerce_restaurant_id(shape.get("restaurant_id"))
    result = UpsertResult(restaurant_id=restaurant_id)

    if restaurant_id is None:
        result.skipped = True
        result.skip_reason = "missing_restaurant_id"
        return result

    fk_violations = check_foreign_keys(shape)
    if fk_violations:
        result.skipped = True
        result.skip_reason = "shape_fk_violations"
        result.fk_violations = fk_violations
        return result

    if session.get(LocalEmployer, restaurant_id) is None:
        result.skipped = True
        result.skip_reason = "missing_local_employer"
        return result

    rows_by_table = {
        "pages": _menu_pages(shape, restaurant_id),
        "sections": _menu_sections(shape, restaurant_id),
        "items": _menu_items(shape, restaurant_id),
        "price_points": _menu_price_points(shape, restaurant_id, result=result),
        "modifiers": _menu_modifiers(shape, restaurant_id),
    }

    with session.begin_nested():
        _prune_stale_menu_scope(
            session,
            restaurant_id=restaurant_id,
            rows_by_table=rows_by_table,
        )

        inserted, updated = _upsert_rows(
            session,
            MenuPage,
            rows_by_table["pages"],
            update_columns=("restaurant_id", "url", "source", "renderer", "source_bundle", "last_seen_at"),
        )
        result.record("pages", inserted=inserted, updated=updated)

        inserted, updated = _upsert_rows(
            session,
            MenuSection,
            rows_by_table["sections"],
            update_columns=(
                "page_id",
                "parent_section_id",
                "restaurant_id",
                "name",
                "path",
                "service_period",
                "course",
                "source",
                "last_seen_at",
            ),
        )
        result.record("sections", inserted=inserted, updated=updated)

        inserted, updated = _upsert_rows(
            session,
            MenuItem,
            rows_by_table["items"],
            update_columns=(
                "section_id",
                "restaurant_id",
                "name",
                "description",
                "course",
                "calories",
                "dietary_tags",
                "source",
                "last_seen_at",
            ),
        )
        result.record("items", inserted=inserted, updated=updated)

        inserted, updated = _upsert_rows(
            session,
            MenuPricePoint,
            rows_by_table["price_points"],
            update_columns=(
                "item_id",
                "section_id",
                "restaurant_id",
                "price",
                "currency",
                "variant",
                "confidence",
                "source",
                "evidence",
                "observed_at",
            ),
        )
        result.record("price_points", inserted=inserted, updated=updated)

        inserted, updated = _upsert_rows(
            session,
            MenuModifier,
            rows_by_table["modifiers"],
            update_columns=(
                "item_id",
                "section_id",
                "restaurant_id",
                "label",
                "price_delta",
                "required",
                "source",
                "last_seen_at",
            ),
        )
        result.record("modifiers", inserted=inserted, updated=updated)

    return result