"""EatDrinkDeals — dedicated food-deal aggregator. Pure-play news format."""

from collectors.hintbook.listing_walker import run_listing_walk
from collectors.hintbook.models import HarvestReport

NAME = "eatdrinkdeals"
HOMEPAGE = "https://www.eatdrinkdeals.com/"
SEED_URLS = [
    "https://www.eatdrinkdeals.com/",
    "https://www.eatdrinkdeals.com/happy-hour-deals/",
    "https://www.eatdrinkdeals.com/kids-eat-free/",
    "https://www.eatdrinkdeals.com/lunch-specials/",
    "https://www.eatdrinkdeals.com/dinner-for-two-deals/",
]
AGG_HOST = "eatdrinkdeals.com"


def collect(report: HarvestReport) -> None:
    run_listing_walk(
        report=report,
        adapter_name=NAME,
        aggregator_host=AGG_HOST,
        seeds=SEED_URLS,
        industry="food",
        max_articles=50,
    )
