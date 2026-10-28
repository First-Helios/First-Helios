"""Several own-site menu pages per venue, against a real migrated database (ADR-0022).

The first page keeps ``<gers>`` while it verifies, further pages get
``<gers>|<path>`` keys up to MAX_MENU_PAGES, a near copy of a kept page is not
stored, each key is re-verified and withdrawn on its own, and a record from
before several-pages discovery (no current PAGES_VERSION) is re-discovered
once. The resolver is a fake, so there is no network.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING

import apps.discovery.url_pipeline as url_pipeline
from apps.discovery.url_pipeline import (
    MAX_MENU_PAGES,
    MENU_URL_NAMESPACE,
    PAGES_VERSION,
    UrlDiscoveryReport,
    resolve_urls,
)
from apps.discovery.web_client import CaptureFailure, MenuUrlDiscovery, PlatformAmbiguous
from test.test_url_pipeline import (
    _NOW,
    _poi,
    _record,
    _seed,
    _versions,
    isolate_existing_venues,  # noqa: F401 - autouse fixture: ignore other modules' venues
)

if TYPE_CHECKING:
    import pytest
    from sqlalchemy.orm import Session


def _html(dishes: str) -> str:
    return f"<html><body><h1>Menu</h1><p>{dishes}</p><p>Open daily</p></body></html>"


class _Pages:
    """A resolver whose discovery verifies ``pages`` (URL → HTML), in that order."""

    def __init__(self, pages: dict[str, str], *, verifier: str = "classifier-v2") -> None:
        self.pages = pages
        self.verifier = verifier
        self.failing: set[str] = set()  # URLs whose re-check fails with no_menu_found
        self.at = _NOW
        self.verified: list[str] = []
        self.discovered: list[str] = []

    def _found(self, url: str, website: str) -> MenuUrlDiscovery:
        return MenuUrlDiscovery(
            url, "crawled", self.at, f"sha256:{url}", website, page_html=self.pages.get(url)
        )

    def verify_menu_attempt(
        self, website: str, menu_url: str, *, not_before: datetime
    ) -> MenuUrlDiscovery | CaptureFailure:
        self.verified.append(menu_url)
        if menu_url in self.failing or menu_url not in self.pages:
            return CaptureFailure("failed", "no_menu_found", self.at)
        return self._found(menu_url, website)

    def discover_menu_attempt(
        self, website: str, *, address: str | None = None
    ) -> tuple[MenuUrlDiscovery | PlatformAmbiguous, ...] | CaptureFailure:
        self.discovered.append(website)
        found = tuple(self._found(url, website) for url in self.pages if url not in self.failing)
        return found or CaptureFailure("failed", "no_menu_found", self.at)


def _run(session: Session, resolver: _Pages, *, at: datetime) -> UrlDiscoveryReport:
    resolver.at = at
    resolver.verified.clear()
    resolver.discovered.clear()
    return resolve_urls(session, resolver=resolver, registry={}, decided_at=at, observed_at=at)


def _url(session: Session, key: str) -> object:
    return _versions(session, MENU_URL_NAMESPACE, key)[-1]["menu_url"]


def test_further_own_site_pages_get_path_keys_up_to_the_cap(session: Session) -> None:
    _seed(session, [_poi("Joes", 30.31, -97.70, gers_id="mp1", websites=("joes.com",))])
    pages = {
        "https://joes.com/lunch": _html("Enchiladas $11"),
        "https://joes.com/services3": _html("Migas $9"),
        "https://joes.com/blank": _html("Margarita $8"),
        "https://joes.com/kids": _html("Quesadilla $6"),
    }
    report = _run(session, _Pages(pages), at=_NOW)

    assert MAX_MENU_PAGES == 3  # noqa: PLR2004
    assert (report.menu_urls_found, report.menu_pages_over_cap) == (3, 1)
    assert _url(session, "mp1") == "https://joes.com/lunch"
    assert _url(session, "mp1|/services3") == "https://joes.com/services3"
    assert _url(session, "mp1|/blank") == "https://joes.com/blank"
    assert _record(session, MENU_URL_NAMESPACE, "mp1|/services3").state == "resolved"
    assert all(
        _versions(session, MENU_URL_NAMESPACE, key)[-1]["pages"] == PAGES_VERSION
        for key in ("mp1", "mp1|/services3", "mp1|/blank")
    )


def test_a_near_copy_of_a_kept_page_is_not_stored(session: Session) -> None:
    _seed(session, [_poi("Copies", 30.32, -97.70, gers_id="mp2", websites=("copies.com",))])
    same = _html("Brisket $18 Ribs $22")
    pages = {"https://copies.com/menu": same, "https://copies.com/menus": same}
    report = _run(session, _Pages(pages), at=_NOW)

    assert (report.menu_urls_found, report.menu_pages_duplicate) == (1, 1)
    assert _url(session, "mp2") == "https://copies.com/menu"


def test_a_venue_from_before_several_pages_keeps_its_first_page_key(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed(session, [_poi("Legacy", 30.33, -97.70, gers_id="mp3", websites=("legacy.com",))])
    blank = "https://legacy.com/blank"
    with monkeypatch.context() as patch:
        patch.setattr(url_pipeline, "PAGES_VERSION", "pages-v0")  # an older record
        _run(session, _Pages({blank: _html("Margarita $8")}), at=_NOW)

    pages = {
        "https://legacy.com/lunch": _html("Enchiladas $11"),
        blank: _html("Margarita $8"),
    }
    resolver = _Pages(pages)
    report = _run(session, resolver, at=_NOW + timedelta(days=1))

    assert resolver.verified == [blank], "the old page is re-checked whatever its window"
    assert resolver.discovered == ["https://legacy.com/"]
    assert report.menu_urls_found == 1
    assert _url(session, "mp3") == blank, "<gers> is sticky though /lunch now ranks first"
    assert _url(session, "mp3|/lunch") == "https://legacy.com/lunch"

    again = _run(session, resolver, at=_NOW + timedelta(days=2))
    assert (resolver.verified, resolver.discovered) == ([], []), "re-discovered once"
    assert again.menu_urls_reused == 1


def test_each_page_key_is_reverified_and_withdrawn_on_its_own(session: Session) -> None:
    _seed(session, [_poi("Split", 30.34, -97.70, gers_id="mp4", websites=("split.com",))])
    lunch, dinner = "https://split.com/lunch", "https://split.com/dinner"
    resolver = _Pages({lunch: _html("Tacos $3"), dinner: _html("Fajitas $15")})
    _run(session, resolver, at=_NOW)

    resolver.verifier = "classifier-v3"
    resolver.failing = {dinner}
    report = _run(session, resolver, at=_NOW + timedelta(days=1))

    assert sorted(resolver.verified) == [dinner, lunch]
    assert report.menu_urls_withdrawn == 1
    assert _record(session, MENU_URL_NAMESPACE, "mp4").state == "resolved"
    withdrawn = _record(session, MENU_URL_NAMESPACE, "mp4|/dinner")
    assert (withdrawn.state, withdrawn.subject_id) == ("needs_review", None)

    resolver.failing = set()
    resolver.verifier = "classifier-v4"  # the withdrawn key is due: discovery retries it
    report = _run(session, resolver, at=_NOW + timedelta(days=2))
    assert resolver.discovered == ["https://split.com/"]
    assert report.menu_urls_found == 1
    session.expire_all()  # ``withdrawn`` above holds the old CurrentResolution row
    assert _record(session, MENU_URL_NAMESPACE, "mp4|/dinner").state == "resolved", "reversible"


def test_a_rule_withdrawn_first_page_is_retried_once_for_several_pages(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed(session, [_poi("Elsewhere", 30.35, -97.70, gers_id="mp5", websites=("else.com",))])
    menu = "https://else.com/menu"
    resolver = _Pages({menu: _html("Lo mein $9")})
    with monkeypatch.context() as patch:
        patch.setattr(url_pipeline, "PAGES_VERSION", "pages-v0")  # an older record
        _run(session, resolver, at=_NOW)
        resolver.verifier, resolver.failing = "classifier-v3", {menu}
        _run(session, resolver, at=_NOW + timedelta(days=1))
    assert _record(session, MENU_URL_NAMESPACE, "mp5").state == "needs_review"

    report = _run(session, resolver, at=_NOW + timedelta(days=2))
    assert resolver.discovered == ["https://else.com/"], "retried once, inside its window"
    assert report.needs_review == 0
    assert _record(session, MENU_URL_NAMESPACE, "mp5").state == "needs_review"
    assert _versions(session, MENU_URL_NAMESPACE, "mp5")[-1]["pages"] == PAGES_VERSION

    later = _run(session, resolver, at=_NOW + timedelta(days=3))
    assert resolver.discovered == []
    assert later.needs_review == 1
