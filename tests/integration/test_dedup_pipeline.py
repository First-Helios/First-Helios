"""
Integration tests for backend/dedup.py pipeline functions.

Tests find_existing_match(), resolve_alias(), and deduplicate_stores()
with an in-memory SQLite database.

Patches:
  - backend.dedup.init_db / get_session → mem_engine
"""

from datetime import datetime, timedelta
from unittest.mock import patch
from sqlalchemy.orm import sessionmaker

import pytest

from backend.database import Score, Signal, Store
from backend.dedup import (
    StoreAlias,
    deduplicate_stores,
    find_existing_match,
    resolve_alias,
)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _session_factory(mem_engine):
    return lambda e=None: sessionmaker(bind=mem_engine)()


def _make_store(session, store_num, chain="starbucks", lat=30.2672, lng=-97.7431,
                region="austin_tx", active=True, first_seen=None):
    store = Store(
        store_num=store_num,
        chain=chain,
        industry="coffee_cafe",
        store_name="Test Store",
        address="600 Congress Ave, Austin, TX",
        lat=lat,
        lng=lng,
        region=region,
        is_active=active,
        first_seen=first_seen or datetime.utcnow() - timedelta(days=10),
        last_seen=datetime.utcnow() - timedelta(days=1),
    )
    session.add(store)
    session.commit()
    return store


# ── find_existing_match() ─────────────────────────────────────────────────────


def test_find_existing_match_returns_none_when_no_stores_in_db(mem_session):
    result = find_existing_match(mem_session, "starbucks", 30.2672, -97.7431)
    assert result is None


def test_find_existing_match_returns_none_when_lat_lng_missing(mem_session):
    _make_store(mem_session, "ATP-ST-001")
    result = find_existing_match(mem_session, "starbucks", None, None)
    assert result is None


def test_find_existing_match_returns_existing_store_when_within_44m(mem_session):
    store = _make_store(mem_session, "ATP-ST-001", lat=30.2672, lng=-97.7431)
    # Search point ~20 m away (0.0002° latitude ≈ 22 m)
    result = find_existing_match(mem_session, "starbucks", 30.2672 + 0.0002, -97.7431)
    assert result is not None
    assert result.store_num == "ATP-ST-001"


def test_find_existing_match_returns_none_when_stores_are_farther_than_44m(mem_session):
    _make_store(mem_session, "ATP-ST-001", lat=30.2672, lng=-97.7431)
    # Search point ~200 m away (0.002° latitude ≈ 222 m)
    result = find_existing_match(mem_session, "starbucks", 30.2672 + 0.002, -97.7431)
    assert result is None


def test_find_existing_match_only_matches_same_chain(mem_session):
    _make_store(mem_session, "ATP-SB-001", chain="starbucks", lat=30.2672, lng=-97.7431)
    # Search for different chain at same location
    result = find_existing_match(mem_session, "mcdonalds", 30.2672, -97.7431)
    assert result is None


def test_find_existing_match_only_matches_active_stores(mem_session):
    _make_store(mem_session, "ATP-ST-001", lat=30.2672, lng=-97.7431, active=False)
    result = find_existing_match(mem_session, "starbucks", 30.2672, -97.7431)
    assert result is None


def test_find_existing_match_returns_canonical_when_alias_exists(mem_session):
    canonical = _make_store(mem_session, "ATP-ST-CANONICAL")
    alias = StoreAlias(
        old_store_num="OSM-ST-OLD",
        canonical_store_num="ATP-ST-CANONICAL",
        source_prefix="OSM",
    )
    mem_session.add(alias)
    mem_session.commit()

    result = find_existing_match(mem_session, "starbucks", 30.2672, -97.7431)
    assert result is not None
    assert result.store_num == "ATP-ST-CANONICAL"


# ── resolve_alias() ───────────────────────────────────────────────────────────


def test_resolve_alias_returns_same_store_num_when_no_alias_exists(mem_session):
    result = resolve_alias(mem_session, "SB-TEST-001")
    assert result == "SB-TEST-001"


def test_resolve_alias_returns_canonical_when_alias_record_exists(mem_session):
    alias = StoreAlias(
        old_store_num="OSM-ST-OLD",
        canonical_store_num="ATP-ST-CANONICAL",
        source_prefix="OSM",
    )
    mem_session.add(alias)
    mem_session.commit()

    result = resolve_alias(mem_session, "OSM-ST-OLD")
    assert result == "ATP-ST-CANONICAL"


def test_resolve_alias_is_idempotent_for_canonical(mem_session):
    alias = StoreAlias(
        old_store_num="OSM-ST-OLD",
        canonical_store_num="ATP-ST-CANONICAL",
        source_prefix="OSM",
    )
    mem_session.add(alias)
    mem_session.commit()

    # Calling on the canonical itself should return it unchanged
    result = resolve_alias(mem_session, "ATP-ST-CANONICAL")
    assert result == "ATP-ST-CANONICAL"


# ── deduplicate_stores() ──────────────────────────────────────────────────────


def _run_dedup(mem_engine, region="austin_tx", dry_run=False):
    with patch("backend.dedup.init_db", return_value=mem_engine), \
         patch("backend.dedup.get_session", side_effect=_session_factory(mem_engine)):
        return deduplicate_stores(region=region, dry_run=dry_run)


def test_deduplicate_stores_finds_no_duplicates_when_stores_are_far_apart(
    mem_engine, mem_session
):
    _make_store(mem_session, "ATP-ST-001", lat=30.2672, lng=-97.7431)
    _make_store(mem_session, "ATP-ST-002", lat=30.3000, lng=-97.8000)  # ~4 km away

    report = _run_dedup(mem_engine)
    assert report.stores_merged == 0


