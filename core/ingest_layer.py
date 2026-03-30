"""
backend/ingest_layer.py

Single write path for all LocalEmployer records.

Every data source — Overture GeoJSON, S3 DuckDB, BLS, Yelp, manual CSV —
calls ingest_employer() instead of writing to local_employers directly.

What it does per record:
  1. Normalize name via backend.normalizer (strip store numbers, join initials,
     strip legal suffixes, title-case)
  2. Compute fingerprint (stable sort-key for grouping name variants)
  3. Upsert brand_groups and increment location_count atomically
     - PostgreSQL: INSERT ... ON CONFLICT DO UPDATE (true atomic increment)
     - SQLite: query-then-update (acceptable for single-writer dev use)
  4. Dedup check for the LocalEmployer row:
     - Overture source: match on overture_id
     - Other sources:   match on fingerprint + lat/lng rounded to ~50 m (0.0005°)
  5. Write (insert or update) LocalEmployer with brand_group_id set

Design for scale:
  - brand_groups.location_count is never recalculated from scratch in normal
    operation. One indexed upsert per insert keeps it always current.
  - classify_local_employers.py remains available as a repair/recalculate
    utility when needed (e.g. after bulk imports outside this layer).

Called by:
  scrapers/overture_adapter.py  ingest_local_geojson()
  Any future scraper or API ingestion pipeline
"""

import logging
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from core.database import BrandGroup, LocalEmployer, get_engine, get_session, init_db
from core.normalizer import make_fingerprint, map_industry, normalize_name

# ── Mobility scoring constants ────────────────────────────────────────────────
# Source: OEWS Austin MSA May 2024, fast food median = $13.90/hr
_SERVICE_BASELINE   = 13.90
_MOBILITY_THRESHOLD = _SERVICE_BASELINE * 1.25   # $17.375/hr

# Lazy-loaded cache: industry_key → mobility_score (populated on first bulk ingest)
_INDUSTRY_MOBILITY: dict[str, float] = {}


def _calc_mobility_score(baseline_wage_hr: float | None) -> float:
    """Compute mobility_score (0.0-1.0) from an industry's median hourly wage.

    wage_lift:       how much median wage exceeds service baseline, capped at 100% lift
    Returns 0.0 if wage is at or below baseline (no upward mobility).
    """
    if not baseline_wage_hr:
        return 0.0
    lift = max(0.0, (baseline_wage_hr - _SERVICE_BASELINE) / _SERVICE_BASELINE)
    return round(min(lift, 1.0), 4)


def _load_mobility_cache(session: Session) -> None:
    """Load IndustryTaxonomy wage data into module-level cache (called once per process)."""
    global _INDUSTRY_MOBILITY
    if _INDUSTRY_MOBILITY:
        return
    try:
        from core.models.reference import IndustryTaxonomy
        rows = session.query(
            IndustryTaxonomy.industry_key,
            IndustryTaxonomy.baseline_wage_hr,
        ).all()
        _INDUSTRY_MOBILITY = {
            r.industry_key: _calc_mobility_score(r.baseline_wage_hr)
            for r in rows
        }
        logger.debug("[IngestLayer] Mobility cache loaded: %d industries", len(_INDUSTRY_MOBILITY))
    except Exception as exc:
        logger.warning("[IngestLayer] Could not load mobility cache: %s", exc)
        _INDUSTRY_MOBILITY = {}

logger = logging.getLogger(__name__)

# Lat/lng precision for non-Overture dedup: round to 0.0005° ≈ 50 m
_COORD_PRECISION = 4


def _is_postgres(session: Session) -> bool:
    return session.bind.dialect.name == "postgresql"  # type: ignore[union-attr]


