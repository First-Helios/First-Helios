"""
Unit tests for backend/dedup.py helper functions.

Tests _normalize_chain(), _haversine_m(), _within_radius(),
_source_prefix(), and _reputation(). All are pure functions — no DB needed.
"""

import math

import pytest

from backend.dedup import (
    DEDUP_RADIUS_DEG,
    DEFAULT_REPUTATION,
    SOURCE_REPUTATION,
    _haversine_m,
    _normalize_chain,
    _reputation,
    _source_prefix,
    _within_radius,
)


# ── _normalize_chain() ────────────────────────────────────────────────────────


def test_normalize_chain_lowercases_input():
    assert _normalize_chain("STARBUCKS") == "starbucks"


def test_normalize_chain_strips_non_alphanumeric():
    assert _normalize_chain("Chick-fil-A") == "chickfila"


def test_normalize_chain_strips_spaces():
    assert _normalize_chain("Dutch Bros") == "dutchbros"


def test_normalize_chain_treats_equivalent_names_as_equal():
    assert _normalize_chain("starbucks") == _normalize_chain("Starbucks")
    assert _normalize_chain("chickfila") == _normalize_chain("Chick-fil-A")


def test_normalize_chain_handles_empty_string():
    assert _normalize_chain("") == ""


def test_normalize_chain_preserves_digits():
    assert _normalize_chain("7-Eleven") == "7eleven"


# ── _haversine_m() ────────────────────────────────────────────────────────────


def test_haversine_m_returns_zero_for_identical_coordinates():
    dist = _haversine_m(30.2672, -97.7431, 30.2672, -97.7431)
    assert dist == pytest.approx(0.0, abs=0.001)


def test_haversine_m_returns_correct_distance_for_known_pair():
    # Austin City Hall → Texas State Capitol: ~1.3 km
    dist = _haversine_m(30.2672, -97.7431, 30.2747, -97.7400)
    assert 700 < dist < 1500


def test_haversine_m_is_symmetric():
    d1 = _haversine_m(30.2672, -97.7431, 30.2747, -97.7400)
    d2 = _haversine_m(30.2747, -97.7400, 30.2672, -97.7431)
    assert d1 == pytest.approx(d2, rel=1e-6)


def test_haversine_m_increases_with_distance():
    close = _haversine_m(30.2672, -97.7431, 30.2673, -97.7431)
    far   = _haversine_m(30.2672, -97.7431, 30.2700, -97.7431)
    assert far > close


# ── _within_radius() ──────────────────────────────────────────────────────────


def test_within_radius_returns_true_for_same_point():
    assert _within_radius(30.2672, -97.7431, 30.2672, -97.7431) is True


def test_within_radius_returns_true_for_stores_within_44m():
    # Move lat by ~0.0003° ≈ 33 m  (well within 44 m)
    lat1, lng1 = 30.2672, -97.7431
    lat2, lng2 = lat1 + 0.0003, lng1
    assert _within_radius(lat1, lng1, lat2, lng2) is True


def test_within_radius_returns_false_for_stores_beyond_44m():
    # Move lat by 0.001° ≈ 111 m (well outside 44 m)
    lat1, lng1 = 30.2672, -97.7431
    lat2, lng2 = lat1 + 0.001, lng1
    assert _within_radius(lat1, lng1, lat2, lng2) is False


def test_within_radius_bounding_box_rejects_far_stores_quickly():
    # Differs by much more than DEDUP_RADIUS_DEG in latitude alone
    assert _within_radius(30.0, -97.0, 31.0, -97.0) is False


def test_within_radius_accepts_stores_just_inside_44m():
    # Construct a point ~40 m north
    # 1° lat ≈ 111 km  → 40 m ≈ 0.00036°
    lat1, lng1 = 30.2672, -97.7431
    lat2, lng2 = lat1 + 0.00035, lng1
    result = _within_radius(lat1, lng1, lat2, lng2)
    # Should be within radius
    assert result is True


# ── _source_prefix() ─────────────────────────────────────────────────────────


def test_source_prefix_extracts_first_segment_before_dash():
    assert _source_prefix("ATP-ST-12345") == "ATP"


def test_source_prefix_returns_osm_prefix():
    assert _source_prefix("OSM-ST-338450997") == "OSM"


def test_source_prefix_returns_empty_string_when_no_dash():
    assert _source_prefix("NOSTORENUM") == ""


def test_source_prefix_handles_multiple_dashes():
    assert _source_prefix("ATP-ST-12345-extra") == "ATP"


# ── _reputation() ─────────────────────────────────────────────────────────────


def test_reputation_returns_low_number_for_atp_prefix():
    r = _reputation("ATP-ST-12345")
    assert r == SOURCE_REPUTATION["ATP"]
    assert r == 0  # most reputable


def test_reputation_returns_higher_number_for_osm_prefix():
    r = _reputation("OSM-ST-999")
    assert r == SOURCE_REPUTATION["OSM"]


def test_reputation_returns_default_for_unknown_prefix():
    r = _reputation("UNKNOWN-ST-001")
    assert r == DEFAULT_REPUTATION


def test_reputation_atp_is_more_trusted_than_osm():
    atp = _reputation("ATP-ST-001")
    osm = _reputation("OSM-ST-001")
    assert atp < osm  # lower = more trusted


def test_reputation_sb_careers_is_more_trusted_than_overture():
    sb = _reputation("SB-ST-001")
    ov = _reputation("OV-ST-001")
    assert sb < ov


def test_reputation_order_atp_sb_ov_osm():
    rep = [
        _reputation("ATP-ST-001"),
        _reputation("SB-ST-001"),
        _reputation("OV-ST-001"),
        _reputation("OSM-ST-001"),
    ]
    assert rep == sorted(rep)
