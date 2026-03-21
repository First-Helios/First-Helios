"""
Unit tests for backend/database.py model properties and helper functions.

Tests SourceFreshness/RateBudget computed properties and
upsert_freshness() / check_freshness() helpers using in-memory SQLite.
"""

from datetime import datetime, timedelta

import pytest

from backend.database import (
    RateBudget,
    Signal,
    SourceFreshness,
    Store,
    check_freshness,
    upsert_freshness,
)


# ── SourceFreshness properties ────────────────────────────────────────────────


def test_source_freshness_age_days_returns_correct_value_for_past_collection():
    sf = SourceFreshness(
        intent="poi_chain_locations",
        region="austin_tx",
        last_collected_at=datetime.utcnow() - timedelta(days=5),
        threshold_days=60.0,
        status="completed",
    )
    assert 4.9 < sf.age_days < 5.1


def test_source_freshness_age_days_returns_inf_when_last_collected_at_is_none():
    sf = SourceFreshness(
        intent="poi_chain_locations",
        region="austin_tx",
        last_collected_at=None,
        threshold_days=60.0,
        status="completed",
    )
    assert sf.age_days == float("inf")


def test_source_freshness_is_stale_returns_true_when_age_exceeds_threshold():
    sf = SourceFreshness(
        intent="poi_chain_locations",
        region="austin_tx",
        last_collected_at=datetime.utcnow() - timedelta(days=70),
        threshold_days=60.0,
        status="completed",
    )
    assert sf.is_stale is True


def test_source_freshness_is_stale_returns_false_when_age_below_threshold():
    sf = SourceFreshness(
        intent="poi_chain_locations",
        region="austin_tx",
        last_collected_at=datetime.utcnow() - timedelta(days=30),
        threshold_days=60.0,
        status="completed",
    )
    assert sf.is_stale is False


def test_source_freshness_is_stale_returns_true_when_last_collected_at_is_none():
    sf = SourceFreshness(
        intent="poi_chain_locations",
        region="austin_tx",
        last_collected_at=None,
        threshold_days=60.0,
        status="completed",
    )
    assert sf.is_stale is True


def test_source_freshness_next_due_at_returns_correct_datetime():
    collected = datetime(2026, 1, 1)
    sf = SourceFreshness(
        intent="poi_chain_locations",
        region="austin_tx",
        last_collected_at=collected,
        threshold_days=60.0,
        status="completed",
    )
    expected = collected + timedelta(days=60)
    assert sf.next_due_at == expected


def test_source_freshness_next_due_at_returns_none_when_last_collected_at_is_none():
    sf = SourceFreshness(
        intent="poi_chain_locations",
        region="austin_tx",
        last_collected_at=None,
        threshold_days=60.0,
        status="completed",
    )
    assert sf.next_due_at is None


def test_source_freshness_to_dict_contains_all_required_keys():
    sf = SourceFreshness(
        intent="poi_chain_locations",
        region="austin_tx",
        last_collected_at=datetime.utcnow() - timedelta(days=10),
        threshold_days=60.0,
        status="completed",
        records_collected=100,
    )
    d = sf.to_dict()
    for key in ("intent", "region", "is_stale", "age_days", "threshold_days",
                "next_due_at", "records_collected", "status"):
        assert key in d, f"Missing key: {key}"


# ── RateBudget properties ─────────────────────────────────────────────────────


def test_rate_budget_remaining_returns_correct_value():
    rb = RateBudget(source_key="bls_v1", date="2026-03-20", daily_limit=100, used=40)
    assert rb.remaining == 60


def test_rate_budget_remaining_never_goes_below_zero():
    rb = RateBudget(source_key="bls_v1", date="2026-03-20", daily_limit=50, used=200)
    assert rb.remaining == 0


def test_rate_budget_success_rate_returns_zero_when_no_requests():
    rb = RateBudget(source_key="bls_v1", date="2026-03-20", daily_limit=100, used=0, succeeded=0)
    assert rb.success_rate == 0.0


def test_rate_budget_success_rate_computes_correctly_with_mixed_results():
    rb = RateBudget(
        source_key="bls_v1", date="2026-03-20", daily_limit=100,
        used=10, succeeded=8, failed=2,
    )
    assert rb.success_rate == 80.0


