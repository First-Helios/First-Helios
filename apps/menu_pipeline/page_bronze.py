"""``menu-page`` Bronze writes: fetch, render, classify, Capture and Version (ADR-0013 §5).

ADR-0013 implementation slice 3, without extraction. For every menu URL a
current venue has saved (resolved ``menu-url-discovery`` records), one run:

1. **Fetches** the page through :class:`~apps.discovery.web_client.SiteFetcher`
   (robots, User-Agent, per-host rate limit, 3 MB cap). A menu URL several
   records share (a chain's platform page) is one unit of work, fetched once
   and written in one transaction (owner decision S3).
2. **Segments** it (``segment-v2``) and asks the page classifier. A page that
   fails is a skipped Capture: ``js_only`` when the §4 render trigger would
   render it (a platform page, or an own-site page that looks
   JavaScript-only), else ``not_menu``. With a renderer (``--render``, off by
   default) a ``js_only`` page, or a platform page answering ``403``, is
   rendered once and classified again; the render is its own Capture. A PDF
   response is skipped ``pdf``; other non-HTML is ``failed/not_html``.
3. **Writes** a menu page per record: the Version payload is the menu URL,
   ``render``, the segmenter version and the text hash. A payload equal to the
   record's latest Version writes a ``succeeded`` Capture with no Version
   (Amendment 4); otherwise a new Version, so "changed" means a new Version.
   Every Capture that read a body has a durable bundle (:mod:`.bundle`).
4. **Assigns** each record to its scope (Amendment 3): a platform page
   (``<gers>|<host>``) to the venue's Establishment, unless that URL is the
   saved menu URL of more than one current venue; an own-site page (``<gers>``)
   to its menu-URL record's Organization. A scope that changed since the last
   run is remapped (owner decision S5); a record in ``needs_review`` is counted
   and left alone.

A verified menu URL that now fails the classifier is only counted: withdrawing
it stays with discovery's ADR-0015 re-verification (owner decision S2).

Resumable: a URL is not due while its last ``menu-page`` Capture is younger than
:data:`REFETCH_WINDOW`, unless a record was saved after that fetch and has no
Version for it. Queue: never-fetched URLs first, then the oldest fetch, ties by
record key. The caller commits after every URL (``on_page``).
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Protocol

from sqlalchemy import func, or_, select
from sqlalchemy.orm import aliased

from apps.discovery.menu_url import menu_pdf_links, ordering_platform_host
from apps.discovery.url_pipeline import MENU_URL_NAMESPACE
from apps.discovery.web_client import CaptureFailure, FetchResult, looks_js_only
from apps.menu_pipeline.bundle import Bundle, BundleStore
from packages.helios_core.identity.commands import (
    DecisionMetadata,
    assign_source_record,
    remap_source_record,
    resolve_source_record_observation,
)
from packages.helios_core.identity.models import (
    CurrentResolution,
    Establishment,
    SubjectCurrentness,
)
from packages.helios_core.provenance.contracts import (
    BronzeObservation,
    canonicalize_http_url,
    record_capture_attempt,
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
from packages.helios_parsing.segment import SEGMENTER_VERSION, Block, segment, text_hash

if TYPE_CHECKING:
    from collections.abc import Callable

    from sqlalchemy.orm import Session

    from apps.discovery.web_client import PageRenderer, PageVerifier

MENU_PAGE_NAMESPACE = "menu-page"
MENU_PAGE_KIND = "menu_page"
# A URL fetched less than this long ago is not fetched again (owner decision S3,
# the same span as discovery's RECRAWL_WINDOW): a chunked run spread over days
# never re-fetches, and the next monthly run does.
REFETCH_WINDOW = timedelta(days=20)
SCOPE_METHOD = "menu-page-scope"


class PageFetcher(Protocol):
    """What the pipeline needs from :class:`~apps.discovery.web_client.SiteFetcher`."""

    def fetch_page(self, url: str) -> FetchResult | CaptureFailure: ...

    def pace(self, host: str, crawl_delay: float = 0.0) -> None: ...


@dataclass(frozen=True, slots=True)
class PageRecord:
    """One saved menu URL: its record key and the Subjects its page may be scoped to."""

    key: str  # "<gers>" or "<gers>|<platform host>", shared by both namespaces
    organization_subject_id: int  # the menu-URL record's Subject
    establishment_subject_id: int  # the venue the GERS id resolves to
    saved_at: datetime  # observed_at of the menu-URL record's latest Version


@dataclass(frozen=True, slots=True)
class PageTarget:
    """One menu URL and every record that saved it."""

    url: str
    records: tuple[PageRecord, ...]
    last_fetched_at: datetime | None
    due: bool

    @property
    def platform(self) -> bool:
        return ordering_platform_host(self.url) is not None

    def scope_subject_id(self, record: PageRecord) -> int:
        """Amendment 3: a platform page of exactly one current venue is Establishment content."""
        venues = {r.establishment_subject_id for r in self.records}
        if "|" in record.key and len(venues) == 1:
            return record.establishment_subject_id
        return record.organization_subject_id


@dataclass(slots=True)
class MenuPageReport:
    """Counts from one ``menu-page`` run (per URL unless named per record)."""

    menu_urls: int = 0  # records: resolved menu URLs of current venues
    pages: int = 0  # distinct URLs among them
    not_due: int = 0  # URLs inside the refetch window
    fetched: int = 0  # URLs fetched this run
    renders: int = 0
    versions_new: int = 0  # records: first Version
    versions_changed: int = 0  # records: a new Version of an existing record
    unchanged: int = 0  # records: re-read, no new Version (Amendment 4)
    outcomes: Counter[str] = field(default_factory=Counter)  # Capture reason codes
    linking_menu_pdf: int = 0  # URLs whose page links a menu-named PDF (Amendment 3)
    establishment_scope: int = 0  # records written with Establishment scope
    organization_scope: int = 0
    remapped: int = 0
    needs_review: int = 0

    def summary(self) -> dict[str, object]:
        out: dict[str, object] = {
            name: getattr(self, name) for name in self.__dataclass_fields__ if name != "outcomes"
        }
        out["outcomes"] = dict(sorted(self.outcomes.items()))
        return out


@dataclass(frozen=True, slots=True)
class _LatestPage:
    version_id: int
    payload: dict[str, object]
    evidence_id: int
    endpoint: str
    state: str | None
    subject_id: int | None


def _sha(payload: dict[str, object]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _decision(*, decided_at: datetime, observed_at: datetime) -> DecisionMetadata:
    return DecisionMetadata(
        confidence=Decimal("1"),
        method=SCOPE_METHOD,
        method_version="1",
        actor_class="rule",
        decided_at=decided_at,
        effective_at=observed_at,
    )


def _saved_menu_urls(session: Session) -> list[tuple[str, int, str, datetime]]:
    """``(key, Subject, menu URL, observed_at)`` of every resolved menu-URL record."""
    rows = session.execute(
        select(
            SourceRecord.external_key,
            CurrentResolution.subject_id,
            SourceRecordVersion.source_payload,
            SourceRecordVersion.observed_at,
        )
        .join(Source, Source.id == SourceRecord.source_id)
        .join(CurrentResolution, CurrentResolution.source_record_id == SourceRecord.id)
        .join(SubjectCurrentness, SubjectCurrentness.subject_id == CurrentResolution.subject_id)
        .join(SourceRecordVersion, SourceRecordVersion.source_record_id == SourceRecord.id)
        .where(
            Source.namespace == MENU_URL_NAMESPACE,
            CurrentResolution.state == "resolved",
            SubjectCurrentness.is_current.is_(True),
        )
        .distinct(SourceRecord.id)
        .order_by(
            SourceRecord.id, SourceRecordVersion.observed_at.desc(), SourceRecordVersion.id.desc()
        )
    ).all()
    out: list[tuple[str, int, str, datetime]] = []
    for key, subject_id, payload, observed_at in rows:
        url = payload.get("menu_url") if isinstance(payload, dict) else None
        if isinstance(url, str) and subject_id is not None:
            out.append((key, subject_id, url, observed_at))
    return out


def _current_venues(session: Session, gers_ids: set[str]) -> dict[str, int]:
    """GERS id → its current, not closed Establishment (with a current Place)."""
    if not gers_ids:
        return {}
    place_currentness = aliased(SubjectCurrentness)
    rows = session.execute(
        select(SourceRecord.external_key, Establishment.subject_id)
        .join(Source, Source.id == SourceRecord.source_id)
        .join(CurrentResolution, CurrentResolution.source_record_id == SourceRecord.id)
        .join(Establishment, Establishment.subject_id == CurrentResolution.subject_id)
        .join(SubjectCurrentness, SubjectCurrentness.subject_id == Establishment.subject_id)
        .join(place_currentness, place_currentness.subject_id == Establishment.place_subject_id)
        .where(
            Source.namespace == "overture",
            SourceRecord.external_key.in_(sorted(gers_ids)),
            CurrentResolution.state == "resolved",
            SubjectCurrentness.is_current.is_(True),
            place_currentness.is_current.is_(True),
            Establishment.operating_status != "closed",
            or_(Establishment.valid_to.is_(None), Establishment.valid_to > func.now()),
        )
    ).all()
    return {str(key): subject_id for key, subject_id in rows}


def _latest_page(session: Session, key: str) -> _LatestPage | None:
    """The ``menu-page`` record's latest Version, its Evidence, Capture endpoint and resolution."""
    row = session.execute(
        select(
            SourceRecordVersion.id,
            SourceRecordVersion.source_payload,
            Evidence.id,
            SourceEndpoint.canonical_uri,
            CurrentResolution.state,
            CurrentResolution.subject_id,
        )
        .select_from(SourceRecord)
        .join(Source, Source.id == SourceRecord.source_id)
        .join(SourceRecordVersion, SourceRecordVersion.source_record_id == SourceRecord.id)
        .join(Evidence, Evidence.source_record_version_id == SourceRecordVersion.id)
        .join(Capture, Capture.id == SourceRecordVersion.capture_id)
        .join(SourceEndpoint, SourceEndpoint.id == Capture.source_endpoint_id)
        .outerjoin(CurrentResolution, CurrentResolution.source_record_id == SourceRecord.id)
        .where(Source.namespace == MENU_PAGE_NAMESPACE, SourceRecord.external_key == key)
        .order_by(
            SourceRecordVersion.observed_at.desc(), SourceRecordVersion.id.desc(), Evidence.id
        )
        .limit(1)
    ).one_or_none()
    if row is None:
        return None
    version_id, payload, evidence_id, endpoint, state, subject_id = row
    return _LatestPage(version_id, payload, evidence_id, endpoint, state, subject_id)


