"""
Signal ingestion pipeline for ChainStaffingTracker.

Receives list[ScraperSignal] from any scraper, upserts Store records,
writes Signal rows, and optionally creates wage_index entries.

No scraper writes directly to the database — all DB writes go through here.

Depends on: backend.database, scrapers.base
Called by: scrapers (via CLI), backend/scheduler.py, server.py /api/scan
"""

import json
import logging
from datetime import datetime

from backend.database import (
    Score,
    Signal,
    Snapshot,
    Store,
    WageIndex,
    get_engine,
    get_session,
    init_db,
)
from config.loader import get_chain
from scrapers.base import ScraperSignal

logger = logging.getLogger(__name__)


def ingest_signals(
    signals: list[ScraperSignal],
    region: str,
    chain: str | None = None,
    source: str | None = None,
) -> int:
    """Write a batch of ScraperSignals to tracker.db.

    1. Upsert Store records (update last_seen if exists).
    2. Insert Signal rows.
    3. Insert WageIndex rows for wage-type signals.
    4. Create a Snapshot summary row.

    Args:
        signals: List of normalized ScraperSignal objects.
        region: Region key, e.g. 'austin_tx'.
        chain: Chain key, e.g. 'starbucks'. Inferred from signals if None.
        source: Source name, e.g. 'careers_api'. Inferred from signals if None.

    Returns:
        Number of signals ingested.
    """
    if not signals:
        logger.info("[Ingest] No signals to ingest for region=%s", region)
        return 0

    engine = init_db()
    session = get_session(engine)

    inferred_chain = chain or (signals[0].chain if signals else "unknown")
    inferred_source = source or (signals[0].source if signals else "unknown")

    try:
        ingested = 0
        store_nums_seen: set[str] = set()

        for sig in signals:
            # ── Upsert Store ─────────────────────────────────────────
            if sig.store_num not in store_nums_seen:
                store_nums_seen.add(sig.store_num)
                existing = session.query(Store).filter_by(
                    store_num=sig.store_num
                ).first()

                if existing:
                    existing.last_seen = datetime.utcnow()
                    existing.is_active = True
                else:
                    # Try to get industry from chain config
                    industry = "unknown"
                    try:
                        chain_cfg = get_chain(sig.chain)
                        industry = chain_cfg.get("industry", "unknown")
                    except (KeyError, TypeError):
                        pass

                    store = Store(
                        store_num=sig.store_num,
                        chain=sig.chain,
                        industry=industry,
                        store_name=sig.metadata.get("store_name", ""),
                        address=sig.metadata.get("address", ""),
                        lat=sig.metadata.get("lat"),
                        lng=sig.metadata.get("lng"),
                        region=region,
                        first_seen=datetime.utcnow(),
                        last_seen=datetime.utcnow(),
                        is_active=True,
                    )
                    # Auto-geocode if no coordinates provided
                    if store.lat is None and store.address:
                        try:
                            from scrapers.geocoding import geocode
                            store.lat, store.lng = geocode(store.address)
                        except Exception as e:
                            logger.warning(
                                "[Ingest] Geocoding failed for %s: %s",
                                store.store_num, e,
                            )
                    session.add(store)

            # ── Insert Signal ────────────────────────────────────────
            signal_row = Signal(
                store_num=sig.store_num,
                source=sig.source,
                signal_type=sig.signal_type,
                value=sig.value,
                observed_at=sig.observed_at,
                created_at=datetime.utcnow(),
            )
            signal_row.set_metadata(sig.metadata)
            session.add(signal_row)

            # ── Insert WageIndex for wage signals ────────────────────
            if sig.signal_type == "wage" and (sig.wage_min or sig.wage_max):
                wage_row = WageIndex(
                    employer=sig.metadata.get("employer", sig.chain),
                    is_chain=sig.metadata.get("is_chain", True),
                    chain_key=sig.chain if sig.metadata.get("is_chain", True) else None,
                    industry=sig.metadata.get("industry", "unknown"),
                    role_title=sig.role_title or "unknown",
                    wage_min=sig.wage_min,
                    wage_max=sig.wage_max,
                    wage_period=sig.wage_period or "hourly",
                    location=sig.metadata.get("location", region),
                    zip_code=sig.metadata.get("zip_code"),
                    source=sig.source,
                    observed_at=sig.observed_at,
                    source_url=sig.source_url,
                )
                session.add(wage_row)

            ingested += 1

        # ── Create Snapshot ──────────────────────────────────────────
        snapshot = Snapshot(
            region=region,
            chain=inferred_chain,
            source=inferred_source,
            scanned_at=datetime.utcnow(),
            store_count=len(store_nums_seen),
            signal_count=ingested,
        )
        snapshot.set_summary({
            "total_signals": ingested,
            "unique_stores": len(store_nums_seen),
            "signal_types": list({s.signal_type for s in signals}),
        })
        session.add(snapshot)

        session.commit()
        logger.info(
            "[Ingest] Ingested %d signals for %d stores (region=%s, chain=%s, source=%s)",
            ingested,
            len(store_nums_seen),
            region,
            inferred_chain,
            inferred_source,
        )
        return ingested

    except Exception as e:
        session.rollback()
        logger.error("[Ingest] Failed to ingest signals: %s", e)
        return 0
    finally:
        session.close()
