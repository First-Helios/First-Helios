"""Seed a DISPOSABLE *_test database through the real discovery code, to exercise
export_candidates.sql on realistic Bronze/Identity rows. Never point at app data.

    DATABASE_URL=postgresql+psycopg://.../spike_test uv run python -m spikes.menu_model.sql.seed_check
    psql ... -q --csv -f spikes/menu_model/sql/export_candidates.sql
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from apps.discovery.overture import OverturePoi
from apps.discovery.pipeline import run_discovery
from apps.discovery.url_pipeline import resolve_urls
from apps.discovery.web_client import MenuUrlDiscovery

CATEGORIES = ["mexican_restaurant", "coffee_shop", "pizza_restaurant", "bar", "restaurant"]


def _pois() -> list[OverturePoi]:
    pois = []
    for i in range(40):
        category = CATEGORIES[i % len(CATEGORIES)]
        if i < 5:
            websites: tuple[str, ...] = ("https://www.chain.example/",)  # one host, 5 venues
        elif i < 8:
            websites = (f"https://www.toasttab.com/venue-{i}",)
        elif i == 8:
            websites = ()
        else:
            websites = (f"https://venue{i}.example/",)
        gers_id, name = f"gers-{i:03d}", f"Venue {i}"
        alternates = ("restaurant", "food") if i % 2 else ()
        longitude, latitude = -97.7 + i * 0.01, 30.2 + i * 0.01  # ~1 km apart: no dedupe
        raw: dict[str, Any] = {
            "id": gers_id,
            "name": name,
            "primary_category": category,
            "alternate_categories": list(alternates) or None,
            "websites": list(websites) or None,
            "addresses": None,
            "longitude": longitude,
            "latitude": latitude,
            "confidence": 0.9,
        }
        pois.append(
            OverturePoi(
                gers_id=gers_id,
                name=name,
                primary_category=category,
                alternate_categories=alternates,
                websites=websites,
                address=None,
                latitude=latitude,
                longitude=longitude,
                confidence=0.9,
                raw=raw,
            )
        )
    return pois


class _FakeResolver:
    def discover_menu_url(self, website: str) -> MenuUrlDiscovery | None:
        if website.endswith(("1.example/", "3.example/")):
            return MenuUrlDiscovery(menu_url=website + "menu", signal="well_known")
        return None


def main() -> None:
    url = os.environ["DATABASE_URL"]
    if not url.rsplit("/", 1)[-1].endswith("_test"):
        raise SystemExit("refusing: DATABASE_URL must name a *_test database")
    now = datetime.now(tz=UTC)
    with Session(create_engine(url)) as session:
        print(run_discovery(session, _pois(), decided_at=now, observed_at=now, release="spike"))
        if os.environ.get("SEED_SKIP_URLS") != "1":  # the Pi today: resolve_urls not yet run
            print(
                resolve_urls(
                    session, resolver=_FakeResolver(), registry={}, decided_at=now, observed_at=now
                )
            )
        session.commit()


if __name__ == "__main__":
    main()