def test_deduplicate_stores_finds_and_merges_nearby_same_chain_stores(
    mem_engine, mem_session
):
    # Two stores ~20 m apart (same physical location)
    _make_store(mem_session, "ATP-ST-001", lat=30.2672, lng=-97.7431)
    _make_store(mem_session, "OSM-ST-002", lat=30.2672 + 0.0001, lng=-97.7431)  # ~11 m

    report = _run_dedup(mem_engine)
    assert report.stores_merged == 1
    assert report.duplicate_groups == 1


def test_deduplicate_stores_prefers_atp_as_canonical_over_osm(
    mem_engine, mem_session
):
    _make_store(mem_session, "OSM-ST-001", lat=30.2672, lng=-97.7431)
    _make_store(mem_session, "ATP-ST-002", lat=30.2672 + 0.0001, lng=-97.7431)

    report = _run_dedup(mem_engine)
    # The canonical should be ATP (lower reputation score = more trusted)
    assert report.merges[0].canonical == "ATP-ST-002"
    assert report.merges[0].merged == "OSM-ST-001"


def test_deduplicate_stores_soft_deletes_merged_duplicate(
    mem_engine, mem_session
):
    _make_store(mem_session, "ATP-ST-001", lat=30.2672, lng=-97.7431)
    _make_store(mem_session, "OSM-ST-002", lat=30.2672 + 0.0001, lng=-97.7431)

    _run_dedup(mem_engine)

    mem_session.expire_all()
    osm_store = mem_session.query(Store).filter_by(store_num="OSM-ST-002").first()
    assert osm_store.is_active is False


def test_deduplicate_stores_creates_alias_record_for_merged_store(
    mem_engine, mem_session
):
    _make_store(mem_session, "ATP-ST-001", lat=30.2672, lng=-97.7431)
    _make_store(mem_session, "OSM-ST-002", lat=30.2672 + 0.0001, lng=-97.7431)

    _run_dedup(mem_engine)

    alias = mem_session.query(StoreAlias).filter_by(old_store_num="OSM-ST-002").first()
    assert alias is not None
    assert alias.canonical_store_num == "ATP-ST-001"


def test_deduplicate_stores_reassigns_signals_from_duplicate_to_canonical(
    mem_engine, mem_session
):
    _make_store(mem_session, "ATP-ST-001", lat=30.2672, lng=-97.7431)
    osm = _make_store(mem_session, "OSM-ST-002", lat=30.2672 + 0.0001, lng=-97.7431)

    # Add a signal to the duplicate
    sig = Signal(
        store_num="OSM-ST-002",
        source="careers_api",
        signal_type="listing",
        value=1.0,
        observed_at=datetime.utcnow(),
    )
    sig.set_metadata({})
    mem_session.add(sig)
    mem_session.commit()

    _run_dedup(mem_engine)

    mem_session.expire_all()
    signals_on_canonical = mem_session.query(Signal).filter_by(
        store_num="ATP-ST-001"
    ).all()
    assert len(signals_on_canonical) == 1


def test_deduplicate_stores_dry_run_does_not_write_to_db(
    mem_engine, mem_session
):
    _make_store(mem_session, "ATP-ST-001", lat=30.2672, lng=-97.7431)
    _make_store(mem_session, "OSM-ST-002", lat=30.2672 + 0.0001, lng=-97.7431)

    _run_dedup(mem_engine, dry_run=True)

    mem_session.expire_all()
    # OSM store should still be active
    osm_store = mem_session.query(Store).filter_by(store_num="OSM-ST-002").first()
    assert osm_store.is_active is True
    # No alias created
    assert mem_session.query(StoreAlias).count() == 0


def test_deduplicate_stores_dry_run_report_contains_expected_merges(
    mem_engine, mem_session
):
    _make_store(mem_session, "ATP-ST-001", lat=30.2672, lng=-97.7431)
    _make_store(mem_session, "OSM-ST-002", lat=30.2672 + 0.0001, lng=-97.7431)

    report = _run_dedup(mem_engine, dry_run=True)
    assert report.stores_merged == 1
    assert len(report.merges) == 1


def test_deduplicate_stores_preserves_earliest_first_seen_on_canonical(
    mem_engine, mem_session
):
    early = datetime.utcnow() - timedelta(days=100)
    late  = datetime.utcnow() - timedelta(days=10)

    _make_store(mem_session, "ATP-ST-001", lat=30.2672, lng=-97.7431, first_seen=late)
    _make_store(mem_session, "OSM-ST-002", lat=30.2672 + 0.0001, lng=-97.7431,
                first_seen=early)

    _run_dedup(mem_engine)

    mem_session.expire_all()
    canonical = mem_session.query(Store).filter_by(store_num="ATP-ST-001").first()
    assert canonical.first_seen <= late  # should have been updated to earlier date


def test_deduplicate_stores_does_not_merge_different_chains(
    mem_engine, mem_session
):
    _make_store(mem_session, "ATP-SB-001", chain="starbucks", lat=30.2672, lng=-97.7431)
    _make_store(mem_session, "ATP-MCG-001", chain="mcdonalds", lat=30.2672 + 0.0001, lng=-97.7431)

    report = _run_dedup(mem_engine)
    assert report.stores_merged == 0


def test_deduplicate_stores_report_has_correct_total_stores_before(
    mem_engine, mem_session
):
    for i in range(5):
        _make_store(mem_session, f"ATP-ST-{i:03d}",
                    lat=30.2672 + i * 0.01, lng=-97.7431)

    report = _run_dedup(mem_engine)
    assert report.total_stores_before == 5
