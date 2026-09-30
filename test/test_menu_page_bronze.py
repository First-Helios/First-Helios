"""``menu-page`` Bronze writes and the batch run (ADR-0013 slice 3, Amendments 3-4).

Synthetic pages and replayed HTTP only: the fetcher is a fake or a mock
transport, the classifier a word check, and the renderer scripted. DB tests use
the rolled-back ``session`` fixture and skip without a ``*_test`` database.
"""

from __future__ import annotations

import gzip
import hashlib
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import select

import apps.menu_pipeline.page_bronze as page_bronze
from apps.discovery.menu_url import menu_pdf_links
from apps.discovery.url_pipeline import MENU_URL_NAMESPACE, resolve_urls
from apps.discovery.web_client import (
    CaptureFailure,
    FetchResult,
    MenuPdfLinked,
    MenuUrlDiscovery,
    PlatformAmbiguous,
)
from apps.menu_pipeline.bundle import Bundle, BundleStore, excerpt
from apps.menu_pipeline.page_bronze import (
    MENU_PAGE_NAMESPACE,
    REFETCH_WINDOW,
    MenuPageReport,
    run_menu_pages,
)
from apps.menu_pipeline.render import _navigation_reason
from packages.helios_core.identity.models import CurrentResolution, Establishment
from packages.helios_core.provenance.contracts import (
    record_capture_evidence,
    record_unchanged_capture,
)
from packages.helios_core.provenance.models import (
    Capture,
    Evidence,
    Source,
    SourceEndpoint,
    SourceRecord,
    SourceRecordVersion,
)
from packages.helios_core.provenance.validation import (
    capture_excerpt_hash,
    parse_capture_locator,
    validate_outcome,
)
from packages.helios_parsing.segment import SEGMENTER_VERSION, segment
from packages.helios_parsing.validator import Row, validate
from test.test_url_pipeline import (
    _NOW,
    _FakeResolver,
    _org_subject,
    _poi,
    _seed,
    isolate_existing_venues,  # noqa: F401 - autouse fixture: ignore other modules' venues
)
from test.test_web_client import _fetcher

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from sqlalchemy.orm import Session

    from apps.discovery.registry import RegistryEntry

_MENU = (
    "<html><body><h1>Menu</h1><p>MENU</p><p>Carne Asada Taco</p><p>$3.50</p>"
    "<p>Queso</p><p>$6.00</p></body></html>"
)
_NOT_MENU = "<html><body><h1>About us</h1><p>Family owned since 1999.</p></body></html>"
_SHELL = "<html><body><div id='app'></div><script src='/app.js'></script></body></html>"
_T1 = _NOW + timedelta(minutes=1)


# -- fakes ---------------------------------------------------------------------


def _page(
    url: str, html: str, *, at: datetime = _T1, content_type: str = "text/html"
) -> FetchResult:
    body = html.encode("utf-8")
    return FetchResult(
        url=url,
        status=200,
        text=html,
        content_type=content_type,
        fetched_at=at.timestamp(),
        content_hash="sha256:" + hashlib.sha256(body).hexdigest(),
        body=body,
        encoding="utf-8",
    )


class _Pages:
    """A scripted :class:`~apps.menu_pipeline.page_bronze.PageFetcher`; unknown URLs 404."""

    def __init__(self, pages: dict[str, FetchResult | CaptureFailure]) -> None:
        self.pages = pages
        self.calls: list[str] = []

    def fetch_page(self, url: str) -> FetchResult | CaptureFailure:
        self.calls.append(url)
        return self.pages.get(url, CaptureFailure("failed", "http_404", _T1))

    def pace(self, host: str, crawl_delay: float = 0.0) -> None:
        del host, crawl_delay


class _WordVerifier:
    """A page is a menu when its HTML says ``MENU`` (the classifier is tested elsewhere)."""

    name = "word-v1"

    def is_menu(self, html: str, url: str, *, trust_path: bool) -> bool:
        del url, trust_path
        return "MENU" in html


class _Renderer:
    name = "headed-chromium"

    def __init__(self, result: FetchResult | CaptureFailure) -> None:
        self.result = result
        self.calls: list[str] = []

    def render(
        self, url: str, *, pace: Callable[[str, float], None]
    ) -> FetchResult | CaptureFailure:
        self.calls.append(url)
        pace("example.com", 0.0)
        return self.result


