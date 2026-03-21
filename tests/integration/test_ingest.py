"""
Integration tests for backend/ingest.py — ingest_signals().

Uses an in-memory SQLite database. Patches:
  - backend.ingest.init_db    → returns mem_engine
  - backend.ingest.get_session → returns a fresh session from mem_engine
  - backend.ingest.get_chain  → returns minimal chain config
  - backend.ingest.find_existing_match → default None (no spatial duplicate)
  - backend.ingest.resolve_alias → identity (no aliases)
  - backend.ingest.geocode     → returns fixed Austin coordinates
"""

from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock

import pytest
from sqlalchemy.orm import sessionmaker

from backend.database import Signal, Snapshot, Store, WageIndex
from backend.ingest import ingest_signals
from scrapers.base import ScraperSignal


# ── Helpers ───────────────────────────────────────────────────────────────────


def _session_factory(mem_engine):
    """Return a callable that always produces a new session from mem_engine."""
    return lambda e=None: sessionmaker(bind=mem_engine)()


def _run_ingest(mem_engine, signals, region="austin_tx", chain=None, source=None,
                find_match=None, geocode_result=(30.2672, -97.7431)):
    """Run ingest_signals with all external deps patched to use mem_engine."""
    with patch("backend.ingest.init_db", return_value=mem_engine), \
         patch("backend.ingest.get_session", side_effect=_session_factory(mem_engine)), \
         patch("backend.ingest.get_chain", return_value={"industry": "coffee_cafe"}), \
         patch("backend.ingest.find_existing_match", return_value=find_match), \
         patch("backend.ingest.resolve_alias", side_effect=lambda s, x: x), \
         patch("scrapers.geocoding.geocode", return_value=geocode_result):
        return ingest_signals(signals, region=region, chain=chain, source=source)


# ── Empty input ───────────────────────────────────────────────────────────────


def test_ingest_signals_returns_zero_for_empty_list(mem_engine, mem_session):
    count = _run_ingest(mem_engine, [])
    assert count == 0


def test_ingest_signals_does_not_create_snapshot_for_empty_list(mem_engine, mem_session):
    _run_ingest(mem_engine, [])
    assert mem_session.query(Snapshot).count() == 0


# ── Store creation ────────────────────────────────────────────────────────────


def test_ingest_signals_creates_store_row_for_new_store(
    mem_engine, mem_session, sample_scraper_signal
):
    _run_ingest(mem_engine, [sample_scraper_signal])
    store = mem_session.query(Store).filter_by(store_num="SB-INGEST-001").first()
    assert store is not None


def test_ingest_signals_sets_correct_region_on_created_store(
    mem_engine, mem_session, sample_scraper_signal
):
    _run_ingest(mem_engine, [sample_scraper_signal], region="austin_tx")
    store = mem_session.query(Store).filter_by(store_num="SB-INGEST-001").first()
    assert store.region == "austin_tx"


def test_ingest_signals_sets_chain_on_created_store(
    mem_engine, mem_session, sample_scraper_signal
):
    _run_ingest(mem_engine, [sample_scraper_signal])
    store = mem_session.query(Store).filter_by(store_num="SB-INGEST-001").first()
    assert store.chain == "starbucks"


def test_ingest_signals_sets_industry_from_chain_config(
    mem_engine, mem_session, sample_scraper_signal
):
    _run_ingest(mem_engine, [sample_scraper_signal])
    store = mem_session.query(Store).filter_by(store_num="SB-INGEST-001").first()
    assert store.industry == "coffee_cafe"


def test_ingest_signals_uses_unknown_industry_when_chain_config_missing(
    mem_engine, mem_session, sample_scraper_signal
):
    with patch("backend.ingest.init_db", return_value=mem_engine), \
         patch("backend.ingest.get_session", side_effect=_session_factory(mem_engine)), \
         patch("backend.ingest.get_chain", side_effect=KeyError("not found")), \
         patch("backend.ingest.find_existing_match", return_value=None), \
         patch("backend.ingest.resolve_alias", side_effect=lambda s, x: x), \
         patch("scrapers.geocoding.geocode", return_value=(30.2672, -97.7431)):
        ingest_signals([sample_scraper_signal], region="austin_tx")
    store = mem_session.query(Store).filter_by(store_num="SB-INGEST-001").first()
    assert store.industry == "unknown"


# ── Store upsert (existing store) ─────────────────────────────────────────────


