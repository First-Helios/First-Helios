"""
pipeline/health.py — Startup self-check for the Helios pipeline.

run_startup_check() verifies that:
  1. Every Intent enum value has at least one route registered in ROUTES
  2. Every live/unwired route's scraper_module and adapter class can be imported
  3. Freshness thresholds in ROUTES agree with schemas.py FRESHNESS_THRESHOLDS
  4. The SCRAPER_OUTPUT_CONTRACTS cover all collection intents

Designed to be called at server startup (e.g. from server.py or a CLI health
check) and exposed at /api/pipeline/health.

Usage
-----
    from pipeline.health import run_startup_check

    result = run_startup_check()
    if not result.passed:
        for issue in result.issues:
            logger.error("[health] %s", issue)
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass, field
from typing import Optional

from agent_interface.schemas import FRESHNESS_THRESHOLDS, COLLECTION_INTENTS, Intent
from pipeline.route_index import ROUTES
from pipeline.validation import SCRAPER_OUTPUT_CONTRACTS


@dataclass
class HealthCheckResult:
    """Result of run_startup_check().

    Attributes
    ----------
    passed                  True if no blocking issues found
    unregistered_intents    Intent values with no entry in ROUTES
    missing_adapters        (intent_key, source_key, adapter_class) tuples where
                            the adapter module/class could not be imported
    threshold_mismatches    (intent_key, route_value, schema_value) where they differ
    missing_contracts       Collection intents with no SCRAPER_OUTPUT_CONTRACTS entry
    issues                  Flat list of all issue strings (union of above)
    """

    passed: bool
    unregistered_intents: list[str] = field(default_factory=list)
    missing_adapters: list[tuple] = field(default_factory=list)
    threshold_mismatches: list[tuple] = field(default_factory=list)
    missing_contracts: list[str] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "passed": self.passed,
            "unregistered_intents": self.unregistered_intents,
            "missing_adapters": [
                {"intent": t[0], "source_key": t[1], "adapter": t[2]}
                for t in self.missing_adapters
            ],
            "threshold_mismatches": [
                {"intent": t[0], "route_value": t[1], "schema_value": t[2]}
                for t in self.threshold_mismatches
            ],
            "missing_contracts": self.missing_contracts,
            "issues": self.issues,
        }


def run_startup_check() -> HealthCheckResult:
    """Run all pipeline self-checks and return a HealthCheckResult."""

    issues: list[str] = []
    unregistered: list[str] = []
    missing_adapters: list[tuple] = []
    threshold_mismatches: list[tuple] = []
    missing_contracts: list[str] = []

    # 1. Every Intent must have at least one route
    for intent in Intent:
        if intent.value not in ROUTES:
            unregistered.append(intent.value)
            issues.append(f"No route registered for intent '{intent.value}'")

    # 2. Verify adapter imports for live/unwired routes
    for intent_key, route_list in ROUTES.items():
        for route in route_list:
            if route.status == "suggested":
                continue  # suggested routes may not have adapters yet
            if route.scraper_module is None or route.scraper_adapter is None:
                continue  # internal/DB-only routes
            try:
                mod = importlib.import_module(route.scraper_module)
                if not hasattr(mod, route.scraper_adapter):
                    missing_adapters.append((intent_key, route.source_key, route.scraper_adapter))
                    issues.append(
                        f"Adapter class '{route.scraper_adapter}' not found in "
                        f"module '{route.scraper_module}' (intent='{intent_key}')"
                    )
            except ImportError as exc:
                missing_adapters.append((intent_key, route.source_key, route.scraper_adapter))
                issues.append(
                    f"Cannot import '{route.scraper_module}' for "
                    f"intent='{intent_key}' source='{route.source_key}': {exc}"
                )

    # 3. Freshness threshold consistency check
    for intent_key, route_list in ROUTES.items():
        schema_threshold = FRESHNESS_THRESHOLDS.get(intent_key, 0.0)
        for route in route_list:
            if route.freshness_threshold_days != schema_threshold:
                threshold_mismatches.append(
                    (intent_key, route.freshness_threshold_days, schema_threshold)
                )
                issues.append(
                    f"Threshold mismatch for intent '{intent_key}': "
                    f"route={route.freshness_threshold_days} vs schemas.py={schema_threshold}"
                )

    # 4. Collection intents should have output contracts
    for intent_value in COLLECTION_INTENTS:
        if intent_value not in SCRAPER_OUTPUT_CONTRACTS:
            missing_contracts.append(intent_value)
            issues.append(
                f"No SCRAPER_OUTPUT_CONTRACTS entry for collection intent '{intent_value}'"
            )

    return HealthCheckResult(
        passed=len(issues) == 0,
        unregistered_intents=unregistered,
        missing_adapters=missing_adapters,
        threshold_mismatches=threshold_mismatches,
        missing_contracts=missing_contracts,
        issues=issues,
    )