def _upsert_brand_group(
    session: Session,
    fingerprint: str,
    canonical_name: str,
    industry: str | None,
) -> int:
    """Upsert brand_groups and return the group id.

    PostgreSQL: atomic INSERT ... ON CONFLICT DO UPDATE — one round-trip,
                no race conditions under concurrent ingestion.
    SQLite:     query-then-update — single-writer only, fine for local dev.
    """
    if _is_postgres(session):
        stmt = (
            pg_insert(BrandGroup)
            .values(
                fingerprint=fingerprint,
                canonical_name=canonical_name,
                location_count=1,
                industry=industry,
                updated_at=datetime.utcnow(),
            )
            .on_conflict_do_update(
                index_elements=["fingerprint"],
                set_={
                    "location_count": BrandGroup.location_count + 1,
                    "updated_at": datetime.utcnow(),
                },
            )
            .returning(BrandGroup.id)
        )
        result = session.execute(stmt)
        return result.scalar_one()
    else:
        # SQLite fallback
        bg = session.query(BrandGroup).filter_by(fingerprint=fingerprint).first()
        if bg:
            bg.location_count += 1
            bg.updated_at = datetime.utcnow()
        else:
            bg = BrandGroup(
                fingerprint=fingerprint,
                canonical_name=canonical_name,
                location_count=1,
                industry=industry,
                updated_at=datetime.utcnow(),
            )
            session.add(bg)
            session.flush()
        return bg.id


def _find_existing(
    session: Session,
    overture_id: str | None,
    source: str,
    fingerprint: str,
    lat: float | None,
    lng: float | None,
) -> LocalEmployer | None:
    """Find an existing LocalEmployer row to update instead of inserting."""
    if overture_id and source == "overture":
        return session.query(LocalEmployer).filter_by(overture_id=overture_id).first()

    # Non-Overture: dedup on fingerprint + rounded coordinates
    if fingerprint and lat is not None and lng is not None:
        rlat = round(lat, _COORD_PRECISION)
        rlng = round(lng, _COORD_PRECISION)
        candidates = (
            session.query(LocalEmployer)
            .filter_by(fingerprint=fingerprint)
            .all()
        )
        for c in candidates:
            if (
                c.lat is not None
                and c.lng is not None
                and round(c.lat, _COORD_PRECISION) == rlat
                and round(c.lng, _COORD_PRECISION) == rlng
            ):
                return c
    return None


def ingest_employer(record: dict[str, Any], source: str = "overture") -> LocalEmployer:
    """Normalize, dedup, and write one employer record to local_employers.

    Args:
        record: dict with keys:
            overture_id  str | None  — source's own identifier
            name         str         — raw name as ingested
            category     str | None  — Overture category string
            industry     str | None  — override (if already mapped)
            address      str | None
            lat          float | None
            lng          float | None
            region       str         — e.g. "austin_tx"
            confidence   float | None
            is_active    bool        — optional, default True
        source: str  — "overture" | "bls" | "yelp" | "manual" | …

    Returns:
        The LocalEmployer ORM object (committed to the session).
    """
    engine = init_db()
    session = get_session(engine)

    try:
        raw_name = (record.get("name") or "").strip()
        if not raw_name:
            logger.warning("[IngestLayer] Skipping record with empty name: %s", record)
            return None  # type: ignore[return-value]

        canonical = normalize_name(raw_name)
        fp = make_fingerprint(raw_name)
        industry = record.get("industry") or map_industry(record.get("category", ""))

        brand_group_id = _upsert_brand_group(session, fp, canonical, industry)

        existing = _find_existing(
            session,
            overture_id=record.get("overture_id"),
            source=source,
            fingerprint=fp,
            lat=record.get("lat"),
            lng=record.get("lng"),
        )

        now = datetime.utcnow()

        if existing:
            # Refresh mutable fields; preserve first_seen and internal id
            existing.name = canonical
            existing.fingerprint = fp
            existing.brand_group_id = brand_group_id
            existing.category = record.get("category") or existing.category
            existing.industry = industry or existing.industry
            existing.address = record.get("address") or existing.address
            existing.lat = record.get("lat") if record.get("lat") is not None else existing.lat
            existing.lng = record.get("lng") if record.get("lng") is not None else existing.lng
            existing.confidence = record.get("confidence") if record.get("confidence") is not None else existing.confidence
            existing.mobility_score = _INDUSTRY_MOBILITY.get(industry or "", existing.mobility_score)
            existing.is_active = record.get("is_active", True)
            existing.last_seen = now
            employer = existing
        else:
            employer = LocalEmployer(
                overture_id=record.get("overture_id"),
                source=source,
                raw_name=raw_name,
                name=canonical,
                fingerprint=fp,
                brand_group_id=brand_group_id,
                location_count=None,   # populated from brand_groups at query time
                category=record.get("category"),
                industry=industry,
                address=record.get("address") or "",
                lat=record.get("lat"),
                lng=record.get("lng"),
                region=record.get("region", "austin_tx"),
                source_discovery=source,
                confidence=record.get("confidence"),
                mobility_score=_INDUSTRY_MOBILITY.get(industry or ""),
                is_active=record.get("is_active", True),
                first_seen=now,
                last_seen=now,
            )
            session.add(employer)

        session.commit()
        session.refresh(employer)
        return employer

    except Exception as exc:
        session.rollback()
        logger.error("[IngestLayer] Failed to ingest employer %r: %s", record.get("name"), exc)
        raise
    finally:
        session.close()


