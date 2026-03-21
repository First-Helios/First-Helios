"""
Integration tests for backend/scoring/engine.py — compute_all_scores().

Uses in-memory SQLite. Patches:
  - backend.scoring.engine.init_db / get_session → mem_engine
  - backend.scoring.engine.get_scoring_weights   → fixed test weights
  - backend.scoring.engine.get_score_tiers       → fixed test tiers
  - backend.scoring.careers.get_posting_age_decay / get_score_tiers
  - backend.scoring.sentiment.get_score_tiers
  - backend.scoring.wage.get_score_tiers
"""

from datetime import datetime, timedelta
from unittest.mock import patch
from sqlalchemy.orm import sessionmaker

import pytest

from backend.database import Score, Signal, Store, WageIndex
from backend.scoring.engine import compute_all_scores


TIERS = {
    "critical": {"min_percentile": 67},
    "elevated": {"min_percentile": 33},
    "adequate": {"min_percentile": 0},
}
WEIGHTS = {"careers_api": 0.40, "job_boards": 0.35, "sentiment": 0.25}
DECAY = {"fresh_days": 7, "stale_days": 90}


def _session_factory(mem_engine):
    return lambda e=None: sessionmaker(bind=mem_engine)()


def _patch_scoring(mem_engine):
    return [
        patch("backend.scoring.engine.init_db", return_value=mem_engine),
        patch("backend.scoring.engine.get_session", side_effect=_session_factory(mem_engine)),
        patch("backend.scoring.engine.get_scoring_weights", return_value=WEIGHTS),
        patch("backend.scoring.engine.get_score_tiers", return_value=TIERS),
        patch("backend.scoring.careers.get_score_tiers", return_value=TIERS),
        patch("backend.scoring.careers.get_posting_age_decay", return_value=DECAY),
        patch("backend.scoring.sentiment.get_score_tiers", return_value=TIERS),
        patch("backend.scoring.wage.get_score_tiers", return_value=TIERS),
    ]


def _run_scoring(mem_engine, region="austin_tx", chain=None):
    patches = _patch_scoring(mem_engine)
    for p in patches: p.start()
    result = compute_all_scores(region, chain=chain)
    for p in patches: p.stop()
    return result


def _make_store(session, store_num, chain="starbucks", region="austin_tx", active=True):
    store = Store(
        store_num=store_num,
        chain=chain,
        industry="coffee_cafe",
        store_name="Test Store",
        address="",
        lat=30.2672,
        lng=-97.7431,
        region=region,
        is_active=active,
    )
    session.add(store)
    session.commit()
    return store


def _make_listing_signal(session, store_num, days_old=1):
    sig = Signal(
        store_num=store_num,
        source="careers_api",
        signal_type="listing",
        value=1.0,
        observed_at=datetime.utcnow() - timedelta(days=days_old),
    )
    sig.set_metadata({"posted_date": (datetime.utcnow() - timedelta(days=days_old)).isoformat()})
    session.add(sig)
    session.commit()
    return sig


# ── No data ───────────────────────────────────────────────────────────────────


def test_compute_all_scores_returns_empty_dict_when_no_stores(mem_engine):
    result = _run_scoring(mem_engine)
    assert result == {}


def test_compute_all_scores_returns_empty_dict_when_region_has_no_active_stores(
    mem_engine, mem_session
):
    _make_store(mem_session, "SB-INACTIVE-001", active=False)
    result = _run_scoring(mem_engine)
    assert result == {}


# ── Basic scoring ─────────────────────────────────────────────────────────────


def test_compute_all_scores_returns_result_for_each_active_store(
    mem_engine, mem_session
):
    _make_store(mem_session, "SB-001")
    _make_store(mem_session, "SB-002")
    result = _run_scoring(mem_engine)
    assert "SB-001" in result
    assert "SB-002" in result


def test_compute_all_scores_result_contains_composite_tier_keys(
    mem_engine, mem_session
):
    _make_store(mem_session, "SB-001")
    result = _run_scoring(mem_engine)
    assert "composite" in result["SB-001"]
    assert "tier" in result["SB-001"]


def test_compute_all_scores_composite_is_float_between_0_and_1(
    mem_engine, mem_session
):
    _make_store(mem_session, "SB-001")
    result = _run_scoring(mem_engine)
    assert 0.0 <= result["SB-001"]["composite"] <= 1.0


def test_compute_all_scores_tier_is_one_of_valid_values(
    mem_engine, mem_session
):
    _make_store(mem_session, "SB-001")
    result = _run_scoring(mem_engine)
    assert result["SB-001"]["tier"] in ("critical", "elevated", "adequate")


# ── Tier assignment ───────────────────────────────────────────────────────────


