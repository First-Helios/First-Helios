"""
scrapers/alltheplaces_adapter.py

Downloads pre-built GeoJSON from alltheplaces.xyz for known chain brands.
AllThePlaces scrapers hit each chain's own store locator API directly —
this is first-party location data, not inferred from map tiles.

License: CC-0 (completely unrestricted)
Depends on: requests (already installed)
Called by: CLI for store discovery, or scheduler weekly

Usage:
    python scrapers/alltheplaces_adapter.py --chain starbucks --region austin_tx
    python scrapers/alltheplaces_adapter.py --chain dutch_bros --region austin_tx
"""

import logging
import sys
from datetime import datetime

import requests

sys.path.insert(0, ".")
from backend.database import Store, get_session, init_db
from config.loader import get_config
from scrapers.base import BaseScraper, ScraperSignal

logger = logging.getLogger(__name__)
config = get_config()

# alltheplaces.xyz spider filenames per brand.
# Verified 2026-03-19 against https://data.alltheplaces.xyz/runs/latest/output/{name}.geojson
# Browse full list at: https://alltheplaces.xyz/spiders.html
ATP_BRAND_MAP: dict[str, str] = {
    "starbucks": "starbucks_us",
    "dutch_bros": "dutch_bros",
    "mcdonalds": "mcdonalds",
    "target_retail": "target_us",
    "chipotle": "chipotle",
    "whataburger": "whataburger",
}

# API root per https://github.com/alltheplaces/alltheplaces/blob/master/API.md
ATP_API_ROOT = "https://data.alltheplaces.xyz"


def _bbox_from_region(region: str) -> dict[str, float]:
    """Compute a bounding box dict from region config."""
    region_cfg = config.get("regions", {}).get(region, {})
    if "bbox" in region_cfg:
        return region_cfg["bbox"]
    lat = region_cfg.get("center_lat", 30.2672)
    lng = region_cfg.get("center_lng", -97.7431)
    r = region_cfg.get("radius_mi", 25) / 69.0  # rough degrees-per-mile
    return {
        "west": lng - r,
        "east": lng + r,
        "south": lat - r,
        "north": lat + r,
    }


