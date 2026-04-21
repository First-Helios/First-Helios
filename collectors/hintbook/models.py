"""
Dataclasses for the hintbook harvest. All records are *proposals* and
never directly update registry JSON; a separate review step merges them.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import date, datetime, timezone
from typing import Any


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class AggregatorRecord:
    """One deal-like claim scraped from an aggregator article/listing."""

    aggregator: str                 # e.g. "eatdrinkdeals"
    fetched_at: datetime
    source_url: str                 # aggregator article URL (NOT evidence)
    industry: str                   # "food", "automotive", "travel", ...
    brand_hint: str | None          # normalized slug, e.g. "dennys"
    target_domain: str | None       # outbound first-party host, if any
    target_first_party_url: str | None
    headline: str                   # aggregator's headline (attribution-safe quote)
    body_excerpt: str               # short excerpt, kept small for attribution safety
    price_hint: float | None
    promo_code: str | None
    valid_through: date | None
    flags: frozenset[str] = field(default_factory=frozenset)
    # e.g. {"app_only", "delivery_only", "bogo", "happy_hour", "free_item",
    #       "percent_off", "promo_code", "new_customer"}

    def to_json(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["fetched_at"] = self.fetched_at.isoformat()
        payload["valid_through"] = self.valid_through.isoformat() if self.valid_through else None
        payload["flags"] = sorted(self.flags)
        return payload


@dataclass(frozen=True)
class HintProposal:
    """Candidate entry for config/meal_deal_hint_registry.json.

    Written to data/cache/hintbook/<date>/hint_proposals.json for human
    review before being merged.
    """

    brand: str
    hint_type: str                  # "corporate_promo_slug", etc.
    slug: str
    target_domain: str
    source: str                     # e.g. "eatdrinkdeals" (aggregator name)
    source_url: str                 # article that prompted the hint
    first_seen: date
    verified_against_url: str | None
    notes: str | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "brand": self.brand,
            "hint_type": self.hint_type,
            "slug": self.slug,
            "target_domain": self.target_domain,
            "source": self.source,
            "source_url": self.source_url,
            "first_seen": self.first_seen.isoformat(),
            "verified_against_url": self.verified_against_url,
            "notes": self.notes,
        }


@dataclass(frozen=True)
class ExpectationProposal:
    """Candidate entry for config/meal_deal_expectation_registry.json."""

    brand: str
    target_domain: str
    expected_label: str
    match_any: tuple[str, ...]
    source: str                     # aggregator key
    source_url: str
    first_seen: date
    page_path_hints: tuple[str, ...] = ()
    notes: str | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "brand": self.brand,
            "target_domain": self.target_domain,
            "expected_label": self.expected_label,
            "match_any": list(self.match_any),
            "source": self.source,
            "source_url": self.source_url,
            "first_seen": self.first_seen.isoformat(),
            "page_path_hints": list(self.page_path_hints),
            "notes": self.notes,
        }


@dataclass(frozen=True)
class IndustrySample:
    """Evidence that a competing deal site covers a non-food industry.

    Used to map the competitive deal landscape so we can decide whether
    a category (automotive, travel, etc.) fits a map-first UX or a broader
    promo-framework UX.
    """

    aggregator: str
    industry: str                   # taxonomy key, see industry_taxonomy.py
    sample_url: str                 # category/listing URL on aggregator
    observed_count: int             # rough count of deals visible on page
    sample_headlines: tuple[str, ...]  # up to 10 short headlines for review
    map_viable: bool                # True if deals are geo-anchored
    notes: str | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "aggregator": self.aggregator,
            "industry": self.industry,
            "sample_url": self.sample_url,
            "observed_count": self.observed_count,
            "sample_headlines": list(self.sample_headlines),
            "map_viable": self.map_viable,
            "notes": self.notes,
        }


@dataclass
class HarvestReport:
    started_at: datetime = field(default_factory=utcnow)
    finished_at: datetime | None = None
    adapters_run: list[str] = field(default_factory=list)
    adapters_failed: list[dict[str, Any]] = field(default_factory=list)
    records: list[AggregatorRecord] = field(default_factory=list)
    hint_proposals: list[HintProposal] = field(default_factory=list)
    expectation_proposals: list[ExpectationProposal] = field(default_factory=list)
    industry_samples: list[IndustrySample] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        return {
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "adapters_run": self.adapters_run,
            "adapters_failed": self.adapters_failed,
            "counts": {
                "records": len(self.records),
                "hint_proposals": len(self.hint_proposals),
                "expectation_proposals": len(self.expectation_proposals),
                "industry_samples": len(self.industry_samples),
            },
            "records": [r.to_json() for r in self.records],
            "hint_proposals": [h.to_json() for h in self.hint_proposals],
            "expectation_proposals": [e.to_json() for e in self.expectation_proposals],
            "industry_samples": [s.to_json() for s in self.industry_samples],
        }
