"""ADR-0011 acceptance: independent provenance, rejected input, and atomic writes."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import func, select, text

from apps.discovery.pipeline import run_discovery
from packages.helios_core.identity.commands import (
    admit_source_record,
    resolve_source_record_observation,
)
from packages.helios_core.identity.models import ResolutionEvent
from packages.helios_core.provenance.contracts import (
    persist_source_record_observation,
    record_capture_attempt,
    source_endpoint_for_evidence,
    source_record_ids_for_identity_match_url,
)
from packages.helios_core.provenance.models import Evidence, Source, SourceRecordVersion
from packages.helios_core.provenance.validation import canonicalize_source_url, excerpt_hash
from test.provider_support import decision, observation
from test.test_discovery import _poi

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from sqlalchemy.orm import Session


@pytest.fixture(autouse=True)
def own_url_venues(monkeypatch: pytest.MonkeyPatch) -> None:
    """Committed concurrency fixtures may exist; exercise only this test's POIs."""
    import apps.discovery.url_pipeline as pipeline

    original = pipeline.iter_venues_to_resolve
    keys = {"evidence-cache", "failure-site", "registry-evidence", "platform-one", "platform-two"}

    def selected(session: Session, *, page_size: int = 100) -> Iterator[pipeline.VenueToResolve]:
        for venue in original(session, page_size=page_size):
            if venue.gers_id in keys:
                yield venue

    monkeypatch.setattr(pipeline, "iter_venues_to_resolve", selected)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (
            "s3://BUCKET/release/2026-01-01/theme=places/type=place/*",
            "s3://bucket/release/2026-01-01/theme=places/type=place/",
        ),
        (
            "s3://bucket/release/2026-01-01/theme=places/type=place/part-?.parquet",
            "s3://bucket/release/2026-01-01/theme=places/type=place/",
        ),
        ("repo:config/sources.yaml", "repo:config/sources.yaml"),
        ("HTTPS://Example.COM:443/menu#x", "https://example.com/menu"),
    ],
)
def test_endpoint_canonicalization(raw: str, expected: str) -> None:
    assert canonicalize_source_url(raw) == expected


@pytest.mark.parametrize(
    "url",
    [
        "repo:/etc/passwd",
        "repo:a/../b",
        "repo:a//b",
        "repo:./a",
        "ftp://example.com/x",
        "s3://bucket/*",
    ],
)
def test_invalid_endpoint(url: str) -> None:
    with pytest.raises(ValueError):
        canonicalize_source_url(url)


def test_excerpt_is_independently_reproducible() -> None:
    payload = {"name": "Café", "primary_category": "restaurant", "websites": ["https://a.test"]}
    encoded = json.dumps(["Café", "restaurant"], ensure_ascii=False, separators=(",", ":")).encode()
    assert (
        excerpt_hash(payload, "$['name','primary_category']")
        == "sha256:" + hashlib.sha256(encoded).hexdigest()
    )
    assert excerpt_hash(payload, "$.websites[0]") == excerpt_hash({"x": "https://a.test"}, "$.x")
    for locator in ("$", "$.missing", "$.websites[9]", "$.*", "$['name','primary_category'].x"):
        with pytest.raises(ValueError):
            excerpt_hash(payload, locator)


def test_invalid_input_caught_then_committed_leaves_no_source(session: Session) -> None:
    obs = observation()
    for invalid in (
        replace(obs, source_url="repo:../bad"),
        replace(obs, identity_match_url="s3://bucket/key/"),
        replace(obs, evidence_locator="$.missing"),
    ):
        with pytest.raises(ValueError):
            persist_source_record_observation(session, invalid)
        session.commit()
        assert (
            session.scalar(
                select(func.count())
                .select_from(Source)
                .where(Source.namespace == obs.source_namespace)
            )
            == 0
        )


def test_savepoint_rolls_back_a_late_database_failure(session: Session) -> None:
    obs = replace(observation(), content_hash="a" * 129)
    from sqlalchemy.exc import DataError

    with pytest.raises(DataError):
        persist_source_record_observation(session, obs)
    session.commit()
    assert (
        session.scalar(
            select(func.count()).select_from(Source).where(Source.namespace == obs.source_namespace)
        )
        == 0
    )


