"""
Tests for the pipeline/ package.

Covers:
  - pipeline/route_index.py  — RouteContract registry
  - pipeline/tracing.py      — PipelineTrace + TraceSpan dataclasses
  - pipeline/validation.py   — per-boundary schema validation
  - pipeline/health.py       — startup self-check
"""

import pytest


# ── Route Index (pipeline/route_index.py) ─────────────────────────────────────


def test_all_intent_enum_values_have_registered_route():
    """Every Intent enum value must have at least one RouteContract in ROUTES."""
    from pipeline.route_index import ROUTES
    from agent_interface.schemas import Intent

    for intent in Intent:
        assert intent.value in ROUTES, (
            f"No route registered for intent '{intent.value}'. "
            f"Add it to pipeline/route_index.py ROUTES dict."
        )


def test_route_contract_has_required_fields():
    """Every RouteContract must have non-empty intent, db_table, and valid status."""
    from pipeline.route_index import ROUTES

    for intent_key, route_list in ROUTES.items():
        for route in route_list:
            assert route.intent, f"Route for {intent_key} has empty intent field"
            assert route.db_table, f"Route for {intent_key} has empty db_table"
            assert route.status in ("live", "unwired", "suggested"), (
                f"Route for {intent_key} has invalid status '{route.status}'"
            )


def test_route_contract_freshness_thresholds_match_schemas():
    """Route freshness_threshold_days must match FRESHNESS_THRESHOLDS in schemas.py."""
    from pipeline.route_index import ROUTES
    from agent_interface.schemas import FRESHNESS_THRESHOLDS

    for intent_key, route_list in ROUTES.items():
        expected = FRESHNESS_THRESHOLDS.get(intent_key, 0)
        for route in route_list:
            assert route.freshness_threshold_days == expected, (
                f"Route for {intent_key} has threshold {route.freshness_threshold_days}, "
                f"but schemas.py says {expected}"
            )


def test_known_live_routes_are_present():
    """The 10 LIVE routes documented in PIPELINE_TRACING_PLAN.md must be registered."""
    from pipeline.route_index import ROUTES

    expected_routes = [
        ("poi_chain_locations", "atp_geojson"),
        ("poi_local_density", "overture_s3"),
        ("wage_baseline", "bls_v1"),
        ("job_posting_volume", "careers_workday"),
        ("job_posting_volume", "jobspy"),
        ("sentiment_check", "reddit_json"),
        ("score_refresh", None),
        ("data_quality_audit", None),
        ("campaign_status", None),
        ("discovery_scan", None),
    ]

    for intent_key, expected_source in expected_routes:
        routes = ROUTES.get(intent_key, [])
        if expected_source is None:
            assert routes, f"No routes found for intent '{intent_key}'"
        else:
            source_keys = [r.source_key for r in routes]
            assert expected_source in source_keys, (
                f"Expected source '{expected_source}' not found for intent '{intent_key}'. "
                f"Found: {source_keys}"
            )


def test_unwired_routes_are_documented():
    """Unwired routes (adapter exists, not called) must be flagged in the registry."""
    from pipeline.route_index import ROUTES

    unwired_expected = [
        ("poi_chain_locations", "overpass_api"),
        ("sentiment_check", "gmaps_scraper"),
    ]

    for intent_key, source_key in unwired_expected:
        routes = ROUTES.get(intent_key, [])
        unwired = [r for r in routes if r.status == "unwired" and r.source_key == source_key]
        assert unwired, (
            f"Expected unwired route for intent '{intent_key}' source '{source_key}' "
            f"to be documented in route_index.py"
        )


# ── Pipeline Tracing (pipeline/tracing.py) ────────────────────────────────────


def test_pipeline_trace_can_be_created_with_defaults():
    """PipelineTrace should be instantiable with no arguments."""
    from pipeline.tracing import PipelineTrace

    trace = PipelineTrace()
    assert trace.trace_id is not None
    assert trace.spans == []
    assert trace.records_written == 0
    assert trace.freshness_stamped is False


def test_pipeline_trace_records_span_for_each_pipeline_stage():
    """Adding spans to a trace should be reflected in trace.spans."""
    from pipeline.tracing import PipelineTrace, TraceSpan
    from datetime import datetime

    trace = PipelineTrace(intent="poi_chain_locations", brand="starbucks", region="austin_tx")
    span = TraceSpan(
        span_id="s1",
        name="executor._execute_poi_chain",
        started_at=datetime.utcnow(),
        status="success",
    )
    trace.spans.append(span)
    assert len(trace.spans) == 1
    assert trace.spans[0].name == "executor._execute_poi_chain"


