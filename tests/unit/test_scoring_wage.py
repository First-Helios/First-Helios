"""
Unit tests for backend/scoring/wage.py.

Tests compute_wage_score() — neutral fallback, gap formula,
yearly→hourly conversion, percentile ranking, tier assignment.
All config.loader calls are patched.
"""

from unittest.mock import patch

import pytest

from backend.scoring.wage import compute_wage_score

TIERS = {
    "critical": {"min_percentile": 67},
    "elevated": {"min_percentile": 33},
    "adequate": {"min_percentile": 0},
}


def _patch_tiers():
    return patch("backend.scoring.wage.get_score_tiers", return_value=TIERS)


# ── No local wage data (neutral fallback) ─────────────────────────────────────


def test_compute_wage_score_returns_neutral_50_when_no_local_avg_wage():
    wages = {"SB-001": {"wage_min": 15.0, "wage_max": 18.0, "wage_period": "hourly"}}
    with _patch_tiers():
        result = compute_wage_score(wages, local_avg_wage=None)
    assert result["SB-001"]["value"] == 50.0


def test_compute_wage_score_returns_elevated_tier_when_no_local_avg_wage():
    wages = {"SB-001": {"wage_min": 15.0, "wage_max": 18.0, "wage_period": "hourly"}}
    with _patch_tiers():
        result = compute_wage_score(wages, local_avg_wage=None)
    assert result["SB-001"]["tier"] == "elevated"


def test_compute_wage_score_returns_neutral_when_local_avg_is_zero():
    wages = {"SB-001": {"wage_min": 15.0, "wage_max": 18.0, "wage_period": "hourly"}}
    with _patch_tiers():
        result = compute_wage_score(wages, local_avg_wage=0.0)
    assert result["SB-001"]["value"] == 50.0


def test_compute_wage_score_handles_empty_chain_wages():
    with _patch_tiers():
        result = compute_wage_score({}, local_avg_wage=18.0)
    assert result == {}


# ── Store with no wage data ───────────────────────────────────────────────────


def test_compute_wage_score_returns_neutral_when_store_has_no_wage_data():
    wages = {"SB-001": {"wage_min": None, "wage_max": None, "wage_period": "hourly"}}
    with _patch_tiers():
        result = compute_wage_score(wages, local_avg_wage=18.0)
    assert result["SB-001"]["value"] == pytest.approx(50.0, abs=1.0)


# ── Gap computation ───────────────────────────────────────────────────────────


def test_compute_wage_score_score_is_50_when_chain_and_local_wages_equal():
    # chain_avg = 18.0, local_avg = 18.0 → gap_pct = 0 → score = 50
    wages = {"SB-001": {"wage_min": 18.0, "wage_max": 18.0, "wage_period": "hourly"}}
    with _patch_tiers():
        result = compute_wage_score(wages, local_avg_wage=18.0)
    assert result["SB-001"]["value"] == pytest.approx(50.0, abs=1.0)


def test_compute_wage_score_score_above_50_when_locals_pay_more():
    # locals pay 20, chain pays 16 → gap_pct = +25% → score = 50 + 25*2.5 = 112.5 → clamped 100
    wages = {"SB-001": {"wage_min": 16.0, "wage_max": 16.0, "wage_period": "hourly"}}
    with _patch_tiers():
        result = compute_wage_score(wages, local_avg_wage=20.0)
    assert result["SB-001"]["value"] > 50.0


def test_compute_wage_score_score_below_50_when_chain_pays_more():
    # chain pays 22, locals pay 18 → gap_pct = -18% → score = 50 + (-18*2.5) = 5
    wages = {"SB-001": {"wage_min": 22.0, "wage_max": 22.0, "wage_period": "hourly"}}
    with _patch_tiers():
        result = compute_wage_score(wages, local_avg_wage=18.0)
    assert result["SB-001"]["value"] < 50.0


def test_compute_wage_score_score_approaches_100_when_large_positive_gap():
    wages = {"SB-001": {"wage_min": 10.0, "wage_max": 10.0, "wage_period": "hourly"}}
    with _patch_tiers():
        result = compute_wage_score(wages, local_avg_wage=30.0)
    assert result["SB-001"]["value"] == pytest.approx(100.0, abs=0.01)


def test_compute_wage_score_score_approaches_0_when_large_negative_gap():
    wages = {"SB-001": {"wage_min": 30.0, "wage_max": 30.0, "wage_period": "hourly"}}
    with _patch_tiers():
        result = compute_wage_score(wages, local_avg_wage=10.0)
    assert result["SB-001"]["value"] == pytest.approx(0.0, abs=0.01)


