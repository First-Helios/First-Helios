from collectors.meal_deals.models import DealSignal
from collectors.meal_deals.website_scraper import _consolidate_site_signals


def _build_signal(
    *,
    deal_name: str,
    deal_type: str,
    source_url: str,
    price: float | None = None,
    valid_days: str | None = None,
    metadata: dict | None = None,
) -> DealSignal:
    return DealSignal(
        restaurant_name="Good Luck Grill",
        local_employer_id=1,
        deal_name=deal_name,
        deal_type=deal_type,
        price=price,
        valid_days=valid_days,
        source="website_scrape",
        source_url=source_url,
        region="austin_tx",
        metadata=metadata or {},
    )


def test_consolidate_site_signals_prefers_newer_pdf_source_when_merging_same_offer():
    stale_html = _build_signal(
        deal_name="Happy Hour",
        deal_type="happy_hour",
        source_url="https://goodluckgrill.com/featured-items/happy-hour",
        price=2.0,
        valid_days="Mon-Fri",
        metadata={
            "source_fetch_type": "hardcoded",
            "source_page_published_at": "2010-09-18T12:50:03+00:00",
        },
    )
    current_pdf = _build_signal(
        deal_name="Happy Hour",
        deal_type="happy_hour",
        source_url="https://goodluckgrill.com/wp-content/uploads/2025/02/happy-hour-03.01.2025.pdf",
        price=3.0,
        metadata={
            "source_fetch_type": "pdf",
            "source_document_date": "2025-03-01T00:00:00+00:00",
        },
    )

    signals = _consolidate_site_signals([stale_html, current_pdf])

    assert len(signals) == 1
    merged = signals[0]
    assert merged.source_url == current_pdf.source_url
    assert merged.price == 3.0
    assert merged.valid_days == "Mon-Fri"
    assert merged.metadata["source_fetch_type"] == "pdf"


def test_consolidate_site_signals_orders_current_page_before_stale_hardcoded_html():
    stale_html = _build_signal(
        deal_name="Happy Hour",
        deal_type="happy_hour",
        source_url="https://goodluckgrill.com/featured-items/happy-hour",
        price=2.0,
        metadata={
            "source_fetch_type": "hardcoded",
            "source_page_published_at": "2010-09-18T12:50:03+00:00",
        },
    )
    current_page = _build_signal(
        deal_name="$8 Daily Lunch Special",
        deal_type="daily_special",
        source_url="https://goodluckgrill.com/food/daily-lunch-specials/",
        price=8.0,
        metadata={
            "source_fetch_type": "discovered",
            "source_page_modified_at": "2026-03-01T00:00:00+00:00",
        },
    )

    signals = _consolidate_site_signals([stale_html, current_page])

    assert [signal.source_url for signal in signals] == [
        current_page.source_url,
        stale_html.source_url,
    ]
