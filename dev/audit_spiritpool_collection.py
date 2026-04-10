"""
dev/audit_spiritpool_collection.py — What is the extension actually sending us?

Reads the local dev Postgres (sync with dev/sync_from_opi.sh first) and
produces a field-level audit of SpiritPool contributions so we can spot:

  1. Fields the extension sends in non-dev mode that we *don't want* to collect
     (anything not in the known-allowed list — e.g. stray IDs, timestamps,
     tracking params, full HTML blobs, user-agent strings, etc.).
  2. Fields that exist in dev-mode raw captures but disappear after
     sanitization (good — shows the privacy pipeline is working).
  3. Fields that exist in non-dev (sp_events.payload) that do NOT exist
     in dev-mode sanitized captures (bad — means sanitize.js isn't catching
     them, or the field was added server-side after sanitization).
  4. The raw size distribution of description text (leading PII vector).
  5. PII patterns that slipped past the scanner and landed in sp_events.

Run after a fresh sync:
    bash dev/sync_from_opi.sh
    python dev/audit_spiritpool_collection.py
    python dev/audit_spiritpool_collection.py --verbose  # dump sample payloads
    python dev/audit_spiritpool_collection.py --limit 500

Layer: dev tooling only. Never imported from the app.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path

# Make the project root importable so we can reuse core.database / core.privacy
_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))

# Load .env so DATABASE_URL is picked up the same way the app does
try:
    from dotenv import load_dotenv  # type: ignore
    load_dotenv(_REPO / ".env")
except Exception:
    pass

from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from core.privacy import scan_pii  # noqa: E402


# ── Field taxonomy ────────────────────────────────────────────────────────────
# Every known key is placed in exactly one bucket based on what the backend
# actually does with it.  Derived from reading postings/spiritpool_routes.py
# and postings/ingest.py — specifically _map_signal() and ingest_job_posting().

# 1. CONSUMED — influences the job_postings row directly
CONSUMED_BY_INGEST = {
    "company", "jobTitle", "title",
    "salary", "location", "postingDate", "url", "description",
    "jobType", "isRemote",
}

# 2. METADATA ONLY — accepted into ScraperSignal.metadata but never persisted
#    to a column in job_postings.  Adds nothing except payload bloat.
METADATA_ONLY = {
    "applicantCount", "salarySource", "companyIndustry",
    "jobLevel", "badges", "rating",
}

# 3. DEAD WEIGHT — sent by the extension but not read by any code path.
#    These are candidates to stop collecting at the extension side.
DEAD_WEIGHT = {
    "jobId",       # not consumed; also trips the PII scanner via phone regex
    "observedAt",  # client-side timestamp; backend uses datetime.utcnow()
    "signalType",  # hardcoded "listing"; endpoint already assumes listing
    "source",      # extension's domain claim; backend derives from body.domain
    "storeNum",    # always null or synthetic; backend synthesizes SP-<chain>
    "_dev_html",   # large HTML blob; should only live in _dev_raw, not top-level
}

# 4. SERVER / SANITIZE — added after the extension hands off
ADDED_DOWNSTREAM = {
    "session_token",         # added by extension sanitize.js (M7)
    "epoch_id",              # added by extension sanitize.js (M7)
    "legacy_contributor_id", # added by _dual_write_to_sp_events
    "legacy_domain",         # added by _dual_write_to_sp_events
}

# 5. FORBIDDEN — must never be present; privacy contract violation
FORBIDDEN_FIELDS = {
    "tabUrl", "collectedAt", "consent_state",
    "ip", "userAgent", "user_agent",
}

# Union for "is this known at all?"  Anything outside this is ?? UNKNOWN.
ALL_KNOWN = (
    CONSUMED_BY_INGEST
    | METADATA_ONLY
    | DEAD_WEIGHT
    | ADDED_DOWNSTREAM
    | FORBIDDEN_FIELDS
)


def _classify(key: str) -> str:
    if key in FORBIDDEN_FIELDS:
        return "!! FORBIDDEN"
    if key in DEAD_WEIGHT:
        return "xx DEAD WEIGHT"
    if key in CONSUMED_BY_INGEST:
        return "ok consumed"
    if key in METADATA_ONLY:
        return "~ metadata-only"
    if key in ADDED_DOWNSTREAM:
        return ".. server/sanitize"
    return "?? UNKNOWN"


# ── URL tracking-token detectors ──────────────────────────────────────────────
# LinkedIn and similar job boards embed per-user tracking tokens in URL query
# strings.  Collecting these strings can deanonymize contributors.
TRACKING_PARAM_NAMES = (
    "trackingid", "trackingId",
    "refid", "refId",
    "ebp", "eBP",
    "origin",
    "sessionid", "sessionId",
    "trk", "trkinfo", "trk_info",
    "li_fat_id", "li_oatml",
)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _get_engine():
    url = os.environ.get("DATABASE_URL") or "postgresql+psycopg://helios:helios@localhost:5432/helios"
    return create_engine(url, future=True)


def _walk_keys(obj, prefix: str = "") -> list[tuple[str, object]]:
    """Return [(dotted_path, leaf_value)] for all leaves in a JSON-ish dict."""
    out: list[tuple[str, object]] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            path = f"{prefix}.{k}" if prefix else k
            if isinstance(v, (dict, list)):
                out.extend(_walk_keys(v, path))
            else:
                out.append((path, v))
    elif isinstance(obj, list):
        # Use [] to denote list index — don't care about index specifically
        path = f"{prefix}[]" if prefix else "[]"
        for item in obj:
            if isinstance(item, (dict, list)):
                out.extend(_walk_keys(item, path))
            else:
                out.append((path, item))
    return out


def _describe_value(v) -> str:
    if v is None:
        return "<None>"
    if isinstance(v, bool):
        return f"bool ({v})"
    if isinstance(v, (int, float)):
        return f"num"
    if isinstance(v, str):
        length = len(v)
        preview = v[:60].replace("\n", " ")
        if length > 60:
            preview += "…"
        return f'str[{length}] "{preview}"'
    return type(v).__name__


def _size_bytes(v) -> int:
    if v is None:
        return 0
    if isinstance(v, str):
        return len(v.encode("utf-8"))
    return len(str(v).encode("utf-8"))


# ── Audit steps ──────────────────────────────────────────────────────────────

def _load_production_payloads(session, limit: int) -> list[tuple[str, str, object, dict]]:
    """Return [(origin, id, when, payload)] merging sp_events + quarantine.

    Both tables carry the same raw-signal shape.  sp_events is the "clean"
    path; quarantine is the "PII-flagged" path.  For a field-level audit we
    want them unioned so we see every field the extension is sending.
    """
    rows: list[tuple[str, str, object, dict]] = []

    sp = session.execute(
        text(
            """
            SELECT event_id, collected_at, payload
            FROM sp_events
            ORDER BY collected_at DESC
            LIMIT :lim
            """
        ),
        {"lim": limit},
    ).fetchall()
    for eid, ts, payload in sp:
        if isinstance(payload, dict):
            rows.append(("sp_events", eid, ts, payload))

    qt = session.execute(
        text(
            """
            SELECT quarantine_id, quarantined_at, original_payload
            FROM quarantine
            ORDER BY quarantined_at DESC
            LIMIT :lim
            """
        ),
        {"lim": limit},
    ).fetchall()
    for qid, ts, payload in qt:
        if isinstance(payload, dict):
            rows.append(("quarantine", qid, ts, payload))

    return rows


def _url_looks_tracked(url: str) -> list[str]:
    """Return list of tracking param names found in a URL's query string."""
    if not isinstance(url, str) or "?" not in url:
        return []
    query = url.split("?", 1)[1]
    params = [seg.split("=", 1)[0] for seg in query.split("&") if seg]
    found = [p for p in params if p in TRACKING_PARAM_NAMES]
    return found


