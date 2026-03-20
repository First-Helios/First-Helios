"""
openclaw/prevalidate.py — Query term pre-validation.

Before the agent spends an API call, every proposed search term and
parameter is checked against the known-valid pool.  This is the gate
that prevents the LLM from hallucinating queries that waste budget.

Three levels of validation:
  1. TERM CHECK — is the search term in the industry's approved pool?
  2. GEO CHECK  — is the target inside the region bounding box?
  3. DRY-RUN    — simulate the query against rate_manager without executing

If a term fails, the validator returns the closest valid alternatives
so the LLM can self-correct in one round-trip.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from difflib import get_close_matches
from typing import Optional

from openclaw.industries import INDUSTRY_REGISTRY, IndustryDimension

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════
# Validation result
# ══════════════════════════════════════════════════════════════════════

@dataclass
class PreValidationResult:
    """Outcome of pre-validating a proposed query."""
    is_valid: bool
    proposed_term: str
    matched_term: Optional[str] = None      # exact or fuzzy match
    rejection_reason: Optional[str] = None
    suggestions: list[str] = field(default_factory=list)
    industry_key: Optional[str] = None
    term_type: Optional[str] = None         # job | poi | sentiment
    budget_ok: bool = True
    budget_detail: Optional[dict] = None

    def to_dict(self) -> dict:
        return {
            "is_valid": self.is_valid,
            "proposed_term": self.proposed_term,
            "matched_term": self.matched_term,
            "rejection_reason": self.rejection_reason,
            "suggestions": self.suggestions,
            "industry_key": self.industry_key,
            "term_type": self.term_type,
            "budget_ok": self.budget_ok,
            "budget_detail": self.budget_detail,
        }


@dataclass
class BatchPreValidationResult:
    """Outcome of pre-validating a batch of proposed queries."""
    total: int = 0
    valid: int = 0
    rejected: int = 0
    results: list[PreValidationResult] = field(default_factory=list)
    estimated_api_calls: int = 0
    budget_ok: bool = True

    def to_dict(self) -> dict:
        return {
            "total": self.total,
            "valid": self.valid,
            "rejected": self.rejected,
            "estimated_api_calls": self.estimated_api_calls,
            "budget_ok": self.budget_ok,
            "results": [r.to_dict() for r in self.results],
        }


# ══════════════════════════════════════════════════════════════════════
# Term validation
# ══════════════════════════════════════════════════════════════════════

def validate_search_term(
    term: str,
    industry_key: str,
    term_type: str = "job",
) -> PreValidationResult:
    """Check if a search term is valid for the given industry.

    Args:
        term: The proposed search term from the LLM.
        industry_key: Which industry dimension to check against.
        term_type: "job" | "poi" | "sentiment"

    Returns:
        PreValidationResult with is_valid=True if term is approved,
        or suggestions for correction if not.
    """
    dim = INDUSTRY_REGISTRY.get(industry_key)
    if dim is None:
        return PreValidationResult(
            is_valid=False,
            proposed_term=term,
            rejection_reason=f"Unknown industry '{industry_key}'",
            suggestions=list(INDUSTRY_REGISTRY.keys()),
            term_type=term_type,
        )

    # Get the valid term pool
    if term_type == "poi":
        pool = list(dim.poi_search_terms)
    elif term_type == "sentiment":
        pool = list(dim.sentiment_keywords)
    else:
        pool = list(dim.job_search_terms)

    normalized = term.strip().lower()

    # Exact match
    pool_lower = {t.lower(): t for t in pool}
    if normalized in pool_lower:
        return PreValidationResult(
            is_valid=True,
            proposed_term=term,
            matched_term=pool_lower[normalized],
            industry_key=industry_key,
            term_type=term_type,
        )

    # Substring match — if the proposed term contains a valid term
    for pool_term_lower, pool_term_orig in pool_lower.items():
        if pool_term_lower in normalized or normalized in pool_term_lower:
            return PreValidationResult(
                is_valid=True,
                proposed_term=term,
                matched_term=pool_term_orig,
                industry_key=industry_key,
                term_type=term_type,
            )

    # Fuzzy match
    close = get_close_matches(normalized, list(pool_lower.keys()), n=5, cutoff=0.5)
    suggestions = [pool_lower[c] for c in close] if close else pool[:8]

    return PreValidationResult(
        is_valid=False,
        proposed_term=term,
        rejection_reason=(
            f"Term '{term}' not in approved {term_type} terms for '{industry_key}'. "
            f"Choose from the suggestions or request a new term via the wishlist."
        ),
        suggestions=suggestions,
        industry_key=industry_key,
        term_type=term_type,
    )


def validate_brand(brand_key: str) -> PreValidationResult:
    """Check if a brand exists in any industry's mega-corp list."""
    normalized = brand_key.strip().lower().replace(" ", "_").replace("'", "")

    for dim in INDUSTRY_REGISTRY.values():
        for mc in dim.mega_corps:
            if mc.key == normalized or normalized in (a.lower() for a in mc.aliases):
                return PreValidationResult(
                    is_valid=True,
                    proposed_term=brand_key,
                    matched_term=mc.key,
                    industry_key=dim.key,
                )

    # Fuzzy match across all mega-corps
    all_brands = {}
    for dim in INDUSTRY_REGISTRY.values():
        for mc in dim.mega_corps:
            all_brands[mc.key] = mc.display_name
    close = get_close_matches(normalized, list(all_brands.keys()), n=5, cutoff=0.4)
    suggestions = [f"{k} ({all_brands[k]})" for k in close] if close else list(all_brands.keys())[:8]

    return PreValidationResult(
        is_valid=False,
        proposed_term=brand_key,
        rejection_reason=f"Brand '{brand_key}' not in any industry registry",
        suggestions=suggestions,
    )