# -- pure parts ------------------------------------------------------------------


def test_new_reason_codes_are_valid_and_scheme_maps_to_redirect_refused() -> None:
    for outcome, reason in (
        ("skipped", "not_menu"),
        ("skipped", "js_only"),
        ("skipped", "bot_challenge"),
        ("skipped", "pdf"),
        ("failed", "render_timeout"),
        ("failed", "menu_pdf_only"),
    ):
        validate_outcome(outcome, reason)
    with pytest.raises(ValueError, match="outcome/reason"):
        validate_outcome("failed", "pdf")
    assert _navigation_reason("scheme") == "redirect_refused"
    assert _navigation_reason("robots_disallowed") == "robots_disallowed"


def test_capture_locator_hash_matches_the_validator() -> None:
    blocks = segment(_MENU)
    (verdict,) = validate(blocks, [Row(item="Carne Asada Taco", amount="3.50")]).verdicts
    field = verdict.price_evidence
    assert field is not None
    block = next(b for b in blocks if b.id == parse_capture_locator(field.locator)[1])
    assert capture_excerpt_hash(block.text, field.locator) == field.excerpt_hash
    for bad in ("blocks:segment-v2:b0001[3:3]", "$.text_hash", "blocks:segment-v2:x1[0:1]"):
        with pytest.raises(ValueError, match="locator"):
            parse_capture_locator(bad)
    with pytest.raises(ValueError, match="past its block"):
        capture_excerpt_hash("abc", "blocks:segment-v2:b0001[0:9]")


def test_bundle_is_content_addressed_and_checkable(tmp_path: Path) -> None:
    store = BundleStore(tmp_path)
    blocks = tuple(segment(_MENU))
    bundle = Bundle(
        "https://k.com/menu", "text/html", _MENU.encode(), None, SEGMENTER_VERSION, blocks
    )
    at = datetime(2026, 9, 29, tzinfo=UTC)

    path = store.write(bundle, fetched_at=at)
    again = store.write(bundle, fetched_at=at + timedelta(hours=1))

    assert path == again
    assert path.startswith("var/replay/menu-page/2026/09/") and path.endswith(".json.gz")
    data = gzip.decompress((tmp_path / path).read_bytes())
    assert path.rsplit("/", 1)[1] == hashlib.sha256(data).hexdigest() + ".json.gz"
    assert store.read(path) == bundle
    block = next(b for b in blocks if "$3.50" in b.text)
    assert excerpt(store.read(path), f"blocks:{SEGMENTER_VERSION}:{block.id}[0:5]") == "$3.50"
    with pytest.raises(ValueError, match="segment-v1"):
        excerpt(bundle, f"blocks:segment-v1:{block.id}[0:5]")
    with pytest.raises(ValueError, match="relative"):
        store.read("../etc/passwd")


def test_menu_pdf_links() -> None:
    html = (
        '<a href="/files/Dinner-Menu.pdf">Download</a>'
        '<a href="https://cdn.example/ugd/a1b2.pdf?v=3">Our Menu</a>'
        '<a href="/files/careers.pdf">Jobs</a>'
        '<a href="/menu-of-services.pdf">Menu</a>'
        '<a href="/menu">Menu</a>'
    )
    assert menu_pdf_links(html, "https://k.com/") == [
        "https://k.com/files/Dinner-Menu.pdf",
        "https://cdn.example/ugd/a1b2.pdf?v=3",
    ]


def test_fetch_page_keeps_raw_bytes_through_the_cache(tmp_path: Path) -> None:
    routes = {"/menu": (200, "<p>Tacos €3</p>", "text/html; charset=utf-8")}
    with _fetcher(tmp_path, routes) as fetcher:
        first = fetcher.fetch_page("https://k.com/menu")
    with _fetcher(tmp_path, {}) as fetcher:  # a fresh fetcher reads the disk cache
        cached = fetcher.fetch_page("https://k.com/menu")
        missing = fetcher.fetch_page("https://k.com/gone")
    assert isinstance(first, FetchResult) and first.body == "<p>Tacos €3</p>".encode()
    assert first.content_hash == "sha256:" + hashlib.sha256(first.body).hexdigest()
    assert cached == first
    assert isinstance(missing, CaptureFailure)
    assert (missing.outcome, missing.reason_code) == ("failed", "http_404")


