"""
storage/ingest_poi.py — Single-point-of-write for POI data.

Takes a list of POIRecord from any collector and upserts into
stores (chain POIs) or local_employers (non-chain POIs).

Deduplication:
  - Chain POIs: keyed by stable_id → store_num
  - Local POIs: keyed by source + source_id → overture_id
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from backend.database import LocalEmployer, Store, get_session, init_db
from backend.dedup import find_existing_match
from collectors.schema import POIRecord

logger = logging.getLogger(__name__)

# Default industry for POIs without explicit mapping
_DEFAULT_INDUSTRY = "other"


def ingest_pois(
    records: list[POIRecord],
    region: str,
    industry_map: Optional[dict[str, str]] = None,
) -> dict:
    """Ingest POI records into stores / local_employers tables.

    Args:
        records: List of POIRecord from any collector.
        region: Region key, e.g. 'austin_tx'.
        industry_map: Optional mapping of category → internal industry key.

    Returns:
        {"inserted": int, "updated": int, "skipped": int, "table": str}
    """
    if not records:
        return {"inserted": 0, "updated": 0, "skipped": 0, "table": "none"}

    chain_records = [r for r in records if r.is_chain]
    local_records = [r for r in records if not r.is_chain]

    result = {"inserted": 0, "updated": 0, "skipped": 0, "table": ""}

    if chain_records:
        chain_result = _ingest_chain_pois(chain_records, region, industry_map)
        result["inserted"] += chain_result["inserted"]
        result["updated"] += chain_result["updated"]
        result["skipped"] += chain_result["skipped"]
        result["table"] = "stores"

    if local_records:
        local_result = _ingest_local_pois(local_records, region, industry_map)
        result["inserted"] += local_result["inserted"]
        result["updated"] += local_result["updated"]
        result["skipped"] += local_result["skipped"]
        if result["table"]:
            result["table"] += "+local_employers"
        else:
            result["table"] = "local_employers"

    return result


def _ingest_chain_pois(
    records: list[POIRecord],
    region: str,
    industry_map: Optional[dict[str, str]] = None,
) -> dict:
    """Upsert chain POI records into the stores table."""
    engine = init_db()
    session = get_session(engine)
    inserted = 0
    updated = 0
    skipped = 0

    try:
        for rec in records:
            store_num = rec.stable_id
            industry = _resolve_industry(rec, industry_map)

            # ── Dedup gate: check for spatial match first ────────
            existing = session.query(Store).filter_by(store_num=store_num).first()
            if not existing and rec.brand and rec.lat and rec.lng:
                existing = find_existing_match(
                    session, rec.brand, rec.lat, rec.lng, name=rec.name,
                )
                if existing:
                    store_num = existing.store_num  # redirect to canonical

            if existing:
                # Update if new data is more complete
                changed = False
                if rec.lat and rec.lng and (not existing.lat or not existing.lng):
                    existing.lat = rec.lat
                    existing.lng = rec.lng
                    changed = True
                if rec.address and (not existing.address or existing.address == ""):
                    existing.address = rec.address
                    changed = True
                if rec.name and (not existing.store_name or existing.store_name == ""):
                    existing.store_name = rec.name
                    changed = True
                existing.last_seen = datetime.utcnow()
                existing.is_active = True
                if changed:
                    updated += 1
                else:
                    skipped += 1
            else:
                session.add(Store(
                    store_num=store_num,
                    chain=rec.brand or "unknown",
                    industry=industry,
                    store_name=rec.name,
                    address=rec.address or "",
                    lat=rec.lat,
                    lng=rec.lng,
                    region=region,
                    first_seen=datetime.utcnow(),
                    last_seen=datetime.utcnow(),
                    is_active=True,
                ))
                inserted += 1

        session.commit()
        logger.info(
            "[IngestPOI] Chain: inserted=%d updated=%d skipped=%d",
            inserted, updated, skipped,
        )
    except Exception as e:
        session.rollback()
        logger.error("[IngestPOI] Chain ingest failed: %s", e)
    finally:
        session.close()

    return {"inserted": inserted, "updated": updated, "skipped": skipped}


def _ingest_local_pois(
    records: list[POIRecord],
    region: str,
    industry_map: Optional[dict[str, str]] = None,
) -> dict:
    """Upsert local employer POI records into the local_employers table."""
    engine = init_db()
    session = get_session(engine)
    inserted = 0
    updated = 0
    skipped = 0

    try:
        for rec in records:
            overture_id = f"{rec.source}-{rec.source_id}"
            industry = _resolve_industry(rec, industry_map)

            existing = session.query(LocalEmployer).filter_by(
                overture_id=overture_id
            ).first()

            if existing:
                changed = False
                if rec.lat and rec.lng and (not existing.lat or not existing.lng):
                    existing.lat = rec.lat
                    existing.lng = rec.lng
                    changed = True
                if rec.address and (not existing.address or existing.address == ""):
                    existing.address = rec.address
                    changed = True
                existing.last_seen = datetime.utcnow()
                existing.is_active = True
                if changed:
                    updated += 1
                else:
                    skipped += 1
            else:
                session.add(LocalEmployer(
                    overture_id=overture_id,
                    name=rec.name,
                    category=rec.category,
                    industry=industry,
                    address=rec.address or "",
                    lat=rec.lat,
                    lng=rec.lng,
                    region=region,
                    confidence=rec.confidence,
                    is_active=True,
                    first_seen=datetime.utcnow(),
                    last_seen=datetime.utcnow(),
                ))
                inserted += 1

        session.commit()
        logger.info(
            "[IngestPOI] Local: inserted=%d updated=%d skipped=%d",
            inserted, updated, skipped,
        )
    except Exception as e:
        session.rollback()
        logger.error("[IngestPOI] Local ingest failed: %s", e)
    finally:
        session.close()

    return {"inserted": inserted, "updated": updated, "skipped": skipped}


def _resolve_industry(
    rec: POIRecord,
    industry_map: Optional[dict[str, str]] = None,
) -> str:
    """Resolve industry from record fields and optional mapping."""
    if rec.industry:
        return rec.industry
    if industry_map and rec.category:
        mapped = industry_map.get(rec.category.lower())
        if mapped:
            return mapped
    return _DEFAULT_INDUSTRY