def test_ingest_signals_updates_last_seen_for_existing_store(
    mem_engine, mem_session, sample_scraper_signal
):
    old_ts = datetime.utcnow() - timedelta(days=10)
    existing = Store(
        store_num="SB-INGEST-001",
        chain="starbucks",
        industry="coffee_cafe",
        store_name="",
        address="",
        region="austin_tx",
        last_seen=old_ts,
        is_active=True,
    )
    mem_session.add(existing)
    mem_session.commit()

    _run_ingest(mem_engine, [sample_scraper_signal])

    mem_session.expire_all()
    updated = mem_session.query(Store).filter_by(store_num="SB-INGEST-001").first()
    assert updated.last_seen > old_ts


def test_ingest_signals_does_not_create_duplicate_store_for_same_store_num(
    mem_engine, mem_session, sample_scraper_signal
):
    _run_ingest(mem_engine, [sample_scraper_signal, sample_scraper_signal])
    stores = mem_session.query(Store).filter_by(store_num="SB-INGEST-001").all()
    assert len(stores) == 1


# ── Signal insertion ──────────────────────────────────────────────────────────


def test_ingest_signals_creates_signal_row_for_each_input_signal(
    mem_engine, mem_session, sample_scraper_signal
):
    _run_ingest(mem_engine, [sample_scraper_signal])
    sigs = mem_session.query(Signal).filter_by(store_num="SB-INGEST-001").all()
    assert len(sigs) == 1


def test_ingest_signals_creates_multiple_signal_rows_for_multiple_inputs(
    mem_engine, mem_session, sample_scraper_signal
):
    sig2 = ScraperSignal(
        store_num="SB-INGEST-002",
        chain="starbucks",
        source="careers_api",
        signal_type="listing",
        value=1.0,
        metadata={"lat": 30.25, "lng": -97.74},
        observed_at=datetime.utcnow(),
    )
    _run_ingest(mem_engine, [sample_scraper_signal, sig2])
    assert mem_session.query(Signal).count() == 2


def test_ingest_signals_stores_metadata_as_json_on_signal_row(
    mem_engine, mem_session, sample_scraper_signal
):
    _run_ingest(mem_engine, [sample_scraper_signal])
    sig = mem_session.query(Signal).filter_by(store_num="SB-INGEST-001").first()
    meta = sig.get_metadata()
    assert "lat" in meta
    assert meta["lat"] == 30.2672


def test_ingest_signals_returns_count_equal_to_number_of_signals(
    mem_engine, mem_session, sample_scraper_signal
):
    count = _run_ingest(mem_engine, [sample_scraper_signal])
    assert count == 1


# ── WageIndex insertion ───────────────────────────────────────────────────────


def test_ingest_signals_creates_wage_index_row_for_wage_signal(
    mem_engine, mem_session, sample_wage_scraper_signal
):
    _run_ingest(mem_engine, [sample_wage_scraper_signal])
    wage_rows = mem_session.query(WageIndex).all()
    assert len(wage_rows) == 1
    assert wage_rows[0].wage_min == 15.0
    assert wage_rows[0].wage_max == 20.0


def test_ingest_signals_does_not_create_wage_index_for_listing_signal(
    mem_engine, mem_session, sample_scraper_signal
):
    _run_ingest(mem_engine, [sample_scraper_signal])
    assert mem_session.query(WageIndex).count() == 0


def test_ingest_signals_skips_wage_index_when_no_wage_min_or_max(
    mem_engine, mem_session
):
    sig = ScraperSignal(
        store_num="SB-INGEST-003",
        chain="starbucks",
        source="bls_v1",
        signal_type="wage",
        value=0.0,
        metadata={},
        wage_min=None,
        wage_max=None,
        observed_at=datetime.utcnow(),
    )
    _run_ingest(mem_engine, [sig])
    assert mem_session.query(WageIndex).count() == 0


# ── Snapshot creation ─────────────────────────────────────────────────────────


def test_ingest_signals_creates_snapshot_row_after_ingestion(
    mem_engine, mem_session, sample_scraper_signal
):
    _run_ingest(mem_engine, [sample_scraper_signal])
    snapshots = mem_session.query(Snapshot).all()
    assert len(snapshots) == 1


def test_ingest_signals_snapshot_has_correct_store_count_and_signal_count(
    mem_engine, mem_session, sample_scraper_signal
):
    _run_ingest(mem_engine, [sample_scraper_signal])
    snap = mem_session.query(Snapshot).first()
    assert snap.store_count == 1
    assert snap.signal_count == 1


def test_ingest_signals_infers_chain_from_first_signal_when_not_provided(
    mem_engine, mem_session, sample_scraper_signal
):
    _run_ingest(mem_engine, [sample_scraper_signal], chain=None)
    snap = mem_session.query(Snapshot).first()
    assert snap.chain == "starbucks"


# ── Dedup via spatial match ───────────────────────────────────────────────────


