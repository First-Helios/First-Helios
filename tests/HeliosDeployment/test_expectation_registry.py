"""Tests for collectors.meal_deals.expectation_registry."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from collectors.meal_deals.expectation_registry import (
    DEFAULT_REGISTRY_PATH,
    EXPECTATION_SCOPE,
    SCHEMA_VERSION,
    build_expectation_report,
    compare_expectations_to_bundles,
    find_expectations,
    load_expectations,
)


_BUNDLE_DIR = Path("data/cache/website_scrape_debug")
_BWW_HOST_BUNDLE = _BUNDLE_DIR / "buffalowildwings_com__57badf49c049.json"
_DENNYS_HOST_BUNDLE = _BUNDLE_DIR / "dennys_com__bfecbf5a25be.json"


def _write_registry(path: Path, expectations: list[dict]) -> None:
    path.write_text(
        json.dumps({"schema_version": SCHEMA_VERSION, "expectations": expectations}, indent=2),
        encoding="utf-8",
    )


def _sample_expectation(**overrides) -> dict:
    base = {
        "id": "exp_demo_001",
        "brand": "demo",
        "target_domain": "demo.com",
        "expected_label": "Demo Deal Tuesday",
        "page_path_hints": ["/deals"],
        "match_any": ["demo deal tuesday"],
        "source": "external_catalog",
        "source_url": "https://catalog.example.com/demo",
        "first_seen": "2026-04-01",
        "last_verified": "2026-04-10",
        "expires_at": "2026-07-01",
        "notes": "test",
    }
    base.update(overrides)
    return base


def _skip_if_missing(bundle: Path) -> None:
    if not bundle.exists():
        pytest.skip(f"Replay bundle not synced locally: {bundle}")


def test_checked_in_expectation_registry_loads_cleanly():
    if not DEFAULT_REGISTRY_PATH.exists():
        pytest.skip("default expectation registry not present in this checkout")

    expectations = load_expectations(include_expired=True)
    assert isinstance(expectations, list)
    for expectation in expectations:
        assert expectation.scope == EXPECTATION_SCOPE


def test_load_expectations_filters_expired(tmp_path):
    path = tmp_path / "registry.json"
    _write_registry(
        path,
        [
            _sample_expectation(id="fresh", expires_at="2099-01-01"),
            _sample_expectation(id="stale", expires_at="2020-01-01"),
        ],
    )

    expectations = load_expectations(path=path, as_of=date(2026, 4, 17))
    assert {expectation.id for expectation in expectations} == {"fresh"}


def test_load_expectations_requires_provenance_fields(tmp_path):
    path = tmp_path / "registry.json"
    bad = _sample_expectation()
    bad.pop("source_url")
    _write_registry(path, [bad])

    with pytest.raises(ValueError, match="missing required fields"):
        load_expectations(path=path)


def test_find_expectations_filters_by_brand_and_domain(tmp_path):
    path = tmp_path / "registry.json"
    _write_registry(
        path,
        [
            _sample_expectation(id="a", brand="brandx", target_domain="brandx.com"),
            _sample_expectation(id="b", brand="brandy", target_domain="brandy.com"),
            _sample_expectation(id="c", brand="brandx", target_domain="brandx.com", expected_label="Other Deal"),
        ],
    )

    expectations = load_expectations(path=path, as_of=date(2026, 4, 17))
    assert len(find_expectations(expectations, brand="brandx")) == 2
    assert len(find_expectations(expectations, target_domain="brandy.com")) == 1
    assert len(find_expectations(expectations, brand="missing")) == 0


def test_build_expectation_report_classifies_found_missed_and_not_testable(tmp_path):
    path = tmp_path / "registry.json"
    _write_registry(
        path,
        [
            _sample_expectation(
                id="found_expectation",
                brand="dennys",
                target_domain="dennys.com",
                expected_label="SLAMMIN MEAL DEALS",
                match_any=["slammin meal deals starting at 5 99"],
                page_path_hints=["/deals"],
            ),
            _sample_expectation(
                id="missed_expectation",
                brand="dennys",
                target_domain="dennys.com",
                expected_label="Burger Monday",
                match_any=["burger monday"],
                page_path_hints=["/deals"],
            ),
            _sample_expectation(
                id="not_testable_expectation",
                brand="buffalowildwings",
                target_domain="buffalowildwings.com",
                expected_label="Happy Hour 3 to 6",
                match_any=["happy hour 3 6 from 3 6 pm"],
                page_path_hints=["/happy-hour"],
            ),
        ],
    )
    expectations = load_expectations(path=path, as_of=date(2026, 4, 17))

    debug_bundles = {
        "dennys-locator": {
            "site_key": "dennys-locator",
            "site_url": "https://locations.dennys.com/TX/AUSTIN/200686",
            "pages": {
                "deals": {
                    "url": "https://www.dennys.com/deals",
                    "fetch_type": "locator_hint",
                    "html": "<html><body><p>SLAMMIN' MEAL DEALS STARTING AT $5.99</p></body></html>",
                }
            },
            "signals": [
                {
                    "deal_name": "SLAMMIN' MEAL DEALS STARTING AT $5.99",
                    "deal_description": "SLAMMIN' MEAL DEALS STARTING AT $5.99",
                    "raw_scraped_text": "SLAMMIN' MEAL DEALS STARTING AT $5.99",
                    "source_url": "https://www.dennys.com/deals",
                }
            ],
            "discovered_pages": [],
            "hinted_pages": [{"url": "https://www.dennys.com/deals"}],
        },
        "bww-host": {
            "site_key": "bww-host",
            "site_url": "https://www.buffalowildwings.com/",
            "pages": {
                "home": {
                    "url": "https://www.buffalowildwings.com/",
                    "fetch_type": "hardcoded",
                    "html": "<html><body><h1>Buffalo Wild Wings</h1></body></html>",
                }
            },
            "signals": [],
            "discovered_pages": ["https://www.buffalowildwings.com/happy-hour"],
            "hinted_pages": [],
        },
    }

    report = build_expectation_report(expectations, debug_bundles)
    by_id = {item["expectation_id"]: item for item in report["results"]}

    assert by_id["found_expectation"]["status"] == "found"
    assert by_id["found_expectation"]["reason"] == "signal_and_page_match"
    assert by_id["missed_expectation"]["status"] == "missed"
    assert by_id["missed_expectation"]["reason"] == "page_hint_fetched_but_phrase_missing"
    assert by_id["not_testable_expectation"]["status"] == "not_testable"
    assert by_id["not_testable_expectation"]["reason"] == "page_hint_discovered_only"
    assert report["summary"]["status_counts"] == {
        "found": 1,
        "missed": 1,
        "not_testable": 1,
    }


def test_compare_expectations_matches_real_bww_and_dennys_bundles(tmp_path):
    _skip_if_missing(_BWW_HOST_BUNDLE)
    _skip_if_missing(_DENNYS_HOST_BUNDLE)

    path = tmp_path / "registry.json"
    _write_registry(
        path,
        [
            _sample_expectation(
                id="bww_bogo_tuesday",
                brand="buffalowildwings",
                target_domain="buffalowildwings.com",
                expected_label="BOGO Wing Tuesday",
                match_any=["bogo wing tuesday"],
                page_path_hints=["/promos"],
            ),
            _sample_expectation(
                id="dennys_slammin_meal_deals",
                brand="dennys",
                target_domain="dennys.com",
                expected_label="SLAMMIN MEAL DEALS",
                match_any=["slammin meal deals starting at 5 99", "super slam"],
                page_path_hints=["/deals", "/meal-deals"],
            ),
        ],
    )
    expectations = load_expectations(path=path, as_of=date(2026, 4, 17))
    debug_bundles = {
        payload["site_key"]: payload
        for payload in (
            json.loads(_BWW_HOST_BUNDLE.read_text(encoding="utf-8")),
            json.loads(_DENNYS_HOST_BUNDLE.read_text(encoding="utf-8")),
        )
    }

    results = compare_expectations_to_bundles(expectations, debug_bundles)
    by_id = {item["expectation_id"]: item for item in results}

    assert by_id["bww_bogo_tuesday"]["status"] == "found"
    assert by_id["bww_bogo_tuesday"]["candidate_bundle_keys"] == ["buffalowildwings.com"]
    assert by_id["dennys_slammin_meal_deals"]["status"] == "found"
    assert by_id["dennys_slammin_meal_deals"]["candidate_bundle_keys"] == ["dennys.com"]