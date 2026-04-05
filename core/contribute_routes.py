"""
core/contribute_routes.py — Flask Blueprint for SpiritPool v2 contributor intake.

Endpoints:
    POST /api/contribute   Universal contributor signal intake
    POST /api/burn         Session burn (anonymization)

Processing order for /api/contribute:
    1. Strip tabUrl, collectedAt (defence-in-depth)
    2. Validate required fields
    3. Set server-side fields (event_id, collected_at, pipeline_version)
    4. PII scan on payload
    5. Route to quarantine or sp_events
    6. Auto-create session_epochs on first POST per token
    7. Return 200 or 400

FH-0 §3 (endpoint spec) and FH-1 §2-3 (privacy controls).

Depends on: core.privacy, core.models.spiritpool, core.database
"""

import json
import logging
import uuid
from datetime import datetime, timedelta

from flask import Blueprint, jsonify, request
from sqlalchemy import func

from core.database import get_session, init_db
from core.models.spiritpool import BurnPool, Contributor, Quarantine, SessionEpoch, SpEvent
from core.privacy import scan_pii, strip_forbidden_fields

logger = logging.getLogger(__name__)

contribute_bp = Blueprint("contribute", __name__)

# ── Constants ─────────────────────────────────────────────────────────────────

_CURRENT_PIPELINE_VERSION = 1

_ALLOWED_EVENT_TYPES = {
    "job_listing", "salary_signal", "business_review", "event_listing",
}

_ALLOWED_DOMAINS = {"jobs", "events", "business"}


# ── POST /api/contribute ─────────────────────────────────────────────────────

@contribute_bp.route("/api/contribute", methods=["POST"])
def contribute():
    """Universal contributor signal intake endpoint."""
    body = request.get_json(silent=True)
    if not body or not isinstance(body, dict):
        return jsonify({"status": "error", "message": "Invalid JSON body"}), 400

    # 1. Strip forbidden fields (defence-in-depth)
    strip_forbidden_fields(body)

    # 2. Validate required fields
    session_token = body.get("session_token")
    epoch_id = body.get("epoch_id")
    event_type = body.get("event_type")
    source = body.get("source")
    domain = body.get("domain")
    payload = body.get("payload")

    if not session_token or not isinstance(session_token, str):
        return jsonify({"status": "error", "message": "session_token required"}), 400
    if epoch_id is None or not isinstance(epoch_id, int) or epoch_id < 1:
        return jsonify({"status": "error", "message": "epoch_id required (integer >= 1)"}), 400
    if event_type not in _ALLOWED_EVENT_TYPES:
        return jsonify({"status": "error", "message": "invalid event_type"}), 400
    if not source or not isinstance(source, str):
        return jsonify({"status": "error", "message": "source required"}), 400
    if domain not in _ALLOWED_DOMAINS:
        return jsonify({"status": "error", "message": "invalid domain"}), 400
    if not payload or not isinstance(payload, dict):
        return jsonify({"status": "error", "message": "payload required (non-empty dict)"}), 400

    # 3. Set server-side fields
    event_id = str(uuid.uuid4())
    collected_at = datetime.utcnow()
    pipeline_version = _CURRENT_PIPELINE_VERSION

    # 4. PII scan
    pii_types = scan_pii(payload)

    engine = init_db()
    db = get_session(engine)
    try:
        if pii_types:
            # 5a. Quarantine — PII detected
            q = Quarantine(
                quarantine_id=str(uuid.uuid4()),
                original_payload=body,
                redaction_types=json.dumps(pii_types),
                rule_version=pipeline_version,
                quarantined_at=collected_at,
            )
            db.add(q)
        else:
            # 5b. Clean — store in sp_events
            ev = SpEvent(
                event_id=event_id,
                session_token=session_token,
                epoch_id=epoch_id,
                event_type=event_type,
                payload=payload,
                source_type="extension",
                collected_at=collected_at,
                pipeline_version=pipeline_version,
            )
            db.add(ev)

        # 6. Auto-create session_epochs on first POST per token
        existing = db.query(SessionEpoch).filter_by(
            session_token=session_token
        ).first()
        if not existing:
            se = SessionEpoch(
                session_token=session_token,
                epoch_id=epoch_id,
                created_at=collected_at,
            )
            db.add(se)

        db.commit()
        return jsonify({"status": "ok"}), 200

    except Exception as e:
        db.rollback()
        logger.error("[Contribute] Insert failed: %s", e, exc_info=True)
        return jsonify({"status": "error", "message": "An internal error occurred"}), 500
    finally:
        db.close()


# ── POST /api/burn ────────────────────────────────────────────────────────────

@contribute_bp.route("/api/burn", methods=["POST"])
def burn():
    """Session burn endpoint — anonymize contributor linkage."""
    body = request.get_json(silent=True)
    if not body or not isinstance(body, dict):
        return jsonify({"status": "error", "message": "Invalid JSON body"}), 400

    session_token = body.get("session_token")
    if not session_token or not isinstance(session_token, str):
        return jsonify({"status": "error", "message": "session_token required"}), 400

    now = datetime.utcnow()

    engine = init_db()
    db = get_session(engine)
    try:
        # Set session_epochs.contributor_id = NULL, burned_at = NOW
        epoch = db.query(SessionEpoch).filter_by(
            session_token=session_token
        ).first()

        if epoch:
            epoch.contributor_id = None
            epoch.burned_at = now

        # Increment burn_pool for current month
        month_key = now.strftime("%Y-%m")
        pool = db.query(BurnPool).filter_by(month_key=month_key).first()
        if pool:
            pool.signal_count += 1
            pool.burned_at = now
        else:
            pool = BurnPool(
                month_key=month_key,
                signal_count=1,
                burned_at=now,
                expires_at=now + timedelta(days=365),
            )
            db.add(pool)

        db.commit()
        return jsonify({"status": "ok"}), 200

    except Exception as e:
        db.rollback()
        logger.error("[Burn] Operation failed: %s", e, exc_info=True)
        return jsonify({"status": "error", "message": "An internal error occurred"}), 500
    finally:
        db.close()