def test_ingest_signals_deduplicates_store_when_spatial_match_found(
    mem_engine, mem_session
):
    # Pre-create a canonical store
    canonical = Store(
        store_num="ATP-ST-CANONICAL",
        chain="starbucks",
        industry="coffee_cafe",
        store_name="Canonical Starbucks",
        address="600 Congress Ave",
        lat=30.2672,
        lng=-97.7431,
        region="austin_tx",
        last_seen=datetime.utcnow() - timedelta(days=5),
        is_active=True,
    )
    mem_session.add(canonical)
    mem_session.commit()

    new_sig = ScraperSignal(
        store_num="OSM-ST-NEW",
        chain="starbucks",
        source="osm",
        signal_type="listing",
        value=1.0,
        metadata={"lat": 30.2672, "lng": -97.7431},
        observed_at=datetime.utcnow(),
    )

    with patch("backend.ingest.init_db", return_value=mem_engine), \
         patch("backend.ingest.get_session", side_effect=_session_factory(mem_engine)), \
         patch("backend.ingest.get_chain", return_value={"industry": "coffee_cafe"}), \
         patch("backend.ingest.find_existing_match", return_value=canonical), \
         patch("backend.ingest.resolve_alias", side_effect=lambda s, x: x), \
         patch("scrapers.geocoding.geocode", return_value=(30.2672, -97.7431)):
        ingest_signals([new_sig], region="austin_tx")

    # Should NOT create a new store; signal should be attached to canonical
    stores = mem_session.query(Store).filter_by(chain="starbucks").all()
    active = [s for s in stores if s.is_active]
    assert len(active) == 1

    # Signal should reference the canonical store
    sigs = mem_session.query(Signal).filter_by(store_num="ATP-ST-CANONICAL").all()
    assert len(sigs) == 1


# ── Geocoding ─────────────────────────────────────────────────────────────────


def test_ingest_signals_calls_geocode_when_address_present_and_no_coordinates(
    mem_engine, mem_session
):
    sig = ScraperSignal(
        store_num="SB-INGEST-NOGEO",
        chain="starbucks",
        source="careers_api",
        signal_type="listing",
        value=1.0,
        metadata={"address": "600 Congress Ave, Austin, TX"},  # no lat/lng
        observed_at=datetime.utcnow(),
    )

    geocode_mock = MagicMock(return_value=(30.2672, -97.7431))
    with patch("backend.ingest.init_db", return_value=mem_engine), \
         patch("backend.ingest.get_session", side_effect=_session_factory(mem_engine)), \
         patch("backend.ingest.get_chain", return_value={"industry": "coffee_cafe"}), \
         patch("backend.ingest.find_existing_match", return_value=None), \
         patch("backend.ingest.resolve_alias", side_effect=lambda s, x: x), \
         patch("scrapers.geocoding.geocode", geocode_mock):
        ingest_signals([sig], region="austin_tx")

    geocode_mock.assert_called_once()


def test_ingest_signals_does_not_call_geocode_when_coordinates_provided(
    mem_engine, mem_session, sample_scraper_signal
):
    geocode_mock = MagicMock(return_value=(30.2672, -97.7431))
    with patch("backend.ingest.init_db", return_value=mem_engine), \
         patch("backend.ingest.get_session", side_effect=_session_factory(mem_engine)), \
         patch("backend.ingest.get_chain", return_value={"industry": "coffee_cafe"}), \
         patch("backend.ingest.find_existing_match", return_value=None), \
         patch("backend.ingest.resolve_alias", side_effect=lambda s, x: x), \
         patch("scrapers.geocoding.geocode", geocode_mock):
        ingest_signals([sample_scraper_signal], region="austin_tx")

    geocode_mock.assert_not_called()


def test_ingest_signals_continues_when_geocode_raises_exception(
    mem_engine, mem_session
):
    sig = ScraperSignal(
        store_num="SB-INGEST-BADGEO",
        chain="starbucks",
        source="careers_api",
        signal_type="listing",
        value=1.0,
        metadata={"address": "Bad Address"},
        observed_at=datetime.utcnow(),
    )
    with patch("backend.ingest.init_db", return_value=mem_engine), \
         patch("backend.ingest.get_session", side_effect=_session_factory(mem_engine)), \
         patch("backend.ingest.get_chain", return_value={"industry": "coffee_cafe"}), \
         patch("backend.ingest.find_existing_match", return_value=None), \
         patch("backend.ingest.resolve_alias", side_effect=lambda s, x: x), \
         patch("scrapers.geocoding.geocode", side_effect=Exception("geocode failed")):
        count = ingest_signals([sig], region="austin_tx")

    # Should still ingest the signal despite geocode failure
    assert count == 1
