"""The Krazy Coupon Lady — food deals near me."""

from collectors.hintbook.listing_walker import run_listing_walk
from collectors.hintbook.models import HarvestReport

NAME = "kcl"
HOMEPAGE = "https://thekrazycouponlady.com/"
SEED_URLS = [
    "https://thekrazycouponlady.com/tips/money/food-deals-near-me",
    "https://thekrazycouponlady.com/topic/restaurant-coupons",
    "https://thekrazycouponlady.com/tips/money/best-food-delivery-deals",
]
AGG_HOST = "thekrazycouponlady.com"


def collect(report: HarvestReport) -> None:
    run_listing_walk(
        report=report,
        adapter_name=NAME,
        aggregator_host=AGG_HOST,
        seeds=SEED_URLS,
        industry="food",
        max_articles=30,
    )