def test_fetch_page_reports_robots_refusal(tmp_path: Path) -> None:
    routes = {"/robots.txt": (200, "User-agent: *\nDisallow: /menu", "text/plain")}
    with _fetcher(tmp_path, routes) as fetcher:
        refused = fetcher.fetch_page("https://k.com/menu")
    assert isinstance(refused, CaptureFailure)
    assert (refused.outcome, refused.reason_code) == ("skipped", "robots_disallowed")


def test_discovery_reports_a_menu_pdf_when_no_menu_page_verifies(tmp_path: Path) -> None:
    routes = {
        "/": (200, '<a href="/files/dinner-menu.pdf">Dinner menu</a>', "text/html"),
        "/files/dinner-menu.pdf": (200, "%PDF-1.7", "application/pdf"),
    }
    with _fetcher(tmp_path, routes) as fetcher:
        found = fetcher.discover_menu_attempt("https://k.com/")
    assert found == (MenuPdfLinked("https://k.com/files/dinner-menu.pdf"),)


# -- database: discovery counts PDF-only venues ------------------------------------------


class _PdfOnlyResolver:
    verifier = "s4-v1"

    def discover_menu_attempt(
        self, website: str, *, address: str | None = None
    ) -> tuple[MenuUrlDiscovery | PlatformAmbiguous | MenuPdfLinked, ...] | CaptureFailure:
        del address
        return (PlatformAmbiguous("toasttab.com"), MenuPdfLinked(website + "menu.pdf"))

    def verify_menu_attempt(
        self, website: str, menu_url: str, *, not_before: datetime
    ) -> MenuUrlDiscovery | CaptureFailure:
        raise AssertionError("nothing is saved to re-verify")


def test_discovery_persists_menu_pdf_only(session: Session) -> None:
    _seed(
        session, [_poi("Pdf Cafe", 30.30, -97.75, gers_id="pdf1", websites=("https://pdf.cafe",))]
    )

    report = resolve_urls(
        session, resolver=_PdfOnlyResolver(), registry={}, decided_at=_NOW, observed_at=_NOW
    )

    assert (report.menu_pdf_only, report.platform_ambiguous, report.menu_urls_absent) == (1, 1, 1)
    reasons = session.scalars(
        select(Capture.reason_code)
        .join(SourceEndpoint, SourceEndpoint.id == Capture.source_endpoint_id)
        .join(Source, Source.id == Capture.source_id)
        .where(
            Source.namespace == MENU_URL_NAMESPACE,
            SourceEndpoint.canonical_uri == "https://pdf.cafe/",
        )
    ).all()
    assert reasons == ["menu_pdf_only"]


# -- database: menu-page writes --------------------------------------------------------


