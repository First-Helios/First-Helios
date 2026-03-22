"""
openclaw/prevalidate.py — Query term pre-validation.

Before the agent spends an API call, every proposed search term and
parameter is checked against the known-valid pool.  This is the gate
that prevents the LLM from hallucinating queries that waste budget.

Four levels of validation:
  1. FRESHNESS CHECK — is existing data still within threshold?
  2. TERM CHECK — is the search term in the industry's approved pool?
  3. GEO CHECK  — is the target inside the region bounding box?
  4. DRY-RUN    — simulate the query against rate_manager without executing

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


def _resolve_industry_key(raw: str) -> Optional[str]:
    """Return canonical INDUSTRY_REGISTRY key for *raw*, or None if unrecognised.

    Checks exact key match first, then exact alias match, then returns None.
    Callers that need a fuzzy suggestion should use validate_industry_key().
    """
    if raw in INDUSTRY_REGISTRY:
        return raw
    normalized = raw.strip().lower()
    for key, dim in INDUSTRY_REGISTRY.items():
        if normalized == key or normalized in (a.lower() for a in dim.aliases):
            return key
    return None


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
    canonical = _resolve_industry_key(industry_key)
    if canonical:
        industry_key = canonical
    dim = INDUSTRY_REGISTRY.get(industry_key)
    if dim is None:
        result = validate_industry(industry_key)
        return PreValidationResult(
            is_valid=False,
            proposed_term=term,
            rejection_reason=result.rejection_reason or f"Unknown industry '{industry_key}'",
            suggestions=result.suggestions,
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

    # Build alias → canonical key map for fuzzy lookup
    normalized = industry_key.strip().lower()
    alias_map: dict[str, str] = {}
    for key, dim in INDUSTRY_REGISTRY.items():
        alias_map[key] = key
        for alias in dim.aliases:
            alias_map[alias.lower()] = key

    # Exact alias match
    if normalized in alias_map:
        canonical = alias_map[normalized]
        return PreValidationResult(
            is_valid=True,
            proposed_term=industry_key,
            matched_term=canonical,
            industry_key=canonical,
        )

    # Fuzzy match across keys + aliases
    close_raw = get_close_matches(normalized, list(alias_map.keys()), n=3, cutoff=0.4)
    close_keys = list(dict.fromkeys(alias_map[m] for m in close_raw))  # deduplicate, preserve order

    return PreValidationResult(
        is_valid=False,
        proposed_term=industry_key,
        rejection_reason=f"Unknown industry '{industry_key}'. Did you mean: {close_keys[0]!r}?" if close_keys else f"Unknown industry '{industry_key}'",
        suggestions=close_keys or list(INDUSTRY_REGISTRY.keys()),
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
        "discovery_scan": [],
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
# Freshness gate
# ══════════════════════════════════════════════════════════════════════

def check_freshness_for_intent(
    intent: str,
    region: str,
    brand: str | None = None,
    industry: str | None = None,
) -> dict | None:
    """Check if data for this query combo is still fresh.

    Two-tier check:
      1. SourceFreshness tracking table (populated by executor after runs)
      2. Fallback: actual data tables (Store, LocalEmployer, etc.) when
         the tracking table has no record (data predates tracking)

    Returns a dict with is_stale, age_days, threshold_days, etc.
    Returns None if freshness tracking is unavailable (import error, etc).
    """
    try:
        from agent_interface.schemas import FRESHNESS_THRESHOLDS
        from backend.database import check_freshness

        threshold = FRESHNESS_THRESHOLDS.get(intent, 14.0)

        # Intents with threshold 0 always run — skip freshness gate
        if threshold <= 0:
            return None

        result = check_freshness(
            intent=intent,
            region=region,
            brand=brand,
            industry=industry,
        )
        # Inject the configured threshold so caller can compare
        result["threshold_days"] = threshold

        # Re-evaluate staleness against the configured threshold
        if result.get("age_days") is not None:
            result["is_stale"] = result["age_days"] > threshold
            return result

        # ── Fallback: check actual data tables ──────────────────────
        # If the tracking table has no record (never_collected), data may
        # still exist from before tracking was implemented.  Query the
        # real tables so we don't re-collect data that's already fresh.
        if result.get("never_collected"):
            fallback = _check_data_table_freshness(intent, region, brand, industry)
            if fallback is not None:
                fallback["threshold_days"] = threshold
                fallback["is_stale"] = (
                    fallback["age_days"] > threshold
                    if fallback.get("age_days") is not None
                    else True
                )
                logger.info(
                    "[PreValidate] Freshness fallback from data tables: "
                    "intent=%s age=%.1f days, records=%d, stale=%s",
                    intent,
                    fallback.get("age_days", -1),
                    fallback.get("records_collected", 0),
                    fallback.get("is_stale"),
                )
                return fallback

        return result

    except Exception as e:
        logger.warning("[PreValidate] Freshness check error: %s — allowing query", e)
        return None


def _check_data_table_freshness(
    intent: str,
    region: str,
    brand: str | None = None,
    industry: str | None = None,
) -> dict | None:
    """Fallback freshness check against actual data tables.

    Used when the SourceFreshness tracking table has no record for a query
    (e.g. data was ingested before tracking was implemented).
    """
    from datetime import datetime
    from backend.database import (
        LocalEmployer, Score, Signal, Store, WageIndex,
        get_session, init_db,
    )

    engine = init_db()
    session = get_session(engine)

    try:
        staleness_days = None
        count = 0

        if intent == "poi_chain_locations":
            q = session.query(Store).filter(
                Store.region == region, Store.is_active.is_(True),
            )
            if brand:
                q = q.filter(Store.chain == brand)
            stores = q.all()
            if stores:
                count = len(stores)
                latest = max((s.last_seen for s in stores if s.last_seen), default=None)
                if latest:
                    staleness_days = (datetime.utcnow() - latest).total_seconds() / 86400.0

        elif intent == "poi_local_density":
            q = session.query(LocalEmployer).filter(
                LocalEmployer.region == region, LocalEmployer.is_active.is_(True),
            )
            if industry:
                q = q.filter(LocalEmployer.industry == industry)
            employers = q.all()
            if employers:
                count = len(employers)
                latest = max((e.last_seen for e in employers if e.last_seen), default=None)
                if latest:
                    staleness_days = (datetime.utcnow() - latest).total_seconds() / 86400.0

        elif intent in ("wage_baseline", "economic_context"):
            q = session.query(WageIndex)
            if industry:
                q = q.filter(WageIndex.industry == industry)
            wages = q.order_by(WageIndex.observed_at.desc()).all()
            if wages:
                count = len(wages)
                if wages[0].observed_at:
                    staleness_days = (datetime.utcnow() - wages[0].observed_at).total_seconds() / 86400.0

        elif intent == "job_posting_volume":
            q = session.query(Signal).filter(Signal.signal_type == "listing")
            if brand:
                store_nums = [
                    s.store_num for s in session.query(Store.store_num).filter(
                        Store.chain == brand, Store.region == region,
                    ).all()
                ]
                if store_nums:
                    q = q.filter(Signal.store_num.in_(store_nums))
                else:
                    return None
            signals = q.order_by(Signal.observed_at.desc()).limit(100).all()
            if signals:
                count = len(signals)
                if signals[0].observed_at:
                    staleness_days = (datetime.utcnow() - signals[0].observed_at).total_seconds() / 86400.0

        elif intent == "sentiment_check":
            q = session.query(Signal).filter(Signal.signal_type == "sentiment")
            if brand:
                store_nums = [
                    s.store_num for s in session.query(Store.store_num).filter(
                        Store.chain == brand, Store.region == region,
                    ).all()
                ]
                if store_nums:
                    q = q.filter(Signal.store_num.in_(store_nums))
                else:
                    return None
            signals = q.order_by(Signal.observed_at.desc()).limit(100).all()
            if signals:
                count = len(signals)
                if signals[0].observed_at:
                    staleness_days = (datetime.utcnow() - signals[0].observed_at).total_seconds() / 86400.0

        elif intent == "score_refresh":
            q = session.query(Score).filter(Score.score_type == "composite")
            if brand:
                store_nums = [
                    s.store_num for s in session.query(Store.store_num).filter(
                        Store.chain == brand, Store.region == region,
                    ).all()
                ]
                if store_nums:
                    q = q.filter(Score.store_num.in_(store_nums))
                else:
                    return None
            scores = q.order_by(Score.computed_at.desc()).all()
            if scores:
                count = len(scores)
                if scores[0].computed_at:
                    staleness_days = (datetime.utcnow() - scores[0].computed_at).total_seconds() / 86400.0

        if count == 0:
            return None  # No data at all — let it through

        return {
            "is_stale": True,  # re-evaluated by caller
            "age_days": round(staleness_days, 1) if staleness_days is not None else None,
            "last_collected_at": None,
            "records_collected": count,
            "next_due_at": None,
            "never_collected": False,
            "source": "data_table_fallback",
        }

    except Exception as e:
        logger.warning("[PreValidate] Data table freshness fallback error: %s", e)
        return None
    finally:
        session.close()


# ══════════════════════════════════════════════════════════════════════
# Batch pre-validation (what the orchestrator calls before sending)
# ══════════════════════════════════════════════════════════════════════

def prevalidate_agent_plan(plan: list[dict], mode: str = "mixed", session_terms: Optional[dict] = None) -> BatchPreValidationResult:
    """Pre-validate a batch of proposed queries from the LLM.

    Each item in plan should have:
        intent: str
        industry: str (optional)
        brand: str (optional)
        search_terms: list[str] (optional)

    Returns a BatchPreValidationResult with per-item details.

    Validation order:
      1. Mode intent check — is this intent allowed in the current mode?
      2. Industry/brand enum check
      3. Freshness gate — skip if data is still fresh (BYPASSED in collect mode)
      4. Term validation against approved pools
      5. Budget dry-run
    """
    from agent_interface.schemas import AgentMode, get_mode_config

    try:
        mode_cfg = get_mode_config(AgentMode(mode))
    except (ValueError, KeyError):
        mode_cfg = get_mode_config(AgentMode.MIXED)

    batch = BatchPreValidationResult(total=len(plan))
    total_api_calls = 0

    for item in plan:
        intent = item.get("intent", "")
        industry = item.get("industry", "")
        brand = item.get("brand", "")
        terms = item.get("search_terms", [])
        max_calls = item.get("max_budget_spend", 5)
        region = item.get("region", "austin_tx")

        # Auto-resolve industry aliases before validation so "mechanics" → "auto_repair"
        if industry:
            resolved = _resolve_industry_key(industry)
            if resolved and resolved != industry:
                logger.debug("[prevalidate] Industry alias resolved: '%s' → '%s'", industry, resolved)
                industry = resolved

        # ── Mode intent check ──────────────────────────────────────
        if intent not in mode_cfg.allowed_intents:
            batch.results.append(PreValidationResult(
                is_valid=False,
                proposed_term=intent,
                rejection_reason=(
                    f"Intent '{intent}' not allowed in mode '{mode}'. "
                    f"Allowed intents: {sorted(mode_cfg.allowed_intents)}"
                ),
                industry_key=industry or None,
            ))
            batch.rejected += 1
            continue

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

        # ── Freshness gate (BYPASSED in collect mode) ───────────────
        freshness = None
        if not mode_cfg.bypass_freshness:
            freshness = check_freshness_for_intent(
                intent=intent,
                region=region,
                brand=brand or None,
                industry=industry or None,
            )
            if freshness and not freshness["is_stale"] and freshness.get("records_collected", 0) > 0:
                batch.results.append(PreValidationResult(
                    is_valid=False,
                    proposed_term=intent,
                    rejection_reason=(
                        f"Data is still fresh — collected {freshness['age_days']:.1f} days ago "
                        f"(threshold: {freshness['threshold_days']} days). "
                        f"Next collection due: {freshness['next_due_at'] or 'unknown'}. "
                        f"Records on file: {freshness['records_collected']}. "
                        f"Pick a different intent, brand, or industry."
                    ),
                    industry_key=industry or None,
                    budget_ok=True,
                    budget_detail={"skipped": "data_still_fresh", **freshness},
                ))
                batch.rejected += 1
                continue
        else:
            # In bypass mode, still fetch freshness for informational purposes
            freshness = check_freshness_for_intent(
                intent=intent,
                region=region,
                brand=brand or None,
                industry=industry or None,
            )
            logger.info(
                "[PreValidate] Freshness gate BYPASSED for %s (mode=%s)",
                intent, mode,
            )

        # Infer term_type from intent so POI queries check poi_search_terms
        term_type = "job"  # default
        if intent.startswith("poi_"):
            term_type = "poi"
        elif intent.startswith("sentiment"):
            term_type = "sentiment"

        # Validate each search term against the correct pool (plus session-local terms)
        term_issues = []
        for t in terms:
            if industry:
                tv = validate_search_term(t, industry, term_type)
                if not tv.is_valid:
                    # Fall back to session-local terms added via wish this session
                    session_pool = (session_terms or {}).get(industry, [])
                    if any(t.strip().lower() == s.strip().lower() for s in session_pool):
                        tv = PreValidationResult(
                            is_valid=True,
                            proposed_term=t,
                            matched_term=t,
                            industry_key=industry,
                            term_type=term_type,
                        )
                    else:
                        term_issues.append(tv)

        if term_issues:
            # Report first bad term
            batch.results.append(term_issues[0])
            batch.rejected += 1
            continue

        # Budget dry-run
        budget = check_budget_for_intent(intent, max_calls)
        total_api_calls += max_calls

        # Build freshness context for valid result
        freshness_note = None
        if freshness and freshness.get("never_collected"):
            freshness_note = "Never collected — first run"
        elif freshness and mode_cfg.bypass_freshness:
            freshness_note = (
                f"Last collected {freshness['age_days']:.1f} days ago — "
                f"freshness BYPASSED (mode={mode})"
            )
        elif freshness:
            freshness_note = (
                f"Last collected {freshness['age_days']:.1f} days ago "
                f"(stale, threshold: {freshness['threshold_days']} days)"
            )

        batch.results.append(PreValidationResult(
            is_valid=True,
            proposed_term=intent,
            matched_term=intent,
            industry_key=industry or None,
            budget_ok=budget.get("budget_ok", True),
            budget_detail={
                **(budget or {}),
                "freshness": freshness_note,
                "mode": mode,
            },
        ))
        batch.valid += 1

    batch.estimated_api_calls = total_api_calls
    batch.budget_ok = all(r.budget_ok for r in batch.results if r.is_valid)
    return batch
