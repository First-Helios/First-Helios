"""
backend/dedup.py — Store deduplication engine.

Problem: Multiple scrapers (AllThePlaces, Overture, OSM) assign different
store_num keys to the same physical location.  A Starbucks at 600 Congress
Ave may appear as ATP-ST-12345, OV-ST-61c7070e, and OSM-ST-338450997.

Strategy:
  1. SPATIAL MATCH — stores within ~40 m (half a city block) with the same
     normalised chain name are assumed to be the same physical store.
  2. SOURCE REPUTATION — when merging, the address/coords from the most
     reputable source win.  Order: AllThePlaces > Overture > OSM > Careers API.
  3. CANONICAL STORE — one store_num is kept as the "canonical" record.
     Others become aliases; their signals are reassigned to the canonical.
  4. ON-INGEST GATE — before inserting a new store, check for a spatial
     match first.  If found, update the existing record instead.

Tables touched:
  - stores       — merged duplicates are soft-deleted (is_active=False)
  - signals      — store_num updated to canonical
  - scores       — store_num updated to canonical
  - store_aliases — NEW lookup table mapping old → canonical store_num

Depends on: backend.database
Called by: backend/ingest.py (on-ingest), server.py (bulk cleanup API)
"""

from __future__ import annotations

import logging
import math
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import text

from backend.database import (
    Base,
    Column,
    DateTime,
    Float,
    Integer,
    Score,
    Signal,
    Store,
    String,
    get_session,
    init_db,
)

logger = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════════════
# Constants
# ══════════════════════════════════════════════════════════════════════

# Half a city block ≈ 40 meters ≈ 0.00036° latitude at 30°N.
# We use a slightly generous threshold to catch GPS jitter between sources.
DEDUP_RADIUS_DEG = 0.00040   # ~44 m at Austin's latitude

# Source reputation order — lower index = more trusted for address data.
# When two stores merge, the one from the higher-ranked source keeps its
# address and coordinates.
SOURCE_REPUTATION = {
    "ATP": 0,       # AllThePlaces — curated per-chain spiders
    "SB":  1,       # Careers API — employer's own data
    "OV":  2,       # Overture Maps — large-scale ML extraction
    "OSM": 3,       # OpenStreetMap — community-edited
    "LOCAL": 4,     # Overture local employers
}

DEFAULT_REPUTATION = 99


# ══════════════════════════════════════════════════════════════════════
# Alias table — maps retired store_nums to their canonical replacement
# ══════════════════════════════════════════════════════════════════════

class StoreAlias(Base):
    """Maps a retired store_num to the canonical store it was merged into."""

    __tablename__ = "store_aliases"

    id = Column(Integer, primary_key=True, autoincrement=True)
    old_store_num = Column(String, unique=True, nullable=False, index=True)
    canonical_store_num = Column(String, nullable=False, index=True)
    source_prefix = Column(String, nullable=True)
    merged_at = Column(DateTime, default=datetime.utcnow)

    def to_dict(self) -> dict:
        return {
            "old_store_num": self.old_store_num,
            "canonical_store_num": self.canonical_store_num,
            "source_prefix": self.source_prefix,
            "merged_at": self.merged_at.isoformat() if self.merged_at else None,
        }


# ══════════════════════════════════════════════════════════════════════
# Result dataclasses
# ══════════════════════════════════════════════════════════════════════

@dataclass
class MergeResult:
    """Outcome of merging one duplicate pair."""
    canonical: str
    merged: str
    signals_moved: int = 0
    scores_moved: int = 0


@dataclass
class DeduplicationReport:
    """Outcome of a full dedup run."""
    region: str
    total_stores_before: int = 0
    total_stores_after: int = 0
    duplicate_groups: int = 0
    stores_merged: int = 0
    signals_reassigned: int = 0
    scores_reassigned: int = 0
    merges: list[MergeResult] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "region": self.region,
            "total_stores_before": self.total_stores_before,
            "total_stores_after": self.total_stores_after,
            "duplicate_groups": self.duplicate_groups,
            "stores_merged": self.stores_merged,
            "signals_reassigned": self.signals_reassigned,
            "scores_reassigned": self.scores_reassigned,
            "merges": [
                {"canonical": m.canonical, "merged": m.merged,
                 "signals_moved": m.signals_moved, "scores_moved": m.scores_moved}
                for m in self.merges
            ],
            "error_count": len(self.errors),
        }


