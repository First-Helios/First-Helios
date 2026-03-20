"""
scrapers/overture_adapter.py

Queries Overture Maps Places dataset via DuckDB directly from S3.
No full download of the 64M POI dataset — bbox + filter queries only.
First-run installs DuckDB spatial/httpfs extensions (~30 sec pause — do not kill).

Two modes:
  chain  — named brand lookup (cross-validates AllThePlaces chain data)
  local  — category lookup excluding known chains (populates local_employers table)

License: CDLA Permissive v2 — derivative products permitted.
Depends on: duckdb (pip install duckdb overturemaps)
Called by: CLI for initial population, scheduler weekly

Usage:
    python scrapers/overture_adapter.py --mode chain --chain starbucks --region austin_tx
    python scrapers/overture_adapter.py --mode local --industry coffee_cafe --region austin_tx
"""

import logging
import sys
from datetime import datetime

import duckdb

sys.path.insert(0, ".")
from backend.database import LocalEmployer, Store, get_session, init_db
from config.loader import get_config
from scrapers.base import BaseScraper, ScraperSignal

logger = logging.getLogger(__name__)
config = get_config()


def _get_overture_s3_path() -> str:
    """Get the S3 parquet path for the latest Overture Maps release."""
    try:
        from overturemaps.core import get_latest_release
        release = get_latest_release()
    except Exception:
        release = "2026-03-18.0"  # fallback
    return (
        f"s3://overturemaps-us-west-2/release/{release}"
        "/theme=places/type=place/*"
    )

# Overture category → industry mapping
CATEGORY_INDUSTRY_MAP: dict[str, str] = {
    "coffee_shop": "coffee_cafe",
    "cafe": "coffee_cafe",
    "donut_shop": "coffee_cafe",
    "tea_house": "coffee_cafe",
    "fast_food_restaurant": "fast_food",
    "sandwich_shop": "fast_food",
    "burger_restaurant": "fast_food",
    "pizza_restaurant": "fast_food",
    "mexican_restaurant": "fast_food",
    "grocery_store": "retail_general",
    "convenience_store": "retail_general",
    "clothing_store": "retail_general",
    "department_store": "retail_general",
    "hotel": "hospitality",
    "motel": "hospitality",
}

# Chain names to exclude from local employer queries (lowercase LIKE patterns)
CHAIN_EXCLUSIONS: list[str] = [
    "starbucks",
    "dutch bros",
    "mcdonald",
    "dunkin",
    "taco bell",
    "subway",
    "chick-fil-a",
    "whataburger",
    "wendy",
    "burger king",
    "domino",
    "pizza hut",
    "panda express",
    "chipotle",
    "sonic",
    "popeyes",
    "jack in the box",
    "in-n-out",
    "five guys",
    "panera",
    "tim horton",
    "peet",
    "caribou",
    "coffee bean",
    "costa coffee",
    "walmart",
    "target",
    "costco",
    "heb",
    "kroger",
    "whole foods",
    "trader joe",
    "aldi",
    "cvs",
    "walgreen",
    "holiday inn",
    "marriott",
    "hilton",
    "hyatt",
    "best western",
]


def _bbox_from_region(region: str) -> dict[str, float]:
    """Compute bounding box from region config."""
    region_cfg = config.get("regions", {}).get(region, {})
    if "bbox" in region_cfg:
        return region_cfg["bbox"]
    lat = region_cfg.get("center_lat", 30.2672)
    lng = region_cfg.get("center_lng", -97.7431)
    r = region_cfg.get("radius_mi", 25) / 69.0
    return {"west": lng - r, "east": lng + r, "south": lat - r, "north": lat + r}


def _get_duckdb_conn() -> duckdb.DuckDBPyConnection:
    """Create a DuckDB connection with spatial and httpfs extensions loaded."""
    conn = duckdb.connect()
    conn.execute("INSTALL spatial; INSTALL httpfs; LOAD spatial; LOAD httpfs;")
    conn.execute("SET s3_region='us-west-2';")
    return conn