@pytest.fixture(autouse=True)
def isolate_existing_menu_urls(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Runs must not pick up menu URLs committed by earlier test modules."""
    if "session" not in request.fixturenames:
        return
    session = request.getfixturevalue("session")
    original = page_bronze._saved_menu_urls  # noqa: SLF001 - test isolation
    existing = {row[0] for row in original(session)}

    def selected(session: Session) -> list[tuple[str, int, str, datetime]]:
        return [row for row in original(session) if row[0] not in existing]

    monkeypatch.setattr(page_bronze, "_saved_menu_urls", selected)


class _Sites:
    """A menu-URL resolver answering per website; other websites have no menu."""

    verifier = "s4-v1"

    def __init__(self, by_site: dict[str, _FakeResolver]) -> None:
        self._by_site = by_site

    def discover_menu_attempt(
        self, website: str, *, address: str | None = None
    ) -> tuple[MenuUrlDiscovery, ...] | CaptureFailure:
        resolver = self._by_site.get(website)
        if resolver is None:
            return CaptureFailure("failed", "no_menu_found", _NOW)
        return resolver.discover_menu_attempt(website, address=address)

    def verify_menu_attempt(
        self, website: str, menu_url: str, *, not_before: datetime
    ) -> MenuUrlDiscovery | CaptureFailure:
        return self._by_site[website].verify_menu_attempt(website, menu_url, not_before=not_before)


def _resolve(session: Session, resolver: _FakeResolver | _Sites, *, at: datetime = _NOW) -> None:
    registry: dict[str, RegistryEntry] = {}
    resolve_urls(session, resolver=resolver, registry=registry, decided_at=at, observed_at=at)


def _run(
    session: Session,
    tmp_path: Path,
    pages: _Pages,
    *,
    now: datetime = _T1,
    renderer: _Renderer | None = None,
) -> MenuPageReport:
    return run_menu_pages(
        session,
        fetcher=pages,
        verifier=_WordVerifier(),
        bundles=BundleStore(tmp_path),
        renderer=renderer,
        now=now,
    )


def _versions(session: Session, key: str) -> list[SourceRecordVersion]:
    return list(
        session.scalars(
            select(SourceRecordVersion)
            .join(SourceRecord, SourceRecord.id == SourceRecordVersion.source_record_id)
            .join(Source, Source.id == SourceRecord.source_id)
            .where(Source.namespace == MENU_PAGE_NAMESPACE, SourceRecord.external_key == key)
            .order_by(SourceRecordVersion.id)
        )
    )


def _captures(session: Session, url: str) -> list[Capture]:
    return list(
        session.scalars(
            select(Capture)
            .join(SourceEndpoint, SourceEndpoint.id == Capture.source_endpoint_id)
            .join(Source, Source.id == Capture.source_id)
            .where(Source.namespace == MENU_PAGE_NAMESPACE, SourceEndpoint.canonical_uri == url)
            .order_by(Capture.id)
        )
    )


def _page_subject(session: Session, key: str) -> int | None:
    return session.scalar(
        select(CurrentResolution.subject_id)
        .join(SourceRecord, SourceRecord.id == CurrentResolution.source_record_id)
        .join(Source, Source.id == SourceRecord.source_id)
        .where(Source.namespace == MENU_PAGE_NAMESPACE, SourceRecord.external_key == key)
    )


def _establishment(session: Session, gers_id: str) -> int:
    subject = session.scalar(
        select(Establishment.subject_id)
        .join(CurrentResolution, CurrentResolution.subject_id == Establishment.subject_id)
        .join(SourceRecord, SourceRecord.id == CurrentResolution.source_record_id)
        .join(Source, Source.id == SourceRecord.source_id)
        .where(Source.namespace == "overture", SourceRecord.external_key == gers_id)
    )
    assert subject is not None
    return subject


def test_own_site_menu_page_versions_bundle_and_organization_scope(
    session: Session, tmp_path: Path
) -> None:
    _seed(
        session,
        [_poi("Kerbey Lane", 30.30, -97.75, gers_id="mp1", websites=("https://kerbey.com",))],
    )
    _resolve(session, _FakeResolver("https://kerbey.com/menu"))
    pages = _Pages({"https://kerbey.com/menu": _page("https://kerbey.com/menu", _MENU)})

    report = _run(session, tmp_path, pages)

    assert (report.pages, report.fetched, report.versions_new) == (1, 1, 1)
    assert (report.organization_scope, report.establishment_scope) == (1, 0)
    assert report.outcomes == {"succeeded": 1}
    (version,) = _versions(session, "mp1")
    assert version.source_payload == {
        "menu_url": "https://kerbey.com/menu",
        "render": None,
        "segmenter": SEGMENTER_VERSION,
        "text_hash": version.source_payload["text_hash"],
    }
    assert _page_subject(session, "mp1") == _org_subject(session, "kerbey lane")
    capture = session.get(Capture, version.capture_id)
    assert capture is not None and capture.bundle_path is not None
    bundle = BundleStore(tmp_path).read(capture.bundle_path)
    assert bundle.body == _MENU.encode() and bundle.rendered_dom is None
    assert capture.content_hash == "sha256:" + hashlib.sha256(_MENU.encode()).hexdigest()

    # A price's Capture-targeted locator is checkable from the bundle alone.
    block = next(b for b in bundle.blocks if b.text == "$3.50")
    locator = f"blocks:{SEGMENTER_VERSION}:{block.id}[0:5]"
    evidence_id = record_capture_evidence(
        session, capture_id=capture.id, locator=locator, block_text=block.text
    )
    assert (
        record_capture_evidence(
            session, capture_id=capture.id, locator=locator, block_text=block.text
        )
        == evidence_id
    )
    evidence = session.get(Evidence, evidence_id)
    assert evidence is not None and evidence.capture_id == capture.id
    assert evidence.excerpt_hash == capture_excerpt_hash(excerpt(bundle, locator), locator)


def test_refetch_window_unchanged_and_changed_text(session: Session, tmp_path: Path) -> None:
    _seed(
        session,
        [_poi("Kerbey Lane", 30.30, -97.75, gers_id="mp2", websites=("https://kerbey.com",))],
    )
    _resolve(session, _FakeResolver("https://kerbey.com/menu"))
    url = "https://kerbey.com/menu"
    _run(session, tmp_path, _Pages({url: _page(url, _MENU)}))

    # Inside the window nothing is fetched.
    soon = _Pages({url: _page(url, _MENU)})
    report = _run(session, tmp_path, soon, now=_T1 + timedelta(days=1))
    assert (report.not_due, report.fetched, soon.calls) == (1, 0, [])

    # Past the window, markup churn with the same text: a Capture, no Version (Amendment 4).
    later = _T1 + REFETCH_WINDOW
    churned = _MENU.replace("<body>", "<body class='x'><script>var t=1;</script>")
    report = _run(session, tmp_path, _Pages({url: _page(url, churned, at=later)}), now=later)
    assert (report.unchanged, report.versions_changed) == (1, 0)
    assert len(_versions(session, "mp2")) == 1
    unchanged = _captures(session, url)[-1]
    assert (unchanged.outcome, unchanged.bundle_path is not None) == ("succeeded", True)
    assert unchanged.id not in {v.capture_id for v in _versions(session, "mp2")}
    # An exact retry of that re-read reuses its Capture.
    again = record_unchanged_capture(
        session,
        source_namespace=MENU_PAGE_NAMESPACE,
        source_kind="menu_page",
        source_url=url,
        fetched_at=unchanged.fetched_at,
        content_hash=str(unchanged.content_hash),
        bundle_path=str(unchanged.bundle_path),
    )
    assert again.id == unchanged.id

    # Changed text: a new Version.
    latest = later + REFETCH_WINDOW
    changed = _MENU.replace("$6.00", "$6.50")
    report = _run(session, tmp_path, _Pages({url: _page(url, changed, at=latest)}), now=latest)
    assert report.versions_changed == 1
    assert len(_versions(session, "mp2")) == 2


def test_platform_page_takes_establishment_scope_until_shared(
    session: Session, tmp_path: Path
) -> None:
    toast = "https://www.toasttab.com/shared-taco"
    _seed(
        session,
        [
            _poi("Taco One", 30.30, -97.75, gers_id="mp3a", websites=("https://one.example",)),
            _poi("Taco Two", 30.40, -97.70, gers_id="mp3b", websites=("https://two.example",)),
        ],
    )
    platform = _FakeResolver(None, platform_urls=(toast,))
    _resolve(session, _Sites({"https://one.example/": platform}))
    pages = _Pages({toast: _page(toast, _MENU)})
    report = _run(session, tmp_path, pages)
    assert report.establishment_scope == 1
    assert _page_subject(session, "mp3a|toasttab.com") == _establishment(session, "mp3a")

    # The second venue saves the same platform page (its cooldown has passed):
    # the URL is due again and both pages become Organization content (S5 remap).
    later = _NOW + timedelta(days=21)
    _resolve(session, _Sites({"https://two.example/": platform}), at=later)
    report = _run(session, tmp_path, pages, now=later + timedelta(minutes=1))
    assert (report.fetched, report.unchanged, report.versions_new, report.remapped) == (1, 1, 1, 1)
    assert _page_subject(session, "mp3a|toasttab.com") == _org_subject(session, "taco one")
    assert _page_subject(session, "mp3b|toasttab.com") == _org_subject(session, "taco two")


def test_skipped_and_failed_pages(session: Session, tmp_path: Path) -> None:
    sites = {
        "mp4a": ("https://about.example", "https://about.example/menu", _page("https://about.example/menu", _NOT_MENU)),
        "mp4b": ("https://shell.example", "https://shell.example/menu", _page("https://shell.example/menu", _SHELL)),
        "mp4c": ("https://pdf.example", "https://pdf.example/menu", _page("https://pdf.example/menu", "%PDF-1.7", content_type="application/pdf")),
        "mp4d": ("https://gone.example", "https://gone.example/menu", None),
    }  # fmt: skip
    _seed(
        session,
        [
            _poi(f"Venue {key}", 30.30 + i / 10, -97.75, gers_id=key, websites=(site,))
            for i, (key, (site, _menu, _page_)) in enumerate(sites.items())
        ],
    )
    _resolve(
        session,
        _Sites({site + "/": _FakeResolver(menu) for site, menu, _result in sites.values()}),
    )
    pages = _Pages({menu: result for _site, menu, result in sites.values() if result is not None})

    report = _run(session, tmp_path, pages)

    assert report.outcomes == {"not_menu": 1, "js_only": 1, "pdf": 1, "http_404": 1}
    assert report.versions_new == 0
    for key, reason, bundled in (
        ("mp4a", "not_menu", True),
        ("mp4b", "js_only", True),
        ("mp4c", "pdf", False),
        ("mp4d", "http_404", False),
    ):
        (capture,) = _captures(session, sites[key][1])
        assert (capture.reason_code, capture.bundle_path is not None) == (reason, bundled)
        assert _versions(session, key) == []
    # A failed or skipped URL isn't fetched again inside the window.
    report = _run(session, tmp_path, pages, now=_T1 + timedelta(days=1))
    assert (report.fetched, report.not_due) == (0, 4)


def test_render_after_js_only_and_menu_pdf_link_count(session: Session, tmp_path: Path) -> None:
    url = "https://shell.example/menu"
    _seed(
        session,
        [_poi("Shell Cafe", 30.30, -97.75, gers_id="mp5", websites=("https://shell.example",))],
    )
    _resolve(session, _FakeResolver(url))
    dom = _MENU.replace("</body>", '<a href="/files/lunch-menu.pdf">Lunch menu</a></body>')
    renderer = _Renderer(_page(url, dom))

    report = _run(session, tmp_path, _Pages({url: _page(url, _SHELL)}), renderer=renderer)

    assert renderer.calls == [url]
    assert (report.renders, report.versions_new, report.linking_menu_pdf) == (1, 1, 1)
    assert report.outcomes == {"js_only": 1, "succeeded": 1}
    (version,) = _versions(session, "mp5")
    assert version.source_payload["render"] == "headed-chromium"
    capture = session.get(Capture, version.capture_id)
    assert capture is not None and capture.bundle_path is not None
    bundle = BundleStore(tmp_path).read(capture.bundle_path)
    assert (bundle.body, bundle.rendered_dom) == (None, dom)


def test_render_failure_is_a_capture(session: Session, tmp_path: Path) -> None:
    toast = "https://www.toasttab.com/refused"
    _seed(
        session,
        [_poi("Refused", 30.30, -97.75, gers_id="mp6", websites=("https://refused.example",))],
    )
    _resolve(session, _FakeResolver(None, platform_urls=(toast,)))
    renderer = _Renderer(CaptureFailure("skipped", "bot_challenge", _T1))

    report = _run(
        session,
        tmp_path,
        _Pages({toast: CaptureFailure("failed", "http_403", _T1)}),
        renderer=renderer,
    )

    assert report.outcomes == {"http_403": 1, "bot_challenge": 1}
    assert [c.reason_code for c in _captures(session, toast)] == ["http_403", "bot_challenge"]


def test_a_record_saved_after_the_fetch_makes_its_url_due(session: Session, tmp_path: Path) -> None:
    toast = "https://www.toasttab.com/soon-shared"
    platform = _FakeResolver(None, platform_urls=(toast,))
    _seed(
        session, [_poi("Soon One", 30.30, -97.75, gers_id="mp7a", websites=("https://s1.example",))]
    )
    _resolve(session, _Sites({"https://s1.example/": platform}))
    pages = _Pages({toast: _page(toast, _MENU)})
    _run(session, tmp_path, pages)

    # A second venue saves the same page an hour later, inside the window.
    later = _T1 + timedelta(hours=1)
    _seed(
        session, [_poi("Soon Two", 30.40, -97.70, gers_id="mp7b", websites=("https://s2.example",))]
    )
    _resolve(session, _Sites({"https://s2.example/": platform}), at=later)
    report = _run(session, tmp_path, pages, now=later + timedelta(minutes=1))

    assert (report.not_due, report.fetched, report.versions_new, report.remapped) == (0, 1, 1, 1)
    assert _page_subject(session, "mp7a|toasttab.com") == _org_subject(session, "soon one")
    # Once both have a Version, the window holds again.
    report = _run(session, tmp_path, pages, now=later + timedelta(hours=1))
    assert (report.not_due, report.fetched) == (1, 0)