def validate_industry(industry_key: str) -> PreValidationResult:
    """Check if an industry key is valid."""
    if industry_key in INDUSTRY_REGISTRY:
        return PreValidationResult(
            is_valid=True,
            proposed_term=industry_key,
            matched_term=industry_key,
            industry_key=industry_key,
        )

    close = get_close_matches(industry_key, list(INDUSTRY_REGISTRY.keys()), n=5, cutoff=0.4)
    return PreValidationResult(
        is_valid=False,
        proposed_term=industry_key,
        rejection_reason=f"Unknown industry '{industry_key}'",
        suggestions=close or list(INDUSTRY_REGISTRY.keys()),
    )


# ══════════════════════════════════════════════════════════════════════
# Budget dry-run
# ══════════════════════════════════════════════════════════════════════

def check_budget_for_intent(intent: str, max_calls: int = 5) -> dict:
    """Check if rate budget allows the given intent without executing.

    Returns dict with budget_ok, sources checked, remaining counts.
    """
    from agent_interface.schemas import Intent

    # Map intent → API source keys
    INTENT_SOURCE_MAP = {
        "poi_chain_locations": ["atp_geojson", "overture_s3", "overpass_api"],
        "poi_local_density": ["overture_s3", "overpass_api"],
        "wage_baseline": ["bls_v1"],
        "job_posting_volume": ["jobspy", "careers_workday"],
        "sentiment_check": ["reddit_json", "reddit_oauth"],
        "economic_context": ["bls_v1"],
        "score_refresh": [],
        "data_quality_audit": [],
        "campaign_status": [],
    }

    sources = INTENT_SOURCE_MAP.get(intent, [])
    if not sources:
        return {"budget_ok": True, "sources": [], "note": "No external API calls needed"}

    try:
        from backend.rate_manager import rate_manager
        available = []
        exhausted = []
        for sk in sources:
            if rate_manager.can_request(sk, count=max_calls):
                status = rate_manager.get_source_status(sk)
                available.append({
                    "source": sk,
                    "remaining": status.get("budget", {}).get("remaining", 0),
                })
            else:
                status = rate_manager.get_source_status(sk)
                exhausted.append({
                    "source": sk,
                    "remaining": status.get("budget", {}).get("remaining", 0),
                })

        return {
            "budget_ok": len(available) > 0,
            "available_sources": available,
            "exhausted_sources": exhausted,
            "estimated_calls": max_calls,
        }
    except Exception as e:
        logger.warning("[PreValidate] Budget check error: %s", e)
        return {"budget_ok": True, "error": str(e), "note": "Assuming OK on error"}


# ══════════════════════════════════════════════════════════════════════
# Batch pre-validation (what the orchestrator calls before sending)
# ══════════════════════════════════════════════════════════════════════

def prevalidate_agent_plan(plan: list[dict]) -> BatchPreValidationResult:
    """Pre-validate a batch of proposed queries from the LLM.

    Each item in plan should have:
        intent: str
        industry: str (optional)
        brand: str (optional)
        search_terms: list[str] (optional)

    Returns a BatchPreValidationResult with per-item details.
    """
    batch = BatchPreValidationResult(total=len(plan))
    total_api_calls = 0

    for item in plan:
        intent = item.get("intent", "")
        industry = item.get("industry", "")
        brand = item.get("brand", "")
        terms = item.get("search_terms", [])
        max_calls = item.get("max_budget_spend", 5)

        # Validate industry if provided
        if industry:
            ind_result = validate_industry(industry)
            if not ind_result.is_valid:
                batch.results.append(ind_result)
                batch.rejected += 1
                continue

        # Validate brand if provided
        if brand:
            brand_result = validate_brand(brand)
            if not brand_result.is_valid:
                batch.results.append(brand_result)
                batch.rejected += 1
                continue

        # Validate each search term
        term_issues = []
        for t in terms:
            if industry:
                tv = validate_search_term(t, industry, "job")
                if not tv.is_valid:
                    term_issues.append(tv)

        if term_issues:
            # Report first bad term
            batch.results.append(term_issues[0])
            batch.rejected += 1
            continue

        # Budget dry-run
        budget = check_budget_for_intent(intent, max_calls)
        total_api_calls += max_calls

        batch.results.append(PreValidationResult(
            is_valid=True,
            proposed_term=intent,
            matched_term=intent,
            industry_key=industry or None,
            budget_ok=budget.get("budget_ok", True),
            budget_detail=budget,
        ))
        batch.valid += 1

    batch.estimated_api_calls = total_api_calls
    batch.budget_ok = all(r.budget_ok for r in batch.results if r.is_valid)
    return batch
