"""Unit tests for the pure menu-URL candidate logic (no I/O)."""

from __future__ import annotations

from apps.discovery.menu_url import (
    MAX_CANDIDATES,
    looks_like_menu,
    menu_links_from_html,
    menu_links_from_sitemap,
    ordered_menu_candidates,
    same_site,
)


def test_same_site_ignores_www_and_case() -> None:
    assert same_site("https://Torchys.com/a", "http://www.torchys.com/b")
    assert not same_site("https://torchys.com", "https://veracruz.com")
    assert not same_site("https://torchys.com", "not-a-url")


def test_looks_like_menu_matches_text_or_path_but_not_chrome() -> None:
    assert looks_like_menu("Our Menu", "/pages/x")
    assert looks_like_menu("", "/food-menu")
    assert looks_like_menu("Menus", "/")
    # Navigation chrome that merely contains "menu" must be rejected.
    assert not looks_like_menu("Toggle menu", "/#")
    assert not looks_like_menu("About", "/about")


def test_menu_links_from_html_keeps_same_site_absolute_urls() -> None:
    html = """
    <html><body>
      <a href="/menu">Menu</a>
      <a href="menus/dinner">Dinner Menu</a>
      <a href="https://external.example/menu">Off-site menu</a>
      <a href="/about">About</a>
      <a>no href</a>
    </body></html>
    """
    links = menu_links_from_html(html, "https://kerbey.com/")
    assert links == ["https://kerbey.com/menu", "https://kerbey.com/menus/dinner"]


def test_menu_links_from_sitemap_filters_by_path_and_host() -> None:
    xml = """<?xml version="1.0"?>
    <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
      <url><loc>https://kerbey.com/menu</loc></url>
      <url><loc>https://kerbey.com/about</loc></url>
      <url><loc>https://other.com/menu</loc></url>
    </urlset>
    """
    assert menu_links_from_sitemap(xml, "https://kerbey.com/") == ["https://kerbey.com/menu"]


def test_menu_links_from_sitemap_tolerates_malformed_xml() -> None:
    assert menu_links_from_sitemap("<not xml", "https://kerbey.com/") == []


def test_ordered_candidates_prioritises_paths_then_sitemap_then_anchors() -> None:
    html = '<a href="/food-menu">Food Menu</a>'
    sitemap = (
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        "<url><loc>https://k.com/lunch-menu</loc></url></urlset>"
    )
    candidates = ordered_menu_candidates("https://k.com/", homepage_html=html, sitemap_xml=sitemap)
    # Well-known paths first, in declared order.
    assert candidates[:4] == [
        "https://k.com/menu",
        "https://k.com/menus",
        "https://k.com/food",
        "https://k.com/our-menu",
    ]
    assert "https://k.com/lunch-menu" in candidates
    assert "https://k.com/food-menu" in candidates
    assert candidates.index("https://k.com/lunch-menu") < candidates.index(
        "https://k.com/food-menu"
    )


def test_ordered_candidates_dedupe_and_cap() -> None:
    # A sitemap and anchor both pointing at /menu must not double the /menu path.
    html = '<a href="/menu">Menu</a>'
    sitemap = (
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        "<url><loc>https://k.com/menu/</loc></url></urlset>"
    )
    candidates = ordered_menu_candidates("https://k.com/", homepage_html=html, sitemap_xml=sitemap)
    assert candidates.count("https://k.com/menu") == 1
    assert len(candidates) <= MAX_CANDIDATES


def test_ordered_candidates_without_crawled_signals_are_just_paths() -> None:
    assert ordered_menu_candidates("https://k.com") == [
        "https://k.com/menu",
        "https://k.com/menus",
        "https://k.com/food",
        "https://k.com/our-menu",
    ]
