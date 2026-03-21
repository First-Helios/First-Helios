"""
Shared pytest fixtures for First-Helios test suite.

Provides:
  - mem_engine   : fresh SQLite in-memory engine per test
  - mem_session  : assertion-only session on the same engine
  - sample_*     : pre-built ORM instances and ScraperSignals
  - AgentQuery builders for common query types
"""

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Import all ORM models so Base.metadata is fully populated before create_all
from backend.database import (
    ApiRequestLog,
    ApiSource,
    Base,
    LocalEmployer,
    RateBudget,
    Score,
    Signal,
    Snapshot,
    SourceFreshness,
    Store,
    WageIndex,
)

# StoreAlias lives in dedup — must import so its table registers with Base.metadata
import backend.dedup  # noqa: F401  (side-effect: registers StoreAlias)

# Silence the optional reference-model import failure
try:
    import backend.models.reference  # noqa: F401
except ImportError:
    pass

from agent_interface.schemas import (
    AgentMode,
    AgentQuery,
    Brand,
    DataSource,
    Industry,
    Intent,
    QueuePriority,
    Region,
)
from scrapers.base import ScraperSignal


# ── In-memory database fixtures ───────────────────────────────────────────────


@pytest.fixture
def mem_engine():
    """Fresh SQLite in-memory engine with all tables created, per test."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        echo=False,
    )
    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture
def mem_session(mem_engine):
    """Assertion-only session bound to mem_engine.

    Does NOT get closed by the system under test — keep it separate so
    functions that manage their own session lifecycle don't kill this one.
    """
    Session = sessionmaker(bind=mem_engine)
    session = Session()
    yield session
    session.rollback()
    session.close()


# ── ORM sample data fixtures ──────────────────────────────────────────────────


@pytest.fixture
def sample_store(mem_session):
    """Active store with coordinates, last_seen 1 day ago."""
    store = Store(
        store_num="SB-TEST-001",
        chain="starbucks",
        industry="coffee_cafe",
        store_name="Starbucks Congress Ave",
        address="600 Congress Ave, Austin, TX",
        lat=30.2672,
        lng=-97.7431,
        region="austin_tx",
        first_seen=datetime.utcnow() - timedelta(days=10),
        last_seen=datetime.utcnow() - timedelta(days=1),
        is_active=True,
    )
    mem_session.add(store)
    mem_session.commit()
    return store


@pytest.fixture
def sample_store_stale(mem_session):
    """Active store whose last_seen is 70 days ago (stale for poi_chain_locations)."""
    store = Store(
        store_num="SB-TEST-002",
        chain="starbucks",
        industry="coffee_cafe",
        store_name="Starbucks Lamar",
        address="1234 S Lamar Blvd, Austin, TX",
        lat=30.2500,
        lng=-97.7700,
        region="austin_tx",
        first_seen=datetime.utcnow() - timedelta(days=100),
        last_seen=datetime.utcnow() - timedelta(days=70),
        is_active=True,
    )
    mem_session.add(store)
    mem_session.commit()
    return store


@pytest.fixture
def sample_listing_signal(mem_session, sample_store):
    """A listing Signal for SB-TEST-001, observed 2 days ago."""
    sig = Signal(
        store_num="SB-TEST-001",
        source="careers_api",
        signal_type="listing",
        value=1.0,
        observed_at=datetime.utcnow() - timedelta(days=2),
    )
    sig.set_metadata({"posted_date": (datetime.utcnow() - timedelta(days=2)).isoformat()})
    mem_session.add(sig)
    mem_session.commit()
    return sig


@pytest.fixture
def sample_sentiment_signal(mem_session, sample_store):
    """A sentiment Signal for SB-TEST-001."""
    sig = Signal(
        store_num="SB-TEST-001",
        source="reddit",
        signal_type="sentiment",
        value=0.7,
        observed_at=datetime.utcnow() - timedelta(days=3),
    )
    sig.set_metadata({})
    mem_session.add(sig)
    mem_session.commit()
    return sig


@pytest.fixture
def sample_wage_index(mem_session):
    """A local (non-chain) WageIndex row."""
    wage = WageIndex(
        employer="Local Coffee LLC",
        is_chain=False,
        chain_key=None,
        industry="coffee_cafe",
        role_title="Barista",
        wage_min=16.0,
        wage_max=20.0,
        wage_period="hourly",
        location="Austin, TX",
        source="bls_v1",
        observed_at=datetime.utcnow() - timedelta(days=5),
    )
    mem_session.add(wage)
    mem_session.commit()
    return wage


@pytest.fixture
def sample_scraper_signal():
    """A ScraperSignal ready to be ingested (listing type, with coordinates)."""
    return ScraperSignal(
        store_num="SB-INGEST-001",
        chain="starbucks",
        source="careers_api",
        signal_type="listing",
        value=1.0,
        metadata={
            "lat": 30.2672,
            "lng": -97.7431,
            "address": "600 Congress Ave, Austin, TX",
            "store_name": "Starbucks Congress Ave",
        },
        observed_at=datetime.utcnow(),
    )


@pytest.fixture
def sample_wage_scraper_signal():
    """A wage-type ScraperSignal with min/max fields."""
    return ScraperSignal(
        store_num="SB-INGEST-001",
        chain="starbucks",
        source="bls_v1",
        signal_type="wage",
        value=17.5,
        metadata={
            "industry": "coffee_cafe",
            "location": "Austin, TX",
            "employer": "Starbucks",
            "is_chain": True,
        },
        wage_min=15.0,
        wage_max=20.0,
        wage_period="hourly",
        role_title="Barista",
        observed_at=datetime.utcnow(),
    )


# ── AgentQuery builder fixtures ───────────────────────────────────────────────


@pytest.fixture
def poi_chain_query():
    """Valid POI_CHAIN_LOCATIONS query in MIXED mode."""
    return AgentQuery(
        intent=Intent.POI_CHAIN_LOCATIONS,
        region=Region.AUSTIN_TX,
        mode=AgentMode.MIXED,
        brand=Brand.STARBUCKS,
        max_results=100,
        max_budget_spend=5,
    )


@pytest.fixture
def wage_baseline_query():
    """Valid WAGE_BASELINE query in COLLECT mode."""
    return AgentQuery(
        intent=Intent.WAGE_BASELINE,
        region=Region.AUSTIN_TX,
        mode=AgentMode.COLLECT,
        industry=Industry.COFFEE_CAFE,
        max_budget_spend=3,
    )


@pytest.fixture
def score_refresh_query():
    """Valid SCORE_REFRESH query in ANALYZE mode."""
    return AgentQuery(
        intent=Intent.SCORE_REFRESH,
        region=Region.AUSTIN_TX,
        mode=AgentMode.ANALYZE,
    )


@pytest.fixture
def job_posting_query():
    """Valid JOB_POSTING_VOLUME query in MIXED mode."""
    return AgentQuery(
        intent=Intent.JOB_POSTING_VOLUME,
        region=Region.AUSTIN_TX,
        mode=AgentMode.MIXED,
        brand=Brand.STARBUCKS,
        max_budget_spend=5,
    )


# ── Mock fixtures for external dependencies ───────────────────────────────────


@pytest.fixture
def mock_rate_manager_has_budget():
    """rate_manager.can_request always returns True (budget available)."""
    with patch("agent_interface.validator.rate_manager") as mock_rm:
        mock_rm.can_request.return_value = True
        mock_rm.get_source_status.return_value = {
            "budget": {"used": 0, "remaining": 100, "daily_limit": 100}
        }
        yield mock_rm


@pytest.fixture
def mock_rate_manager_no_budget():
    """rate_manager.can_request always returns False (all sources exhausted)."""
    with patch("agent_interface.validator.rate_manager") as mock_rm:
        mock_rm.can_request.return_value = False
        mock_rm.get_source_status.return_value = {
            "budget": {"used": 100, "remaining": 0, "daily_limit": 100}
        }
        yield mock_rm


@pytest.fixture
def mock_config_loader():
    """Patch config.loader functions used by scoring modules at their call sites."""
    tiers = {
        "critical": {"min_percentile": 67},
        "elevated": {"min_percentile": 33},
        "adequate": {"min_percentile": 0},
    }
    weights = {"careers_api": 0.40, "job_boards": 0.35, "sentiment": 0.25}
    decay = {"fresh_days": 7, "stale_days": 90}

    patches = [
        patch("backend.scoring.careers.get_score_tiers", return_value=tiers),
        patch("backend.scoring.careers.get_posting_age_decay", return_value=decay),
        patch("backend.scoring.sentiment.get_score_tiers", return_value=tiers),
        patch("backend.scoring.wage.get_score_tiers", return_value=tiers),
        patch("backend.scoring.engine.get_scoring_weights", return_value=weights),
        patch("backend.scoring.engine.get_score_tiers", return_value=tiers),
    ]
    started = [p.start() for p in patches]
    yield {"tiers": tiers, "weights": weights, "decay": decay}
    for p in patches:
        p.stop()


@pytest.fixture
def mock_geocode():
    """scrapers.geocoding.geocode always returns Austin coordinates."""
    with patch("backend.ingest.geocode") as mock_geo:
        mock_geo.return_value = (30.2672, -97.7431)
        yield mock_geo


@pytest.fixture
def mock_get_chain():
    """config.loader.get_chain returns a minimal chain config."""
    with patch("backend.ingest.get_chain") as mock_chain:
        mock_chain.return_value = {"industry": "coffee_cafe", "display_name": "Starbucks"}
        yield mock_chain