def test_rate_budget_success_rate_returns_100_when_all_succeed():
    rb = RateBudget(
        source_key="bls_v1", date="2026-03-20", daily_limit=100,
        used=5, succeeded=5, failed=0,
    )
    assert rb.success_rate == 100.0


def test_rate_budget_avg_latency_returns_zero_when_no_requests():
    rb = RateBudget(source_key="bls_v1", date="2026-03-20", daily_limit=100, used=0, total_latency_ms=0)
    assert rb.avg_latency_ms == 0.0


def test_rate_budget_avg_latency_computes_correctly():
    rb = RateBudget(
        source_key="bls_v1", date="2026-03-20", daily_limit=100,
        used=4, total_latency_ms=800,
    )
    assert rb.avg_latency_ms == 200.0


def test_rate_budget_to_dict_includes_remaining_and_success_rate():
    rb = RateBudget(
        source_key="bls_v1", date="2026-03-20", daily_limit=100,
        used=20, succeeded=18, failed=2, total_latency_ms=4000,
    )
    d = rb.to_dict()
    assert "remaining" in d
    assert "success_rate" in d
    assert d["remaining"] == 80
    assert d["success_rate"] == 90.0


# ── upsert_freshness() ────────────────────────────────────────────────────────


def test_upsert_freshness_creates_new_record_when_none_exists(mem_session):
    before = mem_session.query(SourceFreshness).count()
    upsert_freshness(
        intent="poi_chain_locations",
        region="austin_tx",
        brand="starbucks",
        industry=None,
        records_collected=287,
        threshold_days=60.0,
        db_session=mem_session,
    )
    after = mem_session.query(SourceFreshness).count()
    assert after == before + 1


def test_upsert_freshness_updates_existing_record_on_second_call(mem_session):
    upsert_freshness(
        intent="wage_baseline",
        region="austin_tx",
        brand=None,
        industry="coffee_cafe",
        records_collected=10,
        threshold_days=90.0,
        db_session=mem_session,
    )
    upsert_freshness(
        intent="wage_baseline",
        region="austin_tx",
        brand=None,
        industry="coffee_cafe",
        records_collected=25,
        threshold_days=90.0,
        db_session=mem_session,
    )
    rows = mem_session.query(SourceFreshness).filter_by(
        intent="wage_baseline", region="austin_tx", industry="coffee_cafe"
    ).all()
    assert len(rows) == 1
    assert rows[0].records_collected == 25


def test_upsert_freshness_updates_last_collected_at_to_now(mem_session):
    before = datetime.utcnow() - timedelta(seconds=1)
    upsert_freshness(
        intent="score_refresh",
        region="austin_tx",
        brand=None,
        industry=None,
        records_collected=5,
        threshold_days=1.0,
        db_session=mem_session,
    )
    row = mem_session.query(SourceFreshness).filter_by(
        intent="score_refresh", region="austin_tx"
    ).first()
    assert row is not None
    assert row.last_collected_at >= before


def test_upsert_freshness_stores_null_brand_for_non_brand_intents(mem_session):
    upsert_freshness(
        intent="wage_baseline",
        region="austin_tx",
        brand=None,
        industry="coffee_cafe",
        records_collected=5,
        threshold_days=90.0,
        db_session=mem_session,
    )
    row = mem_session.query(SourceFreshness).filter_by(
        intent="wage_baseline", region="austin_tx"
    ).first()
    assert row.brand is None


def test_upsert_freshness_different_brands_create_separate_rows(mem_session):
    upsert_freshness(
        intent="poi_chain_locations", region="austin_tx",
        brand="starbucks", industry=None, records_collected=100,
        threshold_days=60.0, db_session=mem_session,
    )
    upsert_freshness(
        intent="poi_chain_locations", region="austin_tx",
        brand="dutch_bros", industry=None, records_collected=50,
        threshold_days=60.0, db_session=mem_session,
    )
    rows = mem_session.query(SourceFreshness).filter_by(
        intent="poi_chain_locations", region="austin_tx"
    ).all()
    assert len(rows) == 2