def test_shared_provenance_is_not_identity_and_is_scoped_by_source(session: Session) -> None:
    obs = replace(
        observation(), source_url="s3://bucket/release/2026-01-01/", identity_match_url=None
    )
    one = resolve_source_record_observation(session, observation=obs, decided_at=obs.observed_at)
    two = resolve_source_record_observation(
        session, observation=replace(obs, external_key="another"), decided_at=obs.observed_at
    )
    assert one.state == two.state == "unresolved"
    other = persist_source_record_observation(
        session, replace(obs, source_namespace=obs.source_namespace + "-other")
    )
    assert (
        source_endpoint_for_evidence(session, one.evidence_id).source_url
        == source_endpoint_for_evidence(session, other.evidence_id).source_url
    )
    assert (
        source_record_ids_for_identity_match_url(session, obs.source_url, obs.source_namespace)
        == ()
    )


@pytest.mark.parametrize(
    "reason", ["blank_name", "name_without_letters_or_digits", "name_too_long"]
)
def test_rejected_input_stays_in_bronze_until_valid_observation(
    session: Session, reason: str
) -> None:
    obs = replace(
        observation(), capture_outcome="rejected", reason_code=reason, identity_match_url=None
    )
    persisted = persist_source_record_observation(session, obs)
    assert source_endpoint_for_evidence(session, persisted.evidence_id).reason_code == reason
    assert (
        session.scalar(
            select(func.count())
            .select_from(ResolutionEvent)
            .where(ResolutionEvent.source_record_id == persisted.source_record_id)
        )
        == 0
    )
    with pytest.raises(ValueError, match="rejected"):
        resolve_source_record_observation(session, observation=obs, decided_at=obs.observed_at)
    with pytest.raises(ValueError, match="rejected"):
        admit_source_record(
            session, source_record_id=persisted.source_record_id, decision=decision()
        )
    accepted = resolve_source_record_observation(
        session,
        observation=replace(obs, capture_outcome="succeeded", reason_code=None),
        decided_at=obs.observed_at,
    )
    assert accepted.state == "unresolved"


def test_release_alias_is_exact_retry_and_ingestion_time_is_not_key(session: Session) -> None:
    poi = _poi("Evidence Cafe", 30.3, -97.7)
    now = datetime.now(UTC)
    release = "s3://bucket/release/2026-01-01/theme=places/type=place/"
    first = run_discovery(
        session, [poi], decided_at=now, observed_at=now, release=release + "*.parquet"
    )
    count = session.scalar(select(func.count()).select_from(SourceRecordVersion))
    second = run_discovery(
        session, [poi], decided_at=now, observed_at=now, release=release + "part-*.parquet"
    )
    assert first.minted == 1 and second.reused == 1
    assert session.scalar(select(func.count()).select_from(SourceRecordVersion)) == count
    for table in ("capture", "source_record_version", "evidence"):
        assert (
            session.scalar(text(f"SELECT count(*) FROM bronze.{table} WHERE ingested_at IS NULL"))
            == 0
        )


def test_failed_attempt_has_no_version(session: Session) -> None:
    obs = observation()
    capture = record_capture_attempt(
        session,
        source_namespace=obs.source_namespace,
        source_kind=obs.source_kind,
        source_url=obs.source_url,
        fetched_at=obs.observed_at,
        outcome="failed",
        reason_code="http_503",
    )
    assert (
        session.scalar(
            select(func.count())
            .select_from(SourceRecordVersion)
            .where(SourceRecordVersion.capture_id == capture.id)
        )
        == 0
    )
    assert (
        session.scalar(
            select(func.count()).select_from(Evidence).where(Evidence.capture_id == capture.id)
        )
        == 0
    )


def _namespace_evidence(
    session: Session, namespace: str, external_key: str
) -> tuple[Evidence, SourceRecordVersion]:
    from packages.helios_core.provenance.models import SourceRecord

    row = session.execute(
        select(Evidence, SourceRecordVersion)
        .join(SourceRecordVersion, Evidence.source_record_version_id == SourceRecordVersion.id)
        .join(SourceRecord, SourceRecord.id == SourceRecordVersion.source_record_id)
        .join(Source, Source.id == SourceRecord.source_id)
        .where(Source.namespace == namespace, SourceRecord.external_key == external_key)
    ).one()
    return row[0], row[1]


