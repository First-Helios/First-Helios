# HANDOFF_SESSION7.md — POI Index + Map Layer Build

**Date:** 2026-03-19
**Project root:** `/home/fortune/CodeProjects/First-Helios`
**Venv:** `.venv/` (Python 3.12)
**Picks up from:** `HANDOFF_SESSION6.md`

---

## Read These First

```bash
cat .github/agents/AGENT.md
cat HANDOFF_SESSION6.md
```

Then verify current state:

```bash
cd /home/fortune/CodeProjects/First-Helios
source .venv/bin/activate

python3 -c "
import sqlite3
conn = sqlite3.connect('data/tracker.db')
for t in ['stores','signals','snapshots','scores','wage_index']:
    n = conn.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0]
    print(f'{t}: {n} rows')
null = conn.execute('SELECT COUNT(*) FROM stores WHERE lat IS NULL').fetchone()[0]
chain_w = conn.execute('SELECT COUNT(*) FROM wage_index WHERE is_chain=1').fetchone()[0]
n_stores = conn.execute('SELECT COUNT(*) FROM stores WHERE chain=\"starbucks\"').fetchone()[0]
print(f'null coords: {null}  chain_wages: {chain_w}  starbucks stores: {n_stores}')
conn.close()
"
```

Expected incoming state:
- 10 stores, all geocoded
- 0 chain wage entries (wage gap score still defaulting to 100)
- Map renders but only 10 markers
- OSM adapter was designed last session but may not be run yet

---

## What This Session Builds

The store discovery layer. Right now the system knows about 10 Starbucks locations
in Austin. Austin has ~35. Beyond that, the system has no knowledge of Dutch Bros,
McDonald's, local coffee shops, or any other chain or independent employer.

This session connects three free public POI indexes to build a complete picture
of the Austin employer landscape — chain and local — with coordinates for every
location. That data feeds directly into two broken score components:
- `isolation` score (needs to know where ALL same-chain stores are)
- `local_alternatives` score (needs to know where local employers are within 2mi)

It also gives the Leaflet map something real to show.

---

## Source Hierarchy — Read Before Building

Use these three sources in priority order. When sources conflict, prefer
higher-priority data. Never discard lower-priority data — store all source
IDs for cross-referencing.

```
Priority 1: AllThePlaces (chain stores)
    First-party accuracy — scraped directly from each chain's own store
    locator API. Best source for chain store locations and store ref numbers.
    CC-0 license. Pre-built GeoJSON available for direct download.

Priority 2: Overture Maps (chains + local employers)
    64M POIs globally. Backed by Meta, Microsoft, AWS, TomTom.
    DuckDB query against S3 — no full download needed.
    Austin bbox query returns results in seconds.
    CDLA Permissive v2 license — derivative products allowed.

Priority 3: OpenStreetMap Overpass (cross-reference + fallback)
    Already implemented in scrapers/osm_adapter.py.
    Community-maintained — strong in central Austin, thinner in suburbs.
    Use to fill gaps and cross-validate coordinates.
```

**What NOT to use:**
- Google Places API — licensing prohibits storing data or building a database
- SafeGraph — free sample is from 2020, too stale
- Yelp for location discovery — use for reviews only, not as a POI source

---

## Priority 1 — Install Dependencies

```bash
pip install duckdb overturemaps
```

DuckDB's `spatial` and `httpfs` extensions install automatically on first query.
Add both to the install command in `RUNBOOK.md`.

Verify:
```bash
python3 -c "import duckdb; print('duckdb', duckdb.__version__)"
python3 -c "import overturemaps; print('overturemaps ok')"
```

---

## Priority 2 — Build `scrapers/alltheplaces_adapter.py`

AllThePlaces publishes pre-built GeoJSON scraped directly from each chain's
own store locator. This is the most accurate source for chain store locations.

