"""
collectors/meal_deals/registry.py — Decorator-based deal collector registry.

Each deal collector self-registers via @deal_collector. The scheduler
discovers all registered collectors automatically.

Usage in a collector module:

    from collectors.meal_deals.registry import deal_collector

    @deal_collector("chain_deals", schedule="0 6 * * 1")
    class ChainDealCollector:
        SOURCE = "chain_website"
        def collect(self, region: str = "austin_tx") -> list[DealSignal]: ...
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

_REGISTRY: dict[str, dict[str, Any]] = {}


def deal_collector(name: str, schedule: str = "0 6 * * 1"):
    """Decorator that registers a deal collector class.

    Args:
        name: Unique collector identifier (e.g. "chain_deals", "website_scraper").
        schedule: Cron expression — default Monday 6 AM (weekly).
    """
    def decorator(cls):
        if name in _REGISTRY:
            logger.warning(
                "[DealRegistry] Duplicate collector name %r — overwriting %s with %s",
                name, _REGISTRY[name]["class"].__name__, cls.__name__,
            )
        _REGISTRY[name] = {"class": cls, "schedule": schedule}
        logger.debug("[DealRegistry] Registered collector %r (%s)", name, cls.__name__)
        return cls
    return decorator


def get_all() -> dict[str, dict[str, Any]]:
    """Return the full registry: {name: {"class": cls, "schedule": str}}."""
    return _REGISTRY


def get_collector(name: str):
    """Return a single registered collector class, or None."""
    entry = _REGISTRY.get(name)
    return entry["class"] if entry else None
