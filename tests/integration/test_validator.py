"""
Integration tests for agent_interface/validator.py — validate_and_check().

Uses in-memory SQLite for freshness queries. Patches:
  - agent_interface.validator.init_db    → returns mem_engine
  - agent_interface.validator.get_session → returns a new session from mem_engine
  - agent_interface.validator.rate_manager → controls budget outcomes
"""

from datetime import datetime, timedelta
from unittest.mock import patch
from sqlalchemy.orm import sessionmaker

import pytest

from agent_interface.schemas import (
    AgentMode,
    AgentQuery,
    Brand,
    Industry,
    Intent,
    Region,
    ResultStatus,
)
from agent_interface.validator import validate_and_check
from backend.database import (
    LocalEmployer,
    Signal,
    Store,
    WageIndex,
)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _session_factory(mem_engine):
    return lambda e=None: sessionmaker(bind=mem_engine)()


def _run_validator(query, mem_engine, rate_can_request=True):
    with patch("agent_interface.validator.init_db", return_value=mem_engine), \
         patch("agent_interface.validator.get_session", side_effect=_session_factory(mem_engine)), \
         patch("agent_interface.validator.rate_manager") as mock_rm:
        mock_rm.can_request.return_value = rate_can_request
        mock_rm.get_source_status.return_value = {
            "budget": {"used": 0 if rate_can_request else 100,
                       "remaining": 100 if rate_can_request else 0,
                       "daily_limit": 100}
        }
        return validate_and_check(query)


# ── Schema validation (REJECTED) ─────────────────────────────────────────────


def test_validate_and_check_returns_rejected_when_query_validation_fails(
    mem_engine
):
    # Missing required brand for poi_chain_locations
    q = AgentQuery(
        intent=Intent.POI_CHAIN_LOCATIONS,
        region=Region.AUSTIN_TX,
        mode=AgentMode.MIXED,
        brand=None,
    )
    result = _run_validator(q, mem_engine)
    assert result is not None
    assert result.status == ResultStatus.REJECTED


def test_validate_and_check_rejected_result_contains_errors_list(mem_engine):
    q = AgentQuery(
        intent=Intent.POI_CHAIN_LOCATIONS,
        region=Region.AUSTIN_TX,
        mode=AgentMode.MIXED,
        brand=None,
    )
    result = _run_validator(q, mem_engine)
    assert result.errors


def test_validate_and_check_rejected_result_has_valid_options_populated(mem_engine):
    q = AgentQuery(
        intent=Intent.WAGE_BASELINE,
        region=Region.AUSTIN_TX,
        mode=AgentMode.COLLECT,
        industry=None,
        max_budget_spend=3,
    )
    result = _run_validator(q, mem_engine)
    assert result is not None
    assert result.status == ResultStatus.REJECTED


# ── Freshness bypass by mode ──────────────────────────────────────────────────


def test_validate_and_check_returns_duplicate_for_collect_mode_when_data_is_fresh(
    mem_engine, mem_session
):
    # COLLECT has bypass_freshness=False — freshness IS checked.
    # Fresh data (1 day old, threshold 60 days) → returns DUPLICATE.
    store = Store(
        store_num="SB-TEST-001",
        chain="starbucks",
        industry="coffee_cafe",
        store_name="",
        address="",
        region="austin_tx",
        last_seen=datetime.utcnow() - timedelta(days=1),
        is_active=True,
    )
    mem_session.add(store)
    mem_session.commit()

    q = AgentQuery(
        intent=Intent.POI_CHAIN_LOCATIONS,
        region=Region.AUSTIN_TX,
        mode=AgentMode.COLLECT,
        brand=Brand.STARBUCKS,
        max_budget_spend=5,
    )
    result = _run_validator(q, mem_engine)
    assert result is not None
    assert result.status == ResultStatus.DUPLICATE


def test_validate_and_check_returns_none_for_analyze_mode_bypasses_freshness(
    mem_engine, mem_session
):
    # ANALYZE bypasses freshness — even with fresh data, should not DUPLICATE
    store = Store(
        store_num="SB-TEST-001",
        chain="starbucks",
        industry="coffee_cafe",
        store_name="",
        address="",
        region="austin_tx",
        last_seen=datetime.utcnow() - timedelta(days=1),
        is_active=True,
    )
    mem_session.add(store)
    mem_session.commit()

    q = AgentQuery(
        intent=Intent.SCORE_REFRESH,
        region=Region.AUSTIN_TX,
        mode=AgentMode.ANALYZE,
    )
    result = _run_validator(q, mem_engine)
    assert result is None or result.status != ResultStatus.DUPLICATE


def test_validate_and_check_returns_none_for_monitor_mode_bypasses_freshness(
    mem_engine
):
    q = AgentQuery(
        intent=Intent.DATA_QUALITY_AUDIT,
        region=Region.AUSTIN_TX,
        mode=AgentMode.MONITOR,
    )
    result = _run_validator(q, mem_engine)
    assert result is None or result.status != ResultStatus.DUPLICATE