**What it does:**
- Downloads the pre-built GeoJSON for a given brand from alltheplaces.xyz
- Parses features into Store objects and upserts into tracker.db
- Produces `store_presence` ScraperSignals (one per location)
- Preserves the AllThePlaces `ref` field as the canonical store identifier
  where available (this is the chain's own store number)

**File:** `scrapers/alltheplaces_adapter.py`

```python
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

import requests
import logging
import sys
from datetime import datetime
from typing import Optional

sys.path.insert(0, '.')
from scrapers.base import BaseScraper, ScraperSignal
from backend.database import get_session, Store
from config.loader import get_config

logger = logging.getLogger(__name__)
config = get_config()

# alltheplaces.xyz spider filenames per brand
# Browse full list at: https://alltheplaces.xyz/
ATP_BRAND_MAP = {
    "starbucks":     "starbucks_com",
    "dutch_bros":    "dutch_bros",
    "mcdonalds":     "mcdonalds",
    "target_retail": "target",
    "chipotle":      "chipotle",
    "whataburger":   "whataburger",
}

ATP_BASE = "https://alltheplaces-data.com/runs/latest/output"


class AllThePlacesAdapter(BaseScraper):

    name = "alltheplaces"
    chain = "starbucks"

    def _download_geojson(self, brand_key: str) -> list[dict]:
        filename = ATP_BRAND_MAP.get(brand_key)
        if not filename:
            logger.warning(f"[ATP] No spider mapping for brand: {brand_key}")
            return []
        url = f"{ATP_BASE}/{filename}.geojson"
        try:
            logger.info(f"[ATP] Downloading {url}")
            resp = requests.get(
                url, timeout=60,
                headers={"User-Agent": "ChainStaffingTracker/1.0"}
            )
            resp.raise_for_status()
            features = resp.json().get("features", [])
            logger.info(f"[ATP] Downloaded {len(features)} {brand_key} locations globally")
            return features
        except Exception as e:
            logger.error(f"[ATP] Download failed for {brand_key}: {e}")
            return []

    def _filter_to_region(self, features: list[dict], region: str) -> list[dict]:
        """Filter GeoJSON features to the configured region bounding box."""
        region_cfg = config.regions.get(region, {})
        # Build bbox from center + radius approximation
        # Overridden by explicit bbox in config if present
        bbox = region_cfg.get("bbox")
        if not bbox:
            lat = region_cfg.get("center_lat", 30.2672)
            lng = region_cfg.get("center_lng", -97.7431)
            r = region_cfg.get("radius_mi", 25) / 69.0  # approx degrees
            bbox = {
                "west":  lng - r,
                "east":  lng + r,
                "south": lat - r,
                "north": lat + r,
            }

        filtered = []
        for f in features:
            coords = f.get("geometry", {}).get("coordinates", [])
            if len(coords) < 2:
                continue
            f_lng, f_lat = coords[0], coords[1]
            if (bbox["west"] <= f_lng <= bbox["east"] and
                    bbox["south"] <= f_lat <= bbox["north"]):
                filtered.append(f)

        logger.info(f"[ATP] {len(filtered)} locations within {region} bbox")
        return filtered

    def scrape(self, region: str, radius_mi: int = 25) -> list[ScraperSignal]:
        features = self._download_geojson(self.chain)
        if not features:
            return []

        local_features = self._filter_to_region(features, region)
        if not local_features:
            return []

        chain_cfg = config.chains.get(self.chain, {})
        signals = []

        with get_session() as session:
            for f in local_features:
                props = f.get("properties", {})
                coords = f.get("geometry", {}).get("coordinates", [])
                if len(coords) < 2:
                    continue

                f_lng, f_lat = coords[0], coords[1]

                # Use ATP ref as store number where available
                ref = props.get("ref") or props.get("store_id") or props.get("@ref")
                store_num = f"ATP-{self.chain.upper()[:2]}-{ref}" if ref else \
                            f"ATP-{self.chain.upper()[:2]}-{abs(hash(str(coords)))%100000:05d}"

                # Build address
                addr_parts = []
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
                    store = Store(
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
                    session.add(store)

                signals.append(ScraperSignal(
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
                ))

            session.commit()
            logger.info(f"[ATP] Upserted {len(signals)} {self.chain} stores into tracker.db")

        return signals


if __name__ == "__main__":
    import argparse
    from backend.ingest import ingest_signals
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    parser = argparse.ArgumentParser()
    parser.add_argument("--chain", default="starbucks")
    parser.add_argument("--region", default="austin_tx")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    adapter = AllThePlacesAdapter()
    adapter.chain = args.chain
    signals = adapter.scrape(args.region)

    print(f"\n{'DRY RUN — ' if args.dry_run else ''}Found {len(signals)} stores")
    for s in signals[:5]:
        m = s.metadata
        print(f"  {s.store_num}  {m.get('address')}  ({m.get('lat'):.4f}, {m.get('lng'):.4f})")
    if len(signals) > 5:
        print(f"  ... and {len(signals)-5} more")

    if not args.dry_run and signals:
        ingest_signals(signals)
        print(f"Ingested {len(signals)} signals.")
```

**Run it for all target chains:**
```bash
python scrapers/alltheplaces_adapter.py --chain starbucks --region austin_tx
python scrapers/alltheplaces_adapter.py --chain dutch_bros --region austin_tx
python scrapers/alltheplaces_adapter.py --chain mcdonalds --region austin_tx
```

**Verify:**
```bash
python3 -c "
import sqlite3
conn = sqlite3.connect('data/tracker.db')
for chain in ['starbucks','dutch_bros','mcdonalds']:
    n = conn.execute(
        'SELECT COUNT(*) FROM stores WHERE chain=?', (chain,)
    ).fetchone()[0]
    print(f'{chain}: {n} stores')
conn.close()
"
```

Expected: starbucks ~35, dutch_bros ~15, mcdonalds ~30

---

## Priority 3 — Build `scrapers/overture_adapter.py`

Overture Maps fills two gaps AllThePlaces cannot:
1. Local independent employers (coffee shops, restaurants) — ATP only covers chains
2. Cross-validation of chain store coordinates

**What it does:**
- Queries Overture Places via DuckDB directly against S3 — no full download
- Two modes: `chain` (named brand lookup) and `local` (category lookup, chain-excluded)
- `local` mode results populate a new `local_employers` table used by the
  `local_alternatives` targeting score component
- Chain mode results cross-reference and supplement AllThePlaces data

**Add `local_employers` table to `backend/database.py`:**

```python
class LocalEmployer(Base):
    __tablename__ = "local_employers"

    id           = Column(Integer, primary_key=True, autoincrement=True)
    overture_id  = Column(String, unique=True, nullable=False)
    name         = Column(String, nullable=False)
    category     = Column(String)
    industry     = Column(String)    # mapped from Overture category
    address      = Column(String)
    lat          = Column(Float)
    lng          = Column(Float)
    region       = Column(String)
    confidence   = Column(Float)
    is_active    = Column(Boolean, default=True)
    first_seen   = Column(DateTime, default=datetime.utcnow)
    last_seen    = Column(DateTime, default=datetime.utcnow)
```

This table is what `targeting.py` queries for `local_alternatives` score —
how many local employers within 2 miles are hiring in the same industry.

**File:** `scrapers/overture_adapter.py`

```python
"""
scrapers/overture_adapter.py

Queries Overture Maps Places dataset via DuckDB directly from S3.
No download of the full 64M POI dataset — bbox + filter queries only.

Two modes:
  chain  — named brand lookup (cross-validates AllThePlaces chain data)
  local  — category lookup excluding known chains (populates local_employers table)

License: CDLA Permissive v2 — derivative products permitted
Depends on: duckdb, duckdb spatial + httpfs extensions (auto-install on first run)
Called by: CLI for initial population, scheduler weekly

Usage:
    python scrapers/overture_adapter.py --mode chain --chain starbucks --region austin_tx
    python scrapers/overture_adapter.py --mode local --industry coffee_cafe --region austin_tx
"""

import duckdb
import logging
import sys
from datetime import datetime

sys.path.insert(0, '.')
from scrapers.base import BaseScraper, ScraperSignal
from backend.database import get_session, Store, LocalEmployer
from config.loader import get_config

logger = logging.getLogger(__name__)
config = get_config()

# Update monthly — check https://docs.overturemaps.org/release/latest/
OVERTURE_RELEASE = "2026-02-18.0"
OVERTURE_S3 = (
    f"s3://overturemaps-us-west-2/release/{OVERTURE_RELEASE}"
    f"/theme=places/type=place/*"
)

# Overture category values to industry mapping
CATEGORY_INDUSTRY_MAP = {
    "coffee_shop":          "coffee_cafe",
    "cafe":                 "coffee_cafe",
    "donut_shop":           "coffee_cafe",
    "tea_house":            "coffee_cafe",
    "fast_food_restaurant": "fast_food",
    "sandwich_shop":        "fast_food",
    "burger_restaurant":    "fast_food",
    "pizza_restaurant":     "fast_food",
    "mexican_restaurant":   "fast_food",
    "grocery_store":        "retail_general",
    "convenience_store":    "retail_general",
    "clothing_store":       "retail_general",
    "department_store":     "retail_general",
    "hotel":                "hospitality",
    "motel":                "hospitality",
}

# Known chain names to exclude from local employer queries
CHAIN_EXCLUSIONS = [
    "starbucks", "dutch bros", "mcdonald", "dunkin", "taco bell",
    "subway", "chick-fil-a", "whataburger", "wendy", "burger king",
    "domino", "pizza hut", "panda express", "chipotle", "sonic",
    "popeyes", "jack in the box", "in-n-out", "five guys", "panera",
    "tim horton", "peet", "caribou", "coffee bean", "costa coffee",
    "walmart", "target", "costco", "sam's club", "heb", "kroger",
    "whole foods", "trader joe", "aldi", "cvs", "walgreen",
    "holiday inn", "marriott", "hilton", "hyatt", "best western",
]

AUSTIN_BBOX = {
    "west":  -97.9383,
    "south":  30.0986,
    "east":  -97.4104,
    "north":  30.5168,
}


def _get_bbox(region: str) -> dict:
    region_cfg = config.regions.get(region, {})
    if "bbox" in region_cfg:
        return region_cfg["bbox"]
    lat = region_cfg.get("center_lat", 30.2672)
    lng = region_cfg.get("center_lng", -97.7431)
    r = region_cfg.get("radius_mi", 25) / 69.0
    return {"west": lng-r, "east": lng+r, "south": lat-r, "north": lat+r}


def _get_duckdb_conn():
    conn = duckdb.connect()
    conn.execute("INSTALL spatial; INSTALL httpfs; LOAD spatial; LOAD httpfs;")
    conn.execute("SET s3_region='us-west-2';")
    return conn


class OvertureChainAdapter(BaseScraper):
    """
    Queries Overture for chain store locations.
    Cross-validates AllThePlaces data and fills geographic gaps.
    """

    name = "overture_chain"
    chain = "starbucks"

    CHAIN_NAME_FILTERS = {
        "starbucks":     "%starbucks%",
        "dutch_bros":    "%dutch bros%",
        "mcdonalds":     "%mcdonald%",
        "target_retail": "%target%",
        "whataburger":   "%whataburger%",
    }

    def scrape(self, region: str, radius_mi: int = 25) -> list[ScraperSignal]:
        name_filter = self.CHAIN_NAME_FILTERS.get(self.chain)
        if not name_filter:
            logger.warning(f"[Overture] No filter for chain: {self.chain}")
            return []

        bbox = _get_bbox(region)

        query = f"""
        SELECT
            id,
            names.primary AS name,
            categories.primary AS category,
            addresses[1].freeform AS address,
            ST_X(geometry) AS lng,
            ST_Y(geometry) AS lat,
            confidence
        FROM read_parquet('{OVERTURE_S3}', hive_partitioning=1)
        WHERE names.primary ILIKE '{name_filter}'
        AND bbox.xmin BETWEEN {bbox['west']} AND {bbox['east']}
        AND bbox.ymin BETWEEN {bbox['south']} AND {bbox['north']}
        AND confidence > 0.8
        """

        try:
            conn = _get_duckdb_conn()
            logger.info(f"[Overture] Querying chain={self.chain} region={region}")
            rows = conn.execute(query).fetchall()
        except Exception as e:
            logger.error(f"[Overture] Chain query failed: {e}")
            return []

        cols = ["overture_id", "name", "category", "address", "lng", "lat", "confidence"]
        places = [dict(zip(cols, r)) for r in rows]
        logger.info(f"[Overture] Found {len(places)} {self.chain} locations")

        chain_cfg = config.chains.get(self.chain, {})
        signals = []

        with get_session() as session:
            for p in places:
                store_num = f"OV-{self.chain.upper()[:2]}-{p['overture_id'][-8:]}"
                existing = session.query(Store).filter_by(store_num=store_num).first()
                if existing:
                    existing.lat = p["lat"]
                    existing.lng = p["lng"]
                    existing.last_seen = datetime.utcnow()
                else:
                    session.add(Store(
                        store_num=store_num,
                        chain=self.chain,
                        industry=chain_cfg.get("industry", "unknown"),
                        store_name=p["name"],
                        address=p["address"] or "",
                        lat=p["lat"],
                        lng=p["lng"],
                        region=region,
                        first_seen=datetime.utcnow(),
                        last_seen=datetime.utcnow(),
                        is_active=True,
                    ))
                signals.append(ScraperSignal(
                    store_num=store_num,
                    chain=self.chain,
                    source=self.name,
                    signal_type="store_presence",
                    value=p["confidence"],
                    metadata={
                        "overture_id": p["overture_id"],
                        "address": p["address"],
                        "lat": p["lat"],
                        "lng": p["lng"],
                        "category": p["category"],
                    },
                    observed_at=datetime.utcnow(),
                ))
            session.commit()

        return signals


class OvertureLocalAdapter(BaseScraper):
    """
    Queries Overture for local (non-chain) employers by category.
    Populates the local_employers table used by the targeting score.
    """

    name = "overture_local"
    chain = "local"

    def scrape(self, region: str, radius_mi: int = 25) -> list[ScraperSignal]:
        bbox = _get_bbox(region)
        categories = list(CATEGORY_INDUSTRY_MAP.keys())

        cat_filter = " OR ".join(
            [f"categories.primary = '{c}'" for c in categories]
        )
        chain_filter = " AND ".join(
            [f"lower(names.primary) NOT LIKE '%{c}%'" for c in CHAIN_EXCLUSIONS]
        )

        query = f"""
        SELECT
            id,
            names.primary AS name,
            categories.primary AS category,
            addresses[1].freeform AS address,
            ST_X(geometry) AS lng,
            ST_Y(geometry) AS lat,
            confidence
        FROM read_parquet('{OVERTURE_S3}', hive_partitioning=1)
        WHERE ({cat_filter})
        AND ({chain_filter})
        AND bbox.xmin BETWEEN {bbox['west']} AND {bbox['east']}
        AND bbox.ymin BETWEEN {bbox['south']} AND {bbox['north']}
        AND confidence > 0.7
        """

        try:
            conn = _get_duckdb_conn()
            logger.info(f"[Overture] Querying local employers region={region}")
            rows = conn.execute(query).fetchall()
        except Exception as e:
            logger.error(f"[Overture] Local query failed: {e}")
            return []

        cols = ["overture_id", "name", "category", "address", "lng", "lat", "confidence"]
        places = [dict(zip(cols, r)) for r in rows]
        logger.info(f"[Overture] Found {len(places)} local employers")

        signals = []
        with get_session() as session:
            for p in places:
                industry = CATEGORY_INDUSTRY_MAP.get(p["category"], "unknown")
                existing = session.query(LocalEmployer).filter_by(
                    overture_id=p["overture_id"]
                ).first()
                if existing:
                    existing.last_seen = datetime.utcnow()
                    existing.confidence = p["confidence"]
                else:
                    session.add(LocalEmployer(
                        overture_id=p["overture_id"],
                        name=p["name"],
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
                    ))
                signals.append(ScraperSignal(
                    store_num=f"LOCAL-{p['overture_id'][-8:]}",
                    chain="local",
                    source=self.name,
                    signal_type="local_presence",
                    value=p["confidence"],
                    metadata={
                        "overture_id": p["overture_id"],
                        "name": p["name"],
                        "category": p["category"],
                        "industry": industry,
                        "address": p["address"],
                        "lat": p["lat"],
                        "lng": p["lng"],
                    },
                    observed_at=datetime.utcnow(),
                ))
            session.commit()

        return signals


if __name__ == "__main__":
    import argparse
    from backend.ingest import ingest_signals
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["chain", "local"], required=True)
    parser.add_argument("--chain", default="starbucks")
    parser.add_argument("--industry", default="coffee_cafe")
    parser.add_argument("--region", default="austin_tx")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if args.mode == "chain":
        adapter = OvertureChainAdapter()
        adapter.chain = args.chain
    else:
        adapter = OvertureLocalAdapter()

    signals = adapter.scrape(args.region)

    print(f"\n{'DRY RUN — ' if args.dry_run else ''}Found {len(signals)} locations")
    for s in signals[:5]:
        m = s.metadata
        print(f"  {s.store_num}  {m.get('name') or s.store_num}  "
              f"({m.get('lat', 0):.4f}, {m.get('lng', 0):.4f})")
    if len(signals) > 5:
        print(f"  ... and {len(signals)-5} more")

    if not args.dry_run and signals:
        ingest_signals(signals)
        print(f"Ingested {len(signals)} signals.")
```

**Run it:**
```bash
# Chain stores — cross-validate AllThePlaces data
python scrapers/overture_adapter.py --mode chain --chain starbucks --region austin_tx
python scrapers/overture_adapter.py --mode chain --chain dutch_bros --region austin_tx

# Local employers — this is new, no equivalent source exists yet
python scrapers/overture_adapter.py --mode local --industry coffee_cafe --region austin_tx
```

**Verify local_employers populated:**
```bash
python3 -c "
import sqlite3
conn = sqlite3.connect('data/tracker.db')
n = conn.execute('SELECT COUNT(*) FROM local_employers').fetchone()[0]
cats = conn.execute(
    'SELECT category, COUNT(*) FROM local_employers GROUP BY category ORDER BY 2 DESC LIMIT 8'
).fetchall()
print(f'local_employers: {n} total')
for cat, cnt in cats:
    print(f'  {cat}: {cnt}')
conn.close()
"
```

---

## Priority 4 — Wire Local Employers into Targeting Score

Once `local_employers` is populated, update `backend/targeting.py` to use
it for the `local_alternatives` score component.

Find the `_score_local_alternatives()` method (or wherever that score is
currently computed). Replace the default-50 logic with a real haversine
density calculation:

```python
def _score_local_alternatives(
    store_lat: float,
    store_lng: float,
    industry: str,
    radius_mi: float = 2.0,
    session = None
) -> float:
    """
    Count local (non-chain) employers of the same industry within radius_mi.
    More local hirers nearby = higher score = more effective job fair.
    Returns 0-100 normalized against regional max density.
    """
    if store_lat is None or store_lng is None:
        return 50.0  # neutral fallback if no coords

    from backend.database import LocalEmployer
    from backend.targeting import haversine  # already exists in targeting.py

    employers = session.query(LocalEmployer).filter_by(
        industry=industry,
        is_active=True
    ).all()

    nearby = sum(
        1 for e in employers
        if e.lat and e.lng
        and haversine(store_lat, store_lng, e.lat, e.lng) <= radius_mi
    )

    # Normalize: 5+ nearby = score 100, 0 nearby = score 0
    # Adjust the ceiling based on Austin density once you see real numbers
    return min(nearby / 5.0, 1.0) * 100
```

After patching, re-run scoring:
```bash
python3 -c "
import sys; sys.path.insert(0, '.')
from backend.scoring.engine import compute_all_scores
from collections import Counter
results = compute_all_scores('austin_tx', chain='starbucks')
print('Score distribution:', Counter(r.tier for r in results))
print('Sample targeting scores:')
for r in sorted(results, key=lambda x: x.value, reverse=True)[:3]:
    print(f'  {r.store_num}  composite={r.value:.1f}  tier={r.tier}')
"
```

---

## Priority 5 — Update the Leaflet Map Frontend

The map currently shows 10 markers. After this session it should show:
- ~35 Starbucks markers (color-coded by targeting tier)
- ~15 Dutch Bros markers
- ~30 McDonald's markers
- Local employer density overlay (optional stretch goal)

**Update `frontend/js/app.js`:**

The existing app.js fetches `/api/scores` for Starbucks only. Extend it
to accept a `chain` query param and add a chain selector to the UI.

Add a `/api/stores` endpoint to `server.py` that returns all stores with
coordinates and their current composite score:

```python
@app.route('/api/stores')
def get_stores():
    """
    Returns all stores with coordinates and scores.
    Query params: region (default austin_tx), chain (default all), industry
    """
    region = request.args.get('region', 'austin_tx')
    chain  = request.args.get('chain')
    industry = request.args.get('industry')

    with get_session() as session:
        q = session.query(Store).filter(
            Store.region == region,
            Store.is_active == True,
            Store.lat != None,
        )
        if chain:
            q = q.filter(Store.chain == chain)
        stores = q.all()

        result = []
        for s in stores:
            score_row = session.query(Score).filter_by(
                store_num=s.store_num,
                score_type='composite'
            ).first()
            result.append({
                "store_num": s.store_num,
                "chain":     s.chain,
                "name":      s.store_name,
                "address":   s.address,
                "lat":       s.lat,
                "lng":       s.lng,
                "score":     score_row.value if score_row else None,
                "tier":      score_row.tier  if score_row else "unknown",
            })

    return jsonify({"stores": result, "count": len(result)})
```

**Marker color scheme in app.js:**
```javascript
const TIER_COLORS = {
    critical: '#E24B4A',   // red
    elevated: '#EF9F27',   // amber
    adequate: '#1D9E75',   // teal
    unknown:  '#888780',   // gray
};

// Chain marker shapes — use circleMarker with different radii
const CHAIN_RADIUS = {
    starbucks:     8,
    dutch_bros:    7,
    mcdonalds:     7,
    local:         5,
};
```

**Add `/api/local-employers` endpoint** to `server.py` for the map layer:
```python
@app.route('/api/local-employers')
def get_local_employers():
    region   = request.args.get('region', 'austin_tx')
    industry = request.args.get('industry')

    with get_session() as session:
        q = session.query(LocalEmployer).filter_by(
            region=region, is_active=True
        )
        if industry:
            q = q.filter_by(industry=industry)
        employers = q.all()
        return jsonify({
            "employers": [
                {"name": e.name, "category": e.category, "industry": e.industry,
                 "address": e.address, "lat": e.lat, "lng": e.lng}
                for e in employers if e.lat and e.lng
            ]
        })
```

---

## Priority 6 — Add OSM Adapter to Scheduler

The `osm_adapter.py` was built in Session 6 but not added to the scheduler.
Add it now alongside the new adapters.

In `backend/scheduler.py`, add:

```python
# OSM + AllThePlaces store discovery — weekly Sunday 2am
scheduler.add_job(
    run_scraper, 'cron', day_of_week='sun', hour=2,
    args=['alltheplaces', 'starbucks', 'austin_tx'],
    id='atp_starbucks_austin'
)
scheduler.add_job(
    run_scraper, 'cron', day_of_week='sun', hour=2, minute=15,
    args=['overture_chain', 'starbucks', 'austin_tx'],
    id='overture_starbucks_austin'
)
scheduler.add_job(
    run_scraper, 'cron', day_of_week='sun', hour=3,
    args=['overture_local', None, 'austin_tx'],
    id='overture_local_austin'
)
scheduler.add_job(
    run_scraper, 'cron', day_of_week='sun', hour=2, minute=30,
    args=['osm_adapter', 'starbucks', 'austin_tx'],
    id='osm_starbucks_austin'
)
```

These are weekly — store locations don't change often. Discovery runs are
also slow (DuckDB S3 queries take 30-60 seconds) so they must not overlap
with the daily signal scrapers. Schedule them all Sunday early morning.

---

## Verification Sequence

Run this after completing all priorities:

```bash
cd /home/fortune/CodeProjects/First-Helios
source .venv/bin/activate

# 1. Store counts per chain
python3 -c "
import sqlite3
conn = sqlite3.connect('data/tracker.db')
print('=== Stores by chain ===')
for row in conn.execute('SELECT chain, COUNT(*) FROM stores GROUP BY chain ORDER BY 2 DESC'):
    print(f'  {row[0]}: {row[1]}')
print()
print('=== Local employers by category ===')
for row in conn.execute('SELECT category, COUNT(*) FROM local_employers GROUP BY category ORDER BY 2 DESC LIMIT 10'):
    print(f'  {row[0]}: {row[1]}')
null = conn.execute('SELECT COUNT(*) FROM stores WHERE lat IS NULL').fetchone()[0]
print(f'\nStores with null coords: {null}  (target: 0)')
conn.close()
"

# 2. Score distribution across expanded store set
python3 -c "
import sys; sys.path.insert(0, '.')
from backend.scoring.engine import compute_all_scores
from collections import Counter
results = compute_all_scores('austin_tx', chain='starbucks')
print(f'Scored {len(results)} Starbucks stores  (target: ~35)')
print(Counter(r.tier for r in results))
"

# 3. API endpoints
python server.py &
sleep 2

curl -s "http://localhost:8765/api/stores?region=austin_tx&chain=starbucks" \
    | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'stores API: {d[\"count\"]} stores')"

curl -s "http://localhost:8765/api/local-employers?region=austin_tx&industry=coffee_cafe" \
    | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'local employers API: {len(d[\"employers\"])} locations')"

curl -s "http://localhost:8765/api/targeting?industry=coffee_cafe&region=austin_tx&limit=5" \
    | python3 -m json.tool | grep -E '"address|targeting_score|tier"'

# 4. Open map — should show multi-chain markers with tier colors
# http://localhost:8765
```

---

## What Done Looks Like

| Metric | Before | After |
|--------|--------|-------|
| Starbucks stores in DB | 10 | ~35 |
| Dutch Bros stores | 0 | ~15 |
| McDonald's stores | 0 | ~30 |
| Local employers in DB | 0 | 200+ |
| local_alternatives score | Default 50 | Real density |
| Map markers | 10 (Starbucks only) | ~80+ (multi-chain, color-coded) |
| New tables | — | `local_employers` |
| New API endpoints | — | `/api/stores`, `/api/local-employers` |

---

## Do Not Touch

- `data/spiritpool.db` — never write to it
- `spiritpool/` directory — on hiatus
- Flask port — stays 8765
- `python scraper/scrape.py --location "Austin, TX, US"` — must keep working
- Existing frontend CSS — add to `app.js` only, do not restyle

---

## Known Gotchas

**DuckDB S3 queries are slow on first run.**
The `spatial` and `httpfs` extensions download and install on first use (~30 seconds).
Subsequent queries are faster. Do not mistake the first-run pause for a hang.

**Overture release version.**
`OVERTURE_RELEASE = "2026-02-18.0"` is the version as of this writing.
Check https://docs.overturemaps.org/release/latest/ and update if a newer
release is available. Queries against an old release still work but miss
newer locations.

**AllThePlaces GeoJSON may be large.**
The Starbucks global GeoJSON is ~8MB. The filter to Austin bbox happens
in memory after download. This is fine — but do not attempt to load the
McDonald's full file (~80MB) without filtering immediately.

**Chain exclusion list in OvertureLocalAdapter.**
The `CHAIN_EXCLUSIONS` list filters known chains from the local employer
query. If a known chain appears in local_employers results, add its name
to the list. Err on the side of over-excluding rather than polluting the
local employer index with chains.

**Store deduplication across sources.**
The same physical Starbucks may appear as `ATP-SB-12345` (AllThePlaces),
`OV-SB-abcd1234` (Overture), and `OSM-SB-67890` (OpenStreetMap).
These are three separate rows in the `stores` table right now — that is
acceptable for this session. A deduplication pass (matching by coordinate
proximity < 50m + same chain) is future work, not this session.
