"""
Broader-industry scanner.

Samples category pages from generalist deal aggregators (DealNews, Slickdeals,
RetailMeNot) to observe what *non-food* deal categories the competitive
landscape covers. Produces IndustrySample records tagged with our taxonomy
(industry_taxonomy.py) so product can decide which categories become map
features versus deal-framework features.

This adapter does NOT write hint or expectation proposals — those require a
brand match and we are not attempting brand extraction on non-food pages in
this first pass. The artifact here is strictly landscape intelligence.
"""

from __future__ import annotations

import logging
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from collectors.hintbook.fetcher import fetch
from collectors.hintbook.industry_taxonomy import INDUSTRIES
from collectors.hintbook.models import HarvestReport, IndustrySample
from collectors.hintbook.parsing import text_of

logger = logging.getLogger(__name__)

NAME = "broader_industries"
HOMEPAGE = "https://www.dealnews.com/"
SEED_URLS: list[str] = []  # composed below

# (aggregator, category_url, industry_key)
_SCANS: list[tuple[str, str, str]] = [
    # DealNews — deep category tree
    ("dealnews", "https://www.dealnews.com/c39/Automotive/", "automotive_retail"),
    ("dealnews", "https://www.dealnews.com/c142/Travel/Flights/", "travel_air"),
    ("dealnews", "https://www.dealnews.com/c245/Travel/Hotels/", "travel_hotel"),
    ("dealnews", "https://www.dealnews.com/c244/Travel/Rental-Cars/", "travel_rental"),
    ("dealnews", "https://www.dealnews.com/c143/Travel/Packages/", "travel_cruise_package"),
    ("dealnews", "https://www.dealnews.com/c45/Clothing-Accessories/", "retail_apparel"),
    ("dealnews", "https://www.dealnews.com/c40/Computers/", "retail_electronics"),
    ("dealnews", "https://www.dealnews.com/c197/Home-Garden/", "retail_home"),
    ("dealnews", "https://www.dealnews.com/c388/Health-Beauty/", "pharmacy_health"),
    ("dealnews", "https://www.dealnews.com/c245/Sports-Fitness/", "fitness_gym"),

    # Slickdeals — category listings
    ("slickdeals", "https://slickdeals.net/deals/automotive/", "automotive_retail"),
    ("slickdeals", "https://slickdeals.net/deals/travel/", "travel_air"),
    ("slickdeals", "https://slickdeals.net/deals/health-beauty/", "pharmacy_health"),
    ("slickdeals", "https://slickdeals.net/deals/sports-fitness/", "fitness_gym"),
    ("slickdeals", "https://slickdeals.net/deals/pets/", "pet_services"),

    # RetailMeNot — more coupon-code-centric
    ("retailmenot", "https://www.retailmenot.com/coupons/autoparts", "automotive_retail"),
    ("retailmenot", "https://www.retailmenot.com/coupons/travel", "travel_air"),
    ("retailmenot", "https://www.retailmenot.com/coupons/hotels", "travel_hotel"),
    ("retailmenot", "https://www.retailmenot.com/coupons/carrental", "travel_rental"),
    ("retailmenot", "https://www.retailmenot.com/coupons/beauty", "pharmacy_health"),
    ("retailmenot", "https://www.retailmenot.com/coupons/apparel", "retail_apparel"),
    ("retailmenot", "https://www.retailmenot.com/coupons/electronics", "retail_electronics"),
    ("retailmenot", "https://www.retailmenot.com/coupons/pets", "pet_services"),

    # Specific service-category coverage that maps well
    ("retailmenot", "https://www.retailmenot.com/view/valvoline.com", "automotive_service"),
    ("retailmenot", "https://www.retailmenot.com/view/jiffylube.com", "automotive_service"),
    ("retailmenot", "https://www.retailmenot.com/view/firestonecompleteautocare.com", "automotive_service"),
    ("retailmenot", "https://www.retailmenot.com/view/midas.com", "automotive_service"),
]


def _count_deal_cards(soup: BeautifulSoup) -> int:
    # Heuristic: count article-ish or card-ish nodes
    cards = soup.find_all(["article"])
    if len(cards) >= 3:
        return len(cards)
    # Fallback: elements whose class mentions "deal" or "offer" or "coupon"
    count = 0
    for tag in soup.find_all(True):
        cls = " ".join(tag.get("class", [])).lower()
        if any(tok in cls for tok in ("deal-card", "offer-card", "coupon-card", "deal-item", "coupon")):
            count += 1
    return count


def _sample_headlines(soup: BeautifulSoup, limit: int = 10) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for h in soup.find_all(["h2", "h3", "h4"]):
        t = text_of(h)
        if 5 < len(t) < 180 and t not in seen:
            seen.add(t)
            out.append(t)
        if len(out) >= limit:
            break
    return out


def collect(report: HarvestReport) -> None:
    report.adapters_run.append(NAME)
    for aggregator, url, industry_key in _SCANS:
        html, status, err = fetch(url, ttl_hours=48)
        if html is None:
            report.adapters_failed.append({
                "adapter": NAME, "url": url, "status": status, "error": err,
            })
            continue
        soup = BeautifulSoup(html, "html.parser")
        headlines = _sample_headlines(soup)
        count = _count_deal_cards(soup)
        industry_def = INDUSTRIES.get(industry_key)
        map_viable = industry_def.map_viable if industry_def else False
        sample = IndustrySample(
            aggregator=aggregator,
            industry=industry_key,
            sample_url=url,
            observed_count=count,
            sample_headlines=tuple(headlines),
            map_viable=map_viable,
            notes=industry_def.notes if industry_def else None,
        )
        report.industry_samples.append(sample)