def test_real_pipeline_recovers_page_bytes_redirect_and_cache_time(
    session: Session, tmp_path: Path
) -> None:
    from apps.discovery.url_pipeline import resolve_urls
    from test.test_url_pipeline import _poi as url_poi
    from test.test_url_pipeline import _seed
    from test.test_web_client import FakeClock, _fetcher

    website = "https://evidence.test/"
    body = "<title>Menu</title><h1>Menu</h1><p>Tacos $5</p>"
    routes = {
        "/robots.txt": (404, "", "text/plain"),
        "/": (200, '<a href="/today-offerings">Our menu</a>', "text/html"),
        "/today-offerings": (302, "/actual-menu", ""),
        "/actual-menu": (200, body, "text/html"),
    }
    _seed(
        session, [url_poi("Evidence", 30.3, -97.7, gers_id="evidence-cache", websites=(website,))]
    )
    clock = FakeClock()
    first_time = datetime.fromtimestamp(clock.wall, UTC)
    with _fetcher(tmp_path, routes, clock=clock) as fetcher:
        attempt = fetcher.discover_menu_attempt(website)
    assert isinstance(attempt, tuple)
    (cached,) = attempt
    clock.wall += 3600
    calls: list[str] = []
    with _fetcher(tmp_path, routes, clock=clock, calls=calls) as fetcher:
        resolve_urls(
            session,
            resolver=fetcher,
            registry={},
            observed_at=datetime.fromtimestamp(clock.wall, UTC),
            decided_at=first_time,
        )
    from apps.discovery.url_pipeline import MENU_URL_NAMESPACE, WEBSITE_NAMESPACE

    evidence, version = _namespace_evidence(session, MENU_URL_NAMESPACE, "evidence-cache")
    capture = source_endpoint_for_evidence(session, evidence.id)
    assert capture.source_url == website + "actual-menu"
    assert capture.content_hash == "sha256:" + hashlib.sha256(body.encode()).hexdigest()
    assert capture.fetched_at == first_time
    assert version.source_payload["found_via"] == website
    assert calls == []
    assert cached.content_hash == capture.content_hash
    website_evidence, website_version = _namespace_evidence(
        session, WEBSITE_NAMESPACE, "evidence-cache"
    )
    assert source_endpoint_for_evidence(session, website_evidence.id).source_url.startswith("s3://")
    assert website_version.source_payload["derived_from"]["locator"] == "$.websites[0]"
    overture_evidence, overture_version = _namespace_evidence(session, "overture", "evidence-cache")
    assert (
        source_endpoint_for_evidence(session, website_evidence.id).content_hash
        == overture_version.content_hash
    )
    assert (
        excerpt_hash(overture_version.source_payload, overture_evidence.locator)
        == overture_evidence.excerpt_hash
    )


@pytest.mark.parametrize(
    ("robots", "home", "outcome", "reason"),
    [
        (
            (200, "User-agent: *\nDisallow: /", "text/plain"),
            (200, "", "text/html"),
            "skipped",
            "robots_disallowed",
        ),
        ((503, "", "text/plain"), (200, "", "text/html"), "skipped", "robots_unavailable"),
        ((404, "", "text/plain"), (503, "", "text/html"), "failed", "http_503"),
        ((404, "", "text/plain"), (200, "Welcome", "text/html"), "failed", "no_menu_found"),
    ],
)
def test_site_failure_persists_once_and_obeys_twenty_day_window(
    session: Session,
    tmp_path: Path,
    robots: tuple[int, str, str],
    home: tuple[int, str, str],
    outcome: str,
    reason: str,
) -> None:
    from apps.discovery.url_pipeline import MENU_URL_NAMESPACE, resolve_urls
    from packages.helios_core.provenance.contracts import latest_capture_at
    from packages.helios_core.provenance.models import Capture
    from test.test_url_pipeline import _poi as url_poi
    from test.test_url_pipeline import _seed
    from test.test_web_client import FakeClock, _fetcher

    website = "https://failure.test/"
    _seed(session, [url_poi("Failure", 30.3, -97.7, gers_id="failure-site", websites=(website,))])
    clock = FakeClock()
    routes = {"/robots.txt": robots, "/": home}
    for day, expected_work in ((0, True), (8, False), (21, True)):
        clock.wall = 1_800_000_000.0 + day * 86400
        calls: list[str] = []
        now = datetime.fromtimestamp(clock.wall, UTC)
        with _fetcher(tmp_path, routes, clock=clock, calls=calls) as fetcher:
            report = resolve_urls(
                session, resolver=fetcher, registry={}, observed_at=now, decided_at=now
            )
        assert bool(calls) is expected_work
        assert report.cooldown_skipped == (0 if expected_work else 1)
    latest = latest_capture_at(session, MENU_URL_NAMESPACE, website)
    assert latest is not None and (latest.outcome, latest.reason_code) == (outcome, reason)
    from packages.helios_core.provenance.models import SourceEndpoint, SourceRecord

    assert (
        session.scalar(
            select(func.count())
            .select_from(SourceRecordVersion)
            .join(SourceRecord, SourceRecord.id == SourceRecordVersion.source_record_id)
            .join(Source, Source.id == SourceRecord.source_id)
            .where(
                Source.namespace == MENU_URL_NAMESPACE, SourceRecord.external_key == "failure-site"
            )
        )
        == 0
    )
    assert (
        session.scalar(
            select(func.count())
            .select_from(Capture)
            .join(Source)
            .join(SourceEndpoint, SourceEndpoint.id == Capture.source_endpoint_id)
            .where(Source.namespace == MENU_URL_NAMESPACE, SourceEndpoint.canonical_uri == website)
        )
        == 2
    )