def ingest_employers_bulk(
    records: list[dict[str, Any]],
    source: str = "overture",
    commit_every: int = 500,
) -> dict[str, int]:
    """Ingest a list of employer records efficiently.

    Opens one session for the whole batch. Commits every commit_every records
    to limit memory and enable progress recovery on failure.

    Returns:
        {"inserted": N, "updated": N, "skipped": N}
    """
    engine = init_db()
    session = get_session(engine)
    _load_mobility_cache(session)

    inserted = updated = skipped = 0

    try:
        for i, record in enumerate(records):
            raw_name = (record.get("name") or "").strip()
            if not raw_name:
                skipped += 1
                continue

            canonical = normalize_name(raw_name)
            fp = make_fingerprint(raw_name)
            industry = record.get("industry") or map_industry(record.get("category", ""))

            brand_group_id = _upsert_brand_group(session, fp, canonical, industry)

            existing = _find_existing(
                session,
                overture_id=record.get("overture_id"),
                source=source,
                fingerprint=fp,
                lat=record.get("lat"),
                lng=record.get("lng"),
            )

            now = datetime.utcnow()

            if existing:
                existing.name = canonical
                existing.fingerprint = fp
                existing.brand_group_id = brand_group_id
                existing.category = record.get("category") or existing.category
                existing.industry = industry or existing.industry
                existing.address = record.get("address") or existing.address
                existing.lat = record.get("lat") if record.get("lat") is not None else existing.lat
                existing.lng = record.get("lng") if record.get("lng") is not None else existing.lng
                existing.confidence = record.get("confidence") if record.get("confidence") is not None else existing.confidence
                existing.mobility_score = _INDUSTRY_MOBILITY.get(industry or "", existing.mobility_score)
                existing.is_active = record.get("is_active", True)
                existing.last_seen = now
                updated += 1
            else:
                session.add(LocalEmployer(
                    overture_id=record.get("overture_id"),
                    source=source,
                    raw_name=raw_name,
                    name=canonical,
                    fingerprint=fp,
                    brand_group_id=brand_group_id,
                    location_count=None,
                    category=record.get("category"),
                    industry=industry,
                    address=record.get("address") or "",
                    lat=record.get("lat"),
                    lng=record.get("lng"),
                    region=record.get("region", "austin_tx"),
                    source_discovery=source,
                    confidence=record.get("confidence"),
                    mobility_score=_INDUSTRY_MOBILITY.get(industry or ""),
                    is_active=record.get("is_active", True),
                    first_seen=now,
                    last_seen=now,
                ))
                inserted += 1

            if (i + 1) % commit_every == 0:
                session.commit()
                logger.info(
                    "[IngestLayer] Committed %d/%d records (ins=%d upd=%d skip=%d)",
                    i + 1, len(records), inserted, updated, skipped,
                )

        session.commit()

        # Sync location_count from brand_groups → local_employers so the server
        # can classify brand vs. local without a join on every read.
        if _is_postgres(session):
            session.execute(text(
                "UPDATE local_employers le "
                "SET location_count = bg.location_count "
                "FROM brand_groups bg "
                "WHERE le.brand_group_id = bg.id"
            ))
        else:
            session.execute(text(
                "UPDATE local_employers "
                "SET location_count = ("
                "  SELECT location_count FROM brand_groups "
                "  WHERE brand_groups.id = local_employers.brand_group_id"
                ") WHERE brand_group_id IS NOT NULL"
            ))
        session.commit()

        logger.info(
            "[IngestLayer] Bulk ingest complete: inserted=%d updated=%d skipped=%d",
            inserted, updated, skipped,
        )
        return {"inserted": inserted, "updated": updated, "skipped": skipped}

    except Exception as exc:
        session.rollback()
        logger.error("[IngestLayer] Bulk ingest failed at record %d: %s", i, exc)
        raise
    finally:
        session.close()
