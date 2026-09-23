"""CLI: seed discovered Austin/Round Rock food venues from Overture.

Idempotent and re-runnable (ADR-0009 §3): determinism comes from the stable GERS
key, so re-running a release adds nothing. Run on the Orange Pi against the
staging database::

    python -m apps.discovery --release <overture-parquet-glob>

Reads live Overture parquet over S3 and geocodes coordinate gaps via Nominatim,
so it makes network calls and is not exercised in CI.
"""

from __future__ import annotations

import argparse
import re
from datetime import UTC, datetime
from pathlib import Path

from apps.discovery.overture import DEFAULT_RELEASE, MetroBbox, OvertureConfig, read_overture_pois
from apps.discovery.pipeline import DEFAULT_DEDUPE_RADIUS_M, run_discovery
from packages.helios_core.db.session import get_sessionmaker
from packages.helios_core.geo import NominatimClient

_USER_AGENT = "helios-v2-discovery/0.1 (+https://github.com/First-Helios/First-Helios)"
_RELEASE_DATE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")


def _observed_at(release: str) -> datetime:
    """Use the release date as the observation time so a re-run of it is a no-op."""
    match = _RELEASE_DATE.search(release)
    if match is None:
        return datetime.now(UTC)
    year, month, day = (int(part) for part in match.groups())
    return datetime(year, month, day, tzinfo=UTC)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="python -m apps.discovery", description=__doc__)
    parser.add_argument("--release", default=DEFAULT_RELEASE, help="Overture parquet path/glob")
    bbox = MetroBbox.austin()
    parser.add_argument("--lat-min", type=float, default=bbox.lat_min)
    parser.add_argument("--lat-max", type=float, default=bbox.lat_max)
    parser.add_argument("--lon-min", type=float, default=bbox.lon_min)
    parser.add_argument("--lon-max", type=float, default=bbox.lon_max)
    parser.add_argument("--dedupe-radius-m", type=float, default=DEFAULT_DEDUPE_RADIUS_M)
    parser.add_argument("--geocode-cache", type=Path, default=Path("var/geocode"))
    parser.add_argument(
        "--no-geocode", action="store_true", help="skip Nominatim gap-fill for missing coordinates"
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    config = OvertureConfig(
        release=args.release,
        bbox=MetroBbox(
            lat_min=args.lat_min,
            lat_max=args.lat_max,
            lon_min=args.lon_min,
            lon_max=args.lon_max,
        ),
    )
    observed_at = _observed_at(args.release)
    decided_at = datetime.now(UTC)

    geocoder = (
        None
        if args.no_geocode
        else NominatimClient(cache_dir=args.geocode_cache, user_agent=_USER_AGENT)
    )
    try:
        with get_sessionmaker()() as session:
            report = run_discovery(
                session,
                read_overture_pois(config),
                decided_at=decided_at,
                observed_at=observed_at,
                release=args.release,
                geocoder=geocoder,
                dedupe_radius_m=args.dedupe_radius_m,
                on_batch=session.commit,  # commit every 100 POIs (D3.3)
            )
            session.commit()
    finally:
        if geocoder is not None:
            geocoder.close()

    print(  # noqa: T201 - CLI output
        "discovery complete: "
        f"fetched={report.fetched} minted={report.minted} deduped={report.deduped} "
        f"reused={report.reused} ambiguous={report.ambiguous} "
        f"needs_review={report.needs_review} geocoded={report.geocoded} skipped={report.skipped}"
    )


if __name__ == "__main__":
    main()
