"""Phase 4 precision audit: measure duplicate-venue and geocode error rates.

ADR-0009 and ROADMAP Phase 4 gate discovery on a seeded metro with **< 2%
duplicate venues** and **< 1% wrong geocodes**, both measured against a
hand-labeled 100-row sample (plus written-down website coverage). This module is
the reproducible measurement behind those numbers.

It reads a venue export (the ``psql`` dump documented in the Phase 4 retro),
finds duplicate *candidates* and geocode anomalies, draws a deterministic
sample, and computes the two rates from a worksheet a human confirms
(``auto + confirm flags``): the detectors suggest a label, a reviewer corrects
the ambiguous ones, and the rates are recomputed from the confirmed labels.

Pure and DB-free: the detectors take plain :class:`VenueRow` values so they
unit-test without a database. The only I/O is reading the export, an optional
Nominatim cross-check (reusing the disk-cached client from
:mod:`packages.helios_core.geo`, so a re-run never re-queries), and reading and
writing JSON worksheets.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from apps.discovery.overture import MetroBbox
from packages.helios_core.geo import NominatimClient
from packages.helios_core.identity.normalize import haversine_m

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from packages.helios_core.geo import GeoPoint


class Geocoder(Protocol):
    """The one method :func:`geocode_crosscheck` needs (a mock supplies it in tests)."""

    def geocode(self, query: str) -> GeoPoint | None: ...


# Detector thresholds. A duplicate is a pair close in space *and* similar in
# name; the values are deliberately permissive so the candidate net has high
# recall — a human confirms each one, and a false candidate is cheap while a
# missed duplicate is not (ADR-0004 §3).
DEFAULT_SAME_FP_RADIUS_M = 150.0  # identical fingerprint this close is one venue's twin POI
DEFAULT_FUZZY_RATIO = 0.85  # near-identical names (a fingerprint miss like "Austins"/"Austin")
DEFAULT_FUZZY_RADIUS_M = 75.0
DEFAULT_ADDR_RATIO = 0.72  # looser name bar when the street address is identical
DEFAULT_SAMPLE_SIZE = 100
DEFAULT_GEOCODE_TOLERANCE_M = 150.0  # Overture coord vs geocoded-from-address disagreement
_GRID_PRECISION = 2  # ~1.1 km cells; a 3x3 neighborhood covers every radius used here
_USER_AGENT = "helios-v2-audit/0.1 (+https://github.com/First-Helios/First-Helios)"

# A suite clause is the keyword plus the identifier that follows it ("Ste C",
# "#200"); dropping both keeps the key suite-invariant no matter where the clause
# sits in the freeform string.
_SUITE = re.compile(r"\b(?:ste|suite|unit|bldg|building|apt|fl|floor|rm|#)\b\s*\S*")
_ZIP = re.compile(r"\b\d{5}(?:-?\d{4})?\b")
_NON_ADDR = re.compile(r"[^0-9a-z ]+")


@dataclass(frozen=True, slots=True)
class VenueRow:
    """One current establishment, flattened from identity for the audit."""

    subject_id: int
    name: str
    fingerprint: str
    latitude: float | None
    longitude: float | None
    address: str | None


@dataclass(frozen=True, slots=True)
class DupCandidate:
    """A pair of establishments that may be the same real-world venue."""

    a: VenueRow
    b: VenueRow
    distance_m: float
    name_ratio: float
    same_street: bool
    suggested: str  # "duplicate" | "review"


@dataclass(frozen=True, slots=True)
class GeoCrossCheck:
    """One venue's Overture coordinate vs the geocode of its own address."""

    venue: VenueRow
    distance_m: float | None  # None when the address did not geocode
    flagged: bool


def load_venues(path: Path) -> list[VenueRow]:
    """Load a venue export: a JSON array of ``{subject_id,name,fingerprint,lat,lon,address}``."""
    raw: list[dict[str, Any]] = json.loads(path.read_text(encoding="utf-8"))
    return [
        VenueRow(
            subject_id=int(row["subject_id"]),
            name=str(row["name"]),
            fingerprint=str(row["fingerprint"]),
            latitude=None if row.get("lat") is None else float(row["lat"]),
            longitude=None if row.get("lon") is None else float(row["lon"]),
            address=None if row.get("address") is None else str(row["address"]),
        )
        for row in raw
    ]


def street_key(address: str | None) -> str:
    """Coarse physical-location key: the street line, minus suite clause and ZIP."""
    if not address:
        return ""
    street_line = address.split(",")[0].lower()
    without_suite = _SUITE.sub(" ", street_line)
    without_zip = _ZIP.sub(" ", without_suite)
    return " ".join(_NON_ADDR.sub(" ", without_zip).split())


