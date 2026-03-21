"""
Unit tests for backend/scoring/careers.py.

Tests age_weight(), weighted_listing_count(), baseline_relative_score(),
and compute_careers_score(). All config.loader calls are patched.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from backend.scoring.careers import (
    age_weight,
    baseline_relative_score,
    compute_careers_score,
    weighted_listing_count,
)

DECAY = {"fresh_days": 7, "stale_days": 90}
TIERS = {
    "critical": {"min_percentile": 67},
    "elevated": {"min_percentile": 33},
    "adequate": {"min_percentile": 0},
}


def _patch_config():
    return [
        patch("backend.scoring.careers.get_posting_age_decay", return_value=DECAY),
        patch("backend.scoring.careers.get_score_tiers", return_value=TIERS),
    ]


# ── age_weight() ──────────────────────────────────────────────────────────────


def test_age_weight_returns_1_for_posting_within_fresh_window():
    with patch("backend.scoring.careers.get_posting_age_decay", return_value=DECAY):
        assert age_weight(0) == 1.0
        assert age_weight(3) == 1.0
        assert age_weight(7) == 1.0


def test_age_weight_returns_0_for_posting_beyond_stale_window():
    with patch("backend.scoring.careers.get_posting_age_decay", return_value=DECAY):
        assert age_weight(90) == 0.0
        assert age_weight(200) == 0.0


def test_age_weight_returns_interpolated_value_between_boundaries():
    with patch("backend.scoring.careers.get_posting_age_decay", return_value=DECAY):
        # At the midpoint (48.5 days for fresh=7, stale=90): ~50% weight
        mid = (7 + 90) // 2
        w = age_weight(mid)
        assert 0.0 < w < 1.0


def test_age_weight_returns_exactly_0_at_stale_boundary():
    with patch("backend.scoring.careers.get_posting_age_decay", return_value=DECAY):
        assert age_weight(90) == 0.0


def test_age_weight_uses_config_fresh_days_not_hardcoded():
    custom_decay = {"fresh_days": 14, "stale_days": 60}
    with patch("backend.scoring.careers.get_posting_age_decay", return_value=custom_decay):
        # 14 days should still be fresh with this config
        assert age_weight(14) == 1.0
        # 15 days should start decaying
        assert age_weight(15) < 1.0


# ── weighted_listing_count() ──────────────────────────────────────────────────


def test_weighted_listing_count_returns_zero_for_empty_list():
    with patch("backend.scoring.careers.get_posting_age_decay", return_value=DECAY):
        assert weighted_listing_count([]) == 0.0


def test_weighted_listing_count_returns_full_weight_for_fresh_listings():
    now = datetime.utcnow()
    listings = [
        {"posted_date": (now - timedelta(days=1)).isoformat()},
        {"posted_date": (now - timedelta(days=2)).isoformat()},
    ]
    with patch("backend.scoring.careers.get_posting_age_decay", return_value=DECAY):
        total = weighted_listing_count(listings, now=now)
    assert total == pytest.approx(2.0, abs=0.01)


def test_weighted_listing_count_returns_half_weight_for_unknown_age_listings():
    listings = [{"observed_at": None, "posted_date": None}]
    with patch("backend.scoring.careers.get_posting_age_decay", return_value=DECAY):
        total = weighted_listing_count(listings)
    assert total == 0.5


def test_weighted_listing_count_uses_posted_date_over_observed_at():
    now = datetime.utcnow()
    # posted_date is fresh, observed_at is stale
    listings = [{
        "posted_date": (now - timedelta(days=1)).isoformat(),
        "observed_at": (now - timedelta(days=200)).isoformat(),
    }]
    with patch("backend.scoring.careers.get_posting_age_decay", return_value=DECAY):
        total = weighted_listing_count(listings, now=now)
    assert total == pytest.approx(1.0, abs=0.01)


def test_weighted_listing_count_handles_iso_string_dates():
    now = datetime.utcnow()
    listings = [{"posted_date": (now - timedelta(days=3)).isoformat()}]
    with patch("backend.scoring.careers.get_posting_age_decay", return_value=DECAY):
        total = weighted_listing_count(listings, now=now)
    assert total > 0


def test_weighted_listing_count_handles_timezone_aware_datetimes():
    now = datetime.utcnow()
    tz_aware = (now - timedelta(days=2)).replace(tzinfo=timezone.utc)
    listings = [{"posted_date": tz_aware}]
    with patch("backend.scoring.careers.get_posting_age_decay", return_value=DECAY):
        total = weighted_listing_count(listings, now=now)
    assert total > 0


def test_weighted_listing_count_ignores_unparseable_dates_with_half_weight():
    listings = [{"posted_date": "not-a-date"}]
    with patch("backend.scoring.careers.get_posting_age_decay", return_value=DECAY):
        total = weighted_listing_count(listings)
    assert total == 0.5


def test_weighted_listing_count_sums_weights_across_multiple_listings():
    now = datetime.utcnow()
    listings = [
        {"posted_date": (now - timedelta(days=1)).isoformat()},  # weight ~1.0
        {"posted_date": (now - timedelta(days=1)).isoformat()},  # weight ~1.0
        {"posted_date": None},                                    # weight 0.5
    ]
    with patch("backend.scoring.careers.get_posting_age_decay", return_value=DECAY):
        total = weighted_listing_count(listings, now=now)
    assert total == pytest.approx(2.5, abs=0.05)


# ── baseline_relative_score() ─────────────────────────────────────────────────


def test_baseline_relative_score_returns_50_when_fewer_than_3_regional_stores():
    assert baseline_relative_score(5.0, [5.0, 3.0]) == 50.0
    assert baseline_relative_score(5.0, []) == 50.0
    assert baseline_relative_score(5.0, [1.0]) == 50.0


def test_baseline_relative_score_returns_100_for_highest_count_in_region():
    regional = [1.0, 2.0, 3.0, 4.0, 5.0]
    score = baseline_relative_score(5.0, regional)
    assert score == 100.0


def test_baseline_relative_score_returns_nonzero_for_lowest_count_in_region():
    regional = [1.0, 2.0, 3.0, 4.0, 5.0]
    score = baseline_relative_score(1.0, regional)
    # Should be low but not necessarily zero (1/5 = 20%)
    assert 0 <= score <= 30


def test_baseline_relative_score_returns_50_for_median_store():
    # 5 stores, middle value
    regional = [1.0, 2.0, 3.0, 4.0, 5.0]
    score = baseline_relative_score(3.0, regional)
    assert score == pytest.approx(60.0, abs=1.0)  # 3 out of 5 values are <= 3.0


def test_baseline_relative_score_correctly_ranks_store_at_75th_percentile():
    regional = [1.0, 2.0, 3.0, 4.0]  # 4 stores
    score = baseline_relative_score(3.0, regional)
    assert score == pytest.approx(75.0, abs=1.0)


# ── compute_careers_score() ───────────────────────────────────────────────────


def test_compute_careers_score_returns_empty_dict_for_no_stores():
    patches = _patch_config()
    for p in patches: p.start()
    result = compute_careers_score({})
    for p in patches: p.stop()
    assert result == {}


def test_compute_careers_score_assigns_neutral_score_with_one_store():
    patches = _patch_config()
    for p in patches: p.start()
    result = compute_careers_score({"SB-001": []})
    for p in patches: p.stop()
    # Only 1 store, so baseline_relative_score returns 50.0
    assert result["SB-001"]["value"] == 50.0


def test_compute_careers_score_assigns_critical_tier_to_highest_listing_store():
    now = datetime.utcnow()
    fresh = (now - timedelta(days=1)).isoformat()
    store_listings = {
        "SB-HIGH": [{"posted_date": fresh}] * 10,
        "SB-MED":  [{"posted_date": fresh}] * 3,
        "SB-LOW":  [],
    }
    patches = _patch_config()
    for p in patches: p.start()
    result = compute_careers_score(store_listings)
    for p in patches: p.stop()
    assert result["SB-HIGH"]["tier"] == "critical"


def test_compute_careers_score_assigns_adequate_tier_to_lowest_listing_store():
    # Need 4 stores so the lowest store falls below 33rd percentile (25th)
    now = datetime.utcnow()
    fresh = (now - timedelta(days=1)).isoformat()
    store_listings = {
        "SB-HIGH":  [{"posted_date": fresh}] * 10,
        "SB-MED1":  [{"posted_date": fresh}] * 5,
        "SB-MED2":  [{"posted_date": fresh}] * 3,
        "SB-LOW":   [],
    }
    patches = _patch_config()
    for p in patches: p.start()
    result = compute_careers_score(store_listings)
    for p in patches: p.stop()
    assert result["SB-LOW"]["tier"] == "adequate"


def test_compute_careers_score_keys_match_input_store_nums():
    store_listings = {"SB-A": [], "SB-B": [], "SB-C": []}
    patches = _patch_config()
    for p in patches: p.start()
    result = compute_careers_score(store_listings)
    for p in patches: p.stop()
    assert set(result.keys()) == {"SB-A", "SB-B", "SB-C"}


def test_compute_careers_score_result_contains_value_tier_weighted_count_keys():
    patches = _patch_config()
    for p in patches: p.start()
    result = compute_careers_score({"SB-001": []})
    for p in patches: p.stop()
    assert "value" in result["SB-001"]
    assert "tier" in result["SB-001"]
    assert "weighted_count" in result["SB-001"]