class OvertureChainAdapter(BaseScraper):
    """Queries Overture for chain store locations.

    Cross-validates AllThePlaces data and fills geographic gaps.
    Upserts into the stores table.
    """

    name = "overture_chain"
    chain = "starbucks"

    CHAIN_NAME_FILTERS: dict[str, str] = {
        "starbucks": "%starbucks%",
        "dutch_bros": "%dutch bros%",
        "mcdonalds": "%mcdonald%",
        "target_retail": "%target%",
        "whataburger": "%whataburger%",
        "chipotle": "%chipotle%",
    }

    def scrape(self, region: str, radius_mi: int = 25) -> list[ScraperSignal]:
        try:
            name_filter = self.CHAIN_NAME_FILTERS.get(self.chain)
            if not name_filter:
                logger.warning("[Overture] No name filter for chain: %s", self.chain)
                return []

            bbox = _bbox_from_region(region)
            s3_path = _get_overture_s3_path()

            query = f"""
            SELECT
                id,
                names.primary AS name,
                categories.primary AS category,
                addresses[1].freeform AS address,
                ST_X(geometry) AS lng,
                ST_Y(geometry) AS lat,
                confidence
            FROM read_parquet('{s3_path}', hive_partitioning=1)
            WHERE names.primary ILIKE '{name_filter}'
              AND bbox.xmin BETWEEN {bbox['west']} AND {bbox['east']}
              AND bbox.ymin BETWEEN {bbox['south']} AND {bbox['north']}
              AND confidence > 0.8
            """

            logger.info("[Overture] Connecting to S3 for chain=%s region=%s", self.chain, region)
            conn = _get_duckdb_conn()
            logger.info("[Overture] Querying (first run installs extensions, ~30s)...")
            rows = conn.execute(query).fetchall()
            conn.close()

            cols = ["overture_id", "name", "category", "address", "lng", "lat", "confidence"]
            places = [dict(zip(cols, r)) for r in rows]
            logger.info("[Overture] Found %d %s locations", len(places), self.chain)

            chain_cfg = config.get("chains", {}).get(self.chain, {})
            signals: list[ScraperSignal] = []

            engine = init_db()
            session = get_session(engine)
            try:
                for p in places:
                    oid = str(p["overture_id"])
                    store_num = f"OV-{self.chain.upper()[:2]}-{oid[-8:]}"
                    existing = session.query(Store).filter_by(store_num=store_num).first()
                    if existing:
                        existing.lat = p["lat"]
                        existing.lng = p["lng"]
                        existing.last_seen = datetime.utcnow()
                    else:
                        session.add(
                            Store(
                                store_num=store_num,
                                chain=self.chain,
                                industry=chain_cfg.get("industry", "unknown"),
                                store_name=p["name"] or self.chain.title(),
                                address=p["address"] or "",
                                lat=p["lat"],
                                lng=p["lng"],
                                region=region,
                                first_seen=datetime.utcnow(),
                                last_seen=datetime.utcnow(),
                                is_active=True,
                            )
                        )
                    signals.append(
                        ScraperSignal(
                            store_num=store_num,
                            chain=self.chain,
                            source=self.name,
                            signal_type="store_presence",
                            value=float(p["confidence"] or 0),
                            metadata={
                                "overture_id": oid,
                                "address": p["address"],
                                "lat": p["lat"],
                                "lng": p["lng"],
                                "category": p["category"],
                            },
                            observed_at=datetime.utcnow(),
                        )
                    )
                session.commit()
                logger.info(
                    "[Overture] Upserted %d %s chain stores", len(signals), self.chain
                )
            except Exception as db_e:
                session.rollback()
                logger.error("[Overture] DB write failed (chain): %s", db_e)
            finally:
                session.close()

            return signals

        except Exception as e:
            logger.error("[Overture] chain scrape() failed for %s/%s: %s", self.chain, region, e)
            return []


