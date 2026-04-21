"""FoodDealNow — happy-hour + chain specials."""

from collectors.hintbook.listing_walker import run_listing_walk
from collectors.hintbook.models import HarvestReport

NAME = "fooddealnow"
HOMEPAGE = "https://fooddealnow.com/"
SEED_URLS = [
    "https://fooddealnow.com/",
    "https://fooddealnow.com/best-restaurant-happy-hours/",
    "https://fooddealnow.com/category/happy-hour/",
    "https://fooddealnow.com/category/daily-specials/",
]
AGG_HOST = "fooddealnow.com"


def collect(report: HarvestReport) -> None:
    run_listing_walk(
        report=report,
        adapter_name=NAME,
        aggregator_host=AGG_HOST,
        seeds=SEED_URLS,
        industry="food",
        max_articles=30,
    )
