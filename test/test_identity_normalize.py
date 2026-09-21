"""Unit tests for the pure identity-matching helpers (no DB, no network)."""

from __future__ import annotations

import pytest

from packages.helios_core.identity.normalize import (
    haversine_m,
    name_fingerprint,
    normalize_address,
    normalize_name,
    within_radius_m,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Torchy's Tacos", "torchys tacos"),
        ("  Franklin   Barbecue ", "franklin barbecue"),
        ("Veracruz All-Natural", "veracruz all natural"),
        ("Café Crème", "cafe creme"),
        ("P. Terry's Burger Stand #12", "p terrys burger stand 12"),
        ("", ""),
        ("!!!", ""),
    ],
)
def test_normalize_name_is_stable_and_conservative(raw: str, expected: str) -> None:
    assert normalize_name(raw) == expected
    # Idempotent: normalizing an already-normalized name changes nothing.
    assert normalize_name(normalize_name(raw)) == expected


def test_name_fingerprint_matches_across_punctuation_and_case() -> None:
    assert name_fingerprint("Torchy's Tacos") == name_fingerprint("TORCHYS TACOS")
    assert name_fingerprint("Home Slice Pizza") == name_fingerprint("home-slice pizza")


def test_name_fingerprint_keeps_distinct_names_distinct() -> None:
    # Conservative: it does not collapse different brands together.
    assert name_fingerprint("Home Slice Pizza") != name_fingerprint("Home Slice Cafe")
    assert name_fingerprint("Torchys Tacos") != name_fingerprint("Torchys Burgers")


def test_normalize_address_normalizes_like_a_name() -> None:
    assert normalize_address("1311 S. 1st St, Austin, TX") == "1311 s 1st st austin tx"


def test_haversine_known_short_distance() -> None:
    # ~0.001 deg of latitude is ~111.2 m at any longitude.
    assert haversine_m(30.0, -97.0, 30.001, -97.0) == pytest.approx(111.2, abs=1.0)


def test_haversine_is_symmetric_and_zero_on_identity() -> None:
    assert haversine_m(30.2672, -97.7431, 30.2672, -97.7431) == pytest.approx(0.0, abs=1e-6)
    a = haversine_m(30.27, -97.74, 30.51, -97.68)
    b = haversine_m(30.51, -97.68, 30.27, -97.74)
    assert a == pytest.approx(b, rel=1e-9)


def test_within_radius_respects_the_boundary() -> None:
    # Two points ~33 m apart (0.0003 deg lat).
    assert within_radius_m(30.0, -97.0, 30.0003, -97.0, 50.0)
    assert not within_radius_m(30.0, -97.0, 30.0003, -97.0, 25.0)