class OvertureLocalAdapter(BaseScraper):
    """Queries Overture for local (non-chain) employers by category.

    Populates the local_employers table used by the targeting score
    local_alternatives component.
    """

    name = "overture_local"
    chain = "local"

    def scrape(self, region: str, radius_mi: int = 25) -> list[ScraperSignal]:
        try:
            bbox = _bbox_from_region(region)
            categories = list(CATEGORY_INDUSTRY_MAP.keys())

            cat_filter = " OR ".join(
                f"categories.primary = '{c}'" for c in categories
            )
            chain_filter = " AND ".join(
                f"lower(names.primary) NOT LIKE '%{c}%'" for c in CHAIN_EXCLUSIONS
            )
            s3_path = _get_overture_s3_path()

            query = f"""
            SELECT
                id,
                names.primary AS name,
                categories.primary AS category,
                addresses[1].freeform AS address,
                ST_X(geometry) AS lng,
                ST_Y(geometry) AS lat,
                confidence
            FROM read_parquet('{s3_path}', hive_partitioning=1)
            WHERE ({cat_filter})
              AND ({chain_filter})
              AND bbox.xmin BETWEEN {bbox['west']} AND {bbox['east']}
              AND bbox.ymin BETWEEN {bbox['south']} AND {bbox['north']}
              AND confidence > 0.7
            """

            logger.info("[Overture] Querying local employers for region=%s", region)
            conn = _get_duckdb_conn()
            rows = conn.execute(query).fetchall()
            conn.close()

            cols = ["overture_id", "name", "category", "address", "lng", "lat", "confidence"]
            places = [dict(zip(cols, r)) for r in rows]
            logger.info("[Overture] Found %d local employer locations", len(places))

            signals: list[ScraperSignal] = []
            engine = init_db()
            session = get_session(engine)
            try:
                for p in places:
                    oid = str(p["overture_id"])
                    industry = CATEGORY_INDUSTRY_MAP.get(str(p["category"] or ""), "unknown")
                    existing = (
                        session.query(LocalEmployer).filter_by(overture_id=oid).first()
                    )
                    if existing:
                        existing.last_seen = datetime.utcnow()
                        existing.confidence = p["confidence"]
                    else:
                        session.add(
                            LocalEmployer(
                                overture_id=oid,
                                name=p["name"] or "Unknown",
                                category=p["category"],
                                industry=industry,
                                address=p["address"] or "",
                                lat=p["lat"],
                                lng=p["lng"],
                                region=region,
                                confidence=p["confidence"],
                                is_active=True,
                                first_seen=datetime.utcnow(),
                                last_seen=datetime.utcnow(),
                            )
                        )
                    signals.append(
                        ScraperSignal(
                            store_num=f"LOCAL-{oid[-8:]}",
                            chain="local",
                            source=self.name,
                            signal_type="local_presence",
                            value=float(p["confidence"] or 0),
                            metadata={
                                "overture_id": oid,
                                "name": p["name"],
                                "category": p["category"],
                                "industry": industry,
                                "address": p["address"],
                                "lat": p["lat"],
                                "lng": p["lng"],
                            },
                            observed_at=datetime.utcnow(),
                        )
                    )
                session.commit()
                logger.info("[Overture] Upserted %d local employers", len(signals))
            except Exception as db_e:
                session.rollback()
                logger.error("[Overture] DB write failed (local): %s", db_e)
            finally:
                session.close()

            return signals

        except Exception as e:
            logger.error("[Overture] local scrape() failed for %s: %s", region, e)
            return []


if __name__ == "__main__":
    import argparse

    from backend.ingest import ingest_signals

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    parser = argparse.ArgumentParser(description="Overture Maps POI scraper")
    parser.add_argument("--mode", choices=["chain", "local"], required=True)
    parser.add_argument("--chain", default="starbucks")
    parser.add_argument("--industry", default="coffee_cafe")
    parser.add_argument("--region", default="austin_tx")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if args.mode == "chain":
        adapter: BaseScraper = OvertureChainAdapter()
        adapter.chain = args.chain  # type: ignore[attr-defined]
    else:
        adapter = OvertureLocalAdapter()

    signals = adapter.scrape(args.region)

    print(f"\n{'DRY RUN — ' if args.dry_run else ''}Found {len(signals)} locations")
    for s in signals[:5]:
        m = s.metadata
        print(
            f"  {s.store_num}  {m.get('name') or s.store_num}"
            f"  ({m.get('lat', 0):.4f}, {m.get('lng', 0):.4f})"
        )
    if len(signals) > 5:
        print(f"  ... and {len(signals) - 5} more")

    if not args.dry_run and signals:
        ingest_signals(signals, region=args.region)
        print(f"Ingested {len(signals)} signals.")
