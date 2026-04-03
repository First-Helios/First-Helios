"""
collectors/events/registry.py — Decorator-based event collector registry.

Each event collector self-registers via @event_collector. The scheduler
discovers all registered collectors automatically — adding a new source
only requires creating one file.

Usage in a collector module:

    from collectors.events.registry import event_collector

    @event_collector("meetup", schedule="0 */4 * * *")
    class MeetupCollector:
        SOURCE = "meetup"
        def collect(self, region: str = "austin_tx") -> list[EventSignal]: ...
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

_REGISTRY: dict[str, dict[str, Any]] = {}


def event_collector(name: str, schedule: str = "0 */6 * * *"):
    """Decorator that registers an event collector class.

    Args:
        name: Unique collector identifier (e.g. "meetup", "do512").
        schedule: Cron expression string "min hour dom month dow"
                  or interval notation "*/N" for hours.
    """
    def decorator(cls):
        if name in _REGISTRY:
            logger.warning(
                "[EventRegistry] Duplicate collector name %r — overwriting %s with %s",
                name, _REGISTRY[name]["class"].__name__, cls.__name__,
            )
        _REGISTRY[name] = {"class": cls, "schedule": schedule}
        logger.debug("[EventRegistry] Registered collector %r (%s)", name, cls.__name__)
        return cls
    return decorator


def get_all() -> dict[str, dict[str, Any]]:
    """Return the full registry: {name: {"class": cls, "schedule": str}}."""
    return _REGISTRY


def get_collector(name: str):
    """Return a single registered collector class, or None."""
    entry = _REGISTRY.get(name)
    return entry["class"] if entry else None
