# Fraud Geo Hub — Project Sketch

**Language:** Rust (Cargo workspace)
**Focus:** Efficiency-first local geospatial fraud analytics
**Database:** DuckDB (local, zero-config) → Delta Lake (Databricks sync path)
**Maps:** Offline PMTiles + martin tile server
**Future:** Arrow Flight SQL bridge to Databricks

---

## Why Rust for This

- DuckDB's Rust binding is the same engine used in production analytics — no overhead
- `h3o` is pure Rust H3 (no C FFI), fast hexagonal clustering with no install friction
- DataFusion queries Parquet/GeoParquet natively — Overture public data loads directly
- `deltalake` crate writes Delta format locally; Databricks reads it with zero ETL
- `martin` tile server is already Rust — PMTiles served from localhost with no extra process

---

## Project Layout

```
fraud-geo-hub/
│
├── Cargo.toml                  # Workspace root
│
├── crates/
│   ├── core/                   # Shared types — no external deps except geo primitives
│   │   ├── src/
│   │   │   ├── lib.rs
│   │   │   ├── types.rs        # FraudRecord, GeoPoint, H3Cell, RiskScore
│   │   │   ├── region.rs       # BBox, RegionConfig — center + radius → bounds
│   │   │   └── error.rs        # Hub-wide error type
│   │   └── Cargo.toml
│   │
│   ├── ingest/                 # Pull public geo data into local DuckDB
│   │   ├── src/
│   │   │   ├── lib.rs
│   │   │   ├── overture.rs     # Read Overture GeoParquet (POIs, buildings, addresses)
│   │   │   ├── tiger.rs        # Census TIGER shapefiles (ZIP, county, tract boundaries)
│   │   │   ├── csv.rs          # Generic CSV ingest with address → H3 indexing
│   │   │   └── normalize.rs    # Address normalization (trim, uppercase, dedup)
│   │   └── Cargo.toml
│   │
│   ├── store/                  # Database layer — DuckDB writes, Delta Lake export
│   │   ├── src/
│   │   │   ├── lib.rs
│   │   │   ├── duck.rs         # DuckDB connection pool, spatial extension init
│   │   │   ├── schema.sql      # CREATE TABLE statements (embedded at compile time)
│   │   │   ├── queries.rs      # Parameterized query functions (no raw SQL in business logic)
│   │   │   └── delta.rs        # Write analytics results as Delta Lake tables
│   │   └── Cargo.toml
│   │
│   ├── analytics/              # Fraud detection algorithms — pure functions, no I/O
│   │   ├── src/
│   │   │   ├── lib.rs
│   │   │   ├── clustering.rs   # H3 cell density — flag cells above threshold
│   │   │   ├── velocity.rs     # Event rate per H3 cell in rolling time window
│   │   │   ├── colocation.rs   # Multiple distinct entities at same address/cell
│   │   │   ├── outlier.rs      # Statistical anomaly on geo density (z-score / IQR)
│   │   │   └── score.rs        # Aggregate risk score per record/cell/region
│   │   └── Cargo.toml
│   │
│   ├── api/                    # Axum HTTP API — serves analytics results + map data
│   │   ├── src/
│   │   │   ├── main.rs
│   │   │   ├── routes/
│   │   │   │   ├── mod.rs
│   │   │   │   ├── map.rs      # GET /api/map?bbox=...&h3_res=8 → GeoJSON
│   │   │   │   ├── fraud.rs    # GET /api/fraud/cells → H3 cells with risk scores
│   │   │   │   ├── query.rs    # POST /api/query → ad-hoc DuckDB SQL (internal only)
│   │   │   │   └── ingest.rs   # POST /api/ingest → trigger data pull
│   │   │   ├── state.rs        # AppState: DuckDB pool, config
│   │   │   └── error.rs        # Axum error responses
│   │   └── Cargo.toml
│   │
│   └── sync/                   # Databricks bridge — write-only initially
│       ├── src/
│       │   ├── lib.rs
│       │   ├── delta_writer.rs # Flush local analytics tables → Delta Lake files
│       │   ├── flight.rs       # Arrow Flight SQL client (future: live query pushdown)
│       │   └── schema_map.rs   # Map local DuckDB types → Arrow schema for Databricks
│       └── Cargo.toml
│
├── frontend/                   # Minimal MapLibre GL + PMTiles (no Node build needed)
│   ├── index.html              # Single-file app, CDN MapLibre + pmtiles.js
│   ├── app.js                  # Fetch /api/fraud/cells, render H3 heatmap layer
│   └── style.json              # Dark map style referencing local PMTiles
│
├── data/
│   ├── tiles/
│   │   └── texas.pmtiles       # Download once from Protomaps — ~3GB Texas extract
│   ├── raw/
│   │   ├── overture/           # GeoParquet files (POIs, addresses, buildings)
│   │   └── tiger/              # Census TIGER shapefiles
│   └── db/
│       ├── hub.duckdb          # Live analytics database
│       └── delta/              # Delta Lake tables (synced to Databricks)
│           ├── fraud_cells/
│           ├── risk_scores/
│           └── events/
│
├── config/
│   ├── default.toml            # Region bboxes, H3 resolution, thresholds
│   └── databricks.toml         # Flight SQL endpoint, catalog, schema (gitignored)
│
└── scripts/
    ├── download_tiles.sh       # Pull texas.pmtiles from Protomaps public CDN
    ├── download_overture.sh    # Pull Texas POIs from Overture S3 (public, free)
    └── download_tiger.sh       # Pull Census TIGER TX files
```