# ══════════════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════════════

def _source_prefix(store_num: str) -> str:
    """Extract the source prefix from a store_num (e.g. 'ATP' from 'ATP-ST-123')."""
    return store_num.split("-")[0] if "-" in store_num else ""


def _reputation(store_num: str) -> int:
    """Lower = more reputable."""
    prefix = _source_prefix(store_num)
    return SOURCE_REPUTATION.get(prefix, DEFAULT_REPUTATION)


def _normalize_chain(chain: str) -> str:
    """Normalise chain name for comparison."""
    return re.sub(r"[^a-z0-9]", "", chain.lower())


def _haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Haversine distance in metres between two lat/lng pairs."""
    R = 6_371_000  # Earth radius in metres
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _within_radius(lat1: float, lng1: float, lat2: float, lng2: float) -> bool:
    """Quick bounding-box pre-check + haversine confirm."""
    if abs(lat1 - lat2) > DEDUP_RADIUS_DEG or abs(lng1 - lng2) > DEDUP_RADIUS_DEG:
        return False
    return _haversine_m(lat1, lng1, lat2, lng2) <= 44.0  # 44 metres ≈ half block


# ══════════════════════════════════════════════════════════════════════
# On-ingest duplicate check
# ══════════════════════════════════════════════════════════════════════

def find_existing_match(
    session,
    chain: str,
    lat: float | None,
    lng: float | None,
    name: str | None = None,
) -> Store | None:
    """Check if a store with the same chain already exists near (lat, lng).

    Called by the ingestion pipeline BEFORE inserting a new Store row.
    Returns the existing Store if a match is found, else None.
    """
    if lat is None or lng is None:
        return None

    norm_chain = _normalize_chain(chain)

    # Query stores in a generous bounding box first (fast SQL filter)
    candidates = (
        session.query(Store)
        .filter(
            Store.chain == chain,
            Store.is_active.is_(True),
            Store.lat.isnot(None),
            Store.lng.isnot(None),
            Store.lat.between(lat - DEDUP_RADIUS_DEG, lat + DEDUP_RADIUS_DEG),
            Store.lng.between(lng - DEDUP_RADIUS_DEG, lng + DEDUP_RADIUS_DEG),
        )
        .all()
    )

    for c in candidates:
        if _normalize_chain(c.chain) == norm_chain and _within_radius(lat, lng, c.lat, c.lng):
            return c

    # Also check aliases — the matching store might have been merged away
    alias_rows = (
        session.query(StoreAlias)
        .filter(StoreAlias.canonical_store_num.in_(
            session.query(Store.store_num)
            .filter(
                Store.chain == chain,
                Store.is_active.is_(True),
                Store.lat.between(lat - DEDUP_RADIUS_DEG, lat + DEDUP_RADIUS_DEG),
                Store.lng.between(lng - DEDUP_RADIUS_DEG, lng + DEDUP_RADIUS_DEG),
            )
        ))
        .all()
    )
    if alias_rows:
        # Return the canonical store
        canon = session.query(Store).filter_by(
            store_num=alias_rows[0].canonical_store_num
        ).first()
        if canon:
            return canon

    return None


def resolve_alias(session, store_num: str) -> str:
    """If store_num was merged into another, return the canonical. Else return as-is."""
    alias = session.query(StoreAlias).filter_by(old_store_num=store_num).first()
    if alias:
        return alias.canonical_store_num
    return store_num


# ══════════════════════════════════════════════════════════════════════
# Bulk deduplication — clean up existing data
# ══════════════════════════════════════════════════════════════════════

def deduplicate_stores(
    region: str = "austin_tx",
    dry_run: bool = False,
) -> DeduplicationReport:
    """Find and merge duplicate stores in the given region.

    Algorithm:
      1. Load all active stores with coordinates for the region.
      2. Group by normalised chain name.
      3. Within each chain group, find clusters of stores within DEDUP_RADIUS.
      4. For each cluster, pick the canonical (most reputable source) and
         merge the rest into it.

    Args:
        region: Region key.
        dry_run: If True, report what would be merged but don't write.

    Returns:
        DeduplicationReport summarising what was (or would be) done.
    """
    engine = init_db()
    session = get_session(engine)

    report = DeduplicationReport(region=region)

    try:
        # Load all active stores with coordinates
        all_stores = (
            session.query(Store)
            .filter(
                Store.region == region,
                Store.is_active.is_(True),
                Store.lat.isnot(None),
                Store.lng.isnot(None),
            )
            .all()
        )
        report.total_stores_before = len(all_stores)

        # Group by normalised chain
        chain_groups: dict[str, list[Store]] = defaultdict(list)
        for s in all_stores:
            chain_groups[_normalize_chain(s.chain)].append(s)

        # Find duplicate clusters within each chain
        for chain_key, stores in chain_groups.items():
            clusters = _find_clusters(stores)

            for cluster in clusters:
                if len(cluster) < 2:
                    continue

                report.duplicate_groups += 1

                # Pick canonical: most reputable source, then earliest first_seen
                cluster.sort(key=lambda s: (_reputation(s.store_num), s.first_seen or datetime.max))
                canonical = cluster[0]
                duplicates = cluster[1:]

                # Merge address/coords from most reputable if canonical is thin
                _enrich_canonical(canonical, duplicates)

                for dup in duplicates:
                    if dry_run:
                        report.merges.append(MergeResult(
                            canonical=canonical.store_num,
                            merged=dup.store_num,
                        ))
                        report.stores_merged += 1
                        continue

                    merge = _merge_store_pair(session, canonical, dup)
                    report.merges.append(merge)
                    report.stores_merged += 1
                    report.signals_reassigned += merge.signals_moved
                    report.scores_reassigned += merge.scores_moved

        if not dry_run:
            session.commit()

        # Recount active stores
        active_count = (
            session.query(Store)
            .filter(
                Store.region == region,
                Store.is_active.is_(True),
                Store.lat.isnot(None),
            )
            .count()
        )
        report.total_stores_after = active_count

        logger.info(
            "[Dedup] %s: %d → %d stores (%d groups merged, %d signals reassigned)%s",
            region,
            report.total_stores_before,
            report.total_stores_after,
            report.duplicate_groups,
            report.signals_reassigned,
            " [DRY RUN]" if dry_run else "",
        )

    except Exception as e:
        if not dry_run:
            session.rollback()
        report.errors.append(str(e))
        logger.error("[Dedup] Failed: %s", e)
    finally:
        session.close()

    return report


def _find_clusters(stores: list[Store]) -> list[list[Store]]:
    """Find groups of stores that are within DEDUP_RADIUS of each other.

    Uses a simple greedy union: for each store, check if it falls within
    an existing cluster.  O(n²) per chain group but n is small (< 200 per chain).
    """
    clusters: list[list[Store]] = []
    assigned: set[str] = set()

    # Sort by lat for locality
    stores_sorted = sorted(stores, key=lambda s: (s.lat, s.lng))

    for s in stores_sorted:
        if s.store_num in assigned:
            continue

        # Start a new cluster with this store
        cluster = [s]
        assigned.add(s.store_num)

        # Check all remaining stores
        for other in stores_sorted:
            if other.store_num in assigned:
                continue
            # Check distance to any member of the current cluster
            for member in cluster:
                if _within_radius(s.lat, s.lng, other.lat, other.lng):
                    cluster.append(other)
                    assigned.add(other.store_num)
                    break

        clusters.append(cluster)

    return clusters


def _enrich_canonical(canonical: Store, duplicates: list[Store]) -> None:
    """If the canonical store is missing data, fill from the best duplicate."""
    for dup in sorted(duplicates, key=lambda s: _reputation(s.store_num)):
        if (not canonical.address or canonical.address.strip() == "") and dup.address:
            canonical.address = dup.address
        if not canonical.store_name or canonical.store_name == canonical.chain.title():
            if dup.store_name and dup.store_name != dup.chain.title():
                canonical.store_name = dup.store_name
        if canonical.lat is None and dup.lat is not None:
            canonical.lat = dup.lat
            canonical.lng = dup.lng


def _merge_store_pair(session, canonical: Store, duplicate: Store) -> MergeResult:
    """Merge a single duplicate into the canonical store.

    1. Reassign all signals from duplicate → canonical.
    2. Reassign all scores from duplicate → canonical (drop conflicting).
    3. Create an alias record.
    4. Soft-delete the duplicate.
    """
    result = MergeResult(canonical=canonical.store_num, merged=duplicate.store_num)

    # Reassign signals
    sig_count = (
        session.query(Signal)
        .filter(Signal.store_num == duplicate.store_num)
        .update({Signal.store_num: canonical.store_num}, synchronize_session="fetch")
    )
    result.signals_moved = sig_count

    # Reassign scores — skip if canonical already has that score_type
    existing_score_types = {
        s.score_type
        for s in session.query(Score).filter_by(store_num=canonical.store_num).all()
    }
    dup_scores = session.query(Score).filter_by(store_num=duplicate.store_num).all()
    moved_scores = 0
    for sc in dup_scores:
        if sc.score_type not in existing_score_types:
            sc.store_num = canonical.store_num
            moved_scores += 1
        else:
            session.delete(sc)
    result.scores_moved = moved_scores

    # Preserve earliest first_seen
    if duplicate.first_seen and (
        canonical.first_seen is None or duplicate.first_seen < canonical.first_seen
    ):
        canonical.first_seen = duplicate.first_seen

    # Update last_seen to the most recent
    if duplicate.last_seen and (
        canonical.last_seen is None or duplicate.last_seen > canonical.last_seen
    ):
        canonical.last_seen = duplicate.last_seen

    # Create alias
    alias = StoreAlias(
        old_store_num=duplicate.store_num,
        canonical_store_num=canonical.store_num,
        source_prefix=_source_prefix(duplicate.store_num),
        merged_at=datetime.utcnow(),
    )
    session.add(alias)

    # Soft-delete the duplicate
    duplicate.is_active = False

    return result


# ══════════════════════════════════════════════════════════════════════
# Summary / stats
# ══════════════════════════════════════════════════════════════════════

def get_dedup_summary(region: str = "austin_tx") -> dict:
    """Quick summary of dedup state for a region."""
    engine = init_db()
    session = get_session(engine)

    try:
        total_active = session.query(Store).filter(
            Store.region == region, Store.is_active.is_(True),
        ).count()

        total_inactive = session.query(Store).filter(
            Store.region == region, Store.is_active.is_(False),
        ).count()

        alias_count = session.query(StoreAlias).count()

        # Estimate remaining duplicates (same chain, < threshold distance)
        potential_dupes = session.execute(text("""
            SELECT COUNT(*) FROM (
                SELECT a.store_num
                FROM stores a
                JOIN stores b ON a.chain = b.chain
                    AND a.store_num < b.store_num
                    AND a.is_active = 1 AND b.is_active = 1
                    AND a.lat IS NOT NULL AND b.lat IS NOT NULL
                    AND ABS(a.lat - b.lat) < :radius
                    AND ABS(a.lng - b.lng) < :radius
                    AND a.region = :region AND b.region = :region
            )
        """), {"radius": DEDUP_RADIUS_DEG, "region": region}).scalar()

        return {
            "region": region,
            "active_stores": total_active,
            "inactive_merged": total_inactive,
            "aliases": alias_count,
            "estimated_remaining_duplicates": potential_dupes or 0,
        }
    finally:
        session.close()
