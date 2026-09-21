"""Read Austin/Round Rock food POIs from the Overture Maps Places release.

Overture publishes GeoParquet on a public S3 bucket. DuckDB with ``httpfs``
pushes the bounding-box and category filter down to the remote files, so only
the metro's food venues are read. The parquet ``bbox`` struct is used both for
the spatial filter and to read each point's coordinates, which avoids needing
the spatial extension or WKB decoding.

This module is the one place that touches DuckDB and the network. The pipeline
consumes plain :class:`OverturePoi` values, so tests inject fixtures and CI
makes no live calls (ADR-0009 §1).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import duckdb

if TYPE_CHECKING:
    from collections.abc import Iterator

# Overture's public GeoParquet release. Override per run; releases are monthly.
DEFAULT_RELEASE = (
    "s3://overturemaps-us-west-2/release/2026-08-19.0/theme=places/type=place/*.parquet"
)
DEFAULT_S3_REGION = "us-west-2"

# Travis + Williamson counties (ADR-0009): a coarse coverage bound. Viewing
# filters precisely later, so a bbox (not a polygon) is intentional here.
AUSTIN_METRO_BBOX_LAT = (30.02, 30.85)
AUSTIN_METRO_BBOX_LON = (-98.17, -97.37)

# Overture Places category leaves that denote a food/beverage venue. Overridable;
# the ``%restaurant%`` fallback catches the long tail of cuisine-specific leaves.
DEFAULT_FOOD_CATEGORIES: tuple[str, ...] = (
    "restaurant",
    "cafe",
    "coffee_shop",
    "bar",
    "pub",
    "fast_food",
    "bakery",
    "food_truck",
    "food_court",
    "ice_cream_shop",
    "juice_bar",
    "brewery",
    "diner",
    "bistro",
    "deli",
)


@dataclass(frozen=True, slots=True)
class MetroBbox:
    """A lat/lon coverage bound (inclusive)."""

    lat_min: float
    lat_max: float
    lon_min: float
    lon_max: float

    @classmethod
    def austin(cls) -> MetroBbox:
        return cls(
            lat_min=AUSTIN_METRO_BBOX_LAT[0],
            lat_max=AUSTIN_METRO_BBOX_LAT[1],
            lon_min=AUSTIN_METRO_BBOX_LON[0],
            lon_max=AUSTIN_METRO_BBOX_LON[1],
        )


@dataclass(frozen=True, slots=True)
class OvertureConfig:
    """Everything needed to fetch one metro's food POIs from a release."""

    release: str = DEFAULT_RELEASE
    s3_region: str = DEFAULT_S3_REGION
    bbox: MetroBbox = field(default_factory=MetroBbox.austin)
    food_categories: tuple[str, ...] = DEFAULT_FOOD_CATEGORIES


@dataclass(frozen=True, slots=True)
class OverturePoi:
    """One source-faithful Overture food POI ready for Bronze admission."""

    gers_id: str
    name: str
    primary_category: str | None
    alternate_categories: tuple[str, ...]
    websites: tuple[str, ...]
    address: str | None
    latitude: float | None
    longitude: float | None
    confidence: float | None
    raw: dict[str, Any]


def _select_sql(food_categories: tuple[str, ...]) -> str:
    placeholders = ", ".join("?" for _ in food_categories)
    category_filter = (
        f"(categories.primary IN ({placeholders}) OR categories.primary LIKE '%restaurant%')"
        if food_categories
        else "categories.primary LIKE '%restaurant%'"
    )
    return f"""
        SELECT
            id,
            names.primary AS name,
            categories.primary AS primary_category,
            categories.alternate AS alternate_categories,
            websites,
            addresses,
            bbox.xmin AS longitude,
            bbox.ymin AS latitude,
            confidence
        FROM read_parquet(?, hive_partitioning => true, union_by_name => true)
        WHERE bbox.xmin BETWEEN ? AND ?
          AND bbox.ymin BETWEEN ? AND ?
          AND names.primary IS NOT NULL
          AND categories.primary IS NOT NULL
          AND {category_filter}
    """


def _format_address(addresses: object) -> str | None:
    if not isinstance(addresses, list) or not addresses:
        return None
    first = addresses[0]
    if not isinstance(first, dict):
        return None
    parts = [
        str(first[key]).strip()
        for key in ("freeform", "locality", "region", "postcode")
        if first.get(key)
    ]
    return ", ".join(parts) or None


def _as_str_tuple(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(str(item) for item in value if item)


def _to_poi(row: dict[str, Any]) -> OverturePoi:
    return OverturePoi(
        gers_id=str(row["id"]),
        name=str(row["name"]),
        primary_category=(
            str(row["primary_category"]) if row.get("primary_category") is not None else None
        ),
        alternate_categories=_as_str_tuple(row.get("alternate_categories")),
        websites=_as_str_tuple(row.get("websites")),
        address=_format_address(row.get("addresses")),
        latitude=float(row["latitude"]) if row.get("latitude") is not None else None,
        longitude=float(row["longitude"]) if row.get("longitude") is not None else None,
        confidence=float(row["confidence"]) if row.get("confidence") is not None else None,
        raw=row,
    )


def read_overture_pois(
    config: OvertureConfig | None = None,
    *,
    connection: duckdb.DuckDBPyConnection | None = None,
    batch_size: int = 1000,
) -> Iterator[OverturePoi]:
    """Yield food POIs within the configured metro bbox from an Overture release."""
    config = config or OvertureConfig()
    con = connection or duckdb.connect()
    try:
        con.execute("INSTALL httpfs; LOAD httpfs;")
        con.execute(f"SET s3_region='{config.s3_region}';")
        # Param order matches the ? order in _select_sql: read_parquet path, then
        # the bbox lon/lat bounds, then the category placeholders.
        ordered: list[Any] = [
            config.release,
            config.bbox.lon_min,
            config.bbox.lon_max,
            config.bbox.lat_min,
            config.bbox.lat_max,
            *config.food_categories,
        ]
        cursor = con.execute(_select_sql(config.food_categories), ordered)
        columns = [description[0] for description in cursor.description or []]
        while True:
            rows = cursor.fetchmany(batch_size)
            if not rows:
                break
            for row in rows:
                yield _to_poi(dict(zip(columns, row, strict=True)))
    finally:
        if connection is None:
            con.close()