class AllThePlacesAdapter(BaseScraper):
    """Downloads pre-built AllThePlaces GeoJSON and upserts chain stores.

    Each invocation handles one chain.  Set `adapter.chain` before calling
    `scrape()` or pass ``--chain`` on the CLI.
    """

    name = "alltheplaces"
    chain = "starbucks"

    def _download_geojson(self, brand_key: str) -> list[dict]:
        filename = ATP_BRAND_MAP.get(brand_key)
        if not filename:
            logger.warning("[ATP] No spider mapping for brand: %s", brand_key)
            return []

        # Strategy 1: per-spider redirect endpoint (302 → storage)
        #   GET /runs/latest/output/{spider_name}.geojson
        redirect_url = f"{ATP_API_ROOT}/runs/latest/output/{filename}.geojson"

        # Strategy 2: resolve run_id from /runs/latest.json then build direct URL
        #   GET {output_url_base}/output/{spider_name}.geojson
        urls_to_try: list[str] = [redirect_url]
        try:
            from backend.tracked_request import tracked_get
            meta_resp = tracked_get(
                "atp_geojson", "latest_json",
                f"{ATP_API_ROOT}/runs/latest.json",
                timeout=15,
                headers={"User-Agent": "ChainStaffingTracker/1.0"},
            )
            if meta_resp.ok:
                meta = meta_resp.json()
                output_url = meta.get("output_url", "")
                if output_url:
                    # output_url is like https://…/runs/{run_id}/output.zip
                    # The individual spider file lives at …/runs/{run_id}/output/{spider}.geojson
                    base = output_url.rsplit("/", 1)[0]
                    urls_to_try.append(f"{base}/output/{filename}.geojson")
        except Exception as meta_e:
            logger.debug("[ATP] Could not fetch latest.json: %s", meta_e)

        for url in urls_to_try:
            try:
                logger.info("[ATP] Trying %s", url)
                from backend.tracked_request import tracked_get
                resp = tracked_get(
                    "atp_geojson", "geojson_download",
                    url,
                    timeout=120,
                    headers={"User-Agent": "ChainStaffingTracker/1.0"},
                    allow_redirects=True,
                )
                if resp.status_code == 200 and resp.text.strip().startswith("{"):
                    features = resp.json().get("features", [])
                    logger.info(
                        "[ATP] Downloaded %d %s locations globally",
                        len(features),
                        brand_key,
                    )
                    return features
                logger.warning(
                    "[ATP] %s returned status %d (not valid GeoJSON)",
                    url,
                    resp.status_code,
                )
            except Exception as e:
                logger.warning("[ATP] %s failed: %s", url, e)

        logger.error("[ATP] All download attempts failed for %s", brand_key)
        return []

    def _filter_to_region(self, features: list[dict], region: str) -> list[dict]:
        """Filter GeoJSON features to the configured region bounding box."""
        bbox = _bbox_from_region(region)
        filtered = []
        for f in features:
            coords = f.get("geometry", {}).get("coordinates", [])
            if len(coords) < 2:
                continue
            f_lng, f_lat = float(coords[0]), float(coords[1])
            if (
                bbox["west"] <= f_lng <= bbox["east"]
                and bbox["south"] <= f_lat <= bbox["north"]
            ):
                filtered.append(f)
        logger.info("[ATP] %d locations within %s bbox", len(filtered), region)
        return filtered

    def _query_parquet(self, brand_key: str, region: str) -> list[dict]:
        """Fallback: query the full ATP parquet file via DuckDB for a specific spider.

        The parquet URL comes from /runs/latest.json.  We filter by the
        ``@spider`` column and a geographic bounding box so we only download
        the rows we need (predicate pushdown over HTTP range requests).
        """
        try:
            import duckdb  # optional heavy dep — only used as fallback
        except ImportError:
            logger.warning("[ATP] duckdb not installed — cannot use parquet fallback")
            return []

        filename = ATP_BRAND_MAP.get(brand_key)
        if not filename:
            return []

        # Resolve parquet URL from latest.json
        try:
            from backend.tracked_request import tracked_get, log_external
            meta_resp = tracked_get(
                "atp_parquet", "latest_json",
                f"{ATP_API_ROOT}/runs/latest.json",
                timeout=15,
                headers={"User-Agent": "ChainStaffingTracker/1.0"},
            )
            if not meta_resp.ok:
                logger.warning("[ATP] latest.json returned %d", meta_resp.status_code)
                return []
            parquet_url = meta_resp.json().get("parquet_url", "")
            if not parquet_url:
                logger.warning("[ATP] No parquet_url in latest.json")
                return []
        except Exception as e:
            logger.warning("[ATP] Failed to resolve parquet URL: %s", e)
            return []

        bbox = _bbox_from_region(region)
        query = f"""
            SELECT *
            FROM read_parquet('{parquet_url}')
            WHERE "@spider" = ?
              AND "Longitude" BETWEEN ? AND ?
              AND "Latitude"  BETWEEN ? AND ?
        """
        params = [
            filename,
            bbox["west"], bbox["east"],
            bbox["south"], bbox["north"],
        ]

        try:
            import time as _t
            logger.info("[ATP] Querying parquet for spider=%s in %s", filename, region)
            conn = duckdb.connect()
            conn.execute("INSTALL httpfs; LOAD httpfs;")
            _t0 = _t.time()
            result = conn.execute(query, params).fetchall()
            columns = [desc[0] for desc in conn.description]
            _lat_ms = int((_t.time() - _t0) * 1000)
            conn.close()

            log_external(
                "atp_parquet", "parquet_query",
                url=parquet_url, success=True,
                latency_ms=_lat_ms, data_items=len(result),
            )

            # Convert rows back to GeoJSON-like feature dicts
            features: list[dict] = []
            for row in result:
                row_dict = dict(zip(columns, row))
                lng = row_dict.get("Longitude", 0.0)
                lat = row_dict.get("Latitude", 0.0)
                features.append({
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [lng, lat]},
                    "properties": {
                        "ref": row_dict.get("ref", ""),
                        "name": row_dict.get("name", ""),
                        "addr:housenumber": row_dict.get("addr:housenumber", ""),
                        "addr:street": row_dict.get("addr:street", ""),
                        "addr:city": row_dict.get("addr:city", ""),
                        "addr:state": row_dict.get("addr:state", ""),
                        "phone": row_dict.get("phone", ""),
                        "opening_hours": row_dict.get("opening_hours", ""),
                    },
                })

            logger.info("[ATP] Parquet returned %d features for %s in %s", len(features), brand_key, region)
            return features

        except Exception as e:
            logger.error("[ATP] Parquet query failed: %s", e)
            return []

    def scrape(self, region: str, radius_mi: int = 25) -> list[ScraperSignal]:
        try:
            # Try GeoJSON download first, fall back to parquet query
            features = self._download_geojson(self.chain)
            if not features:
                features = self._query_parquet(self.chain, region)
                local_features = features  # already bbox-filtered
            else:
                local_features = self._filter_to_region(features, region)

            if not local_features:
                logger.warning("[ATP] No %s locations found in %s", self.chain, region)
                return []

            chain_cfg = config.get("chains", {}).get(self.chain, {})
            signals: list[ScraperSignal] = []

            engine = init_db()
            session = get_session(engine)
            try:
                for f in local_features:
                    props = f.get("properties", {})
                    coords = f.get("geometry", {}).get("coordinates", [])
                    if len(coords) < 2:
                        continue

                    f_lng, f_lat = float(coords[0]), float(coords[1])

                    # Use ATP ref as store identifier where available
                    ref = (
                        props.get("ref")
                        or props.get("store_id")
                        or props.get("@ref")
                    )
                    chain_abbr = self.chain.upper()[:2]
                    if ref:
                        store_num = f"ATP-{chain_abbr}-{ref}"
                    else:
                        store_num = f"ATP-{chain_abbr}-{abs(hash(str(coords))) % 100000:05d}"

                    # Build address from OSM-style address props
                    addr_parts: list[str] = []
                    for key in ["addr:housenumber", "addr:street"]:
                        if props.get(key):
                            addr_parts.append(props[key])
                    city = props.get("addr:city", "")
                    state = props.get("addr:state", "")
                    if city:
                        addr_parts.append(city)
                    if state:
                        addr_parts.append(state)
                    address = ", ".join(addr_parts) if addr_parts else props.get("name", "")

                    # Upsert store
                    existing = session.query(Store).filter_by(store_num=store_num).first()
                    if existing:
                        existing.lat = f_lat
                        existing.lng = f_lng
                        existing.last_seen = datetime.utcnow()
                    else:
                        session.add(
                            Store(
                                store_num=store_num,
                                chain=self.chain,
                                industry=chain_cfg.get("industry", "unknown"),
                                store_name=props.get("name", self.chain.title()),
                                address=address,
                                lat=f_lat,
                                lng=f_lng,
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
                                "atp_ref": ref,
                                "address": address,
                                "lat": f_lat,
                                "lng": f_lng,
                                "phone": props.get("phone"),
                                "hours": props.get("opening_hours"),
                            },
                            observed_at=datetime.utcnow(),
                        )
                    )

                session.commit()
                logger.info(
                    "[ATP] Upserted %d %s stores into tracker.db",
                    len(signals),
                    self.chain,
                )
            except Exception as db_e:
                session.rollback()
                logger.error("[ATP] DB write failed: %s", db_e)
            finally:
                session.close()

            return signals

        except Exception as e:
            logger.error("[ATP] scrape() failed for %s/%s: %s", self.chain, region, e)
            return []


if __name__ == "__main__":
    import argparse

    from backend.ingest import ingest_signals

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    parser = argparse.ArgumentParser(description="AllThePlaces store discovery scraper")
    parser.add_argument("--chain", default="starbucks", help="Chain key (e.g. starbucks)")
    parser.add_argument("--region", default="austin_tx", help="Region key (e.g. austin_tx)")
    parser.add_argument(
        "--dry-run", action="store_true", help="Print results without writing to DB"
    )
    args = parser.parse_args()

    adapter = AllThePlacesAdapter()
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
