"""Tests for the Phase 4 precision-audit detectors and the golden matcher set.

The detector tests exercise :mod:`apps.discovery.audit` on hand-built rows (no
DB). ``test_golden_matcher_precision`` is the ROADMAP Phase 4 gate: a 100-pair
hand-labeled fixture over which the discovery matcher (name fingerprint + 50 m
proximity) must reach >= 95% precision. It runs each pair through
``run_discovery`` on a database, so it scores the pipeline's real dedupe path.
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import uuid4

import pytest

from apps.discovery.audit import (
    GeoCrossCheck,
    VenueRow,
    _geocode_flag_dict,
    duplicate_rate,
    find_dup_candidates,
    find_twins,
    geocode_crosscheck,
    is_location_label,
    name_similarity,
    sample_venues,
    street_key,
    structural_geocode_flags,
)
from apps.discovery.overture import MetroBbox, OverturePoi
from apps.discovery.pipeline import run_discovery
from packages.helios_core.geo import GeoPoint
from packages.helios_core.identity.normalize import name_fingerprint

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

GOLDEN_MATCHES = Path(__file__).parent / "fixtures" / "golden_matches.json"
GOLDEN_PRECISION_FLOOR = 0.95
_NOW = datetime.now(UTC)


def _venue(subject_id: int, name: str, lat: float | None, lon: float | None, addr: str) -> VenueRow:
    return VenueRow(
        subject_id=subject_id,
        name=name,
        fingerprint=name_fingerprint(name),
        latitude=lat,
        longitude=lon,
        address=addr,
    )


def test_street_key_strips_suite_and_zip() -> None:
    a = street_key("6218 Brodie Ln Ste C, Austin, TX, 78745-1234")
    b = street_key("6218 Brodie Ln, Austin, TX, 78745")
    assert a == b == "6218 brodie ln"
    assert street_key(None) == ""


def test_street_key_keeps_five_digit_house_numbers() -> None:
    # R: `_ZIP` used to strip these, so the two addresses collided.
    a = street_key("13785 Research Blvd, Austin, TX, 78750")
    b = street_key("14028 Research Blvd, Austin, TX, 78750-1234")
    assert a == "13785 research blvd"
    assert a != b
    assert street_key("13770 N Hwy 183 78750") == "13770 n hwy 183"


def test_street_key_folds_spelling_variants() -> None:
    assert street_key("2800 Hoppe Trail, Round Rock") == street_key("2800 Hoppe Trl")
    assert street_key("517 W MLK Jr. Blvd., Austin") == street_key(
        "517 West Martin Luther King Jr Boulevard, Austin"
    )


@pytest.mark.parametrize(
    ("name", "label"),
    [
        ("Main St & I-35", True),
        ("Spirit of Texas Dr & Presidential Blvd", True),
        ("MLK (24 Hours)", True),
        ("Congress (Downtown)", True),
        ("Research Blvd", True),
        ("Whataburger", False),
        ("Taqueria Jefes", False),
        ("Main Street Pizza", False),
        ("P. Terry's Burger Stand", False),
        ("Salt & Time", False),
    ],
)
def test_is_location_label(name: str, label: bool) -> None:
    assert is_location_label(name) is label


def _row(subject_id: int, name: str, lat: float | None, lon: float | None, addr: str) -> VenueRow:
    return replace(_venue(subject_id, name, lat, lon, addr), fingerprint=name_fingerprint(name))


def test_find_twins_sees_what_the_colocation_detector_misses() -> None:
    venues = [
        # P. Terry's MLK: one record misplaced 1.6 km away at the same address.
        _row(9336, "P. Terry's Burger Stand", 30.267153, -97.743073, "517 W MLK Jr. Blvd."),
        _row(14829, "P. Terry's Burger Stand", 30.281900, -97.743300, "517 W MLK Jr Blvd"),
        # Whataburger #1000 and its locator-label record, 1 m apart.
        _row(3585, "Main St & I-35", 30.080000, -97.840000, "670 Old San Antonio Rd"),
        _row(3588, "Whataburger", 30.080009, -97.840000, "670 OLD SAN ANTONIO RD"),
        # Pinthouse: Trail/Trl, 740 m apart.
        _row(27480, "Pinthouse Pizza", 30.500000, -97.700000, "2800 Hoppe Trail"),
        _row(27456, "Pinthouse Pizza", 30.506650, -97.700000, "2800 Hoppe Trl"),
        # Food hall tenants: different names, one address, close together.
        _row(1, "Soto", 30.250000, -97.760000, "1100 S Lamar Blvd"),
        _row(2, "Shake Shack", 30.250050, -97.760000, "1100 S Lamar Blvd"),
        # A chain 13 km apart.
        _row(3, "Starbucks", 30.30, -97.70, "1 A St"),
        _row(4, "Starbucks", 30.40, -97.80, "2 B St"),
    ]
    # Control: the co-location detector cannot see the misplaced twin.
    assert all(
        {c.a.subject_id, c.b.subject_id} != {9336, 14829} for c in find_dup_candidates(venues)
    )
    twins = {(t.a.subject_id, t.b.subject_id): t.reasons for t in find_twins(venues)}
    assert twins[(9336, 14829)] == ("same_address", "misplaced")
    assert "location_label" in twins[(3585, 3588)]
    assert twins[(27456, 27480)] == ("same_address", "misplaced", "same_fingerprint")
    assert (1, 2) not in twins
    assert (3, 4) not in twins


def test_find_twins_includes_rows_without_coordinates() -> None:
    venues = [
        _row(1, "El Sol y La Luna", None, None, "1224 S Congress Ave"),
        _row(2, "El Sol Y La Luna Restaurant", 30.25, -97.75, "1224 South Congress Avenue"),
    ]
    [twin] = find_twins(venues)
    assert twin.distance_m is None and twin.reasons == ("same_address",)


def test_name_similarity_is_bounded() -> None:
    assert name_similarity("torchys tacos", "torchys tacos") == 1.0
    assert name_similarity("austins pizza", "austin pizza") > 0.9
    assert name_similarity("starbucks", "whataburger") < 0.5


def test_find_dup_candidates_flags_colocated_variants() -> None:
    venues = [
        _venue(1, "Austins Pizza", 30.500000, -97.700000, "1 Main St, Austin, TX"),
        _venue(2, "Austin Pizza", 30.500050, -97.700000, "1 Main St, Austin, TX"),  # ~5 m, fuzzy
        _venue(3, "Torchys Tacos", 30.600000, -97.800000, "9 Far Rd, Austin, TX"),  # unrelated
    ]
    candidates = find_dup_candidates(venues)
    assert len(candidates) == 1
    pair = candidates[0]
    assert {pair.a.subject_id, pair.b.subject_id} == {1, 2}
    assert pair.distance_m < 50


def test_find_dup_candidates_keeps_distant_chains_apart() -> None:
    # Same fingerprint but far beyond the radius: two real, distinct locations.
    venues = [
        _venue(1, "Starbucks", 30.30, -97.70, "1 A St, Austin, TX"),
        _venue(2, "Starbucks", 30.40, -97.80, "2 B St, Austin, TX"),  # ~13 km away
    ]
    assert find_dup_candidates(venues) == []


def test_structural_geocode_flags_catches_null_and_out_of_bbox() -> None:
    bbox = MetroBbox.austin()
    venues = [
        _venue(1, "In Box", 30.30, -97.70, "ok"),
        _venue(2, "No Coord", None, None, "missing"),
        _venue(3, "Out Of Box", 31.90, -97.70, "far north"),
    ]
    flagged = {v.subject_id for v in structural_geocode_flags(venues, bbox=bbox)}
    assert flagged == {2, 3}


def test_sample_venues_is_deterministic_and_sized() -> None:
    venues = [_venue(i, f"V{i}", 30.3, -97.7, "a") for i in range(500)]
    first = sample_venues(venues, size=100)
    second = sample_venues(venues, size=100)
    assert [v.subject_id for v in first] == [v.subject_id for v in second]
    assert len(first) == 100
    assert sample_venues(venues, size=100, seed="other") != first


class _StubGeocoder:
    """Returns a fixed point per address; ``None`` for anything unmapped."""

    def __init__(self, mapping: dict[str, GeoPoint]) -> None:
        self._mapping = mapping

    def geocode(self, query: str) -> GeoPoint | None:
        return self._mapping.get(query)


def test_geocode_crosscheck_flags_disagreement_and_no_match() -> None:
    venues = [
        _venue(1, "Agrees", 30.300000, -97.700000, "near addr"),
        _venue(2, "Disagrees", 30.300000, -97.700000, "far addr"),
        _venue(3, "Unmappable", 30.300000, -97.700000, "no geocode"),
    ]
    geocoder = _StubGeocoder(
        {
            "near addr": GeoPoint(latitude=30.300100, longitude=-97.700000),  # ~11 m
            "far addr": GeoPoint(latitude=30.320000, longitude=-97.700000),  # ~2 km
        }
    )
    results = {c.venue.subject_id: c for c in geocode_crosscheck(venues, geocoder)}
    assert results[1].flagged is False
    assert results[2].flagged is True
    assert results[3].flagged is True and results[3].distance_m is None


def test_geocode_flag_label_distinguishes_far_from_unmappable() -> None:
    far = GeoCrossCheck(venue=_venue(1, "Far", 30.3, -97.7, "far"), distance_m=2200.0, flagged=True)
    unmapped = GeoCrossCheck(
        venue=_venue(2, "Unmapped", 30.3, -97.7, "none"), distance_m=None, flagged=True
    )
    assert _geocode_flag_dict(far)["label"] == "wrong"
    assert _geocode_flag_dict(unmapped)["label"] == "review"


def test_duplicate_rate() -> None:
    assert duplicate_rate(0, 0) == 0.0
    assert duplicate_rate(20, 10000) == 0.002


def _golden_poi(row: dict[str, Any]) -> OverturePoi:
    gers = f"golden-{uuid4().hex}"
    return OverturePoi(
        gers_id=gers,
        name=row["name"],
        primary_category="restaurant",
        alternate_categories=(),
        websites=(),
        address=None,
        latitude=row["lat"],
        longitude=row["lon"],
        confidence=0.9,
        raw={"id": gers, "name": row["name"], "lat": row["lat"], "lon": row["lon"]},
    )


def _pair_is_deduped(session: Session, a: dict[str, Any], b: dict[str, Any]) -> bool:
    """Run ``a`` then ``b`` through discovery; True when ``b`` joins ``a``'s venue.

    Uses the pipeline itself (fingerprint, coordinate quantization,
    ``_dedupe_candidates``) rather than a copy of its rule (R77).
    Each pair runs in its own savepoint so pairs never see each other's rows.
    """
    savepoint = session.begin_nested()
    try:
        report = run_discovery(
            session,
            [_golden_poi(a), _golden_poi(b)],
            decided_at=_NOW,
            observed_at=_NOW,
            release="s3://overturemaps-us-west-2/release/2026-01-01.0/theme=places/type=place/*",
        )
        assert report.ambiguous == 0, f"unexpected ambiguity for {a['name']!r}"
        assert report.minted + report.deduped == 2
        return report.deduped == 1
    finally:
        savepoint.rollback()


def test_golden_matcher_precision(session: Session) -> None:
    """ROADMAP Phase 4: >= 95% matcher precision on the 100-pair golden set."""
    pairs = json.loads(GOLDEN_MATCHES.read_text(encoding="utf-8"))
    assert len(pairs) == 100

    true_positive = false_positive = 0
    for pair in pairs:
        if not _pair_is_deduped(session, pair["a"], pair["b"]):
            continue
        if pair["label"] == "match":
            true_positive += 1
        else:
            false_positive += 1

    assert true_positive + false_positive > 0, "matcher made no positive predictions to score"
    precision = true_positive / (true_positive + false_positive)
    assert precision >= GOLDEN_PRECISION_FLOOR, (
        f"precision {precision:.3f} < {GOLDEN_PRECISION_FLOOR}"
    )


# ~111 m per 0.001 degree of latitude: 0.000405 is ~45 m, 0.000495 is ~55 m.
@pytest.mark.parametrize(
    ("name_a", "name_b", "lat_offset", "expected"),
    [
        ("Radius Grill", "Radius Grill", 0.000405, True),  # inside 50 m
        ("Radius Grill", "Radius Grill", 0.000495, False),  # just outside 50 m
        ("Taco Deli", "Torchy's Tacos", 0.0, False),  # same spot, different names
        ("Café Nuevo", "Cafe Nuevo", 0.0001, True),  # accents fold together
        # R18: non-English letters are kept, so bilingual names stay apart...
        ("Chinese Restaurant 金龍", "Chinese Restaurant 福州", 0.0001, False),
        ("Đông Phương", "Ông Phương", 0.0001, False),
        # ...while accents and apostrophe variants still fold together.
        ("Đông Phương", "Dong Phuong", 0.0001, True),
        ("Torchyʼs Tacos", "Torchy's Tacos", 0.0001, True),
    ],
)
def test_matcher_hard_cases_near_the_boundary(
    session: Session, name_a: str, name_b: str, lat_offset: float, expected: bool
) -> None:
    a = {"name": name_a, "lat": 30.281, "lon": -97.731}
    b = {"name": name_b, "lat": 30.281 + lat_offset, "lon": -97.731}
    assert _pair_is_deduped(session, a, b) is expected