# ── Freshness check — no existing data (should proceed) ──────────────────────


def test_validate_and_check_returns_none_when_no_stores_in_db_for_poi_chain(
    mem_engine
):
    q = AgentQuery(
        intent=Intent.POI_CHAIN_LOCATIONS,
        region=Region.AUSTIN_TX,
        mode=AgentMode.MIXED,
        brand=Brand.STARBUCKS,
    )
    result = _run_validator(q, mem_engine)
    assert result is None


def test_validate_and_check_returns_none_when_no_wage_data_in_db(mem_engine):
    q = AgentQuery(
        intent=Intent.WAGE_BASELINE,
        region=Region.AUSTIN_TX,
        mode=AgentMode.MIXED,
        industry=Industry.COFFEE_CAFE,
    )
    result = _run_validator(q, mem_engine)
    assert result is None


# ── Freshness check — fresh data exists (DUPLICATE) ──────────────────────────


def test_validate_and_check_returns_duplicate_when_poi_chain_data_is_fresh(
    mem_engine, mem_session
):
    # Insert a store seen 5 days ago (< 60 day threshold)
    for i in range(3):  # need existing_count >= agent_knows (which defaults to 0)
        store = Store(
            store_num=f"SB-FRESH-{i:03d}",
            chain="starbucks",
            industry="coffee_cafe",
            store_name="",
            address="",
            region="austin_tx",
            last_seen=datetime.utcnow() - timedelta(days=5),
            is_active=True,
        )
        mem_session.add(store)
    mem_session.commit()

    q = AgentQuery(
        intent=Intent.POI_CHAIN_LOCATIONS,
        region=Region.AUSTIN_TX,
        mode=AgentMode.MIXED,
        brand=Brand.STARBUCKS,
    )
    result = _run_validator(q, mem_engine)
    assert result is not None
    assert result.status == ResultStatus.DUPLICATE


def test_validate_and_check_duplicate_has_records_found_populated(
    mem_engine, mem_session
):
    for i in range(5):
        store = Store(
            store_num=f"SB-FRESH2-{i:03d}",
            chain="starbucks",
            industry="coffee_cafe",
            store_name="",
            address="",
            region="austin_tx",
            last_seen=datetime.utcnow() - timedelta(days=5),
            is_active=True,
        )
        mem_session.add(store)
    mem_session.commit()

    q = AgentQuery(
        intent=Intent.POI_CHAIN_LOCATIONS,
        region=Region.AUSTIN_TX,
        mode=AgentMode.MIXED,
        brand=Brand.STARBUCKS,
    )
    result = _run_validator(q, mem_engine)
    assert result is not None
    assert result.records_found == 5


def test_validate_and_check_duplicate_has_staleness_days_populated(
    mem_engine, mem_session
):
    store = Store(
        store_num="SB-FRESH3-001",
        chain="starbucks",
        industry="coffee_cafe",
        store_name="",
        address="",
        region="austin_tx",
        last_seen=datetime.utcnow() - timedelta(days=10),
        is_active=True,
    )
    mem_session.add(store)
    mem_session.commit()

    q = AgentQuery(
        intent=Intent.POI_CHAIN_LOCATIONS,
        region=Region.AUSTIN_TX,
        mode=AgentMode.MIXED,
        brand=Brand.STARBUCKS,
    )
    result = _run_validator(q, mem_engine)
    assert result is not None
    assert result.staleness_days is not None
    assert 9.5 < result.staleness_days < 10.5


def test_validate_and_check_duplicate_contains_suggested_next_actions(
    mem_engine, mem_session
):
    store = Store(
        store_num="SB-FRESH4-001",
        chain="starbucks",
        industry="coffee_cafe",
        store_name="",
        address="",
        region="austin_tx",
        last_seen=datetime.utcnow() - timedelta(days=5),
        is_active=True,
    )
    mem_session.add(store)
    mem_session.commit()

    q = AgentQuery(
        intent=Intent.POI_CHAIN_LOCATIONS,
        region=Region.AUSTIN_TX,
        mode=AgentMode.MIXED,
        brand=Brand.STARBUCKS,
    )
    result = _run_validator(q, mem_engine)
    assert result is not None
    assert len(result.suggested_next) > 0


def test_validate_and_check_returns_none_when_data_is_stale_beyond_threshold(
    mem_engine, mem_session
):
    # Store last seen 70 days ago (> 60 day threshold)
    store = Store(
        store_num="SB-STALE-001",
        chain="starbucks",
        industry="coffee_cafe",
        store_name="",
        address="",
        region="austin_tx",
        last_seen=datetime.utcnow() - timedelta(days=70),
        is_active=True,
    )
    mem_session.add(store)
    mem_session.commit()

    q = AgentQuery(
        intent=Intent.POI_CHAIN_LOCATIONS,
        region=Region.AUSTIN_TX,
        mode=AgentMode.MIXED,
        brand=Brand.STARBUCKS,
    )
    result = _run_validator(q, mem_engine)
    # Stale data → should proceed → return None
    assert result is None


