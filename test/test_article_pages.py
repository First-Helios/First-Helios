"""Article pages are no menus (ADR-0015 Amendment 3): never a candidate, withdrawn on re-check."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from apps.discovery.menu_url import is_article_path, ordered_menu_candidates
from apps.discovery.url_pipeline import WITHDRAW_REASONS
from apps.discovery.web_client import CaptureFailure
from packages.helios_core.provenance.validation import validate_outcome
from test.test_web_client import _HTML, _fetcher

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize(
    ("url", "article"),
    [
        ("https://www.chick-fil-a.com/stories/9-nutritious-chick-fil-a-menu-picks", True),
        ("https://www.freddys.com/blog/menu-items-can-be-lettuce-wrapped-freddys", True),
        ("https://cottonpatch.com/news/_posts/daily-lunch-specials-in-texas/", True),
        ("https://x.com/menu-items/egg/attachment/taco-egg/", True),
        ("https://x.com/NEWS/our-new-menu/", True),
        ("https://x.com/menu", False),
        ("https://x.com/menus/dinner", False),
        ("https://x.com/newsletter-menu", False),  # a whole segment, not a substring
        ("https://x.com/blogger-brunch/menu", False),
    ],
)
def test_article_paths(url: str, *, article: bool) -> None:
    assert is_article_path(url) is article


def test_an_article_page_is_never_a_candidate() -> None:
    html = (
        '<a href="/blog/our-new-menu">New menu!</a>'
        '<a href="/news/menu-update">Menu news</a>'
        '<a href="/dinner-menu">Dinner menu</a>'
    )
    candidates = ordered_menu_candidates("https://k.com/", homepage_html=html)
    assert "https://k.com/dinner-menu" in candidates
    assert not any(is_article_path(c) for c in candidates)


def test_a_saved_article_page_is_withdrawn_unread(tmp_path: Path) -> None:
    website = "https://k.com/"
    saved = "https://k.com/stories/9-nutritious-menu-picks"
    calls: list[str] = []
    routes = {saved: (200, "<h1>Menu</h1><p>Tacos $10</p>", _HTML)}
    with _fetcher(tmp_path, routes, calls=calls) as fetcher:
        result = fetcher.verify_menu_attempt(
            website, saved, not_before=datetime(2000, 1, 1, tzinfo=UTC)
        )
    assert isinstance(result, CaptureFailure)
    assert (result.outcome, result.reason_code) == ("failed", "article_page")
    assert saved not in calls  # decided from the URL alone
    assert "article_page" in WITHDRAW_REASONS
    validate_outcome("failed", "article_page")
