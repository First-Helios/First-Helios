"""
collectors/hintbook — "cheat sheet" competitive-intelligence scrapers.

Scope and legal framing
-----------------------
These adapters harvest *aggregator* pages (EatDrinkDeals, DealNews, KCL, etc.)
and produce exploration hints and expectation claims. They do **not** write
to the meal_deals pipeline.

- Hints  → proposals for `config/meal_deal_hint_registry.json` (ARCH-04):
           exploration-only pointers to first-party URLs / slugs we should
           probe on the restaurant's own site.
- Expectations → proposals for `config/meal_deal_expectation_registry.json`:
           published claims ("Brand X advertises $Y off on Z page") that we
           verify against first-party replay bundles, producing a
           found / missed / not_testable coverage report.

Aggregator text is never ingested as evidence. Every surfaced deal in our
product comes from our own first-party collection of the restaurant's site.
We observe what competitors do only to find coverage gaps and to audit our
own extraction quality.

See: docs/guides/MEAL_DEAL_FOUNDATION_ASSESSMENT.md
     collectors/meal_deals/hint_registry.py
     collectors/meal_deals/expectation_registry.py
"""

from collectors.hintbook.models import (
    AggregatorRecord,
    HintProposal,
    ExpectationProposal,
    IndustrySample,
    HarvestReport,
)

__all__ = [
    "AggregatorRecord",
    "HintProposal",
    "ExpectationProposal",
    "IndustrySample",
    "HarvestReport",
]
