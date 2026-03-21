"""
Unit tests for backend/scoring/sentiment.py.

Tests compute_sentiment_score() — signal inversion, scaling,
percentile ranking, and tier assignment. All config.loader calls are patched.
"""

from unittest.mock import patch

import pytest

from backend.scoring.sentiment import compute_sentiment_score

TIERS = {
    "critical": {"min_percentile": 67},
    "elevated": {"min_percentile": 33},
    "adequate": {"min_percentile": 0},
}


def _patch_tiers():
    return patch("backend.scoring.sentiment.get_score_tiers", return_value=TIERS)


# ── Empty input ───────────────────────────────────────────────────────────────


def test_compute_sentiment_score_returns_empty_dict_for_empty_input():
    with _patch_tiers():
        result = compute_sentiment_score({})
    assert result == {}


# ── Neutral default (no signals for a store) ─────────────────────────────────


def test_compute_sentiment_score_returns_neutral_for_store_with_no_signals():
    with _patch_tiers():
        result = compute_sentiment_score({"SB-001": []})
    # Single store with no signals → raw=50, percentile=50 (not enough data)
    assert result["SB-001"]["value"] == pytest.approx(50.0, abs=1.0)


# ── Sentiment signal (0-1 scale) ──────────────────────────────────────────────


def test_compute_sentiment_score_processes_sentiment_type_signal():
    signals = [{"signal_type": "sentiment", "value": 0.8, "source": "reddit"}]
    with _patch_tiers():
        result = compute_sentiment_score({"SB-001": signals})
    # raw = 0.8 * 100 = 80, only one store so percentile = raw
    assert result["SB-001"]["value"] == pytest.approx(80.0, abs=1.0)


def test_compute_sentiment_score_high_sentiment_value_gives_high_score():
    signals = [{"signal_type": "sentiment", "value": 1.0, "source": "reddit"}]
    with _patch_tiers():
        result = compute_sentiment_score({"SB-001": signals})
    assert result["SB-001"]["value"] == pytest.approx(100.0, abs=1.0)


def test_compute_sentiment_score_zero_sentiment_value_gives_low_score():
    signals = [{"signal_type": "sentiment", "value": 0.0, "source": "reddit"}]
    with _patch_tiers():
        result = compute_sentiment_score({"SB-001": signals})
    assert result["SB-001"]["value"] == pytest.approx(0.0, abs=1.0)


# ── Review score signal (1-5 scale, inverted) ─────────────────────────────────


def test_compute_sentiment_score_review_score_5_maps_to_low_stress():
    # 5-star rating → inverted = 1 - (5-1)/4 = 0.0 → low stress
    signals = [{"signal_type": "review_score", "value": 5.0, "source": "google_maps"}]
    with _patch_tiers():
        result = compute_sentiment_score({"SB-001": signals})
    assert result["SB-001"]["value"] == pytest.approx(0.0, abs=1.0)


def test_compute_sentiment_score_review_score_1_maps_to_high_stress():
    # 1-star rating → inverted = 1 - (1-1)/4 = 1.0 → high stress
    signals = [{"signal_type": "review_score", "value": 1.0, "source": "google_maps"}]
    with _patch_tiers():
        result = compute_sentiment_score({"SB-001": signals})
    assert result["SB-001"]["value"] == pytest.approx(100.0, abs=1.0)


def test_compute_sentiment_score_review_score_3_maps_to_medium_stress():
    # 3-star → inverted = 1 - (3-1)/4 = 0.5 → 50% stress
    signals = [{"signal_type": "review_score", "value": 3.0, "source": "google_maps"}]
    with _patch_tiers():
        result = compute_sentiment_score({"SB-001": signals})
    assert result["SB-001"]["value"] == pytest.approx(50.0, abs=1.0)


# ── Combined signals ──────────────────────────────────────────────────────────


def test_compute_sentiment_score_combines_sentiment_and_review_signals_by_average():
    # sentiment=0.6 (60%), review=3 → inverted=0.5 (50%). avg=0.55 → 55%
    signals = [
        {"signal_type": "sentiment", "value": 0.6, "source": "reddit"},
        {"signal_type": "review_score", "value": 3.0, "source": "google_maps"},
    ]
    with _patch_tiers():
        result = compute_sentiment_score({"SB-001": signals})
    assert result["SB-001"]["value"] == pytest.approx(55.0, abs=1.0)


# ── Percentile ranking with 3+ stores ────────────────────────────────────────


def test_compute_sentiment_score_uses_percentile_scoring_when_3_or_more_stores():
    store_signals = {
        "SB-HIGH": [{"signal_type": "sentiment", "value": 0.9, "source": "reddit"}],
        "SB-MED":  [{"signal_type": "sentiment", "value": 0.5, "source": "reddit"}],
        "SB-LOW":  [{"signal_type": "sentiment", "value": 0.1, "source": "reddit"}],
    }
    with _patch_tiers():
        result = compute_sentiment_score(store_signals)
    # SB-HIGH should have highest score (100th percentile)
    assert result["SB-HIGH"]["value"] > result["SB-MED"]["value"] > result["SB-LOW"]["value"]


def test_compute_sentiment_score_uses_raw_score_when_fewer_than_3_stores():
    store_signals = {
        "SB-A": [{"signal_type": "sentiment", "value": 0.7, "source": "reddit"}],
        "SB-B": [{"signal_type": "sentiment", "value": 0.3, "source": "reddit"}],
    }
    with _patch_tiers():
        result = compute_sentiment_score(store_signals)
    # With fewer than 3 stores, percentile = raw score
    assert result["SB-A"]["value"] == pytest.approx(70.0, abs=1.0)
    assert result["SB-B"]["value"] == pytest.approx(30.0, abs=1.0)


# ── Tier assignment ───────────────────────────────────────────────────────────


def test_compute_sentiment_score_assigns_critical_tier_when_score_at_or_above_67():
    # 3 stores so percentile ranking applies; highest gets tier based on score
    store_signals = {
        "SB-A": [{"signal_type": "sentiment", "value": 1.0, "source": "reddit"}],
        "SB-B": [{"signal_type": "sentiment", "value": 0.5, "source": "reddit"}],
        "SB-C": [{"signal_type": "sentiment", "value": 0.0, "source": "reddit"}],
    }
    with _patch_tiers():
        result = compute_sentiment_score(store_signals)
    assert result["SB-A"]["tier"] == "critical"


def test_compute_sentiment_score_assigns_adequate_tier_when_score_below_33():
    # Need 4 stores so the lowest store falls below 33rd percentile (25th)
    store_signals = {
        "SB-A": [{"signal_type": "sentiment", "value": 1.0, "source": "reddit"}],
        "SB-B": [{"signal_type": "sentiment", "value": 0.7, "source": "reddit"}],
        "SB-C": [{"signal_type": "sentiment", "value": 0.4, "source": "reddit"}],
        "SB-D": [{"signal_type": "sentiment", "value": 0.0, "source": "reddit"}],
    }
    with _patch_tiers():
        result = compute_sentiment_score(store_signals)
    assert result["SB-D"]["tier"] == "adequate"


def test_compute_sentiment_score_result_contains_value_and_tier_keys():
    with _patch_tiers():
        result = compute_sentiment_score({"SB-001": []})
    assert "value" in result["SB-001"]
    assert "tier" in result["SB-001"]
