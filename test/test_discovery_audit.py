"""Tests for the Phase 4 precision-audit detectors and the golden matcher set.

The detector tests exercise :mod:`apps.discovery.audit` on hand-built rows (no
DB). ``test_golden_matcher_precision`` is the ROADMAP Phase 4 gate: a 100-pair
hand-labeled fixture over which the discovery matcher (name fingerprint + 50 m
proximity, the same rule the pipeline dedupes with) must reach >= 95% precision.
"""

from __future__ import annotations

import json
from pathlib import Path

from apps.discovery.audit import (
    VenueRow,
    duplicate_rate,
    find_dup_candidates,
    geocode_crosscheck,
    name_similarity,
    sample_venues,
    street_key,
    structural_geocode_flags,
)
from apps.discovery.overture import MetroBbox
from apps.discovery.pipeline import DEFAULT_DEDUPE_RADIUS_M
from packages.helios_core.geo import GeoPoint
from packages.helios_core.identity.normalize import name_fingerprint, within_radius_m

GOLDEN_MATCHES = Path(__file__).parent / "fixtures" / "golden_matches.json"
GOLDEN_PRECISION_FLOOR = 0.95


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


def test_duplicate_rate() -> None:
    assert duplicate_rate(0, 0) == 0.0
    assert duplicate_rate(20, 10000) == 0.002


def test_golden_matcher_precision() -> None:
    """ROADMAP Phase 4: >= 95% matcher precision on the 100-pair golden set."""
    pairs = json.loads(GOLDEN_MATCHES.read_text(encoding="utf-8"))
    assert len(pairs) == 100

    true_positive = false_positive = 0
    for pair in pairs:
        a, b = pair["a"], pair["b"]
        predicted_match = name_fingerprint(a["name"]) == name_fingerprint(b["name"]) and (
            within_radius_m(a["lat"], a["lon"], b["lat"], b["lon"], DEFAULT_DEDUPE_RADIUS_M)
        )
        if not predicted_match:
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
