"""Resolve website + menu-URL for discovered venues, Bronze-first (ADR-0010).

For each current Establishment seeded from Overture:

1. **Website** — take Overture's published website (or a registry override for
   that host), persist it as a Bronze ``website`` observation, and assign it to
   the venue's **Organization** Subject. ``canonical_url`` stays ``None``: a
   website is an attribute here, never an Establishment match key, so two
   locations of one chain never collapse (ADR-0009 hazard, ADR-0010 §4).
2. **Menu-URL** — for a venue with a resolved website and no menu-URL yet, use a
   registry override or crawl the site (robots-aware, rate-limited, cached) for
   a menu page, then persist + assign it the same way. Persisted so a re-run
   skips the crawl (per-site grain, owner decision 3).

Every write reuses the published Identity/Bronze commands and adds no schema.
The menu-URL resolver is injected as a Protocol, so tests supply a fake and CI
makes no network calls.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING, Protocol
from urllib.parse import urlsplit

from sqlalchemy import func, select

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
    from collections.abc import Iterator
    from datetime import datetime

    from sqlalchemy.orm import Session

    from apps.discovery.registry import RegistryEntry
    from apps.discovery.web_client import MenuUrlDiscovery

WEBSITE_NAMESPACE = "website-resolution"
MENU_URL_NAMESPACE = "menu-url-discovery"


class MenuUrlResolver(Protocol):
    """The one capability the pipeline needs from the site fetcher."""

    def discover_menu_url(self, website: str) -> MenuUrlDiscovery | None: ...


@dataclass(frozen=True, slots=True)
class VenueToResolve:
    """A current venue and the Overture signal available to resolve its URLs."""

    establishment_subject_id: int
    organization_subject_id: int
    gers_id: str
    overture_websites: tuple[str, ...]


@dataclass(slots=True)
class UrlDiscoveryReport:
    """Counts from one website/menu-URL resolution run."""

    venues: int = 0
    websites_resolved: int = 0
    websites_reused: int = 0
    without_website: int = 0
    menu_urls_found: int = 0
    menu_urls_reused: int = 0
    menu_urls_absent: int = 0


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


def iter_venues_to_resolve(
    session: Session, *, limit: int | None = None
) -> Iterator[VenueToResolve]:
    """Yield current Establishments with their Overture record's published websites."""
    latest_version = (
        select(
            SourceRecordVersion.source_record_id.label("source_record_id"),
            func.max(SourceRecordVersion.id).label("version_id"),
        )
        .group_by(SourceRecordVersion.source_record_id)
        .subquery()
    )
    statement = (
        select(
            Establishment.subject_id,
            Establishment.organization_subject_id,
            SourceRecord.external_key,
            SourceRecordVersion.source_payload,
        )
        .join(SubjectCurrentness, SubjectCurrentness.subject_id == Establishment.subject_id)
        .join(CurrentResolution, CurrentResolution.subject_id == Establishment.subject_id)
        .join(SourceRecord, SourceRecord.id == CurrentResolution.source_record_id)
        .join(Source, Source.id == SourceRecord.source_id)
        .join(latest_version, latest_version.c.source_record_id == SourceRecord.id)
        .join(SourceRecordVersion, SourceRecordVersion.id == latest_version.c.version_id)
        .where(
            SubjectCurrentness.is_current.is_(True),
            CurrentResolution.state == "resolved",
            Source.namespace == "overture",
        )
        .order_by(Establishment.subject_id)
    )
    if limit is not None:
        statement = statement.limit(limit)

    for subject_id, org_subject_id, external_key, payload in session.execute(statement):
        raw = payload.get("websites") if isinstance(payload, dict) else None
        websites = tuple(str(item) for item in raw if item) if isinstance(raw, list) else ()
        yield VenueToResolve(
            establishment_subject_id=subject_id,
            organization_subject_id=org_subject_id,
            gers_id=str(external_key),
            overture_websites=websites,
        )


def _has_current_record(session: Session, *, namespace: str, external_key: str) -> bool:
    return (
        session.scalar(
            select(CurrentResolution.subject_id)
            .join(SourceRecord, SourceRecord.id == CurrentResolution.source_record_id)
            .join(Source, Source.id == SourceRecord.source_id)
            .where(
                Source.namespace == namespace,
                SourceRecord.external_key == external_key,
                CurrentResolution.state == "resolved",
            )
        )
        is not None
    )


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
    observation: BronzeObservation,
    to_subject_id: int,
    method: str,
    decided_at: datetime,
    observed_at: datetime,
) -> bool:
    """Persist a URL observation and assign it to a Subject. False if already resolved."""
    result = resolve_source_record_observation(
        session, observation=observation, decided_at=decided_at
    )
    if result.state == "resolved":
        return False  # a prior run already assigned this record
    assign_source_record(
        session,
        source_record_id=result.source_record_id,
        to_subject_id=to_subject_id,
        decision=_decision(method, decided_at=decided_at, observed_at=observed_at),
        evidence_ids=[result.evidence_id],
    )
    return True


def _first_overture_website(websites: tuple[str, ...]) -> str | None:
    for raw in websites:
        website = _coerce_website(raw)
        if website is not None:
            return website
    return None


def resolve_urls(
    session: Session,
    *,
    resolver: MenuUrlResolver,
    registry: dict[str, RegistryEntry],
    decided_at: datetime,
    observed_at: datetime,
    limit: int | None = None,
) -> UrlDiscoveryReport:
    """Resolve website + menu-URL for current venues. Flushes; caller commits.

    The registry is keyed by host, so it can override or augment a venue that
    Overture already gives a website for; supplying a website to a venue Overture
    has none for is a later unit (it needs a name/Subject key, not a host).
    """
    report = UrlDiscoveryReport()
    for venue in iter_venues_to_resolve(session, limit=limit):
        report.venues += 1

        overture_website = _first_overture_website(venue.overture_websites)
        entry = registry.get(_host_of(overture_website)) if overture_website else None

        if entry is not None and entry.website is not None:
            website, origin = entry.website, "registry"
        elif overture_website is not None:
            website, origin = overture_website, "overture"
        else:
            report.without_website += 1
            continue

        website_written = _persist_and_assign(
            session,
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
            observed_at=observed_at,
        )
        report.websites_resolved += int(website_written)
        report.websites_reused += int(not website_written)

        if _has_current_record(session, namespace=MENU_URL_NAMESPACE, external_key=venue.gers_id):
            report.menu_urls_reused += 1
            continue

        if entry is not None and entry.menu_url is not None:
            menu_url, signal = entry.menu_url, "registry"
        else:
            discovery = resolver.discover_menu_url(website)
            if discovery is None:
                report.menu_urls_absent += 1
                continue
            menu_url, signal = discovery.menu_url, discovery.signal

        _persist_and_assign(
            session,
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
            observed_at=observed_at,
        )
        report.menu_urls_found += 1
    return report