def test_compute_all_scores_assigns_critical_tier_to_high_scoring_store(
    mem_engine, mem_session
):
    # 3 stores needed for percentile ranking; give SB-HIGH many fresh listings
    for i in range(3):
        _make_store(mem_session, f"SB-{i:03d}")
    # Give SB-000 many fresh signals, others none
    for _ in range(10):
        _make_listing_signal(mem_session, "SB-000", days_old=1)

    result = _run_scoring(mem_engine)
    assert result["SB-000"]["tier"] == "critical"


def test_compute_all_scores_assigns_adequate_tier_to_low_scoring_store(
    mem_engine, mem_session
):
    for i in range(3):
        _make_store(mem_session, f"SB-{i:03d}")
    # Only SB-000 gets listings — SB-001 and SB-002 get nothing
    for _ in range(10):
        _make_listing_signal(mem_session, "SB-000", days_old=1)

    result = _run_scoring(mem_engine)
    # SB-001 or SB-002 should be adequate
    assert result["SB-001"]["tier"] == "adequate" or result["SB-002"]["tier"] == "adequate"


# ── Weight redistribution ─────────────────────────────────────────────────────


def test_compute_all_scores_still_scores_when_careers_data_absent(
    mem_engine, mem_session
):
    _make_store(mem_session, "SB-001")
    # Add only a sentiment signal, no listing
    sig = Signal(
        store_num="SB-001",
        source="reddit",
        signal_type="sentiment",
        value=0.5,
        observed_at=datetime.utcnow(),
    )
    sig.set_metadata({})
    mem_session.add(sig)
    mem_session.commit()

    result = _run_scoring(mem_engine)
    assert result["SB-001"]["composite"] >= 0.0


def test_compute_all_scores_still_scores_when_sentiment_data_absent(
    mem_engine, mem_session
):
    _make_store(mem_session, "SB-001")
    _make_listing_signal(mem_session, "SB-001")
    result = _run_scoring(mem_engine)
    assert result["SB-001"]["composite"] >= 0.0


# ── DB writes ─────────────────────────────────────────────────────────────────


def test_compute_all_scores_writes_composite_score_row_to_db(
    mem_engine, mem_session
):
    _make_store(mem_session, "SB-001")
    _run_scoring(mem_engine)

    score_row = mem_session.query(Score).filter_by(
        store_num="SB-001", score_type="composite"
    ).first()
    assert score_row is not None


def test_compute_all_scores_updates_existing_score_row_on_recompute(
    mem_engine, mem_session
):
    _make_store(mem_session, "SB-001")
    _run_scoring(mem_engine)
    # Second run should update, not create another row
    _run_scoring(mem_engine)

    rows = mem_session.query(Score).filter_by(
        store_num="SB-001", score_type="composite"
    ).all()
    assert len(rows) == 1


def test_compute_all_scores_writes_careers_sub_score_when_data_present(
    mem_engine, mem_session
):
    _make_store(mem_session, "SB-001")
    _make_listing_signal(mem_session, "SB-001")
    _run_scoring(mem_engine)

    careers_row = mem_session.query(Score).filter_by(
        store_num="SB-001", score_type="careers"
    ).first()
    assert careers_row is not None


# ── Chain filter ──────────────────────────────────────────────────────────────


def test_compute_all_scores_filters_to_specified_chain(mem_engine, mem_session):
    _make_store(mem_session, "SB-001", chain="starbucks")
    _make_store(mem_session, "MCG-001", chain="mcdonalds")

    result = _run_scoring(mem_engine, chain="starbucks")
    assert "SB-001" in result
    assert "MCG-001" not in result


# ── Local avg wage ────────────────────────────────────────────────────────────


def test_compute_all_scores_uses_local_wage_index_for_wage_gap(
    mem_engine, mem_session
):
    _make_store(mem_session, "SB-001")
    wage = WageIndex(
        employer="Local Cafe",
        is_chain=False,
        industry="coffee_cafe",
        role_title="Barista",
        wage_min=18.0,
        wage_max=22.0,
        wage_period="hourly",
        location="Austin, TX",
        source="bls_v1",
        observed_at=datetime.utcnow(),
    )
    mem_session.add(wage)
    mem_session.commit()

    result = _run_scoring(mem_engine)
    assert result["SB-001"]["wage"] is not None


# ── Error handling ────────────────────────────────────────────────────────────


def test_compute_all_scores_returns_empty_dict_on_exception(mem_engine):
    # get_session is called before the try: block, so we need the exception to
    # occur inside it — use a mock session whose .query() raises instead.
    from unittest.mock import MagicMock
    failing_session = MagicMock()
    failing_session.query.side_effect = Exception("DB exploded")
    patches = _patch_scoring(mem_engine)
    # Override get_session to return the failing mock
    patches.append(
        patch("backend.scoring.engine.get_session", return_value=failing_session)
    )
    for p in patches: p.start()
    result = compute_all_scores("austin_tx")
    for p in patches: p.stop()
    assert result == {}
