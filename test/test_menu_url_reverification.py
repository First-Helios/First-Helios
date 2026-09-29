"""Re-verification of saved menu URLs against a real migrated database (ADR-0015, S6d).

A saved menu URL is re-checked when the page verifier changes or its last pass
is older than REVERIFY_WINDOW; a pass appends a Version, a page verdict
re-discovers and otherwise withdraws the record to ``needs_review`` with a
rejected observation as Evidence, and a failure that says nothing about the
page keeps the URL. Rule-withdrawn records recover; human-disputed ones don't.
The resolver is a fake whose fetch times follow the run, so there is no network.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Literal

import pytest
from sqlalchemy import select

from apps.discovery.registry import RegistryEntry
from apps.discovery.url_pipeline import (
    MENU_URL_NAMESPACE,
    REVERIFY_WINDOW,
    WITHDRAW_METHOD,
    UrlDiscoveryReport,
    resolve_urls,
)
from apps.discovery.web_client import CaptureFailure, MenuUrlDiscovery, PlatformAmbiguous
from packages.helios_core.identity.models import ResolutionEvent, ResolutionEvidence
from packages.helios_core.provenance.models import (
    Capture,
    Evidence,
    Source,
    SourceRecord,
    SourceRecordVersion,
)
from test.test_url_pipeline import (
    _NOW,
    _human_unassign,
    _org_subject,
    _poi,
    _record,
    _seed,
    _versions,
    isolate_existing_venues,  # noqa: F401 - autouse fixture: ignore other modules' venues
)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


class _Reverifier:
    """A resolver with a named verifier and scripted re-check verdicts.

    Fetch times follow the run (``at``), so the window is measured against real
    capture times rather than one fixed fixture instant.
    """

    def __init__(
        self,
        menu_url: str | None,
        *,
        verifier: str = "s4-v1",
        verdict: str | None = None,
        ambiguous: bool = False,
    ) -> None:
        self.menu_url = menu_url
        self.verifier = verifier
        self.verdict = verdict
        self.ambiguous = ambiguous
        self.at = _NOW
        self.verified: list[str] = []
        self.discovered: list[tuple[str, str | None]] = []

    def verify_menu_attempt(
        self, website: str, menu_url: str, *, not_before: datetime
    ) -> MenuUrlDiscovery | CaptureFailure:
        self.verified.append(menu_url)
        if self.verdict is not None:
            outcome: Literal["failed", "skipped"] = (
                "skipped" if self.verdict.startswith("robots") else "failed"
            )
            return CaptureFailure(outcome, self.verdict, self.at)
        return MenuUrlDiscovery(menu_url, "crawled", self.at, "sha256:page", website)

    def discover_menu_attempt(
        self, website: str, *, address: str | None = None
    ) -> tuple[MenuUrlDiscovery | PlatformAmbiguous, ...] | CaptureFailure:
        self.discovered.append((website, address))
        found: tuple[MenuUrlDiscovery | PlatformAmbiguous, ...] = (
            (MenuUrlDiscovery(self.menu_url, "crawled", self.at, "sha256:page", website),)
            if self.menu_url
            else ()
        )
        if self.ambiguous:
            found = (*found, PlatformAmbiguous("toasttab.com"))
        return found or CaptureFailure("failed", "no_menu_found", self.at)


def _run(
    session: Session,
    resolver: _Reverifier,
    *,
    at: datetime,
    registry: dict[str, RegistryEntry] | None = None,
) -> UrlDiscoveryReport:
    resolver.at = at
    resolver.verified.clear()
    resolver.discovered.clear()
    return resolve_urls(
        session, resolver=resolver, registry=registry or {}, decided_at=at, observed_at=at
    )


def _latest_event(session: Session, external_key: str) -> ResolutionEvent:
    event = session.scalar(
        select(ResolutionEvent)
        .join(SourceRecord, SourceRecord.id == ResolutionEvent.source_record_id)
        .join(Source, Source.id == SourceRecord.source_id)
        .where(Source.namespace == MENU_URL_NAMESPACE, SourceRecord.external_key == external_key)
        .order_by(ResolutionEvent.id.desc())
        .limit(1)
    )
    assert event is not None
    return event


def test_saved_menu_url_from_an_older_verifier_is_rechecked(session: Session) -> None:
    _seed(session, [_poi("Verifier Bump", 30.31, -97.70, gers_id="v1", websites=("vb.com",))])
    resolver = _Reverifier("https://vb.com/menu")
    _run(session, resolver, at=_NOW)
    assert _versions(session, MENU_URL_NAMESPACE, "v1")[0]["verifier"] == "s4-v1"

    resolver.verifier = "classifier-v1"
    report = _run(session, resolver, at=_NOW + timedelta(days=1))

    assert resolver.verified == ["https://vb.com/menu"]
    assert resolver.discovered == []
    assert (report.menu_urls_reverified, report.menu_urls_reused) == (1, 0)
    assert [v["verifier"] for v in _versions(session, MENU_URL_NAMESPACE, "v1")] == [
        "s4-v1",
        "classifier-v1",
    ]
    assert _record(session, MENU_URL_NAMESPACE, "v1").state == "resolved"

    again = _run(session, resolver, at=_NOW + timedelta(days=2))
    assert resolver.verified == []
    assert again.menu_urls_reused == 1


def test_menu_url_is_rechecked_only_once_its_window_expires(session: Session) -> None:
    _seed(session, [_poi("Window", 30.32, -97.70, gers_id="v2", websites=("window.com",))])
    resolver = _Reverifier("https://window.com/menu")
    _run(session, resolver, at=_NOW)

    early = _run(session, resolver, at=_NOW + REVERIFY_WINDOW - timedelta(days=1))
    assert resolver.verified == []
    assert early.menu_urls_reused == 1

    due = _run(session, resolver, at=_NOW + REVERIFY_WINDOW)
    assert resolver.verified == ["https://window.com/menu"]
    assert due.menu_urls_reverified == 1
    assert len(_versions(session, MENU_URL_NAMESPACE, "v2")) == 2, "a pass appends a Version"

    after = _run(session, resolver, at=_NOW + REVERIFY_WINDOW + timedelta(days=1))
    assert resolver.verified == [], "the pass reset the window"
    assert after.menu_urls_reused == 1


def test_a_rejected_menu_url_is_withdrawn_not_reused(session: Session) -> None:
    _seed(session, [_poi("Withdrawn", 30.33, -97.70, gers_id="v3", websites=("wd.com",))])
    resolver = _Reverifier("https://wd.com/news")
    _run(session, resolver, at=_NOW)
    resolver.verifier, resolver.verdict, resolver.menu_url = "classifier-v1", "no_menu_found", None

    report = _run(session, resolver, at=_NOW + timedelta(days=1))

    assert resolver.discovered == [("https://wd.com/", None)], "a failed re-check re-discovers"
    assert (report.menu_urls_withdrawn, report.menu_urls_reused) == (1, 0)
    record = _record(session, MENU_URL_NAMESPACE, "v3")
    assert (record.state, record.subject_id) == ("needs_review", None)
    event = _latest_event(session, "v3")
    assert (event.operation, event.method) == ("unassign", WITHDRAW_METHOD)
    capture = session.execute(
        select(Capture.outcome, Capture.reason_code)
        .join(SourceRecordVersion, SourceRecordVersion.capture_id == Capture.id)
        .join(Evidence, Evidence.source_record_version_id == SourceRecordVersion.id)
        .join(ResolutionEvidence, ResolutionEvidence.evidence_id == Evidence.id)
        .where(ResolutionEvidence.resolution_event_id == event.id)
    ).one()
    assert tuple(capture) == ("rejected", "menu_not_verified")
    assert _versions(session, MENU_URL_NAMESPACE, "v3")[-1]["verification_failure"] == (
        "no_menu_found"
    )

    later = _run(session, resolver, at=_NOW + timedelta(days=2))
    assert resolver.verified == []
    assert resolver.discovered == []
    assert later.needs_review == 1, "not retried before the window or a new verifier"


def test_a_failed_recheck_that_rediscovers_another_url_updates_the_record(
    session: Session,
) -> None:
    _seed(session, [_poi("Moved Menu", 30.34, -97.70, gers_id="v4", websites=("moved.com",))])
    resolver = _Reverifier("https://moved.com/old-menu")
    _run(session, resolver, at=_NOW)
    resolver.verdict, resolver.menu_url = "http_404", "https://moved.com/menu"

    report = _run(session, resolver, at=_NOW + REVERIFY_WINDOW)

    assert (report.menu_urls_updated, report.menu_urls_withdrawn) == (1, 0)
    assert _record(session, MENU_URL_NAMESPACE, "v4").state == "resolved"
    assert [v["menu_url"] for v in _versions(session, MENU_URL_NAMESPACE, "v4")] == [
        "https://moved.com/old-menu",
        "https://moved.com/menu",
    ]


def test_a_failed_recheck_that_rediscovers_the_same_url_resets_its_window(
    session: Session,
) -> None:
    _seed(session, [_poi("Same Menu", 30.35, -97.70, gers_id="v5", websites=("same.com",))])
    resolver = _Reverifier("https://same.com/menu")
    _run(session, resolver, at=_NOW)
    resolver.verdict = "no_menu_found"  # the stricter re-check fails; discovery passes

    report = _run(session, resolver, at=_NOW + REVERIFY_WINDOW)

    assert (report.menu_urls_updated, report.menu_urls_withdrawn) == (1, 0)
    assert len(_versions(session, MENU_URL_NAMESPACE, "v5")) == 2
    resolver.verdict = None
    again = _run(session, resolver, at=_NOW + REVERIFY_WINDOW + timedelta(days=1))
    assert resolver.verified == []
    assert again.menu_urls_reused == 1


@pytest.mark.parametrize("reason", ["http_503", "network_error", "robots_unavailable"])
def test_a_transient_recheck_failure_keeps_the_url(session: Session, reason: str) -> None:
    gers = f"v6-{reason}"
    _seed(session, [_poi("Flaky " + reason, 30.36, -97.70, gers_id=gers, websites=("flaky.com",))])
    resolver = _Reverifier("https://flaky.com/menu")
    _run(session, resolver, at=_NOW)
    resolver.verifier, resolver.verdict = "classifier-v1", reason

    report = _run(session, resolver, at=_NOW + timedelta(days=1))

    assert (report.menu_urls_reverify_deferred, report.menu_urls_withdrawn) == (1, 0)
    assert resolver.discovered == []
    assert _record(session, MENU_URL_NAMESPACE, gers).state == "resolved"
    assert len(_versions(session, MENU_URL_NAMESPACE, gers)) == 1

    resolver.verdict = None
    _run(session, resolver, at=_NOW + timedelta(days=2))
    assert resolver.verified == ["https://flaky.com/menu"], "retried on the next run"


def test_registry_menu_urls_are_never_rechecked_or_withdrawn(session: Session) -> None:
    _seed(session, [_poi("Registry", 30.37, -97.70, gers_id="v7", websites=("reg.com",))])
    registry = {
        "reg.com": RegistryEntry(
            content_hash="sha256:fixture-registry",
            host="reg.com",
            website=None,
            menu_url="https://reg.com/menu",
            location_unique=False,
        )
    }
    resolver = _Reverifier(None, verdict="no_menu_found")
    _run(session, resolver, at=_NOW, registry=registry)
    resolver.verifier = "classifier-v1"

    report = _run(session, resolver, at=_NOW + REVERIFY_WINDOW * 2, registry=registry)
    without_entry = _run(session, resolver, at=_NOW + REVERIFY_WINDOW * 3)

    assert resolver.verified == []
    assert (report.menu_urls_withdrawn, without_entry.menu_urls_withdrawn) == (0, 0)
    assert _record(session, MENU_URL_NAMESPACE, "v7").state == "resolved"
    assert "verifier" not in _versions(session, MENU_URL_NAMESPACE, "v7")[0]


def test_a_rule_withdrawn_menu_url_recovers_when_a_url_verifies_again(session: Session) -> None:
    _seed(session, [_poi("Recover", 30.38, -97.70, gers_id="v8", websites=("rec.com",))])
    resolver = _Reverifier("https://rec.com/menu")
    _run(session, resolver, at=_NOW)
    resolver.verifier, resolver.verdict, resolver.menu_url = "classifier-v1", "not_html", None
    _run(session, resolver, at=_NOW + timedelta(days=1))
    assert _record(session, MENU_URL_NAMESPACE, "v8").state == "needs_review"

    resolver.verifier, resolver.menu_url = "classifier-v2", "https://rec.com/food"
    report = _run(session, resolver, at=_NOW + timedelta(days=2))

    assert resolver.discovered == [("https://rec.com/", None)]
    assert report.menu_urls_found == 1
    record = _record(session, MENU_URL_NAMESPACE, "v8")
    assert (record.state, record.subject_id) == ("resolved", _org_subject(session, "recover"))
    assert _versions(session, MENU_URL_NAMESPACE, "v8")[-1]["verifier"] == "classifier-v2"


def test_a_human_disputed_menu_url_is_never_retried(session: Session) -> None:
    _seed(session, [_poi("Disputed", 30.39, -97.70, gers_id="v9", websites=("disp.com",))])
    resolver = _Reverifier("https://disp.com/menu")
    _run(session, resolver, at=_NOW)
    _human_unassign(session, MENU_URL_NAMESPACE, "v9")
    resolver.verifier = "classifier-v1"

    report = _run(session, resolver, at=_NOW + REVERIFY_WINDOW * 2)

    assert resolver.verified == []
    assert resolver.discovered == []
    assert report.needs_review == 1
    assert _record(session, MENU_URL_NAMESPACE, "v9").state == "needs_review"


def test_chain_homepage_skips_are_counted_and_the_venue_address_is_passed(
    session: Session,
) -> None:
    poi = _poi("Chain Stop", 30.40, -97.70, gers_id="v10", websites=("chain.com",))
    _seed(session, [replace(poi, raw={**poi.raw, "addresses": [{"freeform": "1501 E 6th St"}]})])
    resolver = _Reverifier(None, ambiguous=True)

    report = _run(session, resolver, at=_NOW)

    assert resolver.discovered == [("https://chain.com/", "1501 E 6th St")]
    assert (report.platform_ambiguous, report.menu_urls_absent) == (1, 1)
    assert _versions(session, MENU_URL_NAMESPACE, "v10") == []
    again = _run(session, resolver, at=_NOW + timedelta(days=1))
    assert again.cooldown_skipped == 1, "the skip is recorded as a failed site attempt"
