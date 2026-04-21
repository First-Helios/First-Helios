"""RetailMeNot — restaurant coupon codes."""

from collectors.hintbook.listing_walker import run_listing_walk
from collectors.hintbook.models import HarvestReport

NAME = "retailmenot"
HOMEPAGE = "https://www.retailmenot.com/"
SEED_URLS = [
    "https://www.retailmenot.com/coupons/restaurants",
    "https://www.retailmenot.com/coupons/restaurants/chain",
    "https://www.retailmenot.com/coupons/restaurants/fast-food",
]
AGG_HOST = "retailmenot.com"


def collect(report: HarvestReport) -> None:
    run_listing_walk(
        report=report,
        adapter_name=NAME,
        aggregator_host=AGG_HOST,
        seeds=SEED_URLS,
        industry="food",
        max_articles=30,
    )
