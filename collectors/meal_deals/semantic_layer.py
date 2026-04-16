"""Shared semantic layer for consumer-facing meal-deal rows.

This module builds `deal_materializations`, the compatibility layer that the
API reads instead of performing route-level dedupe over raw `meal_deals`.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from core.database import (
    CanonicalVenue,
    CanonicalVenueAlias,
    DealApplicability,
    DealMaterialization,
    DealObservation,
    LocalEmployer,
)


def _alias_rank(alias: CanonicalVenueAlias) -> tuple:
    return (
        1 if alias.alias_role == "primary" else 0,
        alias.match_confidence or 0.0,
        alias.id or 0,
    )


def _applicability_rank(applicability: DealApplicability) -> tuple:
    return (
        1 if applicability.applicability_scope == "venue" else 0,
        applicability.confidence or 0.0,
        applicability.id or 0,
    )


def _load_venue_context(
    session: Session,
    applicability_rows: list[DealApplicability],
    *,
    region: str | None,
) -> tuple[
    dict[int, DealObservation],
    dict[int, CanonicalVenue],
    dict[int, list[CanonicalVenue]],
    dict[int, LocalEmployer],
]:
    observation_ids = {row.observation_id for row in applicability_rows}
    observations = {
        row.id: row
        for row in session.query(DealObservation).filter(
            DealObservation.id.in_(observation_ids)
        ).all()
    }

    direct_venue_ids = {
        row.canonical_venue_id
        for row in applicability_rows
        if row.canonical_venue_id is not None
    }
    brand_group_ids = {
        row.brand_group_id
        for row in applicability_rows
        if row.applicability_scope == "brand" and row.brand_group_id is not None
    }

    venue_query = session.query(CanonicalVenue).filter(CanonicalVenue.is_active.is_(True))
    if direct_venue_ids or brand_group_ids:
        venue_query = venue_query.filter(
            (CanonicalVenue.id.in_(direct_venue_ids))
            | (CanonicalVenue.brand_group_id.in_(brand_group_ids))
        )
    if region:
        venue_query = venue_query.filter(CanonicalVenue.region == region)

    venues = venue_query.all()
    venues_by_id = {venue.id: venue for venue in venues}

    venues_by_brand: dict[int, list[CanonicalVenue]] = defaultdict(list)
    for venue in venues:
        if venue.brand_group_id is not None:
            venues_by_brand[venue.brand_group_id].append(venue)

    alias_rows = session.query(CanonicalVenueAlias).filter(
        CanonicalVenueAlias.canonical_venue_id.in_(venues_by_id.keys())
    ).all() if venues_by_id else []

    best_alias_by_venue: dict[int, CanonicalVenueAlias] = {}
    for alias in alias_rows:
        current = best_alias_by_venue.get(alias.canonical_venue_id)
        if current is None or _alias_rank(alias) > _alias_rank(current):
            best_alias_by_venue[alias.canonical_venue_id] = alias

    employer_ids = {
        alias.local_employer_id
        for alias in best_alias_by_venue.values()
        if alias.local_employer_id is not None
    }
    employers = {
        row.id: row
        for row in session.query(LocalEmployer).filter(LocalEmployer.id.in_(employer_ids)).all()
    } if employer_ids else {}

    primary_employers_by_venue = {
        venue_id: employers.get(alias.local_employer_id)
        for venue_id, alias in best_alias_by_venue.items()
    }

    return observations, venues_by_id, venues_by_brand, primary_employers_by_venue


def _materialization_payload(
    observation: DealObservation,
    applicability: DealApplicability,
    venue: CanonicalVenue,
    employer: LocalEmployer | None,
) -> dict:
    extraction_payload = observation.extraction_payload or {}
    return {
        "observation_id": observation.id,
        "applicability_id": applicability.id,
        "canonical_venue_id": venue.id,
        "local_employer_id": employer.id if employer else None,
        "brand_group_id": venue.brand_group_id or applicability.brand_group_id,
        "restaurant_name": employer.name if employer and employer.name else venue.canonical_name,
        "address": employer.address if employer and employer.address else venue.address,
        "lat": venue.lat if venue.lat is not None else (employer.lat if employer else None),
        "lng": venue.lng if venue.lng is not None else (employer.lng if employer else None),
        "region": venue.region or (employer.region if employer else None) or extraction_payload.get("region") or "austin_tx",
        "applicability_scope": applicability.applicability_scope,
        "is_chain_template": applicability.applicability_scope == "brand",
        "deal_name": observation.deal_name,
        "deal_description": observation.deal_description,
        "deal_type": observation.deal_type,
        "price": observation.price,
        "price_type": observation.price_type,
        "discount_percentage": observation.discount_percentage,
        "original_price": observation.original_price,
        "menu_avg_price": observation.menu_avg_price,
        "calories": observation.calories,
        "calorie_price_ratio": observation.calorie_price_ratio,
        "valid_days": observation.valid_days,
        "valid_start_time": observation.valid_start_time,
        "valid_end_time": observation.valid_end_time,
        "is_recurring": observation.is_recurring,
        "start_date": observation.start_date,
        "end_date": observation.end_date,
        "source": observation.source,
        "source_url": observation.source_url,
        "source_observation_key": observation.source_observation_key,
        "verified_at": observation.observed_at,
        "raw_scraped_text": observation.raw_scraped_text,
        "signal_quality": observation.signal_quality,
        "deal_value_score": observation.deal_value_score,
        "sub_deals": extraction_payload.get("sub_deals_hint"),
        "confidence": applicability.confidence,
        "resolver_method": applicability.resolver_method,
        "review_state": observation.review_state,
        "is_active": observation.review_state == "accepted" and applicability.is_active,
    }


def _build_materialization_payloads(
    session: Session,
    applicability_rows: list[DealApplicability],
    *,
    region: str | None,
) -> list[dict]:
    if not applicability_rows:
        return []

    observations, venues_by_id, venues_by_brand, employers_by_venue = _load_venue_context(
        session,
        applicability_rows,
        region=region,
    )

    payloads_by_key: dict[tuple[int, int], tuple[tuple, dict]] = {}
    for applicability in applicability_rows:
        observation = observations.get(applicability.observation_id)
        if observation is None or observation.review_state == "rejected":
            continue

        if applicability.applicability_scope == "venue":
            targets = [venues_by_id[applicability.canonical_venue_id]] if applicability.canonical_venue_id in venues_by_id else []
        elif applicability.applicability_scope == "brand" and applicability.brand_group_id is not None:
            targets = venues_by_brand.get(applicability.brand_group_id, [])
        else:
            targets = []

        for venue in targets:
            key = (observation.id, venue.id)
            rank = _applicability_rank(applicability)
            payload = _materialization_payload(
                observation,
                applicability,
                venue,
                employers_by_venue.get(venue.id),
            )
            current = payloads_by_key.get(key)
            if current is None or rank > current[0]:
                payloads_by_key[key] = (rank, payload)

    return [item[1] for item in payloads_by_key.values()]


def refresh_deal_materializations(
    session: Session,
    *,
    observation_ids: list[int] | None = None,
    region: str | None = None,
) -> dict[str, int]:
    """Rebuild the shared consumer-facing deal row set.

    When `observation_ids` is provided, only those observation rows are rebuilt.
    Otherwise the entire table, or one region's rows, is refreshed.
    """

    deleted = 0
    if observation_ids is not None:
        scoped_ids = sorted({int(observation_id) for observation_id in observation_ids if observation_id is not None})
        if not scoped_ids:
            return {"deleted": 0, "inserted": 0}

        deleted = session.query(DealMaterialization).filter(
            DealMaterialization.observation_id.in_(scoped_ids)
        ).delete(synchronize_session=False)
        applicability_rows = session.query(DealApplicability).filter(
            DealApplicability.observation_id.in_(scoped_ids),
            DealApplicability.is_active.is_(True),
        ).all()
    else:
        delete_query = session.query(DealMaterialization)
        if region:
            delete_query = delete_query.filter(DealMaterialization.region == region)
        deleted = delete_query.delete(synchronize_session=False)

        applicability_rows = session.query(DealApplicability).filter(
            DealApplicability.is_active.is_(True)
        ).all()

    payloads = _build_materialization_payloads(
        session,
        applicability_rows,
        region=region,
    )
    now = datetime.now(timezone.utc)
    for payload in payloads:
        payload["created_at"] = now
        payload["updated_at"] = now

    if payloads:
        session.add_all(DealMaterialization(**payload) for payload in payloads)
        session.flush()

    return {
        "deleted": deleted,
        "inserted": len(payloads),
    }