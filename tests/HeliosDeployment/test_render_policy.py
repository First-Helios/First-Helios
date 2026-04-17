"""Tests for collectors.meal_deals.render_policy (ARCH-03)."""

from __future__ import annotations

import hashlib

from collectors.meal_deals.render_policy import (
    EXPLORATION_SAMPLE_MODULUS,
    STRONG_DISCOVERY_THRESHOLD,
    PageEvidence,
    RenderBudget,
    should_render,
)


def _evidence(**overrides) -> PageEvidence:
    defaults = dict(
        page_url="https://example.com/menu",
        domain="example.com",
        static_html_empty=True,
        menu_critical=True,
        discovery_evidence_score=0.9,
        discovered_via="promo_card",
    )
    defaults.update(overrides)
    return PageEvidence(**defaults)


def _force_sampleable_url(modulus: int) -> str:
    """Find a URL whose hash bucket == 0 under the given modulus."""
    for i in range(10_000):
        url = f"https://example.com/sample-{i}"
        digest = hashlib.sha1(url.encode("utf-8")).hexdigest()
        if int(digest[:8], 16) % modulus == 0:
            return url
    raise RuntimeError("could not synthesize a sampleable URL")


def _force_non_sampleable_url(modulus: int) -> str:
    for i in range(10_000):
        url = f"https://example.com/nosample-{i}"
        digest = hashlib.sha1(url.encode("utf-8")).hexdigest()
        if int(digest[:8], 16) % modulus != 0:
            return url
    raise RuntimeError("could not synthesize a non-sampleable URL")


def test_non_empty_static_skips_render():
    budget = RenderBudget()
    decision = should_render(_evidence(static_html_empty=False), budget=budget)
    assert decision.should_render is False
    assert decision.reason == "static_html_not_empty"
    assert budget.renders_used == 0


def test_escalation_when_all_gates_pass_within_budget():
    budget = RenderBudget(max_renders=2)
    decision = should_render(_evidence(), budget=budget)
    assert decision.should_render is True
    assert decision.reason == "bounded_escalation"
    assert decision.budget_category == "main"
    assert budget.renders_used == 1


def test_allowlist_bypasses_budget_with_distinct_reason():
    budget = RenderBudget(max_renders=0)
    decision = should_render(
        _evidence(domain="allowed.com", page_url="https://allowed.com/menu"),
        budget=budget,
        allowlist_domains=["ALLOWED.com"],
    )
    assert decision.should_render is True
    assert decision.reason == "allowlist_escalation"
    assert decision.budget_category == "main"


def test_weak_discovery_denies_render_even_if_menu_critical():
    budget = RenderBudget()
    ev = _evidence(
        discovery_evidence_score=STRONG_DISCOVERY_THRESHOLD - 0.1,
        page_url=_force_non_sampleable_url(EXPLORATION_SAMPLE_MODULUS),
    )
    decision = should_render(ev, budget=budget)
    assert decision.should_render is False
    assert decision.reason == "discovery_evidence_weak"


def test_not_menu_critical_denies_render():
    budget = RenderBudget()
    ev = _evidence(
        menu_critical=False,
        page_url=_force_non_sampleable_url(EXPLORATION_SAMPLE_MODULUS),
    )
    decision = should_render(ev, budget=budget)
    assert decision.should_render is False
    assert decision.reason == "not_menu_critical"


def test_budget_exhaustion_denies_render():
    budget = RenderBudget(max_renders=0, max_exploration_samples=0)
    decision = should_render(_evidence(), budget=budget)
    assert decision.should_render is False
    assert decision.reason == "budget_exhausted"


def test_exploration_sample_renders_dead_end_page():
    """Dead-end (menu_critical=False) pages sampled for exploration."""
    budget = RenderBudget(max_renders=0, max_exploration_samples=1)
    url = _force_sampleable_url(EXPLORATION_SAMPLE_MODULUS)
    ev = _evidence(menu_critical=False, page_url=url, discovery_evidence_score=0.1)
    decision = should_render(ev, budget=budget)
    assert decision.should_render is True
    assert decision.reason == "exploration_sample"
    assert decision.budget_category == "exploration"
    assert budget.exploration_used == 1


def test_exploration_sample_is_deterministic():
    """Same URL must always hit the same exploration decision across runs."""
    url = _force_sampleable_url(EXPLORATION_SAMPLE_MODULUS)
    ev = _evidence(menu_critical=False, page_url=url, discovery_evidence_score=0.1)
    for _ in range(3):
        budget = RenderBudget(max_renders=0, max_exploration_samples=1)
        assert should_render(ev, budget=budget).should_render is True


def test_exploration_respects_exhaustion():
    """Once exploration budget is used, no more sampling happens."""
    url = _force_sampleable_url(EXPLORATION_SAMPLE_MODULUS)
    ev = _evidence(menu_critical=False, page_url=url, discovery_evidence_score=0.1)
    budget = RenderBudget(max_renders=0, max_exploration_samples=0)
    decision = should_render(ev, budget=budget)
    assert decision.should_render is False
