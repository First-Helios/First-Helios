"""Unit tests for the pure menu-URL candidate logic (no I/O)."""

from __future__ import annotations

from apps.discovery.menu_url import (
    MAX_CANDIDATES,
    is_platform_venue_page,
    looks_like_menu,
    menu_links_from_html,
    menu_links_from_sitemap,
    ordered_menu_candidates,
    page_menu_signal,
    platform_links_from_html,
    platform_signal,
    same_resource,
    same_site,
    sitemap_index_children,
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


def test_menu_links_from_html_honours_base_href() -> None:
    html = '<head><base href="/en/"></head><a href="dinner-menu">Dinner</a>'
    assert menu_links_from_html(html, "https://kerbey.com/home") == [
        "https://kerbey.com/en/dinner-menu"
    ]


def test_menu_links_from_html_base_href_cannot_leave_the_site() -> None:
    html = '<base href="https://evil.example/"><a href="menu">Menu</a>'
    assert menu_links_from_html(html, "https://kerbey.com/") == []
    # A non-http base is ignored; links resolve against the page itself.
    html = '<base href="javascript:void(0)"><a href="menu">Menu</a>'
    assert menu_links_from_html(html, "https://kerbey.com/a/") == ["https://kerbey.com/a/menu"]


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


# --- Review remediation S4 (R08, R33, R34, R75, R76) ----------------------------


def test_same_resource_ignores_trailing_slash_and_fragment() -> None:
    assert same_resource("https://k.com/", "https://k.com")
    assert same_resource("https://k.com/#menu", "https://k.com/")
    assert same_resource("https://k.com/menu/", "https://k.com/menu")
    assert not same_resource("https://k.com/menu", "https://k.com/")


def test_menu_links_from_html_drops_fragment_and_self_links() -> None:
    # R08: a hamburger toggle ("#") and a full-page link that is really the
    # homepage under another name must never become menu candidates.
    html = (
        '<a href="#">Menu</a>'
        '<a href="/#menu">Menu</a>'
        '<a href="/">Full Menu</a>'
        '<a href="/menu">Menu</a>'
    )
    assert menu_links_from_html(html, "https://kerbey.com/") == ["https://kerbey.com/menu"]


def test_looks_like_menu_rejects_blocklisted_lookalikes() -> None:
    # R34: a menu term alone is not enough once a blocklisted word is present.
    assert not looks_like_menu("", "/menu-of-services")
    assert not looks_like_menu("", "/wp-admin/nav-menus.php")
    assert not looks_like_menu("", "/food-safety-policy")
    assert not looks_like_menu("Food Bank Donations", "/donate")
    # Genuine menu links still hit.
    assert looks_like_menu("", "/menu")
    assert looks_like_menu("", "/dinner-menu")
    assert looks_like_menu("Dinner Menu", "/eat")


def test_menu_links_from_sitemap_rejects_blocklisted_paths() -> None:
    xml = """<?xml version="1.0"?>
    <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
      <url><loc>https://kerbey.com/menu-of-services</loc></url>
      <url><loc>https://kerbey.com/wp-admin/nav-menus.php</loc></url>
      <url><loc>https://kerbey.com/dinner-menu</loc></url>
    </urlset>
    """
    assert menu_links_from_sitemap(xml, "https://kerbey.com/") == ["https://kerbey.com/dinner-menu"]


def test_menu_links_from_sitemap_drops_the_homepage_itself() -> None:
    xml = """<?xml version="1.0"?>
    <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
      <url><loc>https://kerbey.com/</loc></url>
      <url><loc>https://kerbey.com/menu</loc></url>
    </urlset>
    """
    assert menu_links_from_sitemap(xml, "https://kerbey.com/") == ["https://kerbey.com/menu"]


def test_sitemap_index_children_are_not_page_candidates() -> None:
    # R75: an index's <loc> entries name sitemap *documents*; a filename that
    # happens to contain a menu word (sitemap-menu.xml) must not leak through
    # menu_links_from_sitemap as a page candidate.
    xml = """<?xml version="1.0"?>
    <sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
      <sitemap><loc>https://kerbey.com/sitemap-menu.xml</loc></sitemap>
      <sitemap><loc>https://kerbey.com/sitemap-pages.xml</loc></sitemap>
    </sitemapindex>
    """
    assert menu_links_from_sitemap(xml, "https://kerbey.com/") == []
    assert sitemap_index_children(xml, "https://kerbey.com/") == [
        "https://kerbey.com/sitemap-menu.xml",
        "https://kerbey.com/sitemap-pages.xml",
    ]


def test_sitemap_index_children_are_capped_and_same_site() -> None:
    entries = "".join(f"<sitemap><loc>https://k.com/s{i}.xml</loc></sitemap>" for i in range(10))
    xml = (
        '<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        f"{entries}"
        "<sitemap><loc>https://other.com/s.xml</loc></sitemap>"
        "</sitemapindex>"
    )
    children = sitemap_index_children(xml, "https://k.com/")
    assert len(children) == 5  # noqa: PLR2004 - MAX_SITEMAP_CHILDREN
    assert all(child.startswith("https://k.com/") for child in children)


def test_urlset_is_not_treated_as_a_sitemap_index() -> None:
    xml = (
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        "<url><loc>https://k.com/menu</loc></url>"
        "</urlset>"
    )
    assert sitemap_index_children(xml, "https://k.com/") == []


def test_ordered_candidates_reserve_slots_for_homepage_anchors() -> None:
    # R34: ten sitemap-matched blog posts must not crowd a real homepage
    # anchor entirely out of MAX_CANDIDATES.
    html = '<a href="/dinner">Dinner Menu</a>'
    sitemap_matches = tuple(f"https://k.com/blog/food-post-{i}" for i in range(10))
    candidates = ordered_menu_candidates(
        "https://k.com/", homepage_html=html, extra_sitemap_matches=sitemap_matches
    )
    assert "https://k.com/dinner" in candidates
    assert len(candidates) <= MAX_CANDIDATES


def test_page_menu_signal_checks_path_title_or_heading() -> None:
    assert page_menu_signal("<title>Dinner Menu</title>", "https://k.com/x")
    assert page_menu_signal("<h1>Our Menu</h1>", "https://k.com/x")
    assert page_menu_signal("<p>nothing</p>", "https://k.com/menu")
    assert not page_menu_signal("<title>Contact Us</title>", "https://k.com/contact")


def test_page_menu_signal_rejects_blocklisted_title() -> None:
    assert not page_menu_signal("<title>Catering Services</title>", "https://k.com/menu-services")


def test_page_menu_signal_can_distrust_the_url_path() -> None:
    # R08: on a catch-all/soft-404 host, a well-known path's own URL is not
    # evidence of anything -- only the page's title/heading count.
    html = "<p>we could not find that page</p>"
    assert page_menu_signal(html, "https://k.com/menu", trust_path=True)
    assert not page_menu_signal(html, "https://k.com/menu", trust_path=False)


def test_platform_signal_matches_known_hosts_and_subdomains() -> None:
    assert platform_signal("https://order.toasttab.com/venue")
    assert platform_signal("https://www.facebook.com/venue")
    assert platform_signal("https://doordash.com/store/venue-1")
    assert not platform_signal("https://kerbey.com/toasttab")


def test_platform_links_from_html_ignores_site_and_menu_wording() -> None:
    html = (
        '<a href="https://order.toasttab.com/venue">Order Online</a>'
        '<a href="/menu">Menu</a>'
        '<a href="https://instagram.com/venue">Follow us</a>'
    )
    links = platform_links_from_html(html, "https://kerbey.com/")
    assert links == ["https://order.toasttab.com/venue"], "social icons are never a menu fallback"


def test_platform_links_skip_platform_roots() -> None:
    # A "Powered by Toast" footer link is the platform's page, not the venue's (R33).
    html = (
        '<a href="https://pos.toasttab.com/">Powered by Toast</a>'
        '<a href="https://www.doordash.com/store/kerbey-123/">Order delivery</a>'
    )
    links = platform_links_from_html(html, "https://kerbey.com/")
    assert links == ["https://www.doordash.com/store/kerbey-123/"]


def test_is_platform_venue_page_requires_a_non_root_path() -> None:
    assert is_platform_venue_page("https://www.facebook.com/kerbeylane")
    assert not is_platform_venue_page("https://www.facebook.com/")
    assert not is_platform_venue_page("https://www.facebook.com/kerbeylane", ordering_only=True)
    assert is_platform_venue_page("https://order.toasttab.com/online/kerbey", ordering_only=True)
