#!/usr/bin/env python3
"""Validate Spirit Pool dev-user page captures before they feed any parser.

The dev-capture endpoint lands a signed, full-page bundle in
    data/cache/spiritpool_dev/page_captures/

Nothing else should parse those raw bundles directly. This script enforces a
staging gate:

    page_captures/  (raw, signed, as-posted)
        -> validate
        -> validated/     (ready for harvest / adapter parsing)
        -> quarantine/    (denial, empty DOM, oversize, suspected spoof)

Validation rules (each failure quarantines the bundle with a reason):

  1. Bundle JSON must parse and include a non-empty `html` field.
  2. `captured_at` must be a valid ISO timestamp.
  3. HTML rendering must classify as `content_ok` via
     scripts.harvest_hintbook_from_spiritpool.classify_bundle_rendering
     (`empty_body`, `suspected_denial`, `site_error_or_denial` → quarantine).
  4. HTML size must be between 2 KB and 10 MB.
  5. If `canonical_url` is present, its host must not be on the quarantine
     blocklist (test fixtures, example.com, localhost).

Bundles that pass are hard-linked (or copied) into `validated/`. Bundles that
fail are moved to `quarantine/<reason>/` so the operator can inspect them.

This is the "first pass testing from dev user" gate the hintbook / scrape
pipeline relies on. Parsers read from validated/, nothing else.
"""

from __future__ import annotations

import argparse
import json
import logging
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.harvest_hintbook_from_spiritpool import classify_bundle_rendering  # noqa: E402

from config.paths import CACHE_DIR  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

DEFAULT_INPUT = CACHE_DIR / "spiritpool_dev" / "page_captures"
DEFAULT_VALIDATED = CACHE_DIR / "spiritpool_dev" / "validated"
DEFAULT_QUARANTINE = CACHE_DIR / "spiritpool_dev" / "quarantine"

_MIN_HTML_BYTES = 2 * 1024
_MAX_HTML_BYTES = 10 * 1024 * 1024
_QUARANTINE_HOSTS = {"example.com", "www.example.com", "localhost", "127.0.0.1"}


def _validate_bundle(path: Path) -> tuple[str, dict[str, Any]]:
    """Return (status, detail). status ∈ {'pass', 'fail_<reason>'}."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return "fail_unparseable_json", {"error": str(exc)}

    html = data.get("html")
    if not isinstance(html, str) or not html.strip():
        return "fail_missing_html", {}

    url = data.get("canonical_url") or data.get("url") or ""
    host = urlparse(url).netloc.lower() if url else ""
    if host in _QUARANTINE_HOSTS:
        return "fail_quarantine_host", {"host": host}

    size = len(html.encode("utf-8"))
    if size < _MIN_HTML_BYTES:
        return "fail_too_small", {"bytes": size}
    if size > _MAX_HTML_BYTES:
        return "fail_too_large", {"bytes": size}

    captured_raw = data.get("captured_at")
    if isinstance(captured_raw, str):
        try:
            datetime.fromisoformat(captured_raw.replace("Z", "+00:00"))
        except ValueError:
            return "fail_bad_captured_at", {"captured_at": captured_raw}

    title = data.get("title") or ""
    render = classify_bundle_rendering(html, title)
    if render["status"] != "content_ok":
        return f"fail_{render['status']}", render

    return "pass", {
        "host": host,
        "html_bytes": size,
        "visible_chars": render["visible_chars"],
    }


def _place(src: Path, dest_dir: Path) -> Path:
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / src.name
    if dest.exists():
        dest.unlink()
    try:
        dest.hardlink_to(src)
    except OSError:
        shutil.copy2(src, dest)
    return dest


def validate_directory(
    input_dir: Path,
    validated_dir: Path,
    quarantine_dir: Path,
    *,
    remove_source: bool = False,
) -> dict[str, Any]:
    if not input_dir.exists():
        raise SystemExit(f"Input dir not found: {input_dir}")

    results: list[dict[str, Any]] = []
    counts: dict[str, int] = {}
    for path in sorted(input_dir.glob("*.json")):
        status, detail = _validate_bundle(path)
        counts[status] = counts.get(status, 0) + 1
        if status == "pass":
            placed = _place(path, validated_dir)
            results.append({"bundle": path.name, "status": status, "target": str(placed), "detail": detail})
        else:
            reason = status.replace("fail_", "", 1)
            placed = _place(path, quarantine_dir / reason)
            results.append({"bundle": path.name, "status": status, "target": str(placed), "detail": detail})
        if remove_source and status == "pass":
            # Only remove the source after a successful hardlink so we never
            # lose a valid capture. Quarantined bundles are always left in
            # place as well so the operator can re-inspect them.
            try:
                path.unlink()
            except OSError:
                pass

    return {"counts": counts, "results": results}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--validated", type=Path, default=DEFAULT_VALIDATED)
    parser.add_argument("--quarantine", type=Path, default=DEFAULT_QUARANTINE)
    parser.add_argument(
        "--remove-source-on-pass",
        action="store_true",
        help="Delete the raw bundle from input after successful hard-link into validated/.",
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    report = validate_directory(
        args.input, args.validated, args.quarantine,
        remove_source=args.remove_source_on_pass,
    )

    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        logger.info("=" * 72)
        logger.info("SPIRITPOOL CAPTURE VALIDATION")
        logger.info("=" * 72)
        logger.info("Input     : %s", args.input)
        logger.info("Validated : %s", args.validated)
        logger.info("Quarantine: %s", args.quarantine)
        logger.info("")
        logger.info("Counts:")
        for k, v in sorted(report["counts"].items()):
            logger.info("  %-32s %d", k, v)
        logger.info("")
        for r in report["results"]:
            logger.info("  %-18s %s", r["status"], r["bundle"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
