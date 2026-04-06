"""
core/models/dev_capture.py — ORM model for dev-mode raw signal captures.

Table lives in the ``dev_capture`` PostgreSQL schema, fully separated from
production tables in ``public``.  On SQLite (local tests) the schema qualifier
is silently ignored and the table is created in the default namespace.

Purpose:
    When the SpiritPool extension runs in dev mode, each signal includes:
      1. raw_html    — outerHTML of the job-card DOM element
      2. extracted   — pre-sanitization fields (exact values the parser found)
      3. sanitized   — post-sanitization fields (fuzzed, stripped, session attached)

    This enables A/B comparison between what the DOM contained and what the
    Helios privacy pipeline produced, without tainting production tables.

Layer: dev (not queryable by external APIs or dashboards)

Depends on: core.database.Base
Called by: postings.spiritpool_routes._store_dev_capture()
"""

from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB

from core.database import Base


class RawSignalCapture(Base):
    """One dev-mode capture — raw HTML + extracted fields + sanitized fields.

    Stored in the ``dev_capture`` schema to avoid data tainting.
    Never mixed with sp_events, job_postings, or quarantine.
    """

    __tablename__ = "raw_signals"
    __table_args__ = {"schema": "dev_capture"}

    id = Column(Integer, primary_key=True, autoincrement=True)

    # ── Provenance ───────────────────────────────────────────────────────────
    domain = Column(String, nullable=False)             # "linkedin", "indeed", etc.
    session_token = Column(Text, nullable=False)        # opaque contributor identity
    captured_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    # ── Three layers for A/B comparison ──────────────────────────────────────
    raw_html = Column(Text, nullable=True)              # full outerHTML of job card element
    extracted_fields = Column(JSONB, nullable=False)     # pre-sanitization signal (exact parser output)
    sanitized_fields = Column(JSONB, nullable=False)     # post-sanitization signal (fuzzed + stripped)

    # ── Pipeline metadata ────────────────────────────────────────────────────
    extraction_source = Column(String, nullable=True)    # e.g. "content/linkedin.js"
    pipeline_version = Column(Integer, nullable=False, default=1)
