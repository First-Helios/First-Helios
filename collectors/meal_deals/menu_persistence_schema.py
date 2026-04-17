"""
collectors/meal_deals/menu_persistence_schema.py — ARCH-01 target shape.

Defines the *target* persistent shape for the menu graph without actually
committing to DB tables yet. Per the roadmap recommendation for ARCH-01:
stay sidecar-first until replay coverage grows, but lock in the column
names, foreign keys, and provenance fields now so the sidecar stays
forward-compatible with a future schema.

Design rules:
  * Every table carries a deterministic `id` that equals the sidecar key
    (`p_...`, `s_...`, `i_...`, `pp_...`, `mod_...`, `ot_...`). This lets
    future upserts be idempotent from replay bundles.
  * Every table is scoped by `restaurant_id` + `source_url` so rows can
    join local_employers and survive re-scrapes.
  * Every table carries `first_seen_at` / `last_seen_at` (or `observed_at`
    for price evidence) provenance so freshness and trust can be measured
    without a separate lineage table.
  * Nothing here imports SQLAlchemy — this module stays pure so it can be
    consumed from debug bundles, tests, or a future migration script.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal, TypedDict

from collectors.meal_deals.menu_sidecar import MenuSidecar

_ISO = "%Y-%m-%dT%H:%M:%S%z"


# ── Target row shapes ───────────────────────────────────────────────────────


class MenuPageRow(TypedDict):
    id: str
    restaurant_id: str | None
    url: str
    source: str  # "jsonld" | "dom" | "pdf_table"
    renderer: str
    first_seen_at: str
    last_seen_at: str
    source_bundle: str | None


class MenuSectionRow(TypedDict):
    id: str
    page_id: str
    parent_section_id: str | None
    restaurant_id: str | None
    name: str
    path: list[str]
    service_period: str | None
    course: str | None
    source: str
    first_seen_at: str
    last_seen_at: str


class MenuItemRow(TypedDict):
    id: str
    section_id: str
    restaurant_id: str | None
    name: str
    description: str | None
    course: str | None
    calories: int | None
    dietary_tags: list[str]
    source: str
    first_seen_at: str
    last_seen_at: str


class MenuPricePointRow(TypedDict):
    id: str
    item_id: str | None
    section_id: str | None
    restaurant_id: str | None
    price: float
    currency: str | None
    variant: str | None
    confidence: float
    source: str
    evidence: str | None
    observed_at: str


class MenuModifierRow(TypedDict):
    id: str
    item_id: str | None
    section_id: str | None
    restaurant_id: str | None
    label: str
    price_delta: float | None
    required: bool
    source: str
    first_seen_at: str
    last_seen_at: str


class MenuOfferTargetRow(TypedDict):
    id: str
    scope: Literal["item", "section", "service_period", "venue"]
    section_id: str | None
    item_id: str | None
    service_period: str | None
    signal_ref: str | None
    restaurant_id: str | None
    confidence: float | None
    disposition: Literal["auto_accept", "review", "discard"] | None
    created_at: str


class PersistentShape(TypedDict):
    schema_version: str
    restaurant_id: str | None
    source_url: str | None
    source_bundle: str | None
    observed_at: str
    pages: list[MenuPageRow]
    sections: list[MenuSectionRow]
    items: list[MenuItemRow]
    price_points: list[MenuPricePointRow]
    modifiers: list[MenuModifierRow]
    offer_targets: list[MenuOfferTargetRow]


SCHEMA_VERSION = "menu_graph.v1"


# ── Serializer ──────────────────────────────────────────────────────────────


def serialize_sidecar(
    sidecar: MenuSidecar,
    *,
    restaurant_id: str | None = None,
    source_url: str | None = None,
    source_bundle: str | None = None,
    observed_at: datetime | None = None,
) -> PersistentShape:
    """Flatten a MenuSidecar into the target persistent row shape.

    Does not write anywhere — callers decide whether to persist, pickle,
    or diff this against a prior snapshot. Deterministic given the same
    sidecar + timestamp, so replay snapshots remain stable.
    """
    ts = (observed_at or datetime.now(timezone.utc)).astimezone(timezone.utc).strftime(_ISO)

    pages: list[MenuPageRow] = []
    for p in sidecar.pages.values():
        pages.append(MenuPageRow(
            id=p.key,
            restaurant_id=restaurant_id,
            url=p.url,
            source=p.source,
            renderer=p.renderer,
            first_seen_at=ts,
            last_seen_at=ts,
            source_bundle=source_bundle,
        ))

    sections: list[MenuSectionRow] = []
    for s in sidecar.sections.values():
        sections.append(MenuSectionRow(
            id=s.key,
            page_id=s.page_key,
            parent_section_id=s.parent_key,
            restaurant_id=restaurant_id,
            name=s.name,
            path=list(s.path),
            service_period=s.service_period,
            course=s.course,
            source=s.source,
            first_seen_at=ts,
            last_seen_at=ts,
        ))

    items: list[MenuItemRow] = []
    for i in sidecar.items.values():
        items.append(MenuItemRow(
            id=i.key,
            section_id=i.section_key,
            restaurant_id=restaurant_id,
            name=i.name,
            description=i.description,
            course=i.course,
            calories=i.calories,
            dietary_tags=list(i.dietary_tags),
            source=i.source,
            first_seen_at=ts,
            last_seen_at=ts,
        ))

    price_points: list[MenuPricePointRow] = []
    for pp in sidecar.price_points.values():
        price_points.append(MenuPricePointRow(
            id=pp.key,
            item_id=pp.item_key,
            section_id=pp.section_key,
            restaurant_id=restaurant_id,
            price=pp.price,
            currency=pp.currency,
            variant=pp.variant,
            confidence=pp.confidence,
            source=pp.source,
            evidence=pp.evidence,
            observed_at=ts,
        ))

    modifiers: list[MenuModifierRow] = []
    for m in sidecar.modifiers.values():
        modifiers.append(MenuModifierRow(
            id=m.key,
            item_id=m.item_key,
            section_id=m.section_key,
            restaurant_id=restaurant_id,
            label=m.label,
            price_delta=m.price_delta,
            required=m.required,
            source=m.source,
            first_seen_at=ts,
            last_seen_at=ts,
        ))

    offer_targets: list[MenuOfferTargetRow] = []
    for t in sidecar.offer_targets.values():
        confidence = getattr(t, "confidence", None)
        disposition = getattr(t, "disposition", None)
        offer_targets.append(MenuOfferTargetRow(
            id=t.key,
            scope=t.scope,  # type: ignore[typeddict-item]
            section_id=t.section_key,
            item_id=t.item_key,
            service_period=t.service_period,
            signal_ref=t.signal_ref,
            restaurant_id=restaurant_id,
            confidence=confidence,
            disposition=disposition,
            created_at=ts,
        ))

    return PersistentShape(
        schema_version=SCHEMA_VERSION,
        restaurant_id=restaurant_id,
        source_url=source_url,
        source_bundle=source_bundle,
        observed_at=ts,
        pages=pages,
        sections=sections,
        items=items,
        price_points=price_points,
        modifiers=modifiers,
        offer_targets=offer_targets,
    )


# ── Compatibility / drift checks ────────────────────────────────────────────


def check_foreign_keys(shape: PersistentShape) -> list[str]:
    """Return a list of FK violations in the flattened shape.

    Run after `serialize_sidecar` to verify the sidecar is self-consistent
    before it ever touches a database.
    """
    violations: list[str] = []
    page_ids = {p["id"] for p in shape["pages"]}
    section_ids = {s["id"] for s in shape["sections"]}
    item_ids = {i["id"] for i in shape["items"]}

    for s in shape["sections"]:
        if s["page_id"] not in page_ids:
            violations.append(f"section {s['id']} references missing page {s['page_id']}")
        if s["parent_section_id"] and s["parent_section_id"] not in section_ids:
            violations.append(
                f"section {s['id']} references missing parent {s['parent_section_id']}"
            )
    for i in shape["items"]:
        if i["section_id"] not in section_ids:
            violations.append(f"item {i['id']} references missing section {i['section_id']}")
    for pp in shape["price_points"]:
        if pp["item_id"] and pp["item_id"] not in item_ids:
            violations.append(f"price_point {pp['id']} references missing item {pp['item_id']}")
        if pp["section_id"] and pp["section_id"] not in section_ids:
            violations.append(f"price_point {pp['id']} references missing section {pp['section_id']}")
    for m in shape["modifiers"]:
        if m["item_id"] and m["item_id"] not in item_ids:
            violations.append(f"modifier {m['id']} references missing item {m['item_id']}")
        if m["section_id"] and m["section_id"] not in section_ids:
            violations.append(f"modifier {m['id']} references missing section {m['section_id']}")
    for t in shape["offer_targets"]:
        if t["scope"] == "item":
            if not t["item_id"] or t["item_id"] not in item_ids:
                violations.append(f"offer_target {t['id']} scope=item lacks valid item_id")
            if not t["section_id"] or t["section_id"] not in section_ids:
                violations.append(f"offer_target {t['id']} scope=item lacks valid section_id")
        elif t["scope"] == "section":
            if not t["section_id"] or t["section_id"] not in section_ids:
                violations.append(f"offer_target {t['id']} scope=section lacks valid section_id")
    return violations


def summarize_shape(shape: PersistentShape) -> dict[str, Any]:
    """One-liner sanity summary useful for replay bundle inspection."""
    return {
        "schema_version": shape["schema_version"],
        "restaurant_id": shape["restaurant_id"],
        "source_url": shape["source_url"],
        "counts": {
            "pages": len(shape["pages"]),
            "sections": len(shape["sections"]),
            "items": len(shape["items"]),
            "price_points": len(shape["price_points"]),
            "modifiers": len(shape["modifiers"]),
            "offer_targets": len(shape["offer_targets"]),
        },
        "fk_violations": check_foreign_keys(shape),
    }