def _last_fetched_at(session: Session, endpoints: set[str]) -> datetime | None:
    return session.scalar(
        select(func.max(Capture.fetched_at))
        .join(Source, Source.id == Capture.source_id)
        .join(SourceEndpoint, SourceEndpoint.id == Capture.source_endpoint_id)
        .where(
            Source.namespace == MENU_PAGE_NAMESPACE,
            SourceEndpoint.canonical_uri.in_(sorted(endpoints)),
        )
    )


def page_targets(
    session: Session, *, now: datetime, report: MenuPageReport | None = None
) -> list[PageTarget]:
    """Every saved menu URL of a current venue, in queue order (due or not)."""
    saved = _saved_menu_urls(session)
    venues = _current_venues(session, {key.split("|", 1)[0] for key, *_ in saved})
    groups: dict[str, list[PageRecord]] = {}
    for key, subject_id, url, observed_at in saved:
        establishment = venues.get(key.split("|", 1)[0])
        if establishment is None:
            continue
        groups.setdefault(canonicalize_http_url(url), []).append(
            PageRecord(key, subject_id, establishment, observed_at)
        )
    targets: list[PageTarget] = []
    for url, records in groups.items():
        endpoints, fresh_versions = {url}, set()
        for record in records:
            latest = _latest_page(session, record.key)
            if latest is not None and latest.payload.get("menu_url") == url:
                endpoints.add(latest.endpoint)
                fresh_versions.add(record.key)
        last = _last_fetched_at(session, endpoints)
        due = (
            last is None
            or now - last >= REFETCH_WINDOW
            or any(r.key not in fresh_versions and r.saved_at > last for r in records)
        )
        ordered = tuple(sorted(records, key=lambda r: r.key))
        targets.append(PageTarget(url, ordered, last, due))
        if report is not None:
            report.menu_urls += len(records)
    targets.sort(
        key=lambda t: (
            t.last_fetched_at is not None,
            t.last_fetched_at or now,
            t.records[0].key,
        )
    )
    if report is not None:
        report.pages = len(targets)
    return targets


