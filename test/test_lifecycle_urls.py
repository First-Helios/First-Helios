"""Rebrand-derived URLs require per-key fresh verification and evented remaps."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.discovery.menu_url import ordering_platform_host
from apps.discovery.url_pipeline import (
    MENU_URL_NAMESPACE,
    WEBSITE_NAMESPACE,
    _observation,
    _persist_and_assign,
    _saved_record,
    resolve_urls,
)
from apps.discovery.web_client import CaptureFailure, MenuUrlDiscovery
from packages.helios_core.domains.menu.commands import persist_menu
from packages.helios_core.domains.menu.selection import (
    ContextRef,
    SelectionRequest,
    TargetRef,
    select_price,
)
from packages.helios_core.identity.commands import DecisionMetadata, unassign_source_record
from packages.helios_core.identity.contracts import ResolvedScopeRequest
from packages.helios_core.identity.models import CurrentResolution, Establishment, Subject
from packages.helios_core.provenance.contracts import PersistedBronzeObservation
from packages.helios_core.provenance.models import (
    Evidence,
    Source,
    SourceRecord,
    SourceRecordVersion,
)
from test.menu_support import aggregate
from test.provider_support import ScopeFixture, migrate
from test.test_venue_lifecycle import NOW, ingest, mapped, poi

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy.engine import Engine

    from packages.helios_core.domains.menu.contracts import MenuAggregate


@pytest.fixture
def session(historical_database_engine: Engine) -> Iterator[Session]:
    # Menu admission requires committed Identity events from a prior transaction.
    migrate("upgrade", "head")
    with Session(historical_database_engine) as session:
        yield session


URLS = [
    "https://kitchen.example.com/menu",
    "https://www.toasttab.com/kitchen",
    "https://kitchen.square.site/menu",
]


class Resolver:
    def __init__(self, *, failure: bool = False, stale: bool = False) -> None:
        self.failure, self.stale = failure, stale
        self.verified: list[str] = []

    def discover_menu_attempt(self, website: str) -> MenuUrlDiscovery | CaptureFailure:
        return MenuUrlDiscovery(URLS[0], "crawled", NOW, "sha256:menu")

    def verify_menu_attempt(
        self, website: str, menu_url: str, *, not_before: datetime
    ) -> MenuUrlDiscovery | CaptureFailure:
        self.verified.append(menu_url)
        if self.failure:
            return CaptureFailure("failed", "http_503", not_before + timedelta(seconds=1))
        return MenuUrlDiscovery(
            menu_url,
            "platform" if ordering_platform_host(menu_url) else "crawled",
            not_before - timedelta(seconds=1) if self.stale else not_before + timedelta(seconds=1),
            "sha256:fresh-menu",
            website,
        )


def run_urls(session: Session, resolver: Resolver, *, after: bool = False) -> None:
    instant = NOW + timedelta(days=2) if after else NOW
    resolve_urls(session, resolver=resolver, registry={}, decided_at=instant, observed_at=instant)


def seed_urls(session: Session, gers: str, est: Establishment) -> list[str]:
    run_urls(session, Resolver())
    keys = [gers]
    for url in URLS[1:]:
        platform = ordering_platform_host(url)
        key = f"{gers}|{platform}"
        keys.append(key)
        _persist_and_assign(
            session,
            saved=None,
            observation=_observation(
                namespace=MENU_URL_NAMESPACE,
                kind="menu_url",
                external_key=key,
                payload={
                    "menu_url": url,
                    "website": "https://kitchen.example.com/",
                    "signal": "platform",
                    "platform": platform,
                    "found_via": None,
                },
                locator="$.menu_url",
                source_url=url,
                capture_hash="sha256:menu",
                fetched_at=NOW,
                observed_at=NOW,
            ),
            to_subject_id=est.organization_subject_id,
            method="fixture-menu-url",
            decided_at=NOW,
        )
    session.commit()
    return keys


def record(session: Session, namespace: str, key: str) -> CurrentResolution:
    row = session.scalar(
        select(CurrentResolution)
        .join(SourceRecord, SourceRecord.id == CurrentResolution.source_record_id)
        .join(Source)
        .where(Source.namespace == namespace, SourceRecord.external_key == key)
        .execution_options(populate_existing=True)
    )
    assert row
    return row


def menu(
    session: Session, subject: int, source: CurrentResolution, *, shared: bool
) -> MenuAggregate:
    version = session.scalar(
        select(SourceRecordVersion)
        .where(SourceRecordVersion.source_record_id == source.source_record_id)
        .order_by(SourceRecordVersion.observed_at.desc())
        .limit(1)
    )
    assert version and version.capture_id
    evidence = session.scalar(
        select(Evidence.id).where(Evidence.source_record_version_id == version.id)
    )
    assert evidence
    persisted = PersistedBronzeObservation(
        version.source_id,
        0,
        version.source_record_id,
        version.id,
        version.capture_id,
        evidence,
        None,
        False,
        False,
    )
    scope = ResolvedScopeRequest(subject, source.source_record_id, source.last_event_id)
    fixture = ScopeFixture(scope, scope, 0, persisted, persisted)
    return aggregate(fixture, shared=shared)


def request(subject: int, source: int, *, shared: bool = True) -> SelectionRequest:
    return SelectionRequest(
        subject,
        "organization" if shared else "establishment",
        source,
        "main",
        TargetRef("item", (("section", "s-food"), ("item", "i-burger"))),
        ContextRef("dine_in", "lunch"),
        "USD",
        NOW,
    )


@pytest.mark.parametrize("changed_website", [False, True])
def test_rebrand_transfers_every_key_with_fresh_evidence_and_preserves_menu_history(
    session: Session, changed_website: bool
) -> None:
    first = poi()
    ingest(session, [first], 0)
    old = mapped(session, first.gers_id)
    keys = seed_urls(session, first.gers_id, old)
    old_record = record(session, MENU_URL_NAMESPACE, keys[0])
    source_id = old_record.source_record_id
    persisted = persist_menu(
        session, menu(session, old.organization_subject_id, old_record, shared=True)
    )
    session.commit()
    assert (
        select_price(session, request(old.organization_subject_id, source_id)).local_price.state
        == "priced"
    )
    new_poi = poi(key=first.gers_id, name="New Business")
    if changed_website:
        new_poi = replace(
            new_poi,
            websites=("https://new.example.com/",),
            raw=dict(new_poi.raw, websites=["https://new.example.com/"]),
        )
    ingest(session, [new_poi], 1)
    new = mapped(session, first.gers_id)
    resolver = Resolver()
    run_urls(session, resolver, after=True)
    session.commit()
    assert set(resolver.verified) == set(URLS)
    for key in keys:
        assert record(session, MENU_URL_NAMESPACE, key).subject_id == new.organization_subject_id
    assert (
        record(session, WEBSITE_NAMESPACE, first.gers_id).subject_id == new.organization_subject_id
    )
    assert session.get(Subject, new.subject_id).readiness == "eligible"  # type: ignore[union-attr]
    assert (
        select_price(session, request(old.organization_subject_id, source_id)).local_price.state
        != "priced"
    )
    historical = replace(
        request(old.organization_subject_id, source_id), knowledge_cutoff=NOW + timedelta(days=10)
    )
    assert select_price(session, historical).local_price.state == "priced"
    assert (
        select_price(session, request(new.organization_subject_id, source_id)).local_price.state
        != "priced"
    )
    from packages.helios_core.domains.menu.models import MenuPage

    assert session.get(MenuPage, persisted.page_id).subject_id == old.organization_subject_id  # type: ignore[union-attr]
    resolver.verified.clear()
    run_urls(session, resolver, after=True)
    assert resolver.verified == []


@pytest.mark.parametrize("failure", ["http", "stale", "review"])
def test_failed_or_disputed_menu_keys_stay_on_old_organization(
    session: Session, failure: str
) -> None:
    first = poi()
    ingest(session, [first], 0)
    old = mapped(session, first.gers_id)
    keys = seed_urls(session, first.gers_id, old)
    if failure == "review":
        for key in keys:
            current = record(session, MENU_URL_NAMESPACE, key)
            evidence = session.scalar(select(Evidence.id).limit(1))
            assert evidence
            unassign_source_record(
                session,
                source_record_id=current.source_record_id,
                from_subject_id=old.organization_subject_id,
                evidence_ids=[evidence],
                decision=DecisionMetadata(Decimal(1), "fixture-review", "1", "human", NOW, NOW),
            )
    ingest(session, [poi(key=first.gers_id, name="New Business")], 1)
    resolver = Resolver(failure=failure == "http", stale=failure == "stale")
    run_urls(session, resolver, after=True)
    for key in keys:
        current = record(session, MENU_URL_NAMESPACE, key)
        if failure == "review":
            assert current.state == "needs_review"
        else:
            assert current.subject_id == old.organization_subject_id
    assert len(resolver.verified) == (0 if failure == "review" else 3)


def test_website_review_blocks_transfer_and_new_readiness(session: Session) -> None:
    first = poi()
    ingest(session, [first], 0)
    old = mapped(session, first.gers_id)
    seed_urls(session, first.gers_id, old)
    current = record(session, WEBSITE_NAMESPACE, first.gers_id)
    evidence = session.scalar(select(Evidence.id).limit(1))
    assert evidence
    unassign_source_record(
        session,
        source_record_id=current.source_record_id,
        from_subject_id=old.organization_subject_id,
        evidence_ids=[evidence],
        decision=DecisionMetadata(Decimal(1), "fixture-review", "1", "human", NOW, NOW),
    )
    ingest(session, [poi(key=first.gers_id, name="New Business")], 1)
    new = mapped(session, first.gers_id)
    resolver = Resolver()
    run_urls(session, resolver, after=True)
    assert record(session, WEBSITE_NAMESPACE, first.gers_id).state == "needs_review"
    assert resolver.verified == []
    assert session.get(Subject, new.subject_id).readiness == "provisional"  # type: ignore[union-attr]


def test_readiness_promotion_admits_an_establishment_menu(session: Session) -> None:
    first = poi()
    ingest(session, [first], 0)
    est = mapped(session, first.gers_id)
    source = record(session, "overture", first.gers_id)
    value = menu(session, est.subject_id, source, shared=False)
    session.commit()
    from packages.helios_core.identity.contracts import SubjectNotEligibleError

    with pytest.raises(SubjectNotEligibleError):
        persist_menu(session, value)
    run_urls(session, Resolver())
    session.commit()
    persisted = persist_menu(session, value)
    session.commit()
    assert persisted.page_id
    assert (
        select_price(
            session, request(est.subject_id, source.source_record_id, shared=False)
        ).local_price.state
        == "priced"
    )


def test_changed_website_rediscovers_and_verifies_new_own_site_menu(session: Session) -> None:
    first = poi()
    ingest(session, [first], 0)
    old = mapped(session, first.gers_id)
    seed_urls(session, first.gers_id, old)
    changed = poi(key=first.gers_id, name="New Business")
    changed = replace(
        changed,
        websites=("https://new.example.com/",),
        raw=dict(changed.raw, websites=["https://new.example.com/"]),
    )
    ingest(session, [changed], 1)

    class ChangedSite(Resolver):
        def discover_menu_attempt(self, website: str) -> MenuUrlDiscovery | CaptureFailure:
            return MenuUrlDiscovery(website + "menu", "crawled", NOW, "sha256:old-candidate")

        def verify_menu_attempt(
            self, website: str, menu_url: str, *, not_before: datetime
        ) -> MenuUrlDiscovery | CaptureFailure:
            if menu_url == URLS[0]:
                self.verified.append(menu_url)
                return CaptureFailure("failed", "no_menu_found", not_before + timedelta(seconds=1))
            return super().verify_menu_attempt(website, menu_url, not_before=not_before)

    resolver = ChangedSite()
    run_urls(session, resolver, after=True)
    saved = _saved_record(session, namespace=MENU_URL_NAMESPACE, external_key=first.gers_id)
    assert saved and saved.payload["menu_url"] == "https://new.example.com/menu"
    assert saved.subject_id == mapped(session, first.gers_id).organization_subject_id
    assert "https://new.example.com/menu" in resolver.verified