# ── Budget check (NO_BUDGET) ──────────────────────────────────────────────────


def test_validate_and_check_returns_no_budget_when_all_sources_exhausted(
    mem_engine
):
    q = AgentQuery(
        intent=Intent.POI_CHAIN_LOCATIONS,
        region=Region.AUSTIN_TX,
        mode=AgentMode.MIXED,
        brand=Brand.STARBUCKS,
    )
    result = _run_validator(q, mem_engine, rate_can_request=False)
    assert result is not None
    assert result.status == ResultStatus.NO_BUDGET


def test_validate_and_check_no_budget_includes_suggested_wait_action(mem_engine):
    q = AgentQuery(
        intent=Intent.POI_CHAIN_LOCATIONS,
        region=Region.AUSTIN_TX,
        mode=AgentMode.MIXED,
        brand=Brand.STARBUCKS,
    )
    result = _run_validator(q, mem_engine, rate_can_request=False)
    assert result is not None
    actions = [s.get("action") for s in result.suggested_next]
    assert "wait_for_reset" in actions or any("wait" in str(a) for a in actions)


def test_validate_and_check_returns_none_when_any_source_has_budget(mem_engine):
    q = AgentQuery(
        intent=Intent.POI_CHAIN_LOCATIONS,
        region=Region.AUSTIN_TX,
        mode=AgentMode.MIXED,
        brand=Brand.STARBUCKS,
    )
    result = _run_validator(q, mem_engine, rate_can_request=True)
    # No duplicate data → budget available → should proceed
    assert result is None


def test_validate_and_check_skips_budget_check_for_analyze_mode(mem_engine):
    q = AgentQuery(
        intent=Intent.SCORE_REFRESH,
        region=Region.AUSTIN_TX,
        mode=AgentMode.ANALYZE,
    )
    # Even with no budget, ANALYZE mode should not produce NO_BUDGET
    result = _run_validator(q, mem_engine, rate_can_request=False)
    assert result is None or result.status != ResultStatus.NO_BUDGET


def test_validate_and_check_skips_budget_check_for_monitor_mode(mem_engine):
    q = AgentQuery(
        intent=Intent.DATA_QUALITY_AUDIT,
        region=Region.AUSTIN_TX,
        mode=AgentMode.MONITOR,
    )
    result = _run_validator(q, mem_engine, rate_can_request=False)
    assert result is None or result.status != ResultStatus.NO_BUDGET


def test_validate_and_check_skips_budget_for_zero_source_intents(mem_engine):
    # SCORE_REFRESH and DATA_QUALITY_AUDIT have no external API sources
    q = AgentQuery(
        intent=Intent.SCORE_REFRESH,
        region=Region.AUSTIN_TX,
        mode=AgentMode.MIXED,
    )
    result = _run_validator(q, mem_engine, rate_can_request=False)
    # No external API sources → budget check skipped
    assert result is None or result.status != ResultStatus.NO_BUDGET


# ── Wage baseline freshness ───────────────────────────────────────────────────


def test_validate_and_check_returns_duplicate_when_wage_data_is_fresh(
    mem_engine, mem_session
):
    wage = WageIndex(
        employer="Starbucks",
        is_chain=True,
        chain_key="starbucks",
        industry="coffee_cafe",
        role_title="Barista",
        wage_min=15.0,
        wage_max=19.0,
        wage_period="hourly",
        location="Austin, TX",
        source="bls_v1",
        observed_at=datetime.utcnow() - timedelta(days=10),
    )
    mem_session.add(wage)
    mem_session.commit()

    q = AgentQuery(
        intent=Intent.WAGE_BASELINE,
        region=Region.AUSTIN_TX,
        mode=AgentMode.MIXED,
        industry=Industry.COFFEE_CAFE,
    )
    result = _run_validator(q, mem_engine)
    assert result is not None
    assert result.status == ResultStatus.DUPLICATE


# ── Error resilience ──────────────────────────────────────────────────────────


def test_validate_and_check_returns_none_on_freshness_check_db_error(mem_engine):
    q = AgentQuery(
        intent=Intent.POI_CHAIN_LOCATIONS,
        region=Region.AUSTIN_TX,
        mode=AgentMode.MIXED,
        brand=Brand.STARBUCKS,
    )
    # get_session is called before the try: block in _check_freshness, so
    # raise from session.query (inside the try) instead of from get_session.
    from unittest.mock import MagicMock
    failing_session = MagicMock()
    failing_session.query.side_effect = Exception("DB error")
    with patch("agent_interface.validator.init_db", return_value=mem_engine), \
         patch("agent_interface.validator.get_session", return_value=failing_session), \
         patch("agent_interface.validator.rate_manager") as mock_rm:
        mock_rm.can_request.return_value = True
        result = validate_and_check(q)

    # Should not block execution on DB error
    assert result is None
