"""R4: rejected and withdrawn pages leave the queue and their Menu rows are withdrawn
(ADR-0013 Amendment 24 item 5, Amendment 27; session P5-33).

Synthetic venues end to end against a migrated ``*_test`` database, as in
``test_menu_extraction``: a scripted ``llama-server``, the HTML word verifier at
fetch time, and a fixed-probability scorer that rejects pages carrying a word
(the re-score). No network and no model.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from apps.discovery.url_pipeline import resolve_urls
from apps.discovery.web_client import CaptureFailure, MenuUrlDiscovery
from apps.menu_pipeline import menu_writes
from apps.menu_pipeline.bundle import BundleStore
from apps.menu_pipeline.page_bronze import (
    MENU_PAGE_NAMESPACE,
    REFETCH_WINDOW,
    MenuPageReport,
    run_menu_pages,
)
from apps.menu_pipeline.rescore import RescoreReport, rescore_pages
from packages.helios_core.config import get_database_url
from packages.helios_core.domains.menu.enumeration import enumerate_current_requests
from packages.helios_core.domains.menu.models import MenuItem, MenuPage
from packages.helios_core.domains.menu.selection import SelectionRequest, select_price
from packages.helios_core.provenance.models import Source, SourceRecord
from test.test_menu_extraction import _JSONLD, _MENU, _REPO_ROOT, _T1, _Scorer, _Server, _Venues
from test.test_menu_page_bronze import _SHELL, _page, _Pages, _Renderer, _WordVerifier

if TYPE_CHECKING:
    from datetime import datetime as Datetime
    from pathlib import Path

    from sqlalchemy.engine import Engine


@pytest.fixture
def venues(
    disposable_database_engine: Engine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> _Venues:
    subprocess.run(
        ["alembic", "-c", str(_REPO_ROOT / "alembic.ini"), "upgrade", "head"],
        check=True,
        cwd=_REPO_ROOT,
        env={**os.environ, "DATABASE_URL": get_database_url()},
    )
    factory = sessionmaker(bind=disposable_database_engine, expire_on_commit=False)
    return _Venues(factory, tmp_path, monkeypatch)


_LATER = _T1 + REFETCH_WINDOW + timedelta(minutes=1)
_LATEST = _LATER + REFETCH_WINDOW + timedelta(minutes=1)
_NOT_MENU = "<html><body><h1>Gift cards</h1><p>Buy one for a friend.</p></body></html>"


def _fetch(
    venues: _Venues,
    html: dict[str, str | None],
    *,
    at: Datetime,
    renderer: _Renderer | None = None,
) -> MenuPageReport:
    """One menu-page run; ``None`` answers 404 (a failed fetch, no verdict on the page)."""
    pages = _Pages(
        {venues.menus[g]: _page(venues.menus[g], h, at=at) for g, h in html.items() if h}
    )
    with venues.factory() as session:
        report = run_menu_pages(
            session,
            fetcher=pages,
            verifier=_WordVerifier(),
            bundles=BundleStore(venues.tmp_path),
            renderer=renderer,
            now=at,
            on_page=session.commit,
        )
        session.commit()
    return report


def _rescore(venues: _Venues, scorer: _Scorer) -> RescoreReport:
    with venues.factory() as session:
        report = rescore_pages(
            session,
            scorer=scorer,
            bundles=BundleStore(venues.tmp_path),
            model="test-model@0123456789ab",
            commit=session.commit,
        )
        session.commit()
    return report


def _requests(venues: _Venues, gers: str) -> list[SelectionRequest]:
    with venues.factory() as session:
        record = session.scalar(
            select(SourceRecord.id)
            .join(Source, Source.id == SourceRecord.source_id)
            .where(Source.namespace == MENU_PAGE_NAMESPACE, SourceRecord.external_key == gers)
        )
        return [
            r
            for r in enumerate_current_requests(session, effective_instant=datetime.now(UTC))
            if r.source_record_id == record
        ]


def _price_states(venues: _Venues, requests: list[SelectionRequest]) -> set[str]:
    with venues.factory() as session:
        now = datetime.now(UTC)
        return {
            select_price(session, replace(r, effective_instant=now)).local_price.state
            for r in requests
        }


def _stream(venues: _Venues, gers: str, kind: str) -> list[MenuPage]:
    return [p for p in venues.pages(gers) if p.source_kind == kind]


def test_a_rejected_fetch_withdraws_both_streams_and_an_accepted_one_restores_them(
    venues: _Venues,
) -> None:
    gers = venues.add("Taco Deli")
    venues.resolve()
    menu = _MENU.replace("<body>", "<body>" + _JSONLD)
    venues.fetch({gers: menu}, at=_T1)
    server = _Server()
    first = venues.extract(server)
    assert first.extracted == 1 and first.jsonld_pages == 1
    before = _requests(venues, gers)
    assert before and _price_states(venues, before) == {"priced"}

    # the page now fails the classifier at fetch time: a skipped not_menu Capture
    assert _fetch(venues, {gers: _NOT_MENU}, at=_LATER).outcomes == {"not_menu": 1}
    report = venues.extract(server)

    assert (report.due, report.extracted, report.fetch_rejected) == (0, 0, 1)
    assert report.withdrawals.summary() == {
        "records": {"fetch_rejected": 1},
        "pages": {"jsonld": 1, "llm": 1},
        "not_eligible": 0,
    }
    for kind in ("llm", "jsonld"):
        head = _stream(venues, gers, kind)[-1]
        assert (head.operation, head.state, head.stream_revision) == ("withdrawal", "withdrawn", 2)
        assert head.supersedes_page_id == _stream(venues, gers, kind)[0].id
        assert head.method_version.endswith(";word-v1")
    with venues.factory() as session:
        head = _stream(venues, gers, "llm")[-1]
        assert (
            session.scalar(
                select(func.count()).select_from(MenuItem).where(MenuItem.page_id == head.id)
            )
            == 0
        )  # a tombstone has no graph: nothing is deleted, nothing is current
    assert _requests(venues, gers) == []
    assert _price_states(venues, before) == {"withdrawn"}  # Gold reads the tombstone

    # idempotent: nothing more to withdraw; a failed fetch says nothing about the page
    assert _fetch(venues, {gers: None}, at=_LATEST).outcomes == {"http_404": 1}
    again = venues.extract(server)
    assert (again.due, again.fetch_rejected, again.withdrawals.records) == (0, 1, {})
    assert len(venues.pages(gers)) == 4  # noqa: PLR2004 - two streams, two pages each

    # accepted again, same text (no new Version): both streams are restored
    restored_at = _LATEST + REFETCH_WINDOW + timedelta(minutes=1)
    assert _fetch(venues, {gers: menu}, at=restored_at).unchanged == 1
    restore = venues.extract(server)
    assert restore.due_by_reason == {"restore": 1} and restore.extracted == 1
    assert len(server.bodies) == 1  # re-validated from the saved answer
    for kind in ("llm", "jsonld"):
        first_page, withdrawal, restoration = _stream(venues, gers, kind)
        assert (restoration.operation, restoration.state) == ("restoration", "published")
        assert restoration.supersedes_page_id == withdrawal.id
        assert restoration.source_record_version_id == first_page.source_record_version_id
    assert _price_states(venues, _requests(venues, gers)) == {"priced"}


class _Resolver:
    """A menu-URL resolver whose verifier is renamed and whose verdicts are scripted."""

    def __init__(self, menus: dict[str, str], verifier: str) -> None:
        self.menus = menus  # website -> menu URL that verifies; others fail no_menu_found
        self.verifier = verifier
        self.at = _T1

    def _found(self, website: str) -> MenuUrlDiscovery | CaptureFailure:
        url = self.menus.get(website.rstrip("/"))
        if url is None:
            return CaptureFailure("failed", "no_menu_found", self.at)
        return MenuUrlDiscovery(url, "crawled", self.at, "sha256:page", website)

    def verify_menu_attempt(
        self, website: str, menu_url: str, *, not_before: Datetime
    ) -> MenuUrlDiscovery | CaptureFailure:
        del menu_url, not_before
        return self._found(website)

    def discover_menu_attempt(
        self, website: str, *, address: str | None = None
    ) -> tuple[MenuUrlDiscovery, ...] | CaptureFailure:
        del address
        found = self._found(website)
        return found if isinstance(found, CaptureFailure) else (found,)


def _reverify(venues: _Venues, resolver: _Resolver, *, at: Datetime) -> None:
    """A discovery run (over this test's venues only, as ``_Venues`` patches)."""
    resolver.at = at
    with venues.factory.begin() as session:
        resolve_urls(session, resolver=resolver, registry={}, decided_at=at, observed_at=at)


def test_a_withdrawn_menu_url_withdraws_the_page_until_a_url_verifies_again(
    venues: _Venues,
) -> None:
    gers, kept = venues.add("Kerbey Lane"), venues.add("Juan in a Million")
    venues.resolve()
    venues.fetch({gers: _MENU, kept: _MENU}, at=_T1)
    server = _Server()
    venues.extract(server)
    site = venues.menus[gers].removesuffix("/menu")
    kept_site = venues.menus[kept].removesuffix("/menu")

    # the renamed verifier re-checks every saved URL (ADR-0015); one no longer verifies
    _reverify(venues, _Resolver({kept_site: venues.menus[kept]}, "word-v2"), at=_LATER)
    report = venues.extract(server)

    assert report.withdrawals.records == {"menu_url_withdrawn": 1}
    assert report.menu_url_withdrawn == 1 and report.due == 0
    assert [p.operation for p in venues.pages(gers)] == ["initial", "withdrawal"]
    assert [p.operation for p in venues.pages(kept)] == ["initial"]

    # discovery verifies the URL again and the page has changed: a restoration on it
    _reverify(venues, _Resolver({site: venues.menus[gers]}, "word-v3"), at=_LATEST)
    changed = _MENU.replace("</body>", "<p>Elote</p><p>$4.25</p></body>")
    assert _fetch(venues, {gers: changed}, at=_LATEST).versions_changed == 1
    restore = venues.extract(server)
    assert restore.due_by_reason == {"changed": 1}
    initial, withdrawal, restoration = venues.pages(gers)
    assert (restoration.operation, restoration.supersedes_page_id) == ("restoration", withdrawal.id)
    assert restoration.source_record_version_id != initial.source_record_version_id


def test_a_verifier_bump_rescores_every_stored_page_and_withdraws_the_rejected(
    venues: _Venues,
) -> None:
    good, bad = venues.add("Veracruz"), venues.add("Gift Shop")
    venues.resolve()
    shop = _MENU.replace("<h1>Menu</h1>", "<h1>Menu</h1><button>Add to cart</button>")
    venues.fetch({good: _MENU, bad: shop}, at=_T1)
    server = _Server()
    venues.extract(server)
    bumped = _Scorer(name="word-v2", reject="Add to cart")

    report = _rescore(venues, bumped)

    assert (report.due, report.scored, report.accepted, report.rejected) == (2, 2, 1, 1)
    assert report.rejected_keys == [bad] and report.rejected_unwritten == 0
    assert report.withdrawals.records == {"rescored": 1}
    assert report.method_version.endswith(";word-v2")
    withdrawal = venues.pages(bad)[-1]
    assert (withdrawal.operation, withdrawal.method_version) == (
        "withdrawal",
        report.method_version,
    )
    assert [p.operation for p in venues.pages(good)] == ["initial"]  # left for extraction

    again = _rescore(venues, bumped)
    assert (again.due, again.rejected, again.not_due["withdrawn"]) == (1, 0, 1)
    extracted = venues.extract(server, scorer=bumped)
    assert extracted.due_by_reason == {"reinterpret": 1} and extracted.rejected == 0
    assert [p.operation for p in venues.pages(good)] == ["initial", "correction"]
    assert len(venues.pages(bad)) == 2  # noqa: PLR2004 - initial, withdrawal


def test_extraction_rescores_due_pages_itself_and_an_unextracted_reject_stays_due(
    venues: _Venues,
) -> None:
    extracted, fresh = venues.add("Hopdoddy"), venues.add("Brochure Site")
    venues.resolve()
    brochure = _MENU.replace("<h1>Menu</h1>", "<h1>Menu</h1><p>Book the venue</p>")
    venues.fetch({extracted: brochure, fresh: brochure}, at=_T1)
    server = _Server()
    assert venues.extract(server, limit=1).extracted == 1  # the first key: `extracted`
    sent = len(server.bodies)
    bumped = _Scorer(name="word-v2", reject="Book the venue")

    report = venues.extract(server, scorer=bumped)

    assert report.due_by_reason == {"new": 1, "reinterpret": 1}
    assert (report.rejected, report.rejected_unwritten, report.extracted) == (2, 1, 0)
    assert report.withdrawals.records == {"rescored": 1}
    assert len(server.bodies) == sent  # no model call for a rejected page
    assert [p.operation for p in venues.pages(extracted)] == ["initial", "withdrawal"]
    assert venues.pages(fresh) == []  # nothing to withdraw: never extracted
    with venues.factory() as session:
        due, _ = menu_writes.due_pages(session, report.method_version)
    assert [p.key for p in due] == [fresh]  # skipped again by the next run


def test_the_render_verdict_after_a_js_only_fetch_is_the_one_read(venues: _Venues) -> None:
    """§4: a static ``js_only`` skip followed by a render; the render is the later Capture."""
    gers = venues.add("Uchi")
    venues.resolve()
    venues.fetch({gers: _MENU}, at=_T1)
    server = _Server()
    venues.extract(server)
    url = venues.menus[gers]
    shell_render = _Renderer(_page(url, _NOT_MENU, at=_LATER + timedelta(seconds=5)))

    rejected = _fetch(venues, {gers: _SHELL}, at=_LATER, renderer=shell_render)
    assert rejected.outcomes == {"js_only": 1, "not_menu": 1}
    report = venues.extract(server)
    assert report.withdrawals.records == {"fetch_rejected": 1}

    menu_render = _Renderer(_page(url, _MENU, at=_LATEST + timedelta(seconds=5)))
    accepted = _fetch(venues, {gers: _SHELL}, at=_LATEST, renderer=menu_render)
    assert accepted.outcomes == {"js_only": 1, "succeeded": 1}
    restore = venues.extract(server)
    assert restore.due_by_reason == {"changed": 1}  # the render is a new Version payload
    assert [p.operation for p in venues.pages(gers)] == ["initial", "withdrawal", "restoration"]
