"""Resolve website + menu-URL for discovered venues, Bronze-first (ADR-0010).

For each current Establishment seeded from Overture (once, from its most
recently observed Overture record):

1. **Website** — take Overture's published website (or a registry override for
   that host), persist it as a Bronze ``website`` observation, and assign it to
   the venue's **Organization** Subject. ``canonical_url`` stays ``None``: a
   website is an attribute here, never an Establishment match key, so two
   locations of one chain never collapse (ADR-0009 hazard, ADR-0010 §4).
2. **Menu-URL** — a registry ``menu_url`` always wins; otherwise crawl the site
   (robots-aware, rate-limited, cached) for a menu page, then persist + assign
   it the same way. A saved menu-URL is reused until the registry or the
   website changes; a failed re-discovery keeps the saved one.

Records are per venue (keyed by GERS id), not per chain (ADR-0010 Amendment 2).
An unchanged website/menu-URL is not re-persisted, a record a human put in
``needs_review`` is never re-assigned, and a venue whose Organization is no
longer current is counted and skipped.

Every write reuses the published Identity/Bronze commands and adds no schema.
The menu-URL resolver is injected as a Protocol, so tests supply a fake and CI
makes no network calls.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING, Literal, Protocol
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.orm import aliased

from packages.helios_core.identity.commands import (
    DecisionMetadata,
    assign_source_record,
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
)
from packages.helios_core.provenance.models import Source, SourceRecord, SourceRecordVersion

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator
    from datetime import datetime

    from sqlalchemy.orm import Session

    from apps.discovery.registry import RegistryEntry
    from apps.discovery.web_client import MenuUrlDiscovery

WEBSITE_NAMESPACE = "website-resolution"
MENU_URL_NAMESPACE = "menu-url-discovery"

_Outcome = Literal["assigned", "updated", "unchanged", "needs_review"]


class MenuUrlResolver(Protocol):
    """The one capability the pipeline needs from the site fetcher."""

    def discover_menu_url(self, website: str) -> MenuUrlDiscovery | None: ...


@dataclass(frozen=True, slots=True)
class VenueToResolve:
    """A current venue and the Overture signal available to resolve its URLs."""

    establishment_subject_id: int
    organization_subject_id: int
    organization_is_current: bool
    gers_id: str
    overture_websites: tuple[str, ...]


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
    needs_review: int = 0
    org_not_current: int = 0


@dataclass(frozen=True, slots=True)
class _SavedRecord:
    """A URL record's current resolution state and latest saved payload."""

    state: str
    payload: dict[str, object]