# ── check_freshness() ─────────────────────────────────────────────────────────


def test_check_freshness_returns_never_collected_dict_when_no_record(mem_session):
    result = check_freshness(
        intent="poi_chain_locations",
        region="austin_tx",
        brand="starbucks",
        db_session=mem_session,
    )
    assert result["is_stale"] is True
    assert result.get("never_collected") is True
    assert result["records_collected"] == 0


def test_check_freshness_returns_is_stale_true_when_threshold_exceeded(mem_session):
    upsert_freshness(
        intent="poi_chain_locations", region="austin_tx",
        brand="starbucks", industry=None, records_collected=200,
        threshold_days=60.0, db_session=mem_session,
    )
    # Manually backdate
    row = mem_session.query(SourceFreshness).filter_by(
        intent="poi_chain_locations", region="austin_tx", brand="starbucks"
    ).first()
    row.last_collected_at = datetime.utcnow() - timedelta(days=70)
    mem_session.commit()

    result = check_freshness(
        intent="poi_chain_locations", region="austin_tx",
        brand="starbucks", db_session=mem_session,
    )
    assert result["is_stale"] is True


def test_check_freshness_returns_is_stale_false_when_data_is_fresh(mem_session):
    upsert_freshness(
        intent="poi_chain_locations", region="austin_tx",
        brand="starbucks", industry=None, records_collected=287,
        threshold_days=60.0, db_session=mem_session,
    )
    result = check_freshness(
        intent="poi_chain_locations", region="austin_tx",
        brand="starbucks", db_session=mem_session,
    )
    assert result["is_stale"] is False


def test_check_freshness_returns_correct_records_collected_count(mem_session):
    upsert_freshness(
        intent="wage_baseline", region="austin_tx",
        brand=None, industry="coffee_cafe", records_collected=42,
        threshold_days=90.0, db_session=mem_session,
    )
    result = check_freshness(
        intent="wage_baseline", region="austin_tx",
        industry="coffee_cafe", db_session=mem_session,
    )
    assert result["records_collected"] == 42


def test_check_freshness_includes_next_due_at_in_result(mem_session):
    upsert_freshness(
        intent="wage_baseline", region="austin_tx",
        brand=None, industry="coffee_cafe", records_collected=10,
        threshold_days=90.0, db_session=mem_session,
    )
    result = check_freshness(
        intent="wage_baseline", region="austin_tx",
        industry="coffee_cafe", db_session=mem_session,
    )
    assert result["next_due_at"] is not None


# ── Signal.get_metadata / set_metadata ────────────────────────────────────────


def test_signal_get_set_metadata_roundtrip():
    sig = Signal(
        store_num="SB-001",
        source="careers_api",
        signal_type="listing",
        value=1.0,
        observed_at=datetime.utcnow(),
    )
    data = {"posted_date": "2026-01-01", "url": "https://example.com"}
    sig.set_metadata(data)
    assert sig.get_metadata() == data


def test_signal_get_metadata_returns_empty_dict_when_json_is_none():
    sig = Signal(
        store_num="SB-001",
        source="careers_api",
        signal_type="listing",
        value=1.0,
        observed_at=datetime.utcnow(),
        metadata_json=None,
    )
    assert sig.get_metadata() == {}


def test_signal_to_dict_returns_all_expected_keys():
    sig = Signal(
        store_num="SB-001",
        source="careers_api",
        signal_type="listing",
        value=1.0,
        observed_at=datetime.utcnow(),
    )
    d = sig.to_dict()
    for key in ("store_num", "source", "signal_type", "value", "observed_at"):
        assert key in d


# ── Store.to_dict ─────────────────────────────────────────────────────────────


def test_store_to_dict_returns_all_expected_keys():
    store = Store(
        store_num="SB-001",
        chain="starbucks",
        industry="coffee_cafe",
        store_name="Test Store",
        address="123 Main St",
        lat=30.2672,
        lng=-97.7431,
        region="austin_tx",
        is_active=True,
    )
    d = store.to_dict()
    for key in ("store_num", "chain", "industry", "lat", "lng", "region", "is_active"):
        assert key in d