def test_compute_wage_score_clamps_score_between_0_and_100():
    for local in [5.0, 100.0]:
        wages = {"SB-001": {"wage_min": 20.0, "wage_max": 20.0, "wage_period": "hourly"}}
        with _patch_tiers():
            result = compute_wage_score(wages, local_avg_wage=local)
        v = result["SB-001"]["value"]
        assert 0.0 <= v <= 100.0


# ── Yearly → hourly conversion ────────────────────────────────────────────────


def test_compute_wage_score_converts_yearly_wage_to_hourly_before_comparison():
    # $41,600/year ÷ 2080 = $20/hour. Local = $18. gap = (18-20)/20 = -10% → score < 50
    wages = {"SB-001": {"wage_min": 41600.0, "wage_max": 41600.0, "wage_period": "yearly"}}
    with _patch_tiers():
        result = compute_wage_score(wages, local_avg_wage=18.0)
    assert result["SB-001"]["value"] < 50.0


def test_compute_wage_score_does_not_convert_small_yearly_value():
    # wage < 100 shouldn't be divided (could be a raw hourly stored with period="yearly")
    wages = {"SB-001": {"wage_min": 20.0, "wage_max": 20.0, "wage_period": "yearly"}}
    with _patch_tiers():
        result = compute_wage_score(wages, local_avg_wage=18.0)
    # No conversion applied (20 < 100) → chain_avg = 20 > local 18 → score < 50
    assert result["SB-001"]["value"] < 50.0


# ── Wage min/max edge cases ───────────────────────────────────────────────────


def test_compute_wage_score_uses_wage_min_alone_when_max_absent():
    wages = {"SB-001": {"wage_min": 16.0, "wage_max": None, "wage_period": "hourly"}}
    with _patch_tiers():
        result = compute_wage_score(wages, local_avg_wage=18.0)
    assert "value" in result["SB-001"]


def test_compute_wage_score_uses_wage_max_alone_when_min_absent():
    wages = {"SB-001": {"wage_min": None, "wage_max": 20.0, "wage_period": "hourly"}}
    with _patch_tiers():
        result = compute_wage_score(wages, local_avg_wage=18.0)
    assert "value" in result["SB-001"]


# ── Result structure ──────────────────────────────────────────────────────────


def test_compute_wage_score_result_contains_expected_keys():
    wages = {"SB-001": {"wage_min": 16.0, "wage_max": 20.0, "wage_period": "hourly"}}
    with _patch_tiers():
        result = compute_wage_score(wages, local_avg_wage=18.0)
    for key in ("value", "tier", "chain_avg", "local_avg", "gap_pct"):
        assert key in result["SB-001"], f"Missing key: {key}"


def test_compute_wage_score_result_contains_local_avg():
    wages = {"SB-001": {"wage_min": 16.0, "wage_max": 20.0, "wage_period": "hourly"}}
    with _patch_tiers():
        result = compute_wage_score(wages, local_avg_wage=18.0)
    assert result["SB-001"]["local_avg"] == pytest.approx(18.0, abs=0.01)


# ── Tier assignment ───────────────────────────────────────────────────────────


def test_compute_wage_score_assigns_critical_tier_to_highest_gap_store():
    wages = {
        "SB-HIGH": {"wage_min": 10.0, "wage_max": 10.0, "wage_period": "hourly"},
        "SB-MED":  {"wage_min": 15.0, "wage_max": 15.0, "wage_period": "hourly"},
        "SB-LOW":  {"wage_min": 22.0, "wage_max": 22.0, "wage_period": "hourly"},
    }
    with _patch_tiers():
        result = compute_wage_score(wages, local_avg_wage=18.0)
    # SB-HIGH pays least vs local → highest gap → highest stress → critical
    assert result["SB-HIGH"]["tier"] == "critical"


def test_compute_wage_score_uses_percentile_ranking_with_3_or_more_stores():
    wages = {
        "SB-A": {"wage_min": 10.0, "wage_max": 10.0, "wage_period": "hourly"},
        "SB-B": {"wage_min": 15.0, "wage_max": 15.0, "wage_period": "hourly"},
        "SB-C": {"wage_min": 20.0, "wage_max": 20.0, "wage_period": "hourly"},
    }
    with _patch_tiers():
        result = compute_wage_score(wages, local_avg_wage=18.0)
    # With 3 stores, percentile ranking should produce differentiated scores
    scores = [r["value"] for r in result.values()]
    assert len(set(scores)) > 1  # not all the same