def name_similarity(a: str, b: str) -> float:
    """Ratio in ``[0, 1]`` between two name fingerprints (1.0 == identical)."""
    return SequenceMatcher(None, a, b).ratio()


def _suggest(same_street: bool, name_ratio: float) -> str:
    """A same-address, clearly-same-name pair is a duplicate; anything else is reviewed.

    Different business names at one address (ghost kitchens, tenant succession)
    and same-name chains at *different* addresses are exactly the cases a human
    must rule on, so they are surfaced as ``review`` rather than auto-merged.
    """
    if same_street and name_ratio >= 0.90:
        return "duplicate"
    return "review"


def _grid_cell(latitude: float, longitude: float) -> tuple[float, float]:
    return (round(latitude, _GRID_PRECISION), round(longitude, _GRID_PRECISION))


def find_dup_candidates(
    venues: Iterable[VenueRow],
    *,
    same_fp_radius_m: float = DEFAULT_SAME_FP_RADIUS_M,
    fuzzy_ratio: float = DEFAULT_FUZZY_RATIO,
    fuzzy_radius_m: float = DEFAULT_FUZZY_RADIUS_M,
    addr_ratio: float = DEFAULT_ADDR_RATIO,
) -> list[DupCandidate]:
    """Find every pair that is close in space and similar in name.

    A pair ``(a, b)`` is a candidate when it is co-located and either shares a
    name fingerprint, has near-identical names, or shares a street address with
    a looser name match. Chains with the same name at *different* addresses land
    in the list too (same fingerprint within the radius) but are suggested for
    review, not auto-labeled duplicate.
    """
    with_coords = [v for v in venues if v.latitude is not None and v.longitude is not None]
    grid: dict[tuple[float, float], list[VenueRow]] = {}
    for venue in with_coords:
        assert venue.latitude is not None and venue.longitude is not None  # narrowed above
        grid.setdefault(_grid_cell(venue.latitude, venue.longitude), []).append(venue)

    step = 10 ** (-_GRID_PRECISION)
    candidates: list[DupCandidate] = []
    seen: set[tuple[int, int]] = set()
    for venue in with_coords:
        assert venue.latitude is not None and venue.longitude is not None
        cell_lat, cell_lon = _grid_cell(venue.latitude, venue.longitude)
        for d_lat in (-1, 0, 1):
            for d_lon in (-1, 0, 1):
                neighbor_cell = (
                    round(cell_lat + d_lat * step, _GRID_PRECISION),
                    round(cell_lon + d_lon * step, _GRID_PRECISION),
                )
                for other in grid.get(neighbor_cell, ()):
                    if other.subject_id <= venue.subject_id:
                        continue
                    assert other.latitude is not None and other.longitude is not None
                    key = (venue.subject_id, other.subject_id)
                    if key in seen:
                        continue
                    distance = haversine_m(
                        venue.latitude, venue.longitude, other.latitude, other.longitude
                    )
                    ratio = name_similarity(venue.fingerprint, other.fingerprint)
                    same_street = bool(
                        street_key(venue.address)
                        and street_key(venue.address) == street_key(other.address)
                    )
                    same_fp = venue.fingerprint == other.fingerprint
                    is_candidate = (
                        (same_fp and distance <= same_fp_radius_m)
                        or (ratio >= fuzzy_ratio and distance <= fuzzy_radius_m)
                        or (same_street and ratio >= addr_ratio and distance <= same_fp_radius_m)
                    )
                    if not is_candidate:
                        continue
                    seen.add(key)
                    candidates.append(
                        DupCandidate(
                            a=venue,
                            b=other,
                            distance_m=round(distance, 1),
                            name_ratio=round(ratio, 3),
                            same_street=same_street,
                            suggested=_suggest(same_street, ratio),
                        )
                    )
    candidates.sort(key=lambda c: (c.suggested != "duplicate", -c.name_ratio, c.distance_m))
    return candidates


def structural_geocode_flags(
    venues: Iterable[VenueRow], *, bbox: MetroBbox | None = None
) -> list[VenueRow]:
    """Venues with a missing coordinate or one outside the ingest bounding box."""
    box = bbox or MetroBbox.austin()
    flagged: list[VenueRow] = []
    for venue in venues:
        if venue.latitude is None or venue.longitude is None:
            flagged.append(venue)
            continue
        in_box = (
            box.lat_min <= venue.latitude <= box.lat_max
            and box.lon_min <= venue.longitude <= box.lon_max
        )
        if not in_box:
            flagged.append(venue)
    return flagged


def sample_venues(
    venues: Sequence[VenueRow], *, size: int = DEFAULT_SAMPLE_SIZE, seed: str = "phase4-audit"
) -> list[VenueRow]:
    """A deterministic, uniform sample keyed by subject id (reproducible across runs)."""

    def rank(venue: VenueRow) -> str:
        return hashlib.sha256(f"{seed}:{venue.subject_id}".encode()).hexdigest()

    return sorted(venues, key=rank)[:size]