def audit_production_payloads(session, limit: int, verbose: bool) -> None:
    print("\n" + "=" * 72)
    print("  Production payloads (sp_events ∪ quarantine) — field audit")
    print("=" * 72)

    rows = _load_production_payloads(session, limit)
    if not rows:
        print("  No production payloads found. Run: bash dev/sync_from_opi.sh")
        return

    n_sp = sum(1 for r in rows if r[0] == "sp_events")
    n_qt = sum(1 for r in rows if r[0] == "quarantine")
    total = len(rows)

    print(f"  Total payloads: {total}   (sp_events: {n_sp}   quarantine: {n_qt})")
    if n_sp == 0 and n_qt > 0:
        print("  ⚠ sp_events is empty — every contribution is being PII-quarantined.")
        print("    Verify quarantine.redaction_types to see which regex is firing.")

    # Tally field frequencies across the unioned set
    top_counts: Counter[str] = Counter()
    top_counts_by_origin: dict[str, Counter[str]] = {
        "sp_events": Counter(),
        "quarantine": Counter(),
    }
    top_example: dict[str, object] = {}
    top_size_max: dict[str, int] = defaultdict(int)
    url_tracking: Counter[str] = Counter()      # tracking param name → occurrences
    url_lengths: list[int] = []
    pii_scan_results: Counter[str] = Counter()  # "credit_card" → N, etc.

    for origin, row_id, _ts, payload in rows:
        for k, v in payload.items():
            top_counts[k] += 1
            top_counts_by_origin[origin][k] += 1
            if k not in top_example:
                top_example[k] = v
            sz = _size_bytes(v)
            if sz > top_size_max[k]:
                top_size_max[k] = sz

        url = payload.get("url")
        if isinstance(url, str):
            url_lengths.append(len(url))
            for param in _url_looks_tracked(url):
                url_tracking[param] += 1

        for t in scan_pii(payload):
            pii_scan_results[t] += 1

    # ── Top-level field inventory with taxonomy ───────────────────────────────
    print("\n  Field inventory (classified by what the backend does with it):")
    print(f"    {'KEY':24s} {'TOTAL':>7s} {'SP_EV':>7s} {'QUAR':>7s} {'MAX_B':>8s}  STATUS")
    print(f"    {'---':24s} {'-----':>7s} {'-----':>7s} {'-----':>7s} {'-----':>8s}  ------")
    for k, n in top_counts.most_common():
        sp_n = top_counts_by_origin["sp_events"].get(k, 0)
        qt_n = top_counts_by_origin["quarantine"].get(k, 0)
        mx = top_size_max[k]
        status = _classify(k)
        print(f"    {k:24s} {n:7d} {sp_n:7d} {qt_n:7d} {mx:8d}  {status}")

    # ── Call-out: dead-weight fields (present but unused) ────────────────────
    dead = [k for k in top_counts if k in DEAD_WEIGHT]
    if dead:
        print("\n  xx DEAD WEIGHT — fields sent but never read by backend:")
        for k in sorted(dead):
            print(f"     {k:24s}  {top_counts[k]} events   example: {_describe_value(top_example.get(k))}")
        print("     → These can be removed at the extension side with no loss of function.")

    unknown = [k for k in top_counts if _classify(k) == "?? UNKNOWN"]
    if unknown:
        print("\n  ?? UNKNOWN fields (not in any classification bucket — needs review):")
        for k in sorted(unknown):
            print(f"     {k:24s}  {top_counts[k]} events   example: {_describe_value(top_example.get(k))}")

    forbidden = [k for k in top_counts if k in FORBIDDEN_FIELDS]
    if forbidden:
        print("\n  !! FORBIDDEN fields leaked through:")
        for k in sorted(forbidden):
            print(f"     {k}: {top_counts[k]} events")

    # ── URL tracking token analysis ───────────────────────────────────────────
    print("\n  URL hygiene (primary deanonymization vector):")
    if url_lengths:
        url_lengths.sort()
        print(f"    count={len(url_lengths)}  min={url_lengths[0]}  "
              f"median={url_lengths[len(url_lengths)//2]}  max={url_lengths[-1]}")
        if url_lengths[-1] > 500:
            print(f"    ⚠ Max URL length {url_lengths[-1]} chars — almost certainly carries tracking tokens.")
    if url_tracking:
        print("    Tracking query params found:")
        for param, n in url_tracking.most_common():
            print(f"      {param:24s} {n:6d} URLs")
    else:
        print("    (no known tracking params in URL query strings)")

    # ── PII scanner breakdown — why quarantine rows were flagged ─────────────
    if pii_scan_results:
        print("\n  PII scanner hits across ALL payloads (sp_events + quarantine):")
        for t, n in pii_scan_results.most_common():
            print(f"    {t:24s} {n:6d} payloads")
        if n_sp == 0:
            print("    → With sp_events=0, these are the reasons the 'clean' path is empty.")
            print("    → Check core/privacy.py regexes against the example values above;")
            print("      numeric jobId values and URL tracking tokens are common false positives.")

    # ── Verbose dump ─────────────────────────────────────────────────────────
    if verbose:
        print("\n  Sample payloads (first 3 rows):")
        for origin, row_id, ts, payload in rows[:3]:
            print(f"\n    --- [{origin}] id={str(row_id)[:12]}  at={ts} ---")
            for k, v in payload.items():
                print(f"      {k}: {_describe_value(v)}")


