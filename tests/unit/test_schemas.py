"""
Unit tests for agent_interface/schemas.py.

Tests AgentQuery.validate(), parse_agent_query(), ModeConfig, freshness
thresholds, and enum properties. No DB or external calls.
"""

import pytest

from agent_interface.schemas import (
    FRESHNESS_THRESHOLDS,
    AgentMode,
    AgentQuery,
    Brand,
    DataSource,
    Industry,
    Intent,
    QueuePriority,
    Region,
    ResultStatus,
    get_mode_config,
    parse_agent_query,
)


# ── AgentQuery.validate() ─────────────────────────────────────────────────────


def test_validate_returns_empty_list_for_valid_poi_chain_query():
    q = AgentQuery(
        intent=Intent.POI_CHAIN_LOCATIONS,
        region=Region.AUSTIN_TX,
        mode=AgentMode.MIXED,
        brand=Brand.STARBUCKS,
    )
    assert q.validate() == []


def test_validate_returns_empty_list_for_valid_wage_baseline_query():
    q = AgentQuery(
        intent=Intent.WAGE_BASELINE,
        region=Region.AUSTIN_TX,
        mode=AgentMode.COLLECT,
        industry=Industry.COFFEE_CAFE,
        max_budget_spend=3,
    )
    assert q.validate() == []


def test_validate_returns_error_when_poi_chain_intent_missing_brand():
    q = AgentQuery(
        intent=Intent.POI_CHAIN_LOCATIONS,
        region=Region.AUSTIN_TX,
        mode=AgentMode.MIXED,
        brand=None,
    )
    errors = q.validate()
    assert any("brand" in e for e in errors)


def test_validate_returns_error_when_wage_baseline_intent_missing_industry():
    q = AgentQuery(
        intent=Intent.WAGE_BASELINE,
        region=Region.AUSTIN_TX,
        mode=AgentMode.COLLECT,
        industry=None,
        max_budget_spend=3,
    )
    errors = q.validate()
    assert any("industry" in e for e in errors)


def test_validate_returns_error_when_job_posting_volume_missing_brand():
    q = AgentQuery(
        intent=Intent.JOB_POSTING_VOLUME,
        region=Region.AUSTIN_TX,
        mode=AgentMode.MIXED,
        brand=None,
    )
    errors = q.validate()
    assert any("brand" in e for e in errors)


def test_validate_returns_error_when_sentiment_check_missing_brand():
    q = AgentQuery(
        intent=Intent.SENTIMENT_CHECK,
        region=Region.AUSTIN_TX,
        mode=AgentMode.MIXED,
        brand=None,
    )
    errors = q.validate()
    assert any("brand" in e for e in errors)


def test_validate_returns_error_when_max_results_exceeds_5000():
    q = AgentQuery(
        intent=Intent.SCORE_REFRESH,
        region=Region.AUSTIN_TX,
        mode=AgentMode.ANALYZE,
        max_results=5001,
    )
    errors = q.validate()
    assert any("5000" in e for e in errors)


def test_validate_returns_error_when_max_results_below_1():
    q = AgentQuery(
        intent=Intent.SCORE_REFRESH,
        region=Region.AUSTIN_TX,
        mode=AgentMode.ANALYZE,
        max_results=0,
    )
    errors = q.validate()
    assert any("max_results" in e for e in errors)


def test_validate_returns_error_when_max_budget_spend_exceeds_mode_cap():
    # COLLECT mode cap is 10 per query
    q = AgentQuery(
        intent=Intent.POI_CHAIN_LOCATIONS,
        region=Region.AUSTIN_TX,
        mode=AgentMode.COLLECT,
        brand=Brand.STARBUCKS,
        max_budget_spend=20,
    )
    errors = q.validate()
    assert any("max_budget_spend" in e or "cap" in e for e in errors)


def test_validate_returns_error_when_max_budget_spend_below_1():
    q = AgentQuery(
        intent=Intent.SCORE_REFRESH,
        region=Region.AUSTIN_TX,
        mode=AgentMode.ANALYZE,
        max_budget_spend=0,
    )
    errors = q.validate()
    assert any("max_budget_spend" in e for e in errors)


def test_validate_returns_error_when_intent_not_allowed_in_collect_mode():
    # SCORE_REFRESH is not in COLLECT's allowed_intents
    q = AgentQuery(
        intent=Intent.SCORE_REFRESH,
        region=Region.AUSTIN_TX,
        mode=AgentMode.COLLECT,
    )
    errors = q.validate()
    assert any("collect" in e.lower() or "allowed" in e.lower() for e in errors)