def test_registry_pipeline_hashes_loaded_file_bytes(
    session: Session, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import apps.discovery.registry as registry_module
    from apps.discovery.registry import load_registry
    from apps.discovery.url_pipeline import MENU_URL_NAMESPACE, WEBSITE_NAMESPACE
    from test.test_url_pipeline import _FakeResolver, _resolve, _seed
    from test.test_url_pipeline import _poi as url_poi

    path = tmp_path / "config" / "sources.yaml"
    path.parent.mkdir()
    raw = b"venues:\n  - host: registry.test\n    website: https://registry.test/\n    menu_url: https://registry.test/menu\n"
    path.write_bytes(raw)
    monkeypatch.setattr(registry_module, "__file__", str(tmp_path / "apps/discovery/registry.py"))
    registry = load_registry(path)
    _seed(
        session,
        [
            url_poi(
                "Registry",
                30.3,
                -97.7,
                gers_id="registry-evidence",
                websites=("https://registry.test/",),
            )
        ],
    )
    _resolve(session, _FakeResolver(None), registry)
    for namespace in (WEBSITE_NAMESPACE, MENU_URL_NAMESPACE):
        evidence, _ = _namespace_evidence(session, namespace, "registry-evidence")
        capture = source_endpoint_for_evidence(session, evidence.id)
        assert capture.source_url == "repo:config/sources.yaml"
        assert capture.content_hash == "sha256:" + hashlib.sha256(raw).hexdigest()


def test_platform_keys_share_endpoint_and_exact_retries(session: Session) -> None:
    from apps.discovery.url_pipeline import MENU_URL_NAMESPACE
    from test.test_url_pipeline import _FakeResolver, _resolve, _seed
    from test.test_url_pipeline import _poi as url_poi

    platform_url = "https://order.toasttab.com/shared-menu"
    _seed(
        session,
        [
            url_poi("Chain", 30.3, -97.7, gers_id="platform-one", websites=(platform_url,)),
            url_poi("Chain", 30.4, -97.8, gers_id="platform-two", websites=(platform_url,)),
        ],
    )
    resolver = _FakeResolver(platform_url, signal="platform")
    assert _resolve(session, resolver).menu_urls_found == 2
    first, _ = _namespace_evidence(session, MENU_URL_NAMESPACE, "platform-one|toasttab.com")
    second, _ = _namespace_evidence(session, MENU_URL_NAMESPACE, "platform-two|toasttab.com")
    first_capture = source_endpoint_for_evidence(session, first.id)
    second_capture = source_endpoint_for_evidence(session, second.id)
    assert first_capture.source_url == second_capture.source_url == platform_url
    assert _resolve(session, resolver).menu_urls_reused == 2
    assert len(resolver.calls) == 2


@pytest.mark.parametrize(
    ("statement", "params"),
    [
        (
            "INSERT INTO bronze.capture(source_id, source_endpoint_id, fetched_at, outcome) VALUES (:s, NULL, now(), 'succeeded')",
            {},
        ),
        (
            "INSERT INTO bronze.capture(source_id, source_endpoint_id, fetched_at, outcome) VALUES (:s, :e, now(), 'failed')",
            {},
        ),
        (
            "INSERT INTO bronze.capture(source_id, source_endpoint_id, fetched_at, outcome, reason_code) VALUES (:s, :e, now(), 'succeeded', 'network_error')",
            {},
        ),
        (
            "INSERT INTO bronze.capture(source_id, source_endpoint_id, fetched_at, outcome, reason_code) VALUES (:s, :e, now(), 'failed', 'BAD REASON')",
            {},
        ),
        (
            "INSERT INTO bronze.capture(source_id, source_endpoint_id, fetched_at, outcome) VALUES (:s, :e, now(), 'unknown')",
            {},
        ),
        (
            "INSERT INTO bronze.source_endpoint(source_id, canonical_uri, endpoint_kind) VALUES (:s, 'bad:fixture', 'ftp')",
            {},
        ),
        (
            "INSERT INTO bronze.evidence(source_record_version_id, locator, excerpt_hash) VALUES (:v, 'not-jsonpath', 'hash')",
            {},
        ),
    ],
)
def test_s6_database_guards(session: Session, statement: str, params: dict[str, object]) -> None:
    from sqlalchemy.exc import IntegrityError

    persisted = persist_source_record_observation(session, observation())
    with pytest.raises(IntegrityError), session.begin_nested():
        session.execute(
            text(statement),
            {
                "s": persisted.source_id,
                "e": persisted.source_endpoint_id,
                "v": persisted.source_record_version_id,
                **params,
            },
        )


def test_match_endpoint_must_belong_to_version_source(session: Session) -> None:
    from sqlalchemy.exc import IntegrityError

    first = persist_source_record_observation(session, observation())
    second = persist_source_record_observation(session, observation())
    with pytest.raises(IntegrityError), session.begin_nested():
        session.execute(
            text(
                "INSERT INTO bronze.source_record_version(source_id, source_record_id, observed_at, content_hash, source_payload, identity_match_endpoint_id) VALUES (:s, :r, now(), 'hash', '{}', :e)"
            ),
            {"s": first.source_id, "r": first.source_record_id, "e": second.source_endpoint_id},
        )


@pytest.mark.parametrize("url", ["https://facebook.com/venue", "https://order.toasttab.com/venue"])
def test_social_pages_and_platform_redirects_to_roots_are_not_menus(
    tmp_path: Path, url: str
) -> None:
    from apps.discovery.web_client import CaptureFailure
    from test.test_web_client import _fetcher

    routes = {"/venue": (302, "/", ""), "/": (200, "Order", "text/html")}
    with _fetcher(tmp_path, routes) as fetcher:
        assert isinstance(fetcher.discover_menu_attempt(url), CaptureFailure)


def test_distinct_match_endpoint_is_opt_in_and_source_scoped(session: Session) -> None:
    from packages.helios_core.identity.commands import assign_source_record, create_organization

    obs = replace(
        observation(),
        source_url="repo:test/shared-input.json",
        identity_match_url="https://match-key.test/venue",
    )
    anchor = resolve_source_record_observation(session, observation=obs, decided_at=obs.observed_at)
    target = create_organization(
        session, canonical_name="Match Target", name_fingerprint="match target"
    )
    assign_source_record(
        session,
        source_record_id=anchor.source_record_id,
        to_subject_id=target.id,
        decision=decision(),
        evidence_ids=[anchor.evidence_id],
    )
    unrelated = resolve_source_record_observation(
        session,
        observation=replace(obs, external_key="no-opt-in", identity_match_url=None),
        decided_at=obs.observed_at,
    )
    matched = resolve_source_record_observation(
        session, observation=replace(obs, external_key="opt-in"), decided_at=obs.observed_at
    )
    other_source = resolve_source_record_observation(
        session,
        observation=replace(obs, source_namespace=obs.source_namespace + "-other"),
        decided_at=obs.observed_at,
    )
    assert unrelated.state == other_source.state == "unresolved"
    assert matched.subject_id == target.id
    assert source_endpoint_for_evidence(session, matched.evidence_id).source_url == obs.source_url


def test_uncaptured_version_keeps_existing_low_level_admission_contract(session: Session) -> None:
    from packages.helios_core.identity.models import CurrentResolution
    from packages.helios_core.provenance.models import SourceRecord

    obs = observation()
    source = Source(namespace=obs.source_namespace, kind=obs.source_kind)
    session.add(source)
    session.flush()
    record = SourceRecord(source_id=source.id, external_key=obs.external_key)
    session.add(record)
    session.flush()
    version = SourceRecordVersion(
        source_id=source.id,
        source_record_id=record.id,
        observed_at=obs.observed_at,
        content_hash=obs.content_hash,
        source_payload=dict(obs.source_payload),
    )
    session.add(version)
    session.flush()
    evidence = Evidence(
        source_record_version_id=version.id,
        locator="$.id",
        excerpt_hash=excerpt_hash(dict(obs.source_payload), "$.id"),
    )
    session.add(evidence)
    session.flush()
    admit_source_record(
        session, source_record_id=record.id, decision=decision(), evidence_ids=[evidence.id]
    )
    assert (
        session.scalars(
            select(CurrentResolution.state).where(CurrentResolution.source_record_id == record.id)
        ).one()
        == "unresolved"
    )
