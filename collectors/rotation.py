"""
collectors/rotation.py — Round-robin industry query rotation for API-budgeted sources.

Maintains a per-source index in data/rotation_state.json.  Each call to
next_entry() returns the current entry and advances the index by one, cycling
back to 0 when the end of the list is reached.

Usage:
    from collectors.rotation import next_entry
    from config.loader import get_search_rotation

    industries = get_search_rotation()
    entry = next_entry("serpapi", industries)
    # entry = {"key": "healthcare", "serpapi_query": "...", "jobicy_tag": "..."}
"""

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_STATE_FILE = Path(__file__).parent.parent / "data" / "rotation_state.json"


def _load() -> dict:
    try:
        if _STATE_FILE.exists():
            return json.loads(_STATE_FILE.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("[Rotation] State load failed, resetting: %s", exc)
    return {}


def _save(state: dict) -> None:
    try:
        _STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        _STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")
    except Exception as exc:
        logger.warning("[Rotation] State save failed (non-fatal): %s", exc)


def next_entry(source_key: str, industries: list[dict]) -> dict:
    """Return the next industry entry for source_key and advance the index.

    Args:
        source_key:  Identifies which source's index to advance (e.g. "serpapi").
        industries:  The list of industry dicts from get_search_rotation().

    Returns:
        The entry at the current index. Empty dict if industries is empty.
    """
    if not industries:
        return {}

    state = _load()
    idx = state.get(source_key, 0) % len(industries)
    entry = industries[idx]
    state[source_key] = (idx + 1) % len(industries)
    _save(state)

    logger.info(
        "[Rotation] %s: slot %d/%d → industry_key=%s",
        source_key, idx + 1, len(industries), entry.get("key", "?"),
    )
    return entry


def peek_entry(source_key: str, industries: list[dict]) -> dict:
    """Return the current entry without advancing the index (read-only)."""
    if not industries:
        return {}
    state = _load()
    idx = state.get(source_key, 0) % len(industries)
    return industries[idx]


def reset(source_key: str) -> None:
    """Reset a source's rotation index to 0."""
    state = _load()
    state[source_key] = 0
    _save(state)
    logger.info("[Rotation] %s: reset to index 0", source_key)
