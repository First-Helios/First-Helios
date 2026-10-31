"""The collection-coverage harness on synthetic websites (session P8-21; no network).

Each site is a whole website served from memory, with a hand-written fixture: its menu
pages, each page's states and sample items. ``collect_site`` replays a first collection
(discovery, the several-pages cap and duplicate rule) and ``coverage_site`` scores it. The
assertions record today's coverage per kind: what is collected, and what is not (a PDF menu,
a script-loaded tab, another location's menu), measured apart from extraction.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import httpx
import pytest

from apps.discovery.web_client import SiteFetcher
from apps.menu_pipeline.coverage_eval import (
    Captured,
    collect_site,
    coverage_metrics,
    coverage_site,
    page_key,
    site_fixture,
)

if TYPE_CHECKING:
    from collections import Counter
    from pathlib import Path

_HTML = "text/html"


def _menu(title: str, items: list[tuple[str, str]], extra: str = "") -> str:
    rows = "".join(
        f'<li><span class="name">{n}</span> <span class="price">${p}</span></li>' for n, p in items
    )
    return f"<html><head><title>{title}</title></head><body><h1>{title}</h1><ul>{rows}</ul>{extra}</body></html>"


def _home(links: list[tuple[str, str]], body: str = "") -> str:
    nav = "".join(f'<a href="{h}">{t}</a>' for h, t in links)
    return f"<html><head><title>Home</title></head><body><nav>{nav}</nav><h1>Welcome</h1><p>Fresh food daily.</p>{body}</body></html>"


LUNCH = [("Club Sandwich", "11.50"), ("Cobb Salad", "12.00"), ("Tomato Soup", "6.50")]
DINNER = [("Ribeye Steak", "34.00"), ("Roast Chicken", "24.00"), ("Grilled Salmon", "28.00")]
DRINKS = [("House Margarita", "9.00"), ("Iced Tea", "3.00"), ("Lemonade", "3.50")]

# site -> (fixture, routes {absolute URL: (status, body, content type)})
SITES: dict[str, tuple[dict, dict[str, tuple[int, str, str]]]] = {  # type: ignore[type-arg]
    "separate": (
        {
            "site": "separate.example",
            "origin": "synthetic",
            "website": "https://separate.example/",
            "kinds": ["separate_pages"],
            "menu_pages": [
                {
                    "url": "https://separate.example/lunch",
                    "states": [
                        {"state": "static", "sample_items": ["Club Sandwich", "Cobb Salad"]}
                    ],
                },
                {
                    "url": "https://separate.example/dinner",
                    "states": [{"state": "static", "sample_items": ["Ribeye Steak"]}],
                },
                {
                    "url": "https://separate.example/drinks",
                    "states": [{"state": "static", "sample_items": ["House Margarita"]}],
                },
            ],
        },
        {
            "https://separate.example/": (
                200,
                _home([("/lunch", "Lunch"), ("/dinner", "Dinner"), ("/drinks", "Drinks")]),
                _HTML,
            ),
            "https://separate.example/lunch": (200, _menu("Lunch Menu", LUNCH), _HTML),
            "https://separate.example/dinner": (200, _menu("Dinner Menu", DINNER), _HTML),
            "https://separate.example/drinks": (200, _menu("Drinks Menu", DRINKS), _HTML),
        },
    ),
    "tabs": (
        {
            "site": "tabs.example",
            "origin": "synthetic",
            "website": "https://tabs.example/",
            "kinds": ["tabs"],
            "menu_pages": [
                {
                    "url": "https://tabs.example/menu",
                    "states": [
                        {"state": "tab:Lunch", "sample_items": ["Club Sandwich", "Cobb Salad"]},
                        {"state": "tab:Dinner", "sample_items": ["Ribeye Steak", "Roast Chicken"]},
                    ],
                }
            ],
        },
        {
            "https://tabs.example/": (200, _home([("/menu", "Menu")]), _HTML),
            "https://tabs.example/menu": (
                200,
                _menu(
                    "Menu",
                    LUNCH,
                    '<button role="tab" aria-controls="d">Dinner</button>'
                    '<div id="d" role="tabpanel" hidden><ul>'
                    + "".join(f"<li>{n} ${p}</li>" for n, p in DINNER)
                    + "</ul></div>",
                ),
                _HTML,
            ),
        },
    ),
    "tabs_script": (
        {
            "site": "tabscript.example",
            "origin": "synthetic",
            "website": "https://tabscript.example/",
            "kinds": ["tabs", "script"],
            "menu_pages": [
                {
                    "url": "https://tabscript.example/menu",
                    "states": [
                        {"state": "tab:Lunch", "sample_items": ["Club Sandwich", "Cobb Salad"]},
                        {"state": "script", "sample_items": ["Ribeye Steak", "Roast Chicken"]},
                    ],
                }
            ],
        },
        {
            "https://tabscript.example/": (200, _home([("/menu", "Menu")]), _HTML),
            "https://tabscript.example/menu": (
                200,
                _menu(
                    "Menu",
                    LUNCH,
                    '<button role="tab" data-src="/api/dinner.json">Dinner</button><script>/* loads the tab */</script>',
                ),
                _HTML,
            ),
        },
    ),
    "accordion": (
        {
            "site": "accordion.example",
            "origin": "synthetic",
            "website": "https://accordion.example/",
            "kinds": ["accordion"],
            "menu_pages": [
                {
                    "url": "https://accordion.example/menu",
                    "states": [
                        {"state": "accordion", "sample_items": ["Grilled Salmon", "Iced Tea"]}
                    ],
                }
            ],
        },
        {
            "https://accordion.example/": (200, _home([("/menu", "Our Menu")]), _HTML),
            "https://accordion.example/menu": (
                200,
                "<html><head><title>Menu</title></head><body><h1>Menu</h1>"
                + "".join(
                    f"<details><summary>{sec}</summary><ul>{''.join(f'<li>{n} ${p}</li>' for n, p in items)}</ul></details>"
                    for sec, items in (("Mains", DINNER), ("Drinks", DRINKS))
                )
                + "</body></html>",
                _HTML,
            ),
        },
    ),
    "table": (
        {
            "site": "table.example",
            "origin": "synthetic",
            "website": "https://table.example/",
            "kinds": ["table"],
            "menu_pages": [
                {
                    "url": "https://table.example/menu",
                    "states": [{"state": "static", "sample_items": ["Cobb Salad", "Tomato Soup"]}],
                }
            ],
        },
        {
            "https://table.example/": (200, _home([("/menu", "Menu")]), _HTML),
            "https://table.example/menu": (
                200,
                "<html><head><title>Menu</title></head><body><h1>Menu</h1><table>"
                + "".join(f"<tr><td>{n}</td><td>${p}</td></tr>" for n, p in LUNCH)
                + "</table></body></html>",
                _HTML,
            ),
        },
    ),
    "shared_price": (
        {
            "site": "shared.example",
            "origin": "synthetic",
            "website": "https://shared.example/",
            "kinds": ["shared_section_price", "options"],
            "menu_pages": [
                {
                    "url": "https://shared.example/menu",
                    "states": [
                        {"state": "static", "sample_items": ["Al Pastor", "Carnitas", "Nachos"]}
                    ],
                }
            ],
        },
        {
            "https://shared.example/": (200, _home([("/menu", "Menu")]), _HTML),
            "https://shared.example/menu": (
                200,
                "<html><head><title>Menu</title></head><body><h1>Menu</h1><h2>Street Tacos $3.75 each</h2>"
                "<ul><li>Al Pastor</li><li>Carnitas</li><li>Barbacoa</li></ul>"
                "<h3>Nachos</h3><p>Chicken / Bistec / Pastor $14.99</p><p>Shrimp / Combo $16.99</p></body></html>",
                _HTML,
            ),
        },
    ),
    "pdf": (
        {
            "site": "pdf.example",
            "origin": "synthetic",
            "website": "https://pdf.example/",
            "kinds": ["pdf"],
            "menu_pages": [
                {
                    "url": "https://pdf.example/files/menu.pdf",
                    "states": [{"state": "pdf", "sample_items": ["Ribeye Steak"]}],
                }
            ],
        },
        {
            "https://pdf.example/": (200, _home([("/files/menu.pdf", "Menu (PDF)")]), _HTML),
            "https://pdf.example/files/menu.pdf": (200, "%PDF-1.4", "application/pdf"),
        },
    ),
    "multi_location": (
        {
            "site": "group.example",
            "origin": "synthetic",
            "website": "https://group.example/",
            "kinds": ["multi_location"],
            "menu_pages": [
                {
                    "url": "https://group.example/austin/menu",
                    "location": "Austin",
                    "states": [{"state": "static", "sample_items": ["Club Sandwich"]}],
                }
            ],
            "other_location_pages": ["https://group.example/dallas/menu"],
        },
        {
            "https://group.example/": (
                200,
                _home([("/dallas/menu", "Dallas Menu"), ("/austin/menu", "Austin Menu")]),
                _HTML,
            ),
            "https://group.example/austin/menu": (200, _menu("Austin Menu", LUNCH), _HTML),
            "https://group.example/dallas/menu": (200, _menu("Dallas Menu", DINNER), _HTML),
        },
    ),
    "homepage_menu": (
        {
            "site": "onepage.example",
            "origin": "synthetic",
            "website": "https://onepage.example/",
            "kinds": ["homepage_menu"],
            "menu_pages": [
                {
                    "url": "https://onepage.example/",
                    "states": [
                        {"state": "static", "sample_items": ["Ribeye Steak", "Grilled Salmon"]}
                    ],
                }
            ],
        },
        {
            "https://onepage.example/": (
                200,
                _home([("#about", "About")], _menu("Our Food", DINNER)),
                _HTML,
            )
        },
    ),
    "no_menu": (
        {
            "site": "comedy.example",
            "origin": "synthetic",
            "website": "https://comedy.example/",
            "kinds": ["no_menu"],
            "menu_pages": [],
        },
        {
            "https://comedy.example/": (
                200,
                _home([("/shows", "Shows"), ("/tickets", "Tickets")]),
                _HTML,
            ),
            "https://comedy.example/shows": (
                200,
                "<html><head><title>Shows</title></head><body><h1>Shows</h1><p>Friday 8pm</p></body></html>",
                _HTML,
            ),
        },
    ),
}


class _Clock:
    def __init__(self) -> None:
        self.mono = 100.0

    def time(self) -> float:
        return 1_800_000_000.0

    def monotonic(self) -> float:
        return self.mono

    def sleep(self, seconds: float) -> None:
        self.mono += seconds


def _collect(tmp_path: Path, name: str) -> tuple[Counter[str], list[Captured]]:
    fixture_obj, routes = SITES[name]
    fixture = site_fixture(fixture_obj)
    calls: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        status, body, ctype = routes.get(str(request.url), (404, "nope", _HTML))
        return httpx.Response(status, text=body, headers={"content-type": ctype})

    clock = _Clock()
    with SiteFetcher(
        cache_dir=tmp_path,
        user_agent="helios-test/1.0",
        min_interval_s=0.0,
        client=httpx.Client(transport=httpx.MockTransport(handle)),
        resolve=lambda _host: ["93.184.216.34"],
        clock=clock.time,
        monotonic=clock.monotonic,
        sleep=clock.sleep,
    ) as fetcher:
        captured, cost = collect_site(fetcher, fixture, lambda: len(calls))
    return coverage_site(fixture, captured, cost), captured


# (site, pages found, states covered, captured, other-location pages captured)
BASELINE = [
    ("separate", 3, 3, 3, 0),  # lunch, dinner and drinks ("Drinks" a candidate term, ADR-0024 Q6)
    ("tabs", 1, 2, 1, 0),  # a hidden tab panel is in the HTML, so it is collected
    ("tabs_script", 1, 1, 1, 0),  # the script-loaded tab is not
    ("accordion", 1, 1, 1, 0),
    ("table", 1, 1, 1, 0),
    ("shared_price", 1, 1, 1, 0),
    ("pdf", 0, 0, 0, 0),  # a PDF menu is linked, never read (ADR-0013 Amendment 3)
    ("multi_location", 1, 1, 2, 1),  # both locations' menus are collected
    ("homepage_menu", 0, 0, 0, 0),  # a menu printed on the homepage is not a candidate
    ("no_menu", 0, 0, 0, 0),
]


@pytest.mark.parametrize(("name", "found", "covered", "captured", "other"), BASELINE)
def test_synthetic_coverage_baseline(
    tmp_path: Path, name: str, found: int, covered: int, captured: int, other: int
) -> None:
    c, _ = _collect(tmp_path, name)
    assert (c["pages_found"], c["states_covered"], c["captured"], c["captured_other_location"]) == (
        found,
        covered,
        captured,
        other,
    )
    assert c["cost:requests"] > 0


def test_pdf_is_counted_as_linked(tmp_path: Path) -> None:
    c, _ = _collect(tmp_path, "pdf")
    assert c["cost:pdf_linked"] == 1


def test_metrics_and_page_identity() -> None:
    assert page_key("https://www.A.example/menu/#top") == page_key("http://a.example/menu")
    fixture = site_fixture(SITES["separate"][0])
    html = _menu("Lunch Menu", LUNCH)
    c = coverage_site(fixture, [Captured("https://separate.example/lunch/", html)])
    m = coverage_metrics(c)
    assert m["venue_coverage"] == 1.0 and m["complete_coverage"] == 0.0
    assert m["page_recall"] == pytest.approx(1 / 3) and m["page_precision"] == 1.0
    assert m["state_coverage:static"] == pytest.approx(1 / 3)
    none = coverage_site(site_fixture(SITES["no_menu"][0]), [])
    assert coverage_metrics(none)["no_menu_clean"] == 1.0