def _is_pdf(result: FetchResult) -> bool:
    return "pdf" in result.content_type.lower() or (result.body or b"").startswith(b"%PDF-")


def _is_html(result: FetchResult) -> bool:
    content_type = result.content_type.lower()
    return "html" in content_type or content_type == ""


class MenuPageWriter:
    """Fetches, classifies and writes one :class:`PageTarget` (flushes; the caller commits)."""

    def __init__(  # noqa: PLR0913 - the run's collaborators, injected for tests
        self,
        session: Session,
        *,
        fetcher: PageFetcher,
        verifier: PageVerifier,
        bundles: BundleStore,
        renderer: PageRenderer | None = None,
        observed_at: datetime,
        decided_at: datetime,
        report: MenuPageReport,
    ) -> None:
        self._session = session
        self._fetcher = fetcher
        self._verifier = verifier
        self._bundles = bundles
        self._renderer = renderer
        self._observed_at = observed_at
        self._decided_at = decided_at
        self._report = report
        self._pdf_linked = False

    def write(self, target: PageTarget) -> None:
        self._report.fetched += 1
        self._pdf_linked = False
        static = self._fetcher.fetch_page(target.url)
        if isinstance(static, CaptureFailure):
            self._attempt(target.url, static)
            if self._renderer is not None and target.platform and static.reason_code == "http_403":
                self._render(target)  # Amendment 1: a refused platform page is rendered
        elif _is_pdf(static):
            self._skip(static, "pdf", bundle=None)
        elif not _is_html(static):
            self._attempt(
                target.url,
                CaptureFailure("failed", "not_html", _at(static)),
                content_hash=static.content_hash,
            )
        else:
            blocks = segment(static.text)
            self._note_pdf_links(static)
            bundle = Bundle(
                url=static.url,
                content_type=static.content_type,
                body=static.body,
                rendered_dom=None,
                segmenter=SEGMENTER_VERSION,
                blocks=tuple(blocks),
            )
            if self._verifier.is_menu(static.text, static.url, trust_path=False):
                self._succeeded(target, static, blocks, bundle, render=None)
            else:
                needs_js = target.platform or looks_js_only(static.text)
                self._skip(static, "js_only" if needs_js else "not_menu", bundle)
                if needs_js and self._renderer is not None:
                    self._render(target)
        if self._pdf_linked:
            self._report.linking_menu_pdf += 1

    def _render(self, target: PageTarget) -> None:
        assert self._renderer is not None  # noqa: S101 - callers check
        self._report.renders += 1
        rendered = self._renderer.render(target.url, pace=self._fetcher.pace)
        if isinstance(rendered, CaptureFailure):
            self._attempt(target.url, rendered)
            return
        blocks = segment(rendered.text)
        self._note_pdf_links(rendered)
        bundle = Bundle(
            url=rendered.url,
            content_type=rendered.content_type,
            body=None,
            rendered_dom=rendered.text,
            segmenter=SEGMENTER_VERSION,
            blocks=tuple(blocks),
        )
        if self._verifier.is_menu(rendered.text, rendered.url, trust_path=False):
            self._succeeded(target, rendered, blocks, bundle, render=self._renderer.name)
        else:
            self._skip(rendered, "not_menu", bundle)

    def _note_pdf_links(self, result: FetchResult) -> None:
        self._pdf_linked |= bool(menu_pdf_links(result.text, result.url))

    def _attempt(
        self, url: str, failure: CaptureFailure, *, content_hash: str | None = None
    ) -> None:
        record_capture_attempt(
            self._session,
            source_namespace=MENU_PAGE_NAMESPACE,
            source_kind=MENU_PAGE_KIND,
            source_url=url,
            fetched_at=failure.fetched_at,
            outcome=failure.outcome,
            reason_code=failure.reason_code,
            content_hash=content_hash,
        )
        self._report.outcomes[failure.reason_code] += 1

    def _skip(self, result: FetchResult, reason: str, bundle: Bundle | None) -> None:
        """A page that was read but is not extracted: a skipped Capture, bundle kept (S6)."""
        fetched_at = _at(result)
        bundle_path = None if bundle is None else self._bundles.write(bundle, fetched_at=fetched_at)
        record_capture_attempt(
            self._session,
            source_namespace=MENU_PAGE_NAMESPACE,
            source_kind=MENU_PAGE_KIND,
            source_url=result.url,
            fetched_at=fetched_at,
            outcome="skipped",
            reason_code=reason,
            content_hash=result.content_hash,
            bundle_path=bundle_path,
        )
        self._report.outcomes[reason] += 1

    def _succeeded(
        self,
        target: PageTarget,
        result: FetchResult,
        blocks: list[Block],
        bundle: Bundle,
        *,
        render: str | None,
    ) -> None:
        fetched_at = _at(result)
        bundle_path = self._bundles.write(bundle, fetched_at=fetched_at)
        payload: dict[str, object] = {
            "menu_url": target.url,
            "render": render,
            "segmenter": SEGMENTER_VERSION,
            "text_hash": text_hash(blocks),
        }
        wrote_version = False
        for record in target.records:
            scope = target.scope_subject_id(record)
            latest = _latest_page(self._session, record.key)
            if latest is not None and latest.payload == payload:
                self._report.unchanged += 1
                self._keep_scope(latest.state, latest.subject_id, scope, latest.evidence_id, record)
                continue
            resolved = resolve_source_record_observation(
                self._session,
                observation=BronzeObservation(
                    source_namespace=MENU_PAGE_NAMESPACE,
                    source_kind=MENU_PAGE_KIND,
                    external_key=record.key,
                    observed_at=self._observed_at,
                    content_hash=_sha(payload),
                    source_payload=payload,
                    evidence_locator="$.text_hash",
                    source_url=result.url,
                    fetched_at=fetched_at,
                    capture_content_hash=result.content_hash,
                    bundle_path=bundle_path,
                ),
                decided_at=self._decided_at,
            )
            wrote_version = True
            if latest is None:
                self._report.versions_new += 1
            else:
                self._report.versions_changed += 1
            self._keep_scope(
                resolved.state, resolved.subject_id, scope, resolved.evidence_id, record
            )
        if not wrote_version:
            record_unchanged_capture(
                self._session,
                source_namespace=MENU_PAGE_NAMESPACE,
                source_kind=MENU_PAGE_KIND,
                source_url=result.url,
                fetched_at=fetched_at,
                content_hash=result.content_hash,
                bundle_path=bundle_path,
            )
        self._report.outcomes["succeeded"] += 1

    def _keep_scope(
        self,
        state: str | None,
        subject_id: int | None,
        scope: int,
        evidence_id: int,
        record: PageRecord,
    ) -> None:
        """Assign a new record to its scope, remap a changed scope, leave ``needs_review``."""
        if state == "needs_review":
            self._report.needs_review += 1
            return
        if scope == record.establishment_subject_id:
            self._report.establishment_scope += 1
        else:
            self._report.organization_scope += 1
        source_record_id = self._source_record_id(record.key)
        decision = _decision(decided_at=self._decided_at, observed_at=self._observed_at)
        if state == "resolved" and subject_id is not None:
            if subject_id != scope:
                remap_source_record(
                    self._session,
                    source_record_id=source_record_id,
                    from_subject_id=subject_id,
                    to_subject_id=scope,
                    decision=decision,
                    evidence_ids=[evidence_id],
                )
                self._report.remapped += 1
            return
        assign_source_record(
            self._session,
            source_record_id=source_record_id,
            to_subject_id=scope,
            decision=decision,
            evidence_ids=[evidence_id],
        )

    def _source_record_id(self, key: str) -> int:
        return self._session.scalars(
            select(SourceRecord.id)
            .join(Source, Source.id == SourceRecord.source_id)
            .where(Source.namespace == MENU_PAGE_NAMESPACE, SourceRecord.external_key == key)
        ).one()


def _at(result: FetchResult | CaptureFailure) -> datetime:
    if isinstance(result, CaptureFailure):
        return result.fetched_at
    return datetime.fromtimestamp(result.fetched_at, UTC)


def run_menu_pages(  # noqa: PLR0913 - the run's collaborators, injected for tests
    session: Session,
    *,
    fetcher: PageFetcher,
    verifier: PageVerifier,
    bundles: BundleStore,
    renderer: PageRenderer | None = None,
    now: datetime,
    limit: int | None = None,
    on_page: Callable[[], None] | None = None,
) -> MenuPageReport:
    """Fetch and write every due menu URL, one URL per ``on_page`` (the CLI commits).

    ``limit`` caps the URLs fetched; URLs inside the refetch window are counted
    and skipped without a request.
    """
    report = MenuPageReport()
    writer = MenuPageWriter(
        session,
        fetcher=fetcher,
        verifier=verifier,
        bundles=bundles,
        renderer=renderer,
        observed_at=now,
        decided_at=now,
        report=report,
    )
    for target in page_targets(session, now=now, report=report):
        if not target.due:
            report.not_due += 1
            continue
        if limit is not None and report.fetched >= limit:
            break
        writer.write(target)
        if on_page is not None:
            on_page()
    return report
