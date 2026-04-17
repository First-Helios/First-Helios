import json

from collectors.meal_deals.models import DealSignal
from collectors.meal_deals.website_scraper import (
    WebsiteDealCollector,
    _load_site_debug_bundle,
    _site_debug_cache_path,
    run_website_scraper,
    scrape_restaurant_website,
)


def test_website_scrape_debug_cache_replays_without_network(tmp_path, monkeypatch):
    base_url = "https://example.com"

    monkeypatch.setattr(
        "collectors.meal_deals.website_scraper.WEBSITE_SCRAPE_DEBUG_DIR",
        tmp_path,
    )
    monkeypatch.setattr("collectors.meal_deals.website_scraper.DEAL_PATHS", ["/"])
    monkeypatch.setattr("collectors.meal_deals.website_scraper.MAX_PAGES_PER_SITE", 1)
    monkeypatch.setattr("collectors.meal_deals.website_scraper.time.sleep", lambda _seconds: None)
    monkeypatch.setattr(
        "collectors.meal_deals.website_scraper._extract_text_blocks",
        lambda _soup: ["Lunch Special just $10 at Polvos from 11:00 to 14:00 Mon-Fri"],
    )
    monkeypatch.setattr(
        "collectors.meal_deals.website_scraper._discover_deal_pages",
        lambda _soup, _base_url: [],
    )
    monkeypatch.setattr(
        "collectors.meal_deals.website_scraper._discover_pdf_links",
        lambda _soup, _base_url: [],
    )
    monkeypatch.setattr(
        "collectors.meal_deals.website_scraper._extract_jsonld_deals",
        lambda *args, **kwargs: [],
    )
    monkeypatch.setattr(
        "collectors.meal_deals.website_scraper._text_block_to_signals",
        lambda block, **kwargs: [
            DealSignal(
                restaurant_name=kwargs["restaurant_name"],
                local_employer_id=kwargs["local_employer_id"],
                brand_group_id=kwargs["brand_group_id"],
                deal_name="Lunch Special",
                deal_description=block,
                deal_type="combo",
                price=10.0,
                price_type="absolute",
                source="website_scrape",
                source_url=kwargs["source_url"],
                region=kwargs["region"],
                raw_scraped_text=block,
            )
        ],
    )

    monkeypatch.setattr(
        "collectors.meal_deals.website_scraper._fetch_page",
        lambda _url, _ua: "<html><body>Lunch Special</body></html>",
    )

    first = scrape_restaurant_website(
        url=base_url,
        restaurant_name="Polvos",
        local_employer_id=1,
        brand_group_id=10,
        region="austin_tx",
    )

    assert len(first) == 1
    bundle = _load_site_debug_bundle(base_url)
    assert bundle is not None
    assert len(bundle["pages"]) == 1

    path = _site_debug_cache_path(base_url)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["pages"]["stale"] = {"url": "https://example.com/stale", "html": "stale"}
    path.write_text(json.dumps(payload), encoding="utf-8")

    monkeypatch.setattr(
        "collectors.meal_deals.website_scraper._fetch_page",
        lambda _url, _ua: "<html><body>Updated Lunch Special</body></html>",
    )
    second = scrape_restaurant_website(
        url=base_url,
        restaurant_name="Polvos",
        local_employer_id=1,
        brand_group_id=10,
        region="austin_tx",
    )
    assert len(second) == 1

    refreshed = json.loads(path.read_text(encoding="utf-8"))
    assert "stale" not in refreshed["pages"]

    def _no_network(*_args, **_kwargs):
        raise AssertionError("network fetch should not run in replay mode")

    monkeypatch.setattr("collectors.meal_deals.website_scraper._fetch_page", _no_network)

    replayed = scrape_restaurant_website(
        url=base_url,
        restaurant_name="Polvos",
        local_employer_id=1,
        brand_group_id=10,
        region="austin_tx",
        replay_debug_cache=True,
    )

    assert len(replayed) == 1
    assert replayed[0].deal_name == "Lunch Special"


def test_run_website_scraper_reports_inline_ingest_stats(monkeypatch):
    def _fake_collect(self, **_kwargs):
        self.last_run_stats = {
            "signals_found": 14,
            "rows_written": 21,
            "skipped": 3,
            "sites_scanned": 6,
            "chunk_size": 5,
        }
        return []

    monkeypatch.setattr(WebsiteDealCollector, "collect", _fake_collect)

    stats = run_website_scraper(
        region="austin_tx",
        max_sites=20,
        dry_run=False,
        chunk_size=5,
    )

    assert stats["signals_found"] == 14
    assert stats["rows_written"] == 21
    assert stats["skipped"] == 3
    assert stats["sites_scanned"] == 6
    assert stats["chunk_size"] == 5