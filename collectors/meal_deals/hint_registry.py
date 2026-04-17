"""
collectors/meal_deals/hint_registry.py — ARCH-04 lightweight hint registry.

Policy (per roadmap):
  * Hints are EXPLORATION-ONLY. They may be used to probe for evidence
    (e.g. "try this slug on the corporate domain"), but NEVER treated as
    first-party evidence themselves.
  * Every hint carries provenance: source, first_seen, last_verified,
    expires_at, verified_against_url.
  * External internet sources may propose or refresh hints, but those
    hints must be verified against the restaurant's own site or a cached
    first-party bundle before they affect coverage or ingest decisions.
  * The loader filters out expired hints so stale entries stop influencing
    behavior automatically.

This module stays tiny on purpose — the registry file is the source of
truth, and callers should never mutate it at runtime.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Iterable

logger = logging.getLogger(__name__)

DEFAULT_REGISTRY_PATH = Path("config/meal_deal_hint_registry.json")
SCHEMA_VERSION = "hint_registry.v1"
HINT_SCOPE = "exploration"

_REQUIRED_FIELDS = (
    "id",
    "brand",
    "hint_type",
    "source",
    "first_seen",
    "last_verified",
    "expires_at",
    "verified_against_url",
)


@dataclass(frozen=True)
class Hint:
    """An exploration-only hint with enforced provenance."""
    id: str
    brand: str
    hint_type: str
    source: str
    first_seen: date
    last_verified: date
    expires_at: date
    verified_against_url: str
    slug: str | None = None
    target_domain: str | None = None
    notes: str | None = None
    scope: str = HINT_SCOPE  # immutable: never promote to "evidence"

    def is_expired(self, *, as_of: date | None = None) -> bool:
        return (as_of or date.today()) > self.expires_at


# ── Loading ─────────────────────────────────────────────────────────────────


def load_hints(
    *,
    path: Path | str | None = None,
    as_of: date | None = None,
    include_expired: bool = False,
) -> list[Hint]:
    """Load and validate the hint registry, filtering expired entries.

    Raises ValueError if the schema_version is unknown or if any entry is
    missing a required provenance field — we want loud failures here so
    hints can't silently drift into invalid state.
    """
    registry_path = Path(path) if path else DEFAULT_REGISTRY_PATH
    if not registry_path.exists():
        logger.debug("[HintRegistry] registry file missing at %s — returning no hints", registry_path)
        return []

    raw = json.loads(registry_path.read_text())
    version = raw.get("schema_version")
    if version != SCHEMA_VERSION:
        raise ValueError(
            f"hint registry schema_version {version!r} does not match expected {SCHEMA_VERSION!r}"
        )

    hints: list[Hint] = []
    for entry in raw.get("hints", []):
        missing = [f for f in _REQUIRED_FIELDS if not entry.get(f)]
        if missing:
            raise ValueError(
                f"hint registry entry {entry.get('id', '<unknown>')} missing required fields: {missing}"
            )
        hint = Hint(
            id=entry["id"],
            brand=entry["brand"].lower(),
            hint_type=entry["hint_type"],
            slug=entry.get("slug"),
            target_domain=(entry.get("target_domain") or "").lower() or None,
            source=entry["source"],
            first_seen=_parse_date(entry["first_seen"]),
            last_verified=_parse_date(entry["last_verified"]),
            expires_at=_parse_date(entry["expires_at"]),
            verified_against_url=entry["verified_against_url"],
            notes=entry.get("notes"),
        )
        if not include_expired and hint.is_expired(as_of=as_of):
            logger.debug("[HintRegistry] skipping expired hint %s (expired %s)", hint.id, hint.expires_at)
            continue
        hints.append(hint)
    return hints


def find_hints(
    hints: Iterable[Hint],
    *,
    brand: str | None = None,
    hint_type: str | None = None,
    target_domain: str | None = None,
) -> list[Hint]:
    """Filter an already-loaded hint list by brand / type / target domain."""
    out: list[Hint] = []
    brand_l = brand.lower() if brand else None
    domain_l = target_domain.lower() if target_domain else None
    for h in hints:
        if brand_l and h.brand != brand_l:
            continue
        if hint_type and h.hint_type != hint_type:
            continue
        if domain_l and h.target_domain != domain_l:
            continue
        out.append(h)
    return out


def annotate_exploration_use(hint: Hint, *, used_at_url: str) -> dict[str, str]:
    """Return a small audit blob recording that a hint was *explored* (not trusted).

    Call this at the usage site and attach the result to the debug bundle
    so replays can tell hinted probes apart from first-party evidence.
    """
    return {
        "hint_id": hint.id,
        "hint_scope": HINT_SCOPE,
        "hint_source": hint.source,
        "hint_last_verified": hint.last_verified.isoformat(),
        "hint_verified_against_url": hint.verified_against_url,
        "used_at_url": used_at_url,
        "used_as": "exploration_probe",
    }


# ── Helpers ─────────────────────────────────────────────────────────────────


def _parse_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()
