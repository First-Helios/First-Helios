import json

from bs4 import BeautifulSoup

from collectors.meal_deals.website_scrape_audit_utils import (
    classify_domain_family,
    summarize_debug_bundle,
)
from collectors.meal_deals import website_scraper as website_scraper_module
from scripts.build_website_scrape_replay_manifests import build_manifest_entries, build_regression_sets


def test_classify_domain_family_covers_known_families():
    assert classify_domain_family("https://www.facebook.com/roadhouse") == "social"
    assert classify_domain_family("https://m.facebook.com/roadhouse") == "social"
    assert classify_domain_family("https://locations.whataburger.com/tx/austin/store") == "locator"
    assert classify_domain_family("https://www.hilton.com/en/hotels/auscvhh-hilton-austin/dining/") == "hotel"
    assert classify_domain_family("https://thundercloud-100219.square.site/") == "vendor_menu_host"
    assert classify_domain_family("https://www.austintexas.org/listings/the-cloak-room/2762/") == "directory"
    assert classify_domain_family("http://www.huttotx.gov") == "government"


def test_summarize_debug_bundle_counts_pages_jsonld_and_blocks():
    bundle = {
        "pages": {
            "home": {
                "fetch_type": "hardcoded",
                "html": '<html><body><script type="application/ld+json">{"@type":"Menu"}</script><p>Lunch Special $10</p></body></html>',
            },
            "specials": {
                "fetch_type": "discovered",
                "html": "<html><body><div>Happy Hour $5 Margaritas</div></body></html>",
            },
        },
        "pdfs": {
            "menu": {"url": "https://example.com/menu.pdf", "full_text": "Happy Hour PDF"},
        },
        "pdf_links": ["https://example.com/menu.pdf"],
        "discovered_pages": ["https://example.com/specials"],
        "signals": [{"deal_name": "Lunch Special"}],
        "menu_avg_price": 9.5,
    }

    def _extract(html: str) -> list[str]:
        blocks = []
        if "Lunch Special" in html:
            blocks.append("Lunch Special $10")
        if "Happy Hour" in html:
            blocks.append("Happy Hour $5 Margaritas")
        return blocks

    summary = summarize_debug_bundle(bundle, extract_text_blocks=_extract)

    assert summary["page_count"] == 2
    assert summary["page_fetch_types"] == {"hardcoded": 1, "discovered": 1}
    assert summary["has_jsonld"] is True
    assert summary["total_blocks"] == 2
    assert summary["pdf_links"] == ["https://example.com/menu.pdf"]
    assert summary["parsed_pdf_count"] == 1
    assert summary["signal_count"] == 1
    assert summary["menu_avg_price"] == 9.5


def test_build_manifest_entries_and_regression_sets_tag_expected_cases():
    audit_entries = [
        {
            "debug_cache_key": "social-key",
            "name": "Roadhouse Bar",
            "url": "https://www.facebook.com/RoadhouseRR/",
            "outcome": "no_deals",
            "deals_found": 0,
            "locations_sharing_url": 1,
            "canonical_locations": 1,
            "alias_rows_collapsed": 0,
            "total_blocks": 0,
            "sample_blocks": [],
        },
        {
            "debug_cache_key": "jsonld-key",
            "name": "Example Bistro",
            "url": "https://example.com",
            "outcome": "no_deals",
            "deals_found": 0,
            "locations_sharing_url": 1,
            "canonical_locations": 1,
            "alias_rows_collapsed": 0,
            "total_blocks": 4,
            "sample_blocks": ["Lunch Special"],
        },
    ]
    debug_bundles = {
        "social-key": {
            "site_key": "social-key",
            "site_url": "https://www.facebook.com/RoadhouseRR/",
            "restaurant_name": "Roadhouse Bar",
            "pages": {},
            "pdfs": {},
            "pdf_links": [],
            "discovered_pages": [],
            "signals": [],
        },
        "jsonld-key": {
            "site_key": "jsonld-key",
            "site_url": "https://example.com",
            "restaurant_name": "Example Bistro",
            "pages": {
                "home": {
                    "fetch_type": "hardcoded",
                    "html": '<html><body><script type="application/ld+json">{"@type":"Menu"}</script></body></html>',
                },
            },
            "pdfs": {},
            "pdf_links": [],
            "discovered_pages": [],
            "signals": [],
        },
    }

    entries = build_manifest_entries(audit_entries, debug_bundles)
    by_key = {entry["site_key"]: entry for entry in entries}

    assert "social_or_non_first_party" in by_key["social-key"]["tags"]
    assert by_key["social-key"]["domain_family"] == "social"
    assert "jsonld_present_but_zero_signal" in by_key["jsonld-key"]["tags"]

    regression_sets = build_regression_sets(entries, per_set=2)
    assert regression_sets["wrong_target"]
    assert regression_sets["jsonld_zero_signal"]


