"""
scrapers/osm_adapter.py

Queries OpenStreetMap Overpass API for chain store locations.
Used as Priority 3 cross-reference and fallback after AllThePlaces
and Overture Maps. Community-maintained — strong in central Austin, thinner
in suburbs.

License: ODbL (Open Data Commons Open Database License)
Depends on: requests (already installed)
Called by: CLI for store discovery, scheduler weekly

Usage:
    python scrapers/osm_adapter.py --chain starbucks --region austin_tx
"""

import logging
import sys
import time
from datetime import datetime

import requests

sys.path.insert(0, ".")
from backend.database import Store, get_session, init_db
from config.loader import get_config
from scrapers.base import BaseScraper, ScraperSignal

logger = logging.getLogger(__name__)
config = get_config()

OVERPASS_URL = "https://overpass-api.de/api/interpreter"

# Mapping from chain key to OSM brand name filter
OSM_BRAND_MAP: dict[str, str] = {
    "starbucks": "Starbucks",
    "dutch_bros": "Dutch Bros",
    "mcdonalds": "McDonald's",
    "whataburger": "Whataburger",
    "chipotle": "Chipotle",
    "target_retail": "Target",
}


def _bbox_from_region(region: str) -> tuple[float, float, float, float]:
    """Return (south, west, north, east) for Overpass bbox query."""
    region_cfg = config.get("regions", {}).get(region, {})
    if "bbox" in region_cfg:
        b = region_cfg["bbox"]
        return b["south"], b["west"], b["north"], b["east"]
    lat = region_cfg.get("center_lat", 30.2672)
    lng = region_cfg.get("center_lng", -97.7431)
    r = region_cfg.get("radius_mi", 25) / 69.0
    return lat - r, lng - r, lat + r, lng + r


class OSMAdapter(BaseScraper):
    """Queries OpenStreetMap Overpass API for chain brand POIs.

    Produces store_presence ScraperSignals and upserts into the stores table.
    Respects Overpass rate limits with configurable delay.
    """

    name = "osm_adapter"
    chain = "starbucks"

    def scrape(self, region: str, radius_mi: int = 25) -> list[ScraperSignal]:
        try:
            brand = OSM_BRAND_MAP.get(self.chain)
            if not brand:
                logger.warning("[OSM] No brand mapping for chain: %s", self.chain)
                return []

            south, west, north, east = _bbox_from_region(region)

            # Overpass QL: search for nodes and ways with matching brand tag
            query = f"""
            [out:json][timeout:60];
            (
              node["brand"="{brand}"]({south},{west},{north},{east});
              way["brand"="{brand}"]({south},{west},{north},{east});
              node["name"="{brand}"]({south},{west},{north},{east});
            );
            out center;
            """

            logger.info("[OSM] Querying Overpass for %s in %s", brand, region)
            resp = requests.post(
                OVERPASS_URL,
                data={"data": query},
                timeout=90,
                headers={"User-Agent": "ChainStaffingTracker/1.0"},
            )
            resp.raise_for_status()
            elements = resp.json().get("elements", [])
            logger.info("[OSM] Got %d elements for %s", len(elements), brand)

            chain_cfg = config.get("chains", {}).get(self.chain, {})
            signals: list[ScraperSignal] = []

            engine = init_db()
            session = get_session(engine)
            try:
                for elem in elements:
                    # Ways use center point; nodes use direct lat/lon
                    lat = elem.get("lat") or elem.get("center", {}).get("lat")
                    lng = elem.get("lon") or elem.get("center", {}).get("lon")
                    if not lat or not lng:
                        continue

                    tags = elem.get("tags", {})
                    osm_id = str(elem.get("id", ""))
                    chain_abbr = self.chain.upper()[:2]
                    store_num = f"OSM-{chain_abbr}-{osm_id}"

                    # Build address from OSM address tags
                    addr_parts: list[str] = []
                    if tags.get("addr:housenumber"):
                        addr_parts.append(tags["addr:housenumber"])
                    if tags.get("addr:street"):
                        addr_parts.append(tags["addr:street"])
                    if tags.get("addr:city"):
                        addr_parts.append(tags["addr:city"])
                    if tags.get("addr:state"):
                        addr_parts.append(tags["addr:state"])
                    address = ", ".join(addr_parts) if addr_parts else tags.get("name", "")

                    existing = session.query(Store).filter_by(store_num=store_num).first()
                    if existing:
                        existing.lat = lat
                        existing.lng = lng
                        existing.last_seen = datetime.utcnow()
                    else:
                        session.add(
                            Store(
                                store_num=store_num,
                                chain=self.chain,
                                industry=chain_cfg.get("industry", "unknown"),
                                store_name=tags.get("name", brand),
                                address=address,
                                lat=lat,
                                lng=lng,
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
                            value=1.0,
                            metadata={
                                "osm_id": osm_id,
                                "address": address,
                                "lat": lat,
                                "lng": lng,
                                "phone": tags.get("phone"),
                                "hours": tags.get("opening_hours"),
                                "osm_type": elem.get("type"),
                            },
                            observed_at=datetime.utcnow(),
                        )
                    )

                session.commit()
                logger.info(
                    "[OSM] Upserted %d %s stores into tracker.db", len(signals), self.chain
                )
            except Exception as db_e:
                session.rollback()
                logger.error("[OSM] DB write failed: %s", db_e)
            finally:
                session.close()

            return signals

        except Exception as e:
            logger.error("[OSM] scrape() failed for %s/%s: %s", self.chain, region, e)
            return []


def scrape_osm(chain: str = "starbucks", region: str = "austin_tx") -> list[ScraperSignal]:
    """Convenience function for scheduler integration."""
    adapter = OSMAdapter()
    adapter.chain = chain
    return adapter.scrape(region)


if __name__ == "__main__":
    import argparse

    from backend.ingest import ingest_signals

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    parser = argparse.ArgumentParser(description="OSM Overpass store discovery scraper")
    parser.add_argument("--chain", default="starbucks", help="Chain key")
    parser.add_argument("--region", default="austin_tx", help="Region key")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    adapter = OSMAdapter()
    adapter.chain = args.chain
    signals = adapter.scrape(args.region)

    print(f"\n{'DRY RUN — ' if args.dry_run else ''}Found {len(signals)} stores")
    for s in signals[:5]:
        m = s.metadata
        print(
            f"  {s.store_num}  {m.get('address') or '(no address)'}"
            f"  ({m.get('lat', 0):.4f}, {m.get('lng', 0):.4f})"
        )
    if len(signals) > 5:
        print(f"  ... and {len(signals) - 5} more")

    if not args.dry_run and signals:
        ingest_signals(signals, region=args.region)
        print(f"Ingested {len(signals)} signals.")
