"""
collectors/meal_deals/render_policy.py — ARCH-03 renderer escalation policy.

Pure decision layer. Inputs are structured evidence about a page + a
budget tracker; outputs are a RenderDecision that downstream code (e.g.,
RENDER-01's Playwright escalation) consumes.

Policy (per roadmap recommendation):
  * Escalate to rendering ONLY when:
      - static HTML was structurally empty (no menu/promo content found)
      - discovery evidence is strong (score above threshold)
      - the page is menu-critical (discovery classified it as deal-relevant)
      - the site is either allowlisted OR there's per-run budget left
  * Reserve a small exploration budget to render "dead-end" pages (static
    empty + weak discovery) on a sampled basis. This keeps escalation
    behavior measurable — we can tell if our threshold is too strict by
    looking at whether exploration samples ever yield signals.
  * Sampling is deterministic (URL-hashed) so replays stay stable.

Nothing here touches Playwright. That stays behind a separate interface
so this module remains safe to import in any context.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from typing import Iterable

logger = logging.getLogger(__name__)


# ── Evidence + decision types ───────────────────────────────────────────────


@dataclass(frozen=True)
class PageEvidence:
    """What the static pass already knows about a candidate page."""
    page_url: str
    domain: str
    static_html_empty: bool          # no menu/promo content extracted
    menu_critical: bool              # discovery tagged as deal-relevant
    discovery_evidence_score: float  # 0.0–1.0 from discovery scorer
    discovered_via: str | None = None  # "footer_link", "promo_card", "sitemap", etc.


@dataclass
class RenderBudget:
    """Per-run budget tracker. Not thread-safe — one per scraper run."""
    max_renders: int = 20
    max_exploration_samples: int = 3
    renders_used: int = 0
    exploration_used: int = 0

    def has_main_budget(self) -> bool:
        return self.renders_used < self.max_renders

    def has_exploration_budget(self) -> bool:
        return self.exploration_used < self.max_exploration_samples


@dataclass(frozen=True)
class RenderDecision:
    should_render: bool
    reason: str
    budget_category: str | None  # "main" | "exploration" | None
    evidence: PageEvidence


# ── Tunables ────────────────────────────────────────────────────────────────

STRONG_DISCOVERY_THRESHOLD = 0.70
EXPLORATION_SAMPLE_MODULUS = 20  # ~5% of eligible dead-end pages


# ── Core decision function ─────────────────────────────────────────────────


def should_render(
    evidence: PageEvidence,
    *,
    budget: RenderBudget,
    allowlist_domains: Iterable[str] = (),
    exploration_modulus: int = EXPLORATION_SAMPLE_MODULUS,
) -> RenderDecision:
    """Decide whether a page warrants renderer escalation.

    Mutates `budget` to reflect the decision so the caller can track
    remaining slots across a run. Evaluation order matches the policy:
      1. Skip if static HTML wasn't empty (rendering won't help).
      2. Render under main budget if all four escalation gates pass.
      3. Render under exploration budget for a sampled subset of dead-ends.
      4. Skip otherwise.
    """
    if not evidence.static_html_empty:
        return RenderDecision(
            should_render=False,
            reason="static_html_not_empty",
            budget_category=None,
            evidence=evidence,
        )

    allowlist = {d.lower() for d in allowlist_domains}
    allowlisted = evidence.domain.lower() in allowlist
    strong_discovery = evidence.discovery_evidence_score >= STRONG_DISCOVERY_THRESHOLD

    if (
        evidence.menu_critical
        and strong_discovery
        and (allowlisted or budget.has_main_budget())
    ):
        budget.renders_used += 1
        reason = "allowlist_escalation" if allowlisted else "bounded_escalation"
        return RenderDecision(
            should_render=True,
            reason=reason,
            budget_category="main",
            evidence=evidence,
        )

    # Exploration path: static-empty dead-ends we'd normally skip. Sample
    # deterministically so the same URL always gets the same coin flip
    # across replays.
    if (
        budget.has_exploration_budget()
        and _exploration_sample_selects(evidence.page_url, exploration_modulus)
    ):
        budget.exploration_used += 1
        return RenderDecision(
            should_render=True,
            reason="exploration_sample",
            budget_category="exploration",
            evidence=evidence,
        )

    if not evidence.menu_critical:
        reason = "not_menu_critical"
    elif not strong_discovery:
        reason = "discovery_evidence_weak"
    else:
        reason = "budget_exhausted"

    return RenderDecision(
        should_render=False,
        reason=reason,
        budget_category=None,
        evidence=evidence,
    )


# ── Helpers ─────────────────────────────────────────────────────────────────


def _exploration_sample_selects(url: str, modulus: int) -> bool:
    """Deterministic 1-in-N sampler keyed by URL hash.

    Kept deterministic so replay bundles produce the same exploration
    decisions — otherwise we'd get drift between live and replay runs.
    """
    if modulus <= 0:
        return False
    digest = hashlib.sha1(url.encode("utf-8")).hexdigest()
    bucket = int(digest[:8], 16) % modulus
    return bucket == 0