def geocode_crosscheck(
    venues: Iterable[VenueRow],
    geocoder: Geocoder,
    *,
    tolerance_m: float = DEFAULT_GEOCODE_TOLERANCE_M,
) -> list[GeoCrossCheck]:
    """Compare each venue's Overture coordinate to the geocode of its own address.

    A disagreement beyond ``tolerance_m`` (or an address that does not geocode)
    is flagged for a human to rule "wrong geocode" or not.
    """
    results: list[GeoCrossCheck] = []
    for venue in venues:
        if venue.latitude is None or venue.longitude is None:
            results.append(GeoCrossCheck(venue=venue, distance_m=None, flagged=True))
            continue
        point = geocoder.geocode(venue.address) if venue.address else None
        if point is None:
            results.append(GeoCrossCheck(venue=venue, distance_m=None, flagged=True))
            continue
        distance = haversine_m(venue.latitude, venue.longitude, point.latitude, point.longitude)
        results.append(
            GeoCrossCheck(
                venue=venue, distance_m=round(distance, 1), flagged=distance > tolerance_m
            )
        )
    return results


def duplicate_rate(confirmed_duplicates: int, total_venues: int) -> float:
    """Redundant venues as a fraction of the corpus (each duplicate pair is one)."""
    return 0.0 if total_venues == 0 else confirmed_duplicates / total_venues


def _geocode_flag_dict(check: GeoCrossCheck) -> dict[str, Any]:
    # A far geocode suggests wrong coordinates; no geocode at all only says the
    # address didn't resolve, so a reviewer decides.
    suggested = "wrong" if check.distance_m is not None else "review"
    return {
        "id": check.venue.subject_id,
        "name": check.venue.name,
        "address": check.venue.address,
        "distance_m": check.distance_m,
        "suggested": suggested,
        "label": suggested,  # a reviewer edits this to "wrong" or "ok"
    }


def _candidate_dict(candidate: DupCandidate) -> dict[str, Any]:
    return {
        "distance_m": candidate.distance_m,
        "name_ratio": candidate.name_ratio,
        "same_street": candidate.same_street,
        "suggested": candidate.suggested,
        "label": candidate.suggested,  # a reviewer edits this to "duplicate" or "distinct"
        "a": {
            "id": candidate.a.subject_id,
            "name": candidate.a.name,
            "address": candidate.a.address,
        },
        "b": {
            "id": candidate.b.subject_id,
            "name": candidate.b.name,
            "address": candidate.b.address,
        },
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="python -m apps.discovery.audit", description=__doc__)
    parser.add_argument("--export", type=Path, required=True, help="venue export JSON (psql dump)")
    parser.add_argument("--worksheet", type=Path, default=Path("var/audit_worksheet.json"))
    parser.add_argument("--sample-size", type=int, default=DEFAULT_SAMPLE_SIZE)
    parser.add_argument(
        "--geocode-check",
        action="store_true",
        help="cross-check the sample's coordinates against Nominatim (makes network calls)",
    )
    parser.add_argument("--geocode-cache", type=Path, default=Path("var/geocode"))
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    venues = load_venues(args.export)
    candidates = find_dup_candidates(venues)
    structural = structural_geocode_flags(venues)
    sample = sample_venues(venues, size=args.sample_size)

    geo_checks: list[GeoCrossCheck] = []
    if args.geocode_check:
        with NominatimClient(cache_dir=args.geocode_cache, user_agent=_USER_AGENT) as geocoder:
            geo_checks = geocode_crosscheck(sample, geocoder)

    worksheet: dict[str, Any] = {
        "total_venues": len(venues),
        "sample_size": len(sample),
        "structural_flags": [v.subject_id for v in structural],
        "dup_candidates": [_candidate_dict(c) for c in candidates],
        "geocode_flags": [_geocode_flag_dict(check) for check in geo_checks if check.flagged],
    }
    args.worksheet.parent.mkdir(parents=True, exist_ok=True)
    args.worksheet.write_text(json.dumps(worksheet, indent=2), encoding="utf-8")

    suggested_dups = sum(1 for c in candidates if c.suggested == "duplicate")
    print(  # noqa: T201 - CLI output
        "phase4 audit: "
        f"total={len(venues)} dup_candidates={len(candidates)} "
        f"suggested_duplicates={suggested_dups} "
        f"structural_geocode_flags={len(structural)} "
        f"geocode_crosscheck_flags={sum(1 for c in geo_checks if c.flagged)} "
        f"(<=2% dup bound: {duplicate_rate(len(candidates), len(venues)):.3%}) "
        f"worksheet={args.worksheet}"
    )


if __name__ == "__main__":
    main()