def audit_dev_capture(session, limit: int) -> None:
    print("\n" + "=" * 72)
    print("  dev_capture.raw_signals — dev-mode A/B extracted vs sanitized")
    print("=" * 72)

    rows = session.execute(
        text(
            """
            SELECT id, domain, captured_at, extracted_fields, sanitized_fields
            FROM dev_capture.raw_signals
            ORDER BY captured_at DESC
            LIMIT :lim
            """
        ),
        {"lim": limit},
    ).fetchall()

    if not rows:
        print("  dev_capture.raw_signals is empty. Enable Dev Capture Mode in the extension")
        print("  and contribute some signals, then re-sync.")
        return

    total = len(rows)
    print(f"  Sampled {total} dev-mode captures\n")

    extracted_keys: Counter[str] = Counter()
    sanitized_keys: Counter[str] = Counter()

    for _id, _domain, _ts, extracted, sanitized in rows:
        if isinstance(extracted, dict):
            for k in extracted.keys():
                extracted_keys[k] += 1
        if isinstance(sanitized, dict):
            for k in sanitized.keys():
                sanitized_keys[k] += 1

    all_keys = sorted(set(extracted_keys) | set(sanitized_keys))

    print(f"  {'KEY':30s} {'EXTRACTED':>10s} {'SANITIZED':>10s}  DELTA")
    print(f"  {'---':30s} {'-----':>10s} {'-----':>10s}  -----")
    stripped_by_sanitize: list[str] = []
    added_by_sanitize: list[str] = []
    for k in all_keys:
        e = extracted_keys.get(k, 0)
        s = sanitized_keys.get(k, 0)
        if e > 0 and s == 0:
            stripped_by_sanitize.append(k)
            note = "  ← stripped"
        elif e == 0 and s > 0:
            added_by_sanitize.append(k)
            note = "  ← added"
        else:
            note = ""
        print(f"  {k:30s} {e:10d} {s:10d}{note}")

    if stripped_by_sanitize:
        print(f"\n  ✓ Sanitize pipeline removes: {', '.join(stripped_by_sanitize)}")
    if added_by_sanitize:
        print(f"\n  ⓘ Sanitize pipeline adds:   {', '.join(added_by_sanitize)}")