---

## Key Crates per Layer

| Crate | Version | Layer | Role |
|-------|---------|-------|------|
| `duckdb` | 1.x | store | Local analytics DB, spatial queries |
| `datafusion` | 51 | analytics | Parquet/GeoParquet query engine |
| `h3o` | latest | analytics | Pure Rust H3 — no C dependency |
| `geo` | latest | core | Geometry types, BBox, distance math |
| `geozero` | 0.15 | ingest | Zero-copy format conversion (WKB→Rust) |
| `arrow` | 57 | sync | In-memory columnar format |
| `deltalake` | latest | sync | Write Delta tables for Databricks |
| `arrow-flight` | latest | sync | Flight SQL client (Databricks live query) |
| `object_store` | 0.13 | sync | S3/ADLS write path for Delta files |
| `axum` | 0.8 | api | HTTP server |
| `tokio` | 1 | api | Async runtime |
| `serde` + `serde_json` | latest | all | Serialization |
| `toml` | latest | config | Config file parsing |

**martin** runs as a separate binary (installed via `cargo install martin`), not a crate dependency.

---

## Data Flow

```
Public data (Overture GeoParquet, Census TIGER)
  ↓ crates/ingest
  ↓ normalize addresses → H3 index each record
  ↓
DuckDB (data/db/hub.duckdb)
  - spatial extension enabled
  - tables: events, poi_index, h3_cells, risk_scores
  ↓
crates/analytics
  - clustering.rs:   GROUP BY h3_cell → density per cell
  - velocity.rs:     sliding window event count per cell
  - colocation.rs:   COUNT DISTINCT entities WHERE h3_cell = ?
  - score.rs:        weighted sum → risk_score per cell
  ↓
crates/api  (GET /api/fraud/cells)
  → GeoJSON FeatureCollection of H3 cells with risk_score property
  ↓
frontend/app.js
  → MapLibre GL H3 fill-extrusion layer (height = risk_score)
  → PMTiles base map served by martin at localhost:3000

                          ↓ (async, scheduled)
crates/sync/delta_writer.rs
  → Flush risk_scores + events → data/db/delta/
  → object_store writes to ADLS/S3 if Databricks endpoint configured
  → Databricks reads Delta table natively — no ETL, no connector
```

---

## Databricks Connection Path

Two stages, implement in order:

**Stage 1 — Delta Lake files (implement now, no Databricks account needed)**
- `deltalake` crate writes analytics results to `data/db/delta/`
- If you have Databricks later: point it at the S3/ADLS path, register as external table
- Zero code change on the Rust side — same Delta write, different `object_store` target

**Stage 2 — Arrow Flight SQL live queries (future)**
- Databricks exposes a Flight SQL endpoint
- `arrow-flight` crate with `flight-sql` feature connects to it
- Pushes queries down to Databricks cluster — returns Arrow RecordBatches
- Useful when local data volume exceeds single-machine capacity

```toml
# config/databricks.toml (gitignored)
[flight_sql]
endpoint = "https://<workspace>.azuredatabricks.net/cliservice/arrow-flight-sql"
token = "${DATABRICKS_TOKEN}"
catalog = "fraud_hub"
schema = "geo_analytics"
```

---

## Texas Region Config

```toml
# config/default.toml

[region.texas]
display_name = "Texas"
bbox = { west = -106.65, east = -93.50, south = 25.84, north = 36.50 }
h3_resolution = 8          # ~0.5 mile hex cells — good for urban fraud clustering
chain_threshold = 5        # locations >= 5 = branded chain vs local business
risk_threshold = 0.65      # cells above this score are flagged

[region.austin_msa]
display_name = "Austin–Round Rock"
center = { lat = 30.2672, lng = -97.7431 }
radius_mi = 25
h3_resolution = 9          # ~0.2 mile cells — finer grain for dense areas
```

---

## Public Data Sources (No License Risk)

| Dataset | Source | Format | Texas Size |
|---------|--------|--------|-----------|
| POIs + addresses | Overture Maps S3 | GeoParquet | ~800MB |
| Streets + buildings | Geofabrik OSM TX | PBF | ~1.2GB |
| ZIP / county / tract | Census TIGER 2023 | Shapefile | ~200MB |
| Base map tiles | Protomaps TX extract | PMTiles | ~3GB |

All are public domain or CC-BY. No API key required. One-time download via `scripts/`.

---

## What Is NOT in This Project

To keep IP clean:
- No employer scoring logic from First-Helios
- No Spirit Pool extension code
- No BLS labor market baseline
- No name normalization from `backend/normalizer.py`
- No staffing stress or mobility scoring

The H3 clustering and risk scoring here are generic spatial analytics patterns, not derived from any proprietary system.
