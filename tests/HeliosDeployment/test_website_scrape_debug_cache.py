import json
import shutil
from pathlib import Path

import pytest

from collectors.meal_deals.models import DealSignal
from collectors.meal_deals.website_scraper import (
    WebsiteDealCollector,
    _load_site_debug_bundle,
    _site_debug_cache_path,
    run_website_scraper,
    scrape_restaurant_website,
)


_BUNDLE_DIR = Path("data/cache/website_scrape_debug")
_BWW_REPLAY_BUNDLE = _BUNDLE_DIR / "buffalowildwings_com_en_locations_detail_621__9af1c34bd10b.json"
_WINGS_REPLAY_BUNDLE = _BUNDLE_DIR / "wingsnmore_austin_com__4c0b10dd23c9.json"


def _skip_if_missing(bundle: Path) -> None:
    if not bundle.exists():
        pytest.skip(f"Replay bundle not synced locally: {bundle}")


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


def test_website_scrape_extracts_next_data_promos(tmp_path, monkeypatch):
    next_data = {
        "props": {
            "pageProps": {
                "page": {
                    "fields": {
                        "section": [
                            {
                                "fields": {
                                    "cards": [
                                        {
                                            "fields": {
                                                "internalTitle": "BOGO Wing Tuesday - AW3 - 2024 - Type3",
                                                "title": [
                                                    {
                                                        "fields": {
                                                            "text": "BOGO Wing Tuesday",
                                                        }
                                                    }
                                                ],
                                                "description": "Rewards Members score BOGO 100% off bone-in wings.",
                                                "showViewMore": True,
                                                "type": "type3",
                                                "primaryCTAText": "FIND YOUR SPORTS BAR",
                                                "primaryCTAAction": {
                                                    "fields": {
                                                        "action": "locations",
                                                        "name": "/sports-bar",
                                                    }
                                                },
                                                "descriptionCTA": {
                                                    "fields": {
                                                        "message": "Buy one 6-, 10- or 15-count bone-in wings and get one of equal value free on Tuesdays.",
                                                    }
                                                },
                                            }
                                        },
                                        {
                                            "fields": {
                                                "internalTitle": "BOGO Thursday_AW4_2025_type3",
                                                "title": [
                                                    {
                                                        "fields": {
                                                            "text": "Get Free Boneless Wings",
                                                        }
                                                    }
                                                ],
                                                "description": "Every Thursday with takeout & delivery from Buffalo Wild Wings GO.",
                                                "showViewMore": True,
                                                "type": "type3",
                                                "primaryCTAText": "ORDER NOW",
                                                "primaryCTAAction": {
                                                    "fields": {
                                                        "action": "menu/categories/wings/bogo-boneless-wings/",
                                                        "name": "menu/categories/value-bundles/free-boneless-thursday",
                                                    }
                                                },
                                                "descriptionCTA": {
                                                    "fields": {
                                                        "message": "Buy one order of boneless wings and get another free every Thursday.",
                                                    }
                                                },
                                            }
                                        },
                                    ]
                                }
                            }
                        ]
                    }
                }
            }
        }
    }
    html = (
        "<html><body>"
        "<main>Promotions</main>"
        f"<script id=\"__NEXT_DATA__\" type=\"application/json\">{json.dumps(next_data)}</script>"
        "</body></html>"
    )

    monkeypatch.setattr(
        "collectors.meal_deals.website_scraper.WEBSITE_SCRAPE_DEBUG_DIR",
        tmp_path,
    )
    monkeypatch.setattr("collectors.meal_deals.website_scraper.DEAL_PATHS", ["/promotions"])
    monkeypatch.setattr("collectors.meal_deals.website_scraper.MAX_PAGES_PER_SITE", 1)
    monkeypatch.setattr("collectors.meal_deals.website_scraper.time.sleep", lambda _seconds: None)
    monkeypatch.setattr(
        "collectors.meal_deals.website_scraper._fetch_page",
        lambda _url, _ua: html,
    )

    signals = scrape_restaurant_website(
        url="https://www.buffalowildwings.com/en/locations/detail/621",
        restaurant_name="Buffalo Wild Wings",
        local_employer_id=33621,
        brand_group_id=14279,
        region="austin_tx",
    )

    assert len(signals) == 2
    assert {signal.deal_type for signal in signals} == {"bogo"}
    assert {signal.valid_days for signal in signals} == {"Thu", "Tue"}
    assert {signal.deal_name for signal in signals} == {
        "BOGO Wing Tuesday",
        "Get Free Boneless Wings",
    }
    assert all(signal.source_url == "https://www.buffalowildwings.com/promotions" for signal in signals)
    assert all(signal.metadata.get("embedded_app_source") == "__NEXT_DATA__" for signal in signals)
    assert any(
        signal.metadata.get("embedded_app_cta_url")
        == "https://www.buffalowildwings.com/menu/categories/wings/bogo-boneless-wings/"
        for signal in signals
    )