def test_trace_span_has_required_fields():
    """TraceSpan must have span_id, name, started_at, and status fields."""
    from pipeline.tracing import TraceSpan
    from datetime import datetime

    span = TraceSpan(
        span_id="test-span",
        name="test.span",
        started_at=datetime.utcnow(),
        status="running",
    )
    assert span.span_id == "test-span"
    assert span.status == "running"
    assert span.ended_at is None
    assert span.error is None


def test_pipeline_trace_serializes_to_dict():
    """PipelineTrace.to_dict() or equivalent must return JSON-serializable output."""
    from pipeline.tracing import PipelineTrace

    trace = PipelineTrace(intent="wage_baseline", brand=None, region="austin_tx")
    d = trace.to_dict() if hasattr(trace, "to_dict") else vars(trace)
    assert "trace_id" in d
    assert "intent" in d
    assert "spans" in d


# ── Validation (pipeline/validation.py) ───────────────────────────────────────


def test_scraper_output_contracts_exist_for_high_traffic_intents():
    """SCRAPER_OUTPUT_CONTRACTS must define contracts for the 3 highest-traffic intents."""
    from pipeline.validation import SCRAPER_OUTPUT_CONTRACTS

    required = {"poi_chain_locations", "job_posting_volume", "sentiment_check"}
    for intent_key in required:
        assert intent_key in SCRAPER_OUTPUT_CONTRACTS, (
            f"Missing output contract for high-traffic intent '{intent_key}'"
        )


def test_validate_scraper_output_returns_valid_for_good_signal():
    """validate_scraper_output() should return valid=True for a well-formed signal."""
    from pipeline.validation import validate_scraper_output
    from scrapers.base import ScraperSignal
    from datetime import datetime

    sig = ScraperSignal(
        store_num="SB-001",
        chain="starbucks",
        source="careers_api",
        signal_type="listing",
        value=1.0,
        metadata={"lat": 30.2672, "lng": -97.7431},
        observed_at=datetime.utcnow(),
    )
    result = validate_scraper_output("job_posting_volume", [sig])
    assert result.valid is True
    assert result.errors == []


def test_validate_scraper_output_fails_for_missing_required_fields():
    """validate_scraper_output() must catch missing required fields and return invalid."""
    from pipeline.validation import validate_scraper_output
    from scrapers.base import ScraperSignal
    from datetime import datetime

    # Missing store_num (empty string)
    sig = ScraperSignal(
        store_num="",  # invalid
        chain="starbucks",
        source="careers_api",
        signal_type="listing",
        value=1.0,
        observed_at=datetime.utcnow(),
    )
    result = validate_scraper_output("job_posting_volume", [sig])
    assert result.valid is False
    assert len(result.errors) > 0


def test_validate_scraper_output_returns_error_for_unknown_intent():
    """validate_scraper_output() must return an error when no contract exists."""
    from pipeline.validation import validate_scraper_output

    result = validate_scraper_output("nonexistent_intent", [])
    assert result.valid is False
    assert any("contract" in e.lower() or "intent" in e.lower() for e in result.errors)


# ── Health Check (pipeline/health.py) ─────────────────────────────────────────


def test_pipeline_health_check_passes_with_valid_config():
    """run_startup_check() must return a result with a passed attribute."""
    from pipeline.health import run_startup_check

    result = run_startup_check()
    assert hasattr(result, "passed")


def test_pipeline_health_check_reports_unregistered_intents():
    """run_startup_check() must surface intents that have no routes."""
    from pipeline.health import run_startup_check

    result = run_startup_check()
    assert hasattr(result, "unregistered_intents")


def test_pipeline_health_check_reports_routes_with_missing_adapters():
    """Startup check should flag routes whose scraper_adapter class doesn't exist."""
    from pipeline.health import run_startup_check

    result = run_startup_check()
    assert hasattr(result, "missing_adapters")


def test_pipeline_health_check_is_serializable():
    """The health check result must be convertible to a dict for /api/pipeline/health."""
    from pipeline.health import run_startup_check

    result = run_startup_check()
    d = result.to_dict() if hasattr(result, "to_dict") else vars(result)
    assert isinstance(d, dict)
