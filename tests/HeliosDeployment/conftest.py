"""
tests/HeliosDeployment/conftest.py — Shared fixtures for SpiritPool intake pipeline tests.

Provides:
    - In-memory SQLite database with all tables created
    - Flask test client with the contribute blueprint registered
    - Clean database session per test (rolled back after each)
"""

import os
import sys

import pytest

# Ensure project root is importable
_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

# Force SQLite in-memory for all tests — never touch production DB
os.environ["DATABASE_URL"] = "sqlite://"

from flask import Flask
from flask_cors import CORS
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from core.database import Base

# ── PostgreSQL → SQLite type adapters ─────────────────────────────────────────
# PostgreSQL JSONB and ARRAY are not renderable by SQLite.  Register compile-time
# rules that map them to generic equivalents when the dialect is SQLite.
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy import JSON, String
from sqlalchemy.ext.compiler import compiles

@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(element, compiler, **kw):
    return compiler.visit_JSON(element, **kw)

@compiles(ARRAY, "sqlite")
def _compile_array_sqlite(element, compiler, **kw):
    # Degrade ARRAY to TEXT on SQLite
    return "TEXT"


def _enable_sqlite_fk(dbapi_conn, connection_record):
    """Enable foreign key enforcement on SQLite connections."""
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


@pytest.fixture()
def engine():
    """Create a fresh in-memory SQLite engine per test.

    Using function-scope ensures complete isolation — each test starts
    with empty tables and no data leakage from prior tests.
    """
    eng = create_engine("sqlite://", echo=False)
    event.listen(eng, "connect", _enable_sqlite_fk)

    # Import all models so Base.metadata has them
    import core.metadata  # noqa: F401
    import core.models.spiritpool  # noqa: F401

    Base.metadata.create_all(eng)
    return eng


@pytest.fixture()
def db(engine):
    """Provide a database session for ORM-level tests."""
    session = Session(bind=engine)

    yield session

    session.rollback()
    session.close()


@pytest.fixture()
def seeded_db(engine):
    """Provide a database session pre-loaded with SpiritPool metadata entries.

    Calls the populate_metadata.py functions so that metadata-quality
    tests can verify completeness without touching the production DB.
    """
    session = Session(bind=engine)

    from scripts.populate_metadata import (
        populate_column_catalog,
        populate_data_lineage,
        populate_table_catalog,
    )

    populate_table_catalog(session)
    populate_column_catalog(session)
    populate_data_lineage(session)

    yield session

    session.rollback()
    session.close()


@pytest.fixture()
def app(engine, monkeypatch):
    """Create a Flask test app with the contribute blueprint and IP suppression."""
    test_app = Flask(__name__)
    test_app.config["TESTING"] = True
    test_app.config["MAX_CONTENT_LENGTH"] = 1 * 1024 * 1024
    CORS(test_app)

    # IP suppression (same as server.py)
    class _IPSuppressedRequest(Flask.request_class):
        @property
        def remote_addr(self):
            return "0.0.0.0"

        @remote_addr.setter
        def remote_addr(self, value):
            pass

    test_app.request_class = _IPSuppressedRequest

    # Patch init_db and get_session to use our shared test engine
    def _mock_init_db():
        return engine

    def _mock_get_session(eng):
        return Session(bind=eng)

    monkeypatch.setattr("core.contribute_routes.init_db", _mock_init_db)
    monkeypatch.setattr("core.contribute_routes.get_session", _mock_get_session)

    from core.contribute_routes import contribute_bp
    test_app.register_blueprint(contribute_bp)

    # Register legacy spiritpool blueprint for E2E legacy path tests
    monkeypatch.setattr("postings.spiritpool_routes.init_db", _mock_init_db)
    monkeypatch.setattr("postings.spiritpool_routes.get_session", _mock_get_session)
    # Mock ingest_job_posting — legacy path writes to job_postings which we don't
    # need for sp_events dual-write validation.  Return a fake JobPosting-like object.
    monkeypatch.setattr(
        "postings.spiritpool_routes.ingest_job_posting",
        lambda signal, region=None, session=None: (type("FakePosting", (), {"id": 1})(), False),
    )

    from postings.spiritpool_routes import spiritpool_bp
    test_app.register_blueprint(spiritpool_bp)

    monkeypatch.setattr("collectors.meal_deals.routes.get_engine", _mock_init_db)
    monkeypatch.setattr("collectors.meal_deals.routes.get_session", _mock_get_session)
    monkeypatch.setattr("collectors.meal_deals.routes._engine", None, raising=False)

    from collectors.meal_deals.routes import deals_bp
    test_app.register_blueprint(deals_bp)

    return test_app


@pytest.fixture()
def client(app):
    """Flask test client."""
    return app.test_client()


# ── Common test payloads ─────────────────────────────────────────────────────

@pytest.fixture()
def clean_signal():
    """A valid, PII-free contributor signal."""
    return {
        "session_token": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
        "epoch_id": 1,
        "event_type": "job_listing",
        "source": "indeed",
        "domain": "jobs",
        "payload": {
            "company": "Whole Foods Market",
            "jobTitle": "Grocery Team Member",
            "location": "Austin, TX 78701",
            "salary": {"min": 16, "max": 20, "period": "hourly"},
        },
    }


@pytest.fixture()
def pii_signal_email():
    """A signal with PII (email) in the payload."""
    return {
        "session_token": "b2c3d4e5-f6a7-8901-bcde-f12345678901",
        "epoch_id": 1,
        "event_type": "job_listing",
        "source": "indeed",
        "domain": "jobs",
        "payload": {
            "company": "Acme Corp",
            "jobTitle": "Sales Rep",
            "contact": "hiring@acme.com",
        },
    }