def test_website_scrape_bww_replay_consolidates_promo_variants(tmp_path, monkeypatch):
    _skip_if_missing(_BWW_REPLAY_BUNDLE)

    staging = tmp_path / "website_scrape_debug"
    staging.mkdir()
    shutil.copy(_BWW_REPLAY_BUNDLE, staging / _BWW_REPLAY_BUNDLE.name)

    monkeypatch.setattr(
        "collectors.meal_deals.website_scraper.WEBSITE_SCRAPE_DEBUG_DIR",
        staging,
    )
    monkeypatch.setattr("collectors.meal_deals.website_scraper.time.sleep", lambda _seconds: None)

    def _no_network(*_args, **_kwargs):
        raise AssertionError("network fetch should not run in replay mode")

    monkeypatch.setattr("collectors.meal_deals.website_scraper._fetch_page", _no_network)

    signals = scrape_restaurant_website(
        url="https://www.buffalowildwings.com/en/locations/detail/621",
        restaurant_name="Buffalo Wild Wings",
        local_employer_id=33621,
        brand_group_id=14279,
        region="austin_tx",
        replay_debug_cache=True,
    )

    happy_hour_signals = [
        signal for signal in signals
        if signal.source_url == "https://www.buffalowildwings.com/happy-hour"
    ]
    assert len(happy_hour_signals) == 1
    happy_hour = happy_hour_signals[0]
    assert happy_hour.deal_name == "Happy Hour"
    assert happy_hour.price == 3.0
    assert happy_hour.valid_days == "Mon-Fri"
    assert happy_hour.valid_start_time == "3:00 PM"
    assert happy_hour.valid_end_time == "6:00 PM"

    names = {signal.deal_name for signal in signals}
    reward_signals = [signal for signal in signals if "burger" in (signal.deal_name or "").lower()]
    assert "BOGO Wing Tuesday" in names
    assert "Get Free Boneless Wings" in names
    assert len(reward_signals) == 1
    assert "BUFFALO WILD WINGS REWARDS" not in names
    assert "$3-6 FROM 3-6 PM" not in names


def test_website_scrape_wings_replay_preserves_day_headings_on_child_specials(tmp_path, monkeypatch):
    _skip_if_missing(_WINGS_REPLAY_BUNDLE)

    staging = tmp_path / "website_scrape_debug"
    staging.mkdir()
    shutil.copy(_WINGS_REPLAY_BUNDLE, staging / _WINGS_REPLAY_BUNDLE.name)

    monkeypatch.setattr(
        "collectors.meal_deals.website_scraper.WEBSITE_SCRAPE_DEBUG_DIR",
        staging,
    )
    monkeypatch.setattr("collectors.meal_deals.website_scraper.time.sleep", lambda _seconds: None)

    def _no_network(*_args, **_kwargs):
        raise AssertionError("network fetch should not run in replay mode")

    monkeypatch.setattr("collectors.meal_deals.website_scraper._fetch_page", _no_network)

    signals = scrape_restaurant_website(
        url="http://wingsnmore-austin.com",
        restaurant_name="Wings N More",
        local_employer_id=36352,
        brand_group_id=36352,
        region="austin_tx",
        replay_debug_cache=True,
    )

    bogo_signals = [
        signal for signal in signals
        if signal.deal_type == "bogo" and "wingsnmore-austin.com/specials" in (signal.source_url or "")
    ]

    assert bogo_signals
    assert {signal.valid_days for signal in bogo_signals} == {"Tue"}
    assert any("Buy One Get One Free" in (signal.deal_name or "") for signal in bogo_signals)