def _sha(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def _host_of(url: str) -> str:
    host = (urlsplit(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def _coerce_website(value: str) -> str | None:
    """Canonicalize an Overture website string, tolerating a missing scheme."""
    candidate = value.strip()
    if not candidate:
        return None
    for attempt in (candidate, f"https://{candidate}"):
        try:
            return canonicalize_http_url(attempt)
        except ValueError:
            continue
    return None


def iter_venues_to_resolve(session: Session, *, page_size: int = 100) -> Iterator[VenueToResolve]:
    """Yield each current Establishment once, with its latest Overture websites.

    An Establishment deduped from several Overture records yields one venue: the
    most recently observed version wins (by ``observed_at``, not id, so a
    backfilled older release can't drive resolution), and a tie goes to the
    oldest Source Record so the per-GERS URL records keep a stable key. Pages
    by subject id so the caller can commit between pages.
    """
    organization_currentness = aliased(SubjectCurrentness)
    statement = (
        select(
            Establishment.subject_id,
            Establishment.organization_subject_id,
            organization_currentness.is_current,
            SourceRecord.external_key,
            SourceRecordVersion.source_payload,
        )
        .join(SubjectCurrentness, SubjectCurrentness.subject_id == Establishment.subject_id)
        .outerjoin(
            organization_currentness,
            organization_currentness.subject_id == Establishment.organization_subject_id,
        )
        .join(CurrentResolution, CurrentResolution.subject_id == Establishment.subject_id)
        .join(SourceRecord, SourceRecord.id == CurrentResolution.source_record_id)
        .join(Source, Source.id == SourceRecord.source_id)
        .join(SourceRecordVersion, SourceRecordVersion.source_record_id == SourceRecord.id)
        .where(
            SubjectCurrentness.is_current.is_(True),
            CurrentResolution.state == "resolved",
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
        for subject_id, org_subject_id, org_is_current, external_key, payload in rows:
            raw = payload.get("websites") if isinstance(payload, dict) else None
            websites = tuple(str(item) for item in raw if item) if isinstance(raw, list) else ()
            yield VenueToResolve(
                establishment_subject_id=subject_id,
                organization_subject_id=org_subject_id,
                organization_is_current=org_is_current is True,
                gers_id=str(external_key),
                overture_websites=websites,
            )
        if len(rows) < page_size:
            return
        after = rows[-1][0]


def _saved_record(session: Session, *, namespace: str, external_key: str) -> _SavedRecord | None:
    row = session.execute(
        select(CurrentResolution.state, SourceRecordVersion.source_payload)
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
    state, payload = row
    return _SavedRecord(state=state, payload=payload)


def _observation(
    *,
    namespace: str,
    kind: str,
    external_key: str,
    payload: dict[str, object],
    locator: str,
    excerpt: str,
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
        evidence_excerpt_hash=_sha(excerpt),
        canonical_url=None,  # a website/menu URL is an attribute, never a match key
        capture_content_hash=content_hash,
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
) -> _Outcome:
    """Persist a URL observation unless unchanged; assign it only if unresolved.

    The caller skips a record already in ``needs_review``; this can still
    return ``needs_review`` when the resolver unassigns a record whose Subject
    was retired without a successor.
    """
    if (
        saved is not None
        and saved.state == "resolved"
        and saved.payload == dict(observation.source_payload)
    ):
        return "unchanged"
    result = resolve_source_record_observation(
        session, observation=observation, decided_at=decided_at
    )
    if result.state == "resolved":
        return "updated"  # a new version of an already-assigned record
    if result.state == "needs_review":
        return "needs_review"
    assign_source_record(
        session,
        source_record_id=result.source_record_id,
        to_subject_id=to_subject_id,
        decision=_decision(method, decided_at=decided_at, observed_at=observation.observed_at),
        evidence_ids=[result.evidence_id],
    )
    return "assigned"


def _first_overture_website(websites: tuple[str, ...]) -> str | None:
    for raw in websites:
        website = _coerce_website(raw)
        if website is not None:
            return website
    return None


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
    if saved_website is not None and saved_website.state == "needs_review":
        report.needs_review += 1  # a human disputed this website: don't write or crawl
        return False
    website_outcome = _persist_and_assign(
        session,
        saved=saved_website,
        observation=_observation(
            namespace=WEBSITE_NAMESPACE,
            kind="website",
            external_key=venue.gers_id,
            payload={
                "website": website,
                "origin": origin,
                "host": _host_of(website),
                "location_unique": entry.location_unique if entry else False,
            },
            locator=f"website:{venue.gers_id}",
            excerpt=website,
            observed_at=observed_at,
        ),
        to_subject_id=venue.organization_subject_id,
        method=f"website-{origin}",
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

    saved_menu = _saved_record(session, namespace=MENU_URL_NAMESPACE, external_key=venue.gers_id)
    if saved_menu is not None and saved_menu.state == "needs_review":
        report.needs_review += 1
        return worked
    if entry is not None and entry.menu_url is not None:
        menu_url, signal = entry.menu_url, "registry"  # the registry always wins
    elif (
        saved_menu is not None
        and saved_menu.state == "resolved"
        and saved_menu.payload.get("website") == website
    ):
        report.menu_urls_reused += 1
        return worked
    else:
        discovery = resolver.discover_menu_url(website)
        worked = True  # a crawl is work even when it finds nothing
        if discovery is None:
            report.menu_urls_absent += 1  # a saved menu-URL, if any, stays current
            return worked
        menu_url, signal = discovery.menu_url, discovery.signal

    menu_outcome = _persist_and_assign(
        session,
        saved=saved_menu,
        observation=_observation(
            namespace=MENU_URL_NAMESPACE,
            kind="menu_url",
            external_key=venue.gers_id,
            payload={"menu_url": menu_url, "signal": signal, "website": website},
            locator=f"menu-url:{venue.gers_id}",
            excerpt=menu_url,
            observed_at=observed_at,
        ),
        to_subject_id=venue.organization_subject_id,
        method=f"menu-url-{signal}",
        decided_at=decided_at,
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
    return report
