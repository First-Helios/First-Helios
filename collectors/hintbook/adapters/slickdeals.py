"""Slickdeals — restaurants category. Community-sourced."""

from collectors.hintbook.listing_walker import run_listing_walk
from collectors.hintbook.models import HarvestReport

NAME = "slickdeals"
HOMEPAGE = "https://slickdeals.net/"
SEED_URLS = [
    "https://slickdeals.net/deals/restaurants/",
    "https://slickdeals.net/deals/food-drink/",
]
AGG_HOST = "slickdeals.net"


def collect(report: HarvestReport) -> None:
    run_listing_walk(
        report=report,
        adapter_name=NAME,
        aggregator_host=AGG_HOST,
        seeds=SEED_URLS,
        industry="food",
        max_articles=30,
    )