def audit_crosscheck(session) -> None:
    """Find fields present in sp_events but NEVER in dev_capture.sanitized_fields.

    Indicates the sanitization pipeline isn't aware of those keys — either
    because sanitize.js doesn't know about them, or because the non-dev
    extension is sending extra fields.
    """
    print("\n" + "=" * 72)
    print("  CROSSCHECK — sp_events keys NOT present in any dev_capture.sanitized")
    print("=" * 72)

    sp_keys = set(
        r[0] for r in session.execute(
            text(
                """
                SELECT DISTINCT jsonb_object_keys(payload)
                FROM sp_events
                """
            )
        )
    )
    san_keys = set(
        r[0] for r in session.execute(
            text(
                """
                SELECT DISTINCT jsonb_object_keys(sanitized_fields)
                FROM dev_capture.raw_signals
                """
            )
        )
    )

    if not sp_keys:
        print("  No sp_events data. Sync first.")
        return
    if not san_keys:
        print("  No dev_capture data. Enable Dev Capture Mode, contribute, re-sync.")
        return

    only_in_sp = sorted(sp_keys - san_keys)
    print(f"  sp_events keys     : {len(sp_keys)}")
    print(f"  dev_capture keys   : {len(san_keys)}")
    print(f"  Only in sp_events  : {len(only_in_sp)}")
    if only_in_sp:
        print("\n  Fields flowing to production that the sanitizer never saw:")
        for k in only_in_sp:
            print(f"    {k:30s}  {_classify(k)}")


# ── Main ─────────────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--limit", type=int, default=2000, help="Max rows to sample per table (default 2000)")
    ap.add_argument("--verbose", action="store_true", help="Dump sample payloads")
    args = ap.parse_args()

    engine = _get_engine()
    Session = sessionmaker(bind=engine, future=True)
    session = Session()

    try:
        audit_production_payloads(session, args.limit, args.verbose)
        audit_dev_capture(session, args.limit)
        audit_crosscheck(session)
    finally:
        session.close()

    print("\nDone.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
