"""Resolve website + menu-URL for discovered venues, Bronze-first (ADR-0010).

For each current Establishment seeded from Overture (once, from its most
recently observed Overture record):

1. **Website** — take Overture's published website (or a registry override for
   that host), persist it as a Bronze ``website`` observation, and assign it to
   the venue's **Organization** Subject. ``identity_match_url`` stays ``None``: a
   website is an attribute here, never an Establishment match key, so two
   locations of one chain never collapse (ADR-0009 hazard, ADR-0010 §4).
2. **Menu-URL** — a registry ``menu_url`` always wins; otherwise crawl the site
   (robots-aware, rate-limited, cached) for a menu page, then persist + assign
   it the same way. The site's own menu is keyed ``<gers>``; each verified
   ordering-platform page linked from the homepage gets its own
   ``<gers>|<platform host>`` record, even when an own-site menu verifies
   (ADR-0011 §7, S6b). A saved menu-URL is reused until the registry or the
   website changes, or until it is due for re-verification (ADR-0015): saved
   by an older page verifier, or last verified more than
   :data:`REVERIFY_WINDOW` ago. A re-check that passes appends a Version; one
   that the page itself fails (see :data:`WITHDRAW_REASONS`) triggers
   re-discovery, and if nothing verifies the record is withdrawn to
   ``needs_review`` with a rejected observation as Evidence. Such a
   rule-withdrawn record is retried on the same schedule and re-assigned when a
   URL verifies again; a failure that says nothing about the page (network,
   5xx, robots) keeps the URL and retries next run.

Records are per venue (keyed by GERS id), not per chain (ADR-0010 Amendment 2).
An unchanged website/menu-URL is not re-persisted, a record a human put in
``needs_review`` is never re-assigned, and a venue whose Organization is no
longer current is counted and skipped. A chain homepage's platform links count
as ``platform_ambiguous`` unless exactly one shows the venue's address. A site
where no menu page verifies but a fetched page links a menu-named PDF is recorded
as ``failed/menu_pdf_only`` (ADR-0013 Amendments 3-4).

Every write reuses the published Identity/Bronze commands (ADR-0011).
The menu-URL resolver is injected as a Protocol, so tests supply a fake and CI
makes no network calls.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Literal, Protocol
from urllib.parse import urlsplit

from sqlalchemy import func, or_, select
from sqlalchemy.orm import aliased

from apps.discovery.menu_url import ordering_platform_host, platform_signal
from apps.discovery.models import DiscoveryLifecycleState
from apps.discovery.web_client import (
    CaptureFailure,
    MenuPdfLinked,
    MenuUrlDiscovery,
    PlatformAmbiguous,
)
from packages.helios_core.identity.commands import (
    DecisionMetadata,
    assign_source_record,
    remap_source_record,
    resolve_source_record_observation,
    unassign_source_record,
)
from packages.helios_core.identity.models import (
    CurrentResolution,
    Establishment,
    ResolutionEvent,
    SubjectCurrentness,
)
from packages.helios_core.provenance.contracts import (
    BronzeObservation,
    canonicalize_http_url,
    latest_capture_at,
    persist_source_record_observation,
    record_capture_attempt,
)
from packages.helios_core.provenance.models import (
    Capture,
    Source,
    SourceEndpoint,
    SourceRecord,
    SourceRecordVersion,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator
    from datetime import datetime

    from sqlalchemy.orm import Session

    from apps.discovery.registry import RegistryEntry

WEBSITE_NAMESPACE = "website-resolution"
MENU_URL_NAMESPACE = "menu-url-discovery"
RECRAWL_WINDOW = timedelta(days=20)
# A saved menu URL is re-verified once its last passing check is this old (ADR-0015).
REVERIFY_WINDOW = timedelta(days=90)
# Re-verification failures that are a verdict on the page itself: it answered
# and isn't a menu (or is gone). Any other failure keeps the URL and retries.
WITHDRAW_REASONS = frozenset(
    {"no_menu_found", "not_html", "http_404", "http_410", "platform_root", "social_link"}
)
WITHDRAW_METHOD = "menu-url-reverify"

_Outcome = Literal["assigned", "updated", "unchanged", "needs_review"]


class MenuUrlResolver(Protocol):
    """The one capability the pipeline needs from the site fetcher."""

    @property
    def verifier(self) -> str: ...

    def discover_menu_attempt(
        self, website: str, *, address: str | None = None
    ) -> tuple[MenuUrlDiscovery | PlatformAmbiguous | MenuPdfLinked, ...] | CaptureFailure: ...

    def verify_menu_attempt(
        self, website: str, menu_url: str, *, not_before: datetime
    ) -> MenuUrlDiscovery | CaptureFailure: ...


@dataclass(frozen=True, slots=True)
class VenueToResolve:
    """A current venue and the Overture signal available to resolve its URLs."""

    establishment_subject_id: int
    organization_subject_id: int
    organization_is_current: bool
    gers_id: str
    overture_websites: tuple[str, ...]
    source_url: str
    content_hash: str
    address: str | None = None


@dataclass(slots=True)
class UrlDiscoveryReport:
    """Counts from one website/menu-URL resolution run.

    ``*_resolved``/``*_found`` are new assignments, ``*_updated`` are new
    versions of an already-assigned record, ``*_reused`` wrote nothing.
    """

    venues: int = 0
    websites_resolved: int = 0
    websites_updated: int = 0
    websites_reused: int = 0
    without_website: int = 0
    menu_urls_found: int = 0
    menu_urls_updated: int = 0
    menu_urls_reused: int = 0
    menu_urls_absent: int = 0
    menu_urls_reverified: int = 0
    menu_urls_reverify_deferred: int = 0
    menu_urls_withdrawn: int = 0
    platform_ambiguous: int = 0
    menu_pdf_only: int = 0
    needs_review: int = 0
    org_not_current: int = 0
    cooldown_skipped: int = 0


@dataclass(frozen=True, slots=True)
class _SavedRecord:
    """A URL record's current resolution state and latest saved payload."""

    state: str
    payload: dict[str, object]
    subject_id: int | None