def test_site_audit_context_from_debug_bundle_includes_success_fields(tmp_path, monkeypatch):
    base_url = "https://example.com"

    monkeypatch.setattr(
        "collectors.meal_deals.website_scraper.WEBSITE_SCRAPE_DEBUG_DIR",
        tmp_path,
    )

    bundle = website_scraper_module._reset_site_debug_bundle(
        base_url,
        restaurant_name="Polvos",
        region="austin_tx",
    )
    website_scraper_module._record_debug_page(
        bundle,
        base_url,
        html='<html><body><script type="application/ld+json">{"@type":"Menu"}</script><p>Lunch Special $10</p></body></html>',
        fetch_type="hardcoded",
    )
    website_scraper_module._record_debug_page(
        bundle,
        f"{base_url}/specials",
        html="<html><body><div>Happy Hour $5 Margaritas</div></body></html>",
        fetch_type="discovered",
    )

    path = website_scraper_module._site_debug_cache_path(base_url)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["discovered_pages"] = [f"{base_url}/specials"]
    payload["pdf_links"] = [f"{base_url}/menu.pdf"]
    payload["signals"] = [{"deal_name": "Lunch Special"}]
    path.write_text(json.dumps(payload), encoding="utf-8")

    context = website_scraper_module._site_audit_context_from_debug_bundle(base_url)

    assert context["page_count"] == 2
    assert context["structured_data_present"] is True
    assert context["page_fetch_types"] == {"hardcoded": 1, "discovered": 1}
    assert context["total_blocks"] >= 1
    assert context["discovered_page_count"] == 1
    assert context["bundle_signal_count"] == 1


def test_scrape_restaurant_website_skips_obvious_non_first_party_targets(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "collectors.meal_deals.website_scraper.WEBSITE_SCRAPE_DEBUG_DIR",
        tmp_path,
    )

    def _no_network(*_args, **_kwargs):
        raise AssertionError("network fetch should not run for suppressed targets")

    monkeypatch.setattr("collectors.meal_deals.website_scraper._fetch_page", _no_network)

    signals = website_scraper_module.scrape_restaurant_website(
        url="https://www.facebook.com/RoadhouseRR/",
        restaurant_name="Roadhouse Bar",
        local_employer_id=1,
        brand_group_id=None,
        region="austin_tx",
    )

    assert signals == []

    bundle = website_scraper_module._load_site_debug_bundle("https://www.facebook.com/RoadhouseRR/")
    assert bundle is not None
    assert bundle["domain_family"] == "social"
    assert bundle["skip_reason"] == "non_first_party_target"


def test_discover_deal_pages_picks_promo_card_learn_more_link():
        html = """
        <html><body>
            <section class="promo-card">
                <h2>BOGO Days</h2>
                <p>Limited time offer every Tuesday.</p>
                <a href="/bogo-days/">Learn More</a>
            </section>
        </body></html>
        """
        soup = BeautifulSoup(html, "html.parser")

        discovered = website_scraper_module._discover_deal_pages(soup, "https://example.com")

        assert "https://example.com/bogo-days/" in discovered


def test_discover_deal_pages_rejects_generic_learn_more_link_without_promo_context():
        html = """
        <html><body>
            <section class="about-card">
                <h2>About Our Story</h2>
                <p>Get to know the team.</p>
                <a href="/about-us/">Learn More</a>
            </section>
        </body></html>
        """
        soup = BeautifulSoup(html, "html.parser")

        discovered = website_scraper_module._discover_deal_pages(soup, "https://example.com")

        assert discovered == []