def test_validate_returns_error_when_analyze_mode_used_with_collection_intent():
    # POI_CHAIN_LOCATIONS is not in ANALYZE's allowed_intents
    q = AgentQuery(
        intent=Intent.POI_CHAIN_LOCATIONS,
        region=Region.AUSTIN_TX,
        mode=AgentMode.ANALYZE,
        brand=Brand.STARBUCKS,
    )
    errors = q.validate()
    assert any("analyze" in e.lower() or "allowed" in e.lower() for e in errors)


def test_validate_collects_multiple_errors_in_single_call():
    # Missing brand AND max_results out of range
    q = AgentQuery(
        intent=Intent.POI_CHAIN_LOCATIONS,
        region=Region.AUSTIN_TX,
        mode=AgentMode.MIXED,
        brand=None,
        max_results=0,
    )
    errors = q.validate()
    assert len(errors) >= 2


def test_validate_mixed_mode_allows_all_intents():
    for intent in Intent:
        # Supply required fields
        brand = Brand.STARBUCKS if intent in (
            Intent.POI_CHAIN_LOCATIONS,
            Intent.JOB_POSTING_VOLUME,
            Intent.SENTIMENT_CHECK,
        ) else None
        industry = Industry.COFFEE_CAFE if intent in (
            Intent.POI_LOCAL_DENSITY,
            Intent.WAGE_BASELINE,
        ) else None
        q = AgentQuery(
            intent=intent,
            region=Region.AUSTIN_TX,
            mode=AgentMode.MIXED,
            brand=brand,
            industry=industry,
        )
        errors = [e for e in q.validate() if "not allowed in mode" in e]
        assert errors == [], f"Intent {intent.value} incorrectly blocked in MIXED mode"


# ── parse_agent_query() ───────────────────────────────────────────────────────


def test_parse_agent_query_returns_query_and_empty_errors_on_valid_data():
    data = {
        "intent": "poi_chain_locations",
        "region": "austin_tx",
        "brand": "starbucks",
    }
    query, errors = parse_agent_query(data)
    assert query is not None
    assert errors == []
    assert query.intent == Intent.POI_CHAIN_LOCATIONS
    assert query.brand == Brand.STARBUCKS


def test_parse_agent_query_returns_none_and_error_on_invalid_intent():
    data = {"intent": "nonexistent_intent", "region": "austin_tx"}
    query, errors = parse_agent_query(data)
    assert query is None
    assert len(errors) > 0
    assert "nonexistent_intent" in errors[0]


def test_parse_agent_query_returns_none_and_error_on_invalid_region():
    data = {"intent": "score_refresh", "region": "mars"}
    query, errors = parse_agent_query(data)
    assert query is None
    assert any("mars" in e for e in errors)


def test_parse_agent_query_returns_none_and_error_on_invalid_brand():
    data = {
        "intent": "poi_chain_locations",
        "region": "austin_tx",
        "brand": "not_a_real_brand",
    }
    query, errors = parse_agent_query(data)
    assert query is None
    assert any("not_a_real_brand" in e for e in errors)


def test_parse_agent_query_returns_none_and_error_on_invalid_industry():
    data = {
        "intent": "wage_baseline",
        "region": "austin_tx",
        "industry": "flying_cars",
    }
    query, errors = parse_agent_query(data)
    assert query is None
    assert any("flying_cars" in e for e in errors)


def test_parse_agent_query_returns_none_and_error_on_invalid_mode():
    data = {
        "intent": "score_refresh",
        "region": "austin_tx",
        "mode": "turbo",
    }
    query, errors = parse_agent_query(data)
    assert query is None
    assert any("turbo" in e for e in errors)


def test_parse_agent_query_caps_max_results_at_5000():
    data = {
        "intent": "score_refresh",
        "region": "austin_tx",
        "max_results": 99999,
    }
    query, errors = parse_agent_query(data)
    assert query is not None
    assert query.max_results == 5000


def test_parse_agent_query_caps_max_budget_spend_at_50():
    # ANALYZE mode has max_api_calls_per_query=0 → effective_budget_cap=50
    # so max_budget_spend=50 passes validation
    data = {
        "intent": "score_refresh",
        "region": "austin_tx",
        "mode": "analyze",
        "max_budget_spend": 999,
    }
    query, errors = parse_agent_query(data)
    assert query is not None
    assert query.max_budget_spend == 50


def test_parse_agent_query_uses_defaults_when_optional_fields_absent():
    data = {"intent": "score_refresh", "region": "austin_tx"}
    query, errors = parse_agent_query(data)
    assert query is not None
    assert query.mode == AgentMode.MIXED
    assert query.brand is None
    assert query.industry is None


def test_parse_agent_query_error_message_contains_valid_options_on_bad_intent():
    data = {"intent": "bad_intent", "region": "austin_tx"}
    _, errors = parse_agent_query(data)
    # Error should hint at valid options
    combined = " ".join(errors)
    assert "poi_chain_locations" in combined or "Valid" in combined