def _sha(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def _host_of(url: str) -> str:
    host = (urlsplit(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def _coerce_website(value: str) -> str | None:
    """Canonicalize an Overture website string, tolerating a missing scheme.

    The ``https://`` retry is only trusted when it parses into a real
    hostname (one with a dot). Without that guard, garbage like
    ``'http:/site.com'`` (a typo'd single slash) parses on retry as scheme
    ``https``, host ``http`` — a URL-shaped string, but not a website
    (R76) — silently "fixing" it into ``https://http/site.com``.
    """
    candidate = value.strip()
    if not candidate:
        return None
    try:
        return canonicalize_http_url(candidate)
    except ValueError:
        pass
    retry = f"https://{candidate}"
    try:
        canonical = canonicalize_http_url(retry)
    except ValueError:
        return None
    if "." not in (urlsplit(canonical).hostname or ""):
        return None
    return canonical


def iter_venues_to_resolve(session: Session, *, page_size: int = 100) -> Iterator[VenueToResolve]:
    """Yield each current Establishment once, with its latest Overture websites.

    An Establishment deduped from several Overture records yields one venue: the
    most recently observed version wins (by ``observed_at``, not id, so a
    backfilled older release can't drive resolution), and a tie goes to the
    oldest Source Record so the per-GERS URL records keep a stable key. Pages
    by subject id so the caller can commit between pages.
    """
    organization_currentness = aliased(SubjectCurrentness)
    place_currentness = aliased(SubjectCurrentness)
    statement = (
        select(
            Establishment.subject_id,
            Establishment.organization_subject_id,
            organization_currentness.is_current,
            SourceRecord.external_key,
            SourceRecordVersion.source_payload,
            SourceEndpoint.canonical_uri,
            SourceRecordVersion.content_hash,
        )
        .join(SubjectCurrentness, SubjectCurrentness.subject_id == Establishment.subject_id)
        .join(place_currentness, place_currentness.subject_id == Establishment.place_subject_id)
        .outerjoin(
            organization_currentness,
            organization_currentness.subject_id == Establishment.organization_subject_id,
        )
        .join(CurrentResolution, CurrentResolution.subject_id == Establishment.subject_id)
        .join(SourceRecord, SourceRecord.id == CurrentResolution.source_record_id)
        .join(Source, Source.id == SourceRecord.source_id)
        .join(SourceRecordVersion, SourceRecordVersion.source_record_id == SourceRecord.id)
        .join(Capture, Capture.id == SourceRecordVersion.capture_id)
        .join(SourceEndpoint, SourceEndpoint.id == Capture.source_endpoint_id)
        .where(
            SubjectCurrentness.is_current.is_(True),
            CurrentResolution.state == "resolved",
            place_currentness.is_current.is_(True),
            Establishment.operating_status != "closed",
            or_(Establishment.valid_to.is_(None), Establishment.valid_to > func.now()),
            Capture.outcome == "succeeded",
            Source.namespace == "overture",
        )
        .distinct(Establishment.subject_id)
        .order_by(
            Establishment.subject_id,
            SourceRecordVersion.observed_at.desc(),
            SourceRecord.id,
            SourceRecordVersion.id.desc(),
        )
        .limit(page_size)
    )

    after: int | None = None
    while True:
        page = statement if after is None else statement.where(Establishment.subject_id > after)
        rows = session.execute(page).all()
        for (
            subject_id,
            org_subject_id,
            org_is_current,
            external_key,
            payload,
            source_url,
            content_hash,
        ) in rows:
            from apps.discovery.lifecycle import winning_version

            record_id = session.scalar(
                select(SourceRecord.id)
                .join(Source)
                .where(Source.namespace == "overture", SourceRecord.external_key == external_key)
            )
            if record_id is None or winning_version(session, record_id) is None:
                continue
            raw = payload.get("websites") if isinstance(payload, dict) else None
            websites = (
                tuple(str(item) if item is not None else "" for item in raw)
                if isinstance(raw, list)
                else ()
            )
            addresses = payload.get("addresses") if isinstance(payload, dict) else None
            first = addresses[0] if isinstance(addresses, list) and addresses else None
            freeform = first.get("freeform") if isinstance(first, dict) else None
            yield VenueToResolve(
                establishment_subject_id=subject_id,
                organization_subject_id=org_subject_id,
                organization_is_current=org_is_current is True,
                gers_id=str(external_key),
                overture_websites=websites,
                source_url=source_url,
                content_hash=content_hash,
                address=freeform if isinstance(freeform, str) else None,
            )
        if len(rows) < page_size:
            return
        after = rows[-1][0]


def _saved_record(session: Session, *, namespace: str, external_key: str) -> _SavedRecord | None:
    row = session.execute(
        select(
            CurrentResolution.state,
            SourceRecordVersion.source_payload,
            CurrentResolution.subject_id,
        )
        .select_from(SourceRecord)
        .join(Source, Source.id == SourceRecord.source_id)
        .join(CurrentResolution, CurrentResolution.source_record_id == SourceRecord.id)
        .join(SourceRecordVersion, SourceRecordVersion.source_record_id == SourceRecord.id)
        .where(Source.namespace == namespace, SourceRecord.external_key == external_key)
        .order_by(SourceRecordVersion.observed_at.desc(), SourceRecordVersion.id.desc())
        .limit(1)
    ).one_or_none()
    if row is None:
        return None
    state, payload, subject_id = row
    return _SavedRecord(state=state, payload=payload, subject_id=subject_id)


def _observation(
    *,
    namespace: str,
    kind: str,
    external_key: str,
    payload: dict[str, object],
    locator: str,
    source_url: str,
    capture_hash: str,
    fetched_at: datetime,
    observed_at: datetime,
) -> BronzeObservation:
    content_hash = _sha(json.dumps(payload, sort_keys=True, default=str))
    return BronzeObservation(
        source_namespace=namespace,
        source_kind=kind,
        external_key=external_key,
        observed_at=observed_at,
        content_hash=content_hash,
        source_payload=payload,
        evidence_locator=locator,
        source_url=source_url,
        capture_content_hash=capture_hash,
        fetched_at=fetched_at,
    )


def _decision(method: str, *, decided_at: datetime, observed_at: datetime) -> DecisionMetadata:
    return DecisionMetadata(
        confidence=Decimal("1"),
        method=method,
        method_version="1",
        actor_class="rule",
        decided_at=decided_at,
        effective_at=observed_at,
    )


def _persist_and_assign(
    session: Session,
    *,
    saved: _SavedRecord | None,
    observation: BronzeObservation,
    to_subject_id: int,
    method: str,
    decided_at: datetime,
    allow_remap: bool = False,
    refresh: bool = False,
    reassign: bool = False,
) -> _Outcome:
    """Persist a URL observation unless unchanged; assign it only if unresolved.

    ``refresh`` appends the observation even when its payload is unchanged (a
    passing re-verification). ``reassign`` assigns a record re-verification
    withdrew to ``needs_review``; any other ``needs_review`` record is skipped
    by the caller, and this can still return ``needs_review`` when the resolver
    unassigns a record whose Subject was retired without a successor.
    """
    if (
        not refresh
        and saved is not None
        and saved.state == "resolved"
        and saved.subject_id == to_subject_id
        and saved.payload == dict(observation.source_payload)
    ):
        return "unchanged"
    result = resolve_source_record_observation(
        session, observation=observation, decided_at=decided_at
    )
    if result.state == "resolved":
        if result.subject_id != to_subject_id:
            if (
                not allow_remap
                or saved is None
                or result.subject_id is None
                or result.subject_id != saved.subject_id
            ):
                return "needs_review"
            remap_source_record(
                session,
                source_record_id=result.source_record_id,
                from_subject_id=result.subject_id,
                to_subject_id=to_subject_id,
                evidence_ids=[result.evidence_id],
                decision=_decision(
                    "overture-lifecycle-derived-url",
                    decided_at=decided_at,
                    observed_at=observation.observed_at,
                ),
            )
            from apps.discovery.lifecycle import LifecycleReport, refresh_readiness

            refresh_readiness(session, report=LifecycleReport(), organization_id=result.subject_id)
        return "updated"  # a new version of an already-assigned record
    if result.state == "needs_review" and not reassign:
        return "needs_review"
    assign_source_record(
        session,
        source_record_id=result.source_record_id,
        to_subject_id=to_subject_id,
        decision=_decision(method, decided_at=decided_at, observed_at=observation.observed_at),
        evidence_ids=[result.evidence_id],
    )
    return "assigned"


def _with_render(payload: dict[str, object], menu: MenuUrlDiscovery) -> dict[str, object]:
    """Record the renderer when a browser verified the page; a static pass drops it."""
    out = {name: value for name, value in payload.items() if name != "render"}
    if menu.render:
        out["render"] = menu.render
    return out


def _menu_key(gers_id: str, menu_url: str) -> str:
    platform = ordering_platform_host(menu_url)
    return f"{gers_id}|{platform}" if platform else gers_id


def _menu_keys(session: Session, gers_id: str) -> list[str]:
    """Every menu-URL record key of one venue: ``<gers>`` and each ``<gers>|<host>``."""
    return sorted(
        session.scalars(
            select(SourceRecord.external_key)
            .join(Source)
            .where(
                Source.namespace == MENU_URL_NAMESPACE,
                or_(
                    SourceRecord.external_key == gers_id,
                    SourceRecord.external_key.startswith(gers_id + "|"),
                ),
            )
        ).all()
    )


def _last_capture_at(session: Session, key: str, *, succeeded_only: bool) -> datetime | None:
    statement = (
        select(func.max(Capture.fetched_at))
        .select_from(SourceRecordVersion)
        .join(Capture, Capture.id == SourceRecordVersion.capture_id)
        .join(SourceRecord, SourceRecord.id == SourceRecordVersion.source_record_id)
        .join(Source, Source.id == SourceRecord.source_id)
        .where(Source.namespace == MENU_URL_NAMESPACE, SourceRecord.external_key == key)
    )
    if succeeded_only:
        statement = statement.where(Capture.outcome == "succeeded")
    return session.scalar(statement)


def _rule_withdrawn(session: Session, key: str) -> bool:
    """True when the record's latest Identity decision is a re-verification withdrawal."""
    method = session.scalar(
        select(ResolutionEvent.method)
        .join(SourceRecord, SourceRecord.id == ResolutionEvent.source_record_id)
        .join(Source, Source.id == SourceRecord.source_id)
        .where(Source.namespace == MENU_URL_NAMESPACE, SourceRecord.external_key == key)
        .order_by(ResolutionEvent.id.desc())
        .limit(1)
    )
    return method == WITHDRAW_METHOD


def _reverify_due(
    session: Session, key: str, saved: _SavedRecord, *, verifier: str, observed_at: datetime
) -> bool:
    """A newer verifier, or a last check (a pass; for a withdrawn record, any) past the window.

    Registry menu URLs are never re-verified: the registry wins (D3.2).
    """
    if saved.payload.get("signal") == "registry":
        return False
    if saved.payload.get("verifier") != verifier:
        return True
    last = _last_capture_at(session, key, succeeded_only=saved.state == "resolved")
    return last is None or observed_at - last >= REVERIFY_WINDOW


def _reverify_menus(
    session: Session,
    venue: VenueToResolve,
    *,
    website: str,
    resolver: MenuUrlResolver,
    observed_at: datetime,
    decided_at: datetime,
    report: UrlDiscoveryReport,
) -> tuple[bool, dict[str, CaptureFailure]]:
    """Re-check each of the venue's due menu URLs; return (fetched?, failed key → verdict).

    A pass appends a Version with the current verifier (resetting the window).
    A failure in :data:`WITHDRAW_REASONS` is returned for re-discovery; any
    other failure is recorded as a Capture and the URL is kept.
    """
    worked = False
    failed: dict[str, CaptureFailure] = {}
    for key in _menu_keys(session, venue.gers_id):
        saved = _saved_record(session, namespace=MENU_URL_NAMESPACE, external_key=key)
        url = saved.payload.get("menu_url") if saved else None
        if (
            saved is None
            or saved.state != "resolved"
            or saved.subject_id != venue.organization_subject_id
            or saved.payload.get("website") != website
            or not isinstance(url, str)
            or not _reverify_due(
                session, key, saved, verifier=resolver.verifier, observed_at=observed_at
            )
        ):
            continue
        result = resolver.verify_menu_attempt(website, url, not_before=observed_at)
        worked = True
        if isinstance(result, CaptureFailure):
            if result.reason_code in WITHDRAW_REASONS:
                failed[key] = result
                continue
            record_capture_attempt(
                session,
                source_namespace=MENU_URL_NAMESPACE,
                source_kind="menu_url",
                source_url=url,
                fetched_at=result.fetched_at,
                outcome=result.outcome,
                reason_code=result.reason_code,
            )
            report.menu_urls_reverify_deferred += 1
            continue
        if _menu_key(venue.gers_id, result.menu_url) != key:
            failed[key] = CaptureFailure("failed", "no_menu_found", result.fetched_at)
            continue
        payload = _with_render(
            dict(saved.payload, menu_url=result.menu_url, verifier=resolver.verifier), result
        )
        _persist_and_assign(
            session,
            saved=saved,
            observation=_observation(
                namespace=MENU_URL_NAMESPACE,
                kind="menu_url",
                external_key=key,
                payload=payload,
                locator="$.menu_url",
                source_url=result.menu_url,
                capture_hash=result.content_hash,
                fetched_at=result.fetched_at,
                observed_at=observed_at,
            ),
            to_subject_id=venue.organization_subject_id,
            method=f"menu-url-{payload.get('signal')}",
            decided_at=decided_at,
            refresh=True,
        )
        report.menu_urls_reverified += 1
    return worked, failed


def _withdraw_menu(
    session: Session,
    venue: VenueToResolve,
    key: str,
    failure: CaptureFailure,
    *,
    verifier: str,
    observed_at: datetime,
    decided_at: datetime,
    report: UrlDiscoveryReport,
) -> None:
    """Move a menu URL the current verifier rejects to ``needs_review`` (ADR-0015 item 3).

    The rejected check is persisted as a ``rejected/menu_not_verified``
    observation, whose Evidence supports the unassignment.
    """
    saved = _saved_record(session, namespace=MENU_URL_NAMESPACE, external_key=key)
    url = saved.payload.get("menu_url") if saved else None
    if (
        saved is None
        or saved.state != "resolved"
        or saved.subject_id != venue.organization_subject_id
        or not isinstance(url, str)
    ):
        return
    payload = dict(saved.payload, verifier=verifier, verification_failure=failure.reason_code)
    persisted = persist_source_record_observation(
        session,
        BronzeObservation(
            source_namespace=MENU_URL_NAMESPACE,
            source_kind="menu_url",
            external_key=key,
            observed_at=observed_at,
            content_hash=_sha(json.dumps(payload, sort_keys=True, default=str)),
            source_payload=payload,
            evidence_locator="$.menu_url",
            source_url=url,
            fetched_at=failure.fetched_at,
            capture_outcome="rejected",
            reason_code="menu_not_verified",
        ),
    )
    unassign_source_record(
        session,
        source_record_id=persisted.source_record_id,
        from_subject_id=venue.organization_subject_id,
        decision=_decision(WITHDRAW_METHOD, decided_at=decided_at, observed_at=observed_at),
        evidence_ids=[persisted.evidence_id],
    )
    report.menu_urls_withdrawn += 1


def _first_overture_website(websites: tuple[str, ...]) -> str | None:
    for raw in websites:
        website = _coerce_website(raw)
        if website is not None:
            return website
    return None


def _transition_at(session: Session, venue: VenueToResolve) -> datetime | None:
    return session.scalar(
        select(func.max(DiscoveryLifecycleState.recorded_at))
        .select_from(ResolutionEvent)
        .join(SourceRecord, SourceRecord.id == ResolutionEvent.source_record_id)
        .join(Source, Source.id == SourceRecord.source_id)
        .join(Establishment, Establishment.subject_id == ResolutionEvent.to_subject_id)
        .join(
            DiscoveryLifecycleState,
            (DiscoveryLifecycleState.subject_id == Establishment.subject_id)
            & (DiscoveryLifecycleState.source_record_id == SourceRecord.id)
            & (DiscoveryLifecycleState.release_at == ResolutionEvent.effective_at)
            & (DiscoveryLifecycleState.action == "projected"),
        )
        .where(
            Source.namespace == "overture",
            SourceRecord.external_key == venue.gers_id,
            ResolutionEvent.method == "overture-lifecycle-rebrand",
            Establishment.organization_subject_id == venue.organization_subject_id,
        )
    )


def _predecessor_organization(
    session: Session, venue: VenueToResolve, organization_id: int | None
) -> bool:
    """Only transfer records belonging to this GERS lifecycle ancestry."""
    rows = session.execute(
        select(ResolutionEvent.from_subject_id, ResolutionEvent.to_subject_id)
        .join(SourceRecord, SourceRecord.id == ResolutionEvent.source_record_id)
        .join(Source, Source.id == SourceRecord.source_id)
        .where(
            Source.namespace == "overture",
            SourceRecord.external_key == venue.gers_id,
            ResolutionEvent.operation == "remap",
            ResolutionEvent.method.startswith("overture-lifecycle-"),
        )
    ).all()
    pending, seen = [venue.establishment_subject_id], set()
    while pending:
        child = pending.pop()
        if child in seen:
            continue
        seen.add(child)
        for parent, successor in rows:
            if successor == child and parent is not None:
                est = session.get(Establishment, parent)
                if est is not None and est.organization_subject_id == organization_id:
                    return True
                pending.append(parent)
    return False


def _transfer_menus(
    session: Session,
    venue: VenueToResolve,
    *,
    website: str,
    resolver: MenuUrlResolver,
    observed_at: datetime,
    decided_at: datetime,
    not_before: datetime,
    report: UrlDiscoveryReport,
) -> bool:
    worked = False
    for key in _menu_keys(session, venue.gers_id):
        saved = _saved_record(session, namespace=MENU_URL_NAMESPACE, external_key=key)
        if saved is None or saved.subject_id == venue.organization_subject_id:
            continue
        if (
            saved.state != "resolved"
            or observed_at < not_before
            or not _predecessor_organization(session, venue, saved.subject_id)
        ):
            report.needs_review += 1
            continue
        url = saved.payload.get("menu_url")
        if not isinstance(url, str):
            continue
        result = resolver.verify_menu_attempt(website, url, not_before=not_before)
        worked = True
        if isinstance(result, CaptureFailure):
            record_capture_attempt(
                session,
                source_namespace=MENU_URL_NAMESPACE,
                source_kind="menu_url",
                source_url=url,
                fetched_at=result.fetched_at,
                outcome=result.outcome,
                reason_code=result.reason_code,
            )
            report.menu_urls_absent += 1
            continue
        if result.fetched_at < not_before:
            report.menu_urls_absent += 1
            continue
        if key != _menu_key(venue.gers_id, result.menu_url):
            report.needs_review += 1
            continue
        payload = _with_render(
            dict(
                saved.payload,
                menu_url=result.menu_url,
                website=website,
                signal=result.signal,
                found_via=result.found_via,
                verifier=resolver.verifier,
            ),
            result,
        )
        outcome = _persist_and_assign(
            session,
            saved=saved,
            observation=_observation(
                namespace=MENU_URL_NAMESPACE,
                kind="menu_url",
                external_key=key,
                payload=payload,
                locator="$.menu_url",
                source_url=result.menu_url,
                capture_hash=result.content_hash,
                fetched_at=result.fetched_at,
                observed_at=observed_at,
            ),
            to_subject_id=venue.organization_subject_id,
            method="overture-lifecycle-menu-url",
            allow_remap=True,
            decided_at=decided_at,
        )
        if outcome == "needs_review":
            report.needs_review += 1
        else:
            report.menu_urls_updated += 1
    return worked


def _resolve_venue(
    session: Session,
    venue: VenueToResolve,
    *,
    resolver: MenuUrlResolver,
    registry: dict[str, RegistryEntry],
    decided_at: datetime,
    observed_at: datetime,
    report: UrlDiscoveryReport,
) -> bool:
    """Resolve one venue's website and menu-URL. True if it wrote or crawled."""
    if not venue.organization_is_current:
        report.org_not_current += 1  # e.g. merged/retired; venue lifecycle fixes it
        return False

    overture_website = _first_overture_website(venue.overture_websites)
    entry = registry.get(_host_of(overture_website)) if overture_website else None

    if entry is not None and entry.website is not None:
        website, origin = entry.website, "registry"
    elif overture_website is not None:
        website, origin = overture_website, "overture"
    else:
        report.without_website += 1
        return False

    saved_website = _saved_record(session, namespace=WEBSITE_NAMESPACE, external_key=venue.gers_id)
    transition_at = _transition_at(session, venue)
    if (
        saved_website
        and saved_website.state == "resolved"
        and saved_website.subject_id != venue.organization_subject_id
    ) and (
        transition_at is None
        or observed_at < transition_at
        or not _predecessor_organization(session, venue, saved_website.subject_id)
    ):
        report.needs_review += 1
        return False
    if saved_website is not None and saved_website.state == "needs_review":
        report.needs_review += 1  # a human disputed this website: don't write or crawl
        return False
    if origin == "registry" and (
        entry is None or not entry.content_hash or entry.source_url is None
    ):
        raise ValueError("registry provenance requires file bytes and a repo-relative path")
    website_payload: dict[str, object] = {
        "website": website,
        "origin": origin,
        "host": _host_of(website),
        "location_unique": entry.location_unique if entry else False,
    }
    if origin == "overture":
        index = next(
            i for i, raw in enumerate(venue.overture_websites) if _coerce_website(raw) == website
        )
        website_payload["derived_from"] = {
            "namespace": "overture",
            "external_key": venue.gers_id,
            "locator": f"$.websites[{index}]",
        }
    website_outcome = _persist_and_assign(
        session,
        saved=saved_website,
        observation=_observation(
            namespace=WEBSITE_NAMESPACE,
            kind="website",
            external_key=venue.gers_id,
            payload=website_payload,
            locator="$.website",
            source_url=entry.source_url
            if origin == "registry" and entry and entry.source_url
            else venue.source_url,
            capture_hash=entry.content_hash
            if origin == "registry" and entry
            else venue.content_hash,
            fetched_at=observed_at,
            observed_at=observed_at,
        ),
        to_subject_id=venue.organization_subject_id,
        method=f"website-{origin}",
        allow_remap=transition_at is not None,
        decided_at=decided_at,
    )
    if website_outcome == "needs_review":
        report.needs_review += 1
        return True
    if website_outcome == "assigned":
        report.websites_resolved += 1
    elif website_outcome == "updated":
        report.websites_updated += 1
    else:
        report.websites_reused += 1
    worked = website_outcome != "unchanged"
    from apps.discovery.lifecycle import LifecycleReport, refresh_readiness

    refresh_readiness(
        session, report=LifecycleReport(), organization_id=venue.organization_subject_id
    )
    # Every existing own-site/platform key is independently verified on transfer.
    if transition_at is not None:
        worked |= _transfer_menus(
            session,
            venue,
            website=website,
            resolver=resolver,
            observed_at=observed_at,
            decided_at=decided_at,
            not_before=transition_at,
            report=report,
        )

    platform_host = ordering_platform_host(entry.menu_url if entry and entry.menu_url else website)
    menu_key = (
        f"{venue.gers_id}|{platform_host}"
        if platform_signal(entry.menu_url if entry and entry.menu_url else website)
        else venue.gers_id
    )
    saved_menu = _saved_record(session, namespace=MENU_URL_NAMESPACE, external_key=menu_key)
    if saved_menu is None:
        # A venue can hold several platform records (S6b); any saved verified
        # menu for this unchanged website keeps S6's no-recrawl behavior.
        platform_keys = session.scalars(
            select(SourceRecord.external_key)
            .join(Source)
            .where(
                Source.namespace == MENU_URL_NAMESPACE,
                SourceRecord.external_key.startswith(venue.gers_id + "|"),
            )
        ).all()
        for key in sorted(platform_keys):
            candidate = _saved_record(session, namespace=MENU_URL_NAMESPACE, external_key=key)
            if candidate and candidate.payload.get("website") == website:
                menu_key, saved_menu = key, candidate
                break
    if saved_menu is not None and saved_menu.state == "needs_review":
        # Only a rule-withdrawn record is retried: when the registry now names a
        # menu, or when the verifier or the window says it's due (ADR-0015).
        if not (
            _rule_withdrawn(session, menu_key)
            and (
                (entry is not None and entry.menu_url is not None)
                or _reverify_due(
                    session,
                    menu_key,
                    saved_menu,
                    verifier=resolver.verifier,
                    observed_at=observed_at,
                )
            )
        ):
            report.needs_review += 1
            return worked
    elif (
        saved_menu
        and saved_menu.subject_id != venue.organization_subject_id
        and (
            transition_at is None
            or (saved_menu.payload.get("website") == website and not (entry and entry.menu_url))
        )
    ):
        # An unchanged site's failed verification was already attempted per-key.
        return worked
    acquired: tuple[MenuUrlDiscovery, ...]
    failed: dict[str, CaptureFailure] = {}
    if entry is not None and entry.menu_url is not None:
        # The registry always wins, and is never crawled for platform links.
        if not entry.content_hash or entry.source_url is None:
            raise ValueError("registry provenance requires file bytes and a repo-relative path")
        acquired = (
            MenuUrlDiscovery(entry.menu_url, "registry", observed_at, entry.content_hash, None),
        )
        registry_source_url: str | None = entry.source_url
    else:
        if (
            saved_menu is not None
            and saved_menu.state == "resolved"
            and saved_menu.subject_id == venue.organization_subject_id
            and saved_menu.payload.get("website") == website
        ):
            reverified, failed = _reverify_menus(
                session,
                venue,
                website=website,
                resolver=resolver,
                observed_at=observed_at,
                decided_at=decided_at,
                report=report,
            )
            worked |= reverified
            if not failed:
                if not reverified:
                    report.menu_urls_reused += 1
                return worked
            # A saved URL failed its re-check: re-discover now, whatever the cooldown.
        elif saved_menu is None or saved_menu.state != "needs_review":
            # (A due rule-withdrawn record is retried whatever the cooldown.)
            latest = latest_capture_at(session, MENU_URL_NAMESPACE, website)
            if (
                latest
                and latest.outcome in {"failed", "skipped"}
                and observed_at - latest.fetched_at < RECRAWL_WINDOW
            ):
                report.cooldown_skipped += 1
                return worked
        discovery = resolver.discover_menu_attempt(website, address=venue.address)
        worked = True
        # The own-site menu (if any) plus one per ordering platform (S6b).
        acquired = (
            ()
            if isinstance(discovery, CaptureFailure)
            else tuple(item for item in discovery if isinstance(item, MenuUrlDiscovery))
        )
        if not isinstance(discovery, CaptureFailure):
            report.platform_ambiguous += sum(
                isinstance(item, PlatformAmbiguous) for item in discovery
            )
        if not acquired:
            if isinstance(discovery, CaptureFailure):
                failure = discovery
            elif any(isinstance(item, MenuPdfLinked) for item in discovery):
                # Counted where it is seen: the venue's menu is likely PDF-only,
                # which v1 does not read (ADR-0013 Amendment 3).
                failure = CaptureFailure("failed", "menu_pdf_only", observed_at)
                report.menu_pdf_only += 1
            else:
                failure = CaptureFailure("failed", "no_menu_found", observed_at)
            record_capture_attempt(
                session,
                source_namespace=MENU_URL_NAMESPACE,
                source_kind="menu_url",
                source_url=website,
                fetched_at=failure.fetched_at,
                outcome=failure.outcome,
                reason_code=failure.reason_code,
            )
            report.menu_urls_absent += 1
        registry_source_url = None

    for menu in acquired:
        worked |= _persist_menu(
            session,
            venue,
            menu,
            source_url=registry_source_url or menu.menu_url,
            website=website,
            resolver=resolver,
            transition_at=transition_at,
            observed_at=observed_at,
            decided_at=decided_at,
            report=report,
            refresh=_menu_key(venue.gers_id, menu.menu_url) in failed,
        )
    rediscovered = {_menu_key(venue.gers_id, menu.menu_url) for menu in acquired}
    for key, failure in sorted(failed.items()):
        if key not in rediscovered:
            _withdraw_menu(
                session,
                venue,
                key,
                failure,
                verifier=resolver.verifier,
                observed_at=observed_at,
                decided_at=decided_at,
                report=report,
            )
    return worked


def _persist_menu(
    session: Session,
    venue: VenueToResolve,
    menu: MenuUrlDiscovery,
    *,
    source_url: str,
    website: str,
    resolver: MenuUrlResolver,
    transition_at: datetime | None,
    observed_at: datetime,
    decided_at: datetime,
    report: UrlDiscoveryReport,
    refresh: bool = False,
) -> bool:
    """Persist one menu URL under its own key: ``<gers>`` or ``<gers>|<platform host>``.

    Each key is checked on its own (ADR-0011 §7): a disputed key, or one held by
    an Organization outside this GERS lifecycle, is counted and kept as history
    without blocking the venue's other menu records. A key re-verification
    withdrew is re-assigned. ``refresh`` appends a Version even when unchanged
    (the key just failed its re-check and discovery verified it again). True if
    it wrote or crawled.
    """
    worked = False
    platform = ordering_platform_host(menu.menu_url)
    menu_key = _menu_key(venue.gers_id, menu.menu_url)
    saved_menu = _saved_record(session, namespace=MENU_URL_NAMESPACE, external_key=menu_key)
    withdrawn = (
        saved_menu is not None
        and saved_menu.state == "needs_review"
        and _rule_withdrawn(session, menu_key)
    )
    if saved_menu is not None and saved_menu.state == "needs_review" and not withdrawn:
        report.needs_review += 1
        return worked
    remapping = (
        saved_menu is not None
        and not withdrawn
        and saved_menu.subject_id != venue.organization_subject_id
    )
    if (
        saved_menu is not None
        and remapping
        and (
            transition_at is None
            or not _predecessor_organization(session, venue, saved_menu.subject_id)
        )
    ):
        report.needs_review += 1
        return worked
    if transition_at is not None and (remapping or saved_menu is None):
        verified = resolver.verify_menu_attempt(website, menu.menu_url, not_before=transition_at)
        worked = True
        if isinstance(verified, CaptureFailure):
            record_capture_attempt(
                session,
                source_namespace=MENU_URL_NAMESPACE,
                source_kind="menu_url",
                source_url=menu.menu_url,
                fetched_at=verified.fetched_at,
                outcome=verified.outcome,
                reason_code=verified.reason_code,
            )
            report.menu_urls_absent += 1
            return worked
        if (
            verified.fetched_at < transition_at
            or ordering_platform_host(verified.menu_url) != platform
        ):
            report.menu_urls_absent += 1
            return worked
        menu, source_url = verified, verified.menu_url
    menu_payload: dict[str, object] = {
        "menu_url": menu.menu_url,
        "signal": menu.signal,
        "website": website,
        "found_via": menu.found_via,
    }
    if platform:
        menu_payload["platform"] = platform
    if menu.signal != "registry":  # a registry menu is never re-verified (D3.2)
        menu_payload["verifier"] = resolver.verifier
    menu_payload = _with_render(menu_payload, menu)
    menu_outcome = _persist_and_assign(
        session,
        saved=saved_menu,
        observation=_observation(
            namespace=MENU_URL_NAMESPACE,
            kind="menu_url",
            external_key=menu_key,
            payload=menu_payload,
            locator="$.menu_url",
            source_url=source_url,
            capture_hash=menu.content_hash,
            fetched_at=menu.fetched_at,
            observed_at=observed_at,
        ),
        to_subject_id=venue.organization_subject_id,
        method=f"menu-url-{menu.signal}",
        allow_remap=remapping,
        decided_at=decided_at,
        refresh=refresh,
        reassign=withdrawn,
    )
    if menu_outcome == "needs_review":
        report.needs_review += 1
    elif menu_outcome == "assigned":
        report.menu_urls_found += 1
    elif menu_outcome == "updated":
        report.menu_urls_updated += 1
    else:
        report.menu_urls_reused += 1
    return worked or menu_outcome != "unchanged"


def resolve_urls(
    session: Session,
    *,
    resolver: MenuUrlResolver,
    registry: dict[str, RegistryEntry],
    decided_at: datetime,
    observed_at: datetime,
    limit: int | None = None,
    batch_size: int = 100,
    on_batch: Callable[[], None] | None = None,
) -> UrlDiscoveryReport:
    """Resolve website + menu-URL for current venues. Flushes; caller commits.

    ``limit`` caps the venues that need work (a write or a crawl); venues whose
    records are current and unchanged are skipped without counting, so chunked
    runs advance. ``on_batch`` (the CLI passes ``session.commit``) runs after
    every ``batch_size`` venues, bounding what one crash can lose.

    The registry is keyed by host, so it can override or augment a venue that
    Overture already gives a website for; supplying a website to a venue Overture
    has none for is a later unit (it needs a name/Subject key, not a host).
    """
    from apps.discovery.lifecycle import lock_lifecycle

    lock_lifecycle(session)
    report = UrlDiscoveryReport()
    worked = 0
    for venue in iter_venues_to_resolve(session, page_size=batch_size):
        if limit is not None and worked >= limit:
            break
        report.venues += 1
        if _resolve_venue(
            session,
            venue,
            resolver=resolver,
            registry=registry,
            decided_at=decided_at,
            observed_at=observed_at,
            report=report,
        ):
            worked += 1
        if on_batch is not None and report.venues % batch_size == 0:
            on_batch()
            lock_lifecycle(session)
    return report