# ── get_mode_config() ─────────────────────────────────────────────────────────


def test_get_mode_config_collect_mode_has_bypass_freshness_false():
    cfg = get_mode_config(AgentMode.COLLECT)
    assert cfg.bypass_freshness is False


def test_get_mode_config_analyze_mode_has_bypass_freshness_true():
    cfg = get_mode_config(AgentMode.ANALYZE)
    assert cfg.bypass_freshness is True


def test_get_mode_config_monitor_mode_has_bypass_freshness_true():
    cfg = get_mode_config(AgentMode.MONITOR)
    assert cfg.bypass_freshness is True


def test_get_mode_config_collect_mode_has_allow_collection_true():
    cfg = get_mode_config(AgentMode.COLLECT)
    assert cfg.allow_collection is True


def test_get_mode_config_analyze_mode_has_allow_collection_false():
    cfg = get_mode_config(AgentMode.ANALYZE)
    assert cfg.allow_collection is False


def test_get_mode_config_monitor_mode_has_allow_collection_false():
    cfg = get_mode_config(AgentMode.MONITOR)
    assert cfg.allow_collection is False


def test_get_mode_config_mixed_mode_allows_all_intents():
    cfg = get_mode_config(AgentMode.MIXED)
    all_intent_values = {i.value for i in Intent}
    assert all_intent_values <= cfg.allowed_intents


def test_get_mode_config_collect_mode_does_not_allow_score_refresh():
    cfg = get_mode_config(AgentMode.COLLECT)
    assert Intent.SCORE_REFRESH.value not in cfg.allowed_intents


def test_get_mode_config_analyze_mode_does_not_allow_poi_chain():
    cfg = get_mode_config(AgentMode.ANALYZE)
    assert Intent.POI_CHAIN_LOCATIONS.value not in cfg.allowed_intents


def test_get_mode_config_accepts_string_mode_key():
    cfg = get_mode_config("mixed")
    assert cfg.name == "mixed"


# ── FRESHNESS_THRESHOLDS ──────────────────────────────────────────────────────


def test_freshness_thresholds_keys_match_all_intent_values():
    intent_values = {i.value for i in Intent}
    threshold_keys = set(FRESHNESS_THRESHOLDS.keys())
    assert intent_values == threshold_keys


def test_freshness_thresholds_zero_threshold_for_always_run_intents():
    always_run = {
        Intent.DATA_QUALITY_AUDIT.value,
        Intent.CAMPAIGN_STATUS.value,
        Intent.DISCOVERY_SCAN.value,
    }
    for key in always_run:
        assert FRESHNESS_THRESHOLDS[key] == 0.0, f"{key} should have 0 threshold"


def test_freshness_threshold_poi_chain_is_60_days():
    assert FRESHNESS_THRESHOLDS[Intent.POI_CHAIN_LOCATIONS.value] == 60.0


def test_freshness_threshold_wage_baseline_is_90_days():
    assert FRESHNESS_THRESHOLDS[Intent.WAGE_BASELINE.value] == 90.0


def test_freshness_threshold_job_posting_volume_is_14_days():
    assert FRESHNESS_THRESHOLDS[Intent.JOB_POSTING_VOLUME.value] == 14.0


def test_freshness_threshold_sentiment_check_is_14_days():
    assert FRESHNESS_THRESHOLDS[Intent.SENTIMENT_CHECK.value] == 14.0


def test_freshness_threshold_score_refresh_is_1_day():
    assert FRESHNESS_THRESHOLDS[Intent.SCORE_REFRESH.value] == 1.0


# ── QueuePriority.weight ──────────────────────────────────────────────────────


def test_queue_priority_weight_critical_is_10():
    assert QueuePriority.CRITICAL.weight == 10


def test_queue_priority_weight_normal_is_50():
    assert QueuePriority.NORMAL.weight == 50


def test_queue_priority_weight_backfill_is_90():
    assert QueuePriority.BACKFILL.weight == 90


def test_queue_priority_weight_increases_from_critical_to_backfill():
    weights = [p.weight for p in QueuePriority]
    assert weights == sorted(weights)


# ── Enum string membership ────────────────────────────────────────────────────


def test_agent_mode_is_str_enum():
    assert isinstance(AgentMode.COLLECT, str)
    assert AgentMode.COLLECT == "collect"


def test_intent_is_str_enum():
    assert isinstance(Intent.WAGE_BASELINE, str)
    assert Intent.WAGE_BASELINE == "wage_baseline"


def test_result_status_has_all_expected_values():
    expected = {"completed", "partial", "queued", "rejected", "duplicate", "paused", "no_budget", "failed"}
    actual = {s.value for s in ResultStatus}
    assert expected == actual
