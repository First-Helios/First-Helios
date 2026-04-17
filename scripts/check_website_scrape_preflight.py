#!/usr/bin/env python3
"""Run pre-flight checks before the next website scrape.

This script does NOT start a scrape. It validates the local environment,
target query, hint-registry load, cache paths, and optional remote SSH
reachability so operators can catch avoidable failures before launching a
dry-run canary or a full scrape.

Usage:
  PYTHONPATH=. python scripts/check_website_scrape_preflight.py
  PYTHONPATH=. python scripts/check_website_scrape_preflight.py --region austin_tx --skip-checked-days 0
  PYTHONPATH=. python scripts/check_website_scrape_preflight.py --remote-host orangepi@192.168.1.191
  PYTHONPATH=. python scripts/check_website_scrape_preflight.py --json
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from collectors.meal_deals.hint_registry import DEFAULT_REGISTRY_PATH, load_hints
from collectors.meal_deals.website_scrape_audit_utils import classify_domain_family
from collectors.meal_deals.website_scraper import load_website_scrape_target_groups
from config.paths import CACHE_DIR, WEBSITE_SCRAPE_DEBUG_DIR
from core.database import get_session, init_db


@dataclass
class CheckResult:
    name: str
    status: str  # pass | warn | fail
    detail: str
    recommendation: str | None = None


def check_imports() -> CheckResult:
    """Verify the key website-scrape modules import cleanly."""
    try:
        from collectors.meal_deals import website_scraper  # noqa: F401
        from collectors.meal_deals import hint_registry  # noqa: F401
        from collectors.meal_deals import menu_persistence_schema  # noqa: F401
        from collectors.meal_deals import render_policy  # noqa: F401
    except Exception as exc:
        return CheckResult(
            name="imports",
            status="fail",
            detail=f"module import failed: {exc}",
            recommendation="Fix import or dependency errors before starting any dry-run or live scrape.",
        )

    return CheckResult(
        name="imports",
        status="pass",
        detail="website_scraper, hint_registry, render_policy, and menu_persistence_schema import cleanly.",
    )


def check_cache_paths(
    *,
    cache_dir: Path = CACHE_DIR,
    debug_dir: Path = WEBSITE_SCRAPE_DEBUG_DIR,
) -> CheckResult:
    """Ensure cache directories exist and summarize replay artifact presence."""
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
        debug_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return CheckResult(
            name="cache_paths",
            status="fail",
            detail=f"unable to create cache paths: {exc}",
            recommendation="Ensure the local scrape cache directories are writable before the next run.",
        )

    audit_path = cache_dir / "website_scrape_audit.json"
    bundle_count = sum(1 for path in debug_dir.glob("*.json") if path.is_file())
    audit_exists = audit_path.exists()
    status = "pass" if bundle_count > 0 or audit_exists else "warn"
    detail = (
        f"debug_dir={debug_dir}, debug_bundle_count={bundle_count}, "
        f"audit_snapshot={'present' if audit_exists else 'missing'}"
    )
    recommendation = None
    if status == "warn":
        recommendation = "Sync replay artifacts with `bash dev/sync_from_opi.sh` if you want replay-first debugging before the next live run."

    return CheckResult(
        name="cache_paths",
        status=status,
        detail=detail,
        recommendation=recommendation,
    )


def check_hint_registry(*, registry_path: Path | str | None = None) -> CheckResult:
    """Validate the checked-in hint registry and count active versus expired hints."""
    path = Path(registry_path) if registry_path else DEFAULT_REGISTRY_PATH
    try:
        all_hints = load_hints(path=path, include_expired=True)
        active_hints = load_hints(path=path)
    except Exception as exc:
        return CheckResult(
            name="hint_registry",
            status="fail",
            detail=f"failed to load hint registry {path}: {exc}",
            recommendation="Fix registry schema or provenance issues before relying on hint-driven discovery.",
        )

    expired_count = max(0, len(all_hints) - len(active_hints))
    status = "pass" if active_hints else "warn"
    detail = f"registry={path}, active_hints={len(active_hints)}, expired_hints={expired_count}"
    recommendation = None
    if status == "warn":
        recommendation = "No active hints is allowed, but it lowers discovery leverage on locator and hidden-promo sites."

    return CheckResult(
        name="hint_registry",
        status=status,
        detail=detail,
        recommendation=recommendation,
    )


def check_target_query(
    *,
    region: str,
    max_sites: int,
    skip_checked_days: int | None,
    preview_targets: int = 3,
) -> CheckResult:
    """Run the same target-group query the scraper uses and summarize it."""
    session = None
    try:
        engine = init_db()
        session = get_session(engine)
        group_items, total_rows = load_website_scrape_target_groups(
            session,
            region=region,
            max_sites=max_sites,
            skip_checked_days=skip_checked_days,
        )
    except Exception as exc:
        return CheckResult(
            name="target_query",
            status="fail",
            detail=f"failed to load website scrape targets: {exc}",
            recommendation="Fix DB connectivity or target-query regressions before launching the next scrape.",
        )
    finally:
        if session is not None:
            session.close()

    unique_urls = len(group_items)
    family_counts: Counter[str] = Counter()
    suppressed_families = {"social", "government", "directory", "other_nonrestaurant"}
    suppressed_candidates = 0
    preview: list[str] = []
    for _normalized_url, group in group_items:
        url = group[0][0].url
        family = classify_domain_family(url)
        family_counts[family] += 1
        if family in suppressed_families:
            suppressed_candidates += 1
        if len(preview) < preview_targets:
            preview.append(f"{family}:{url}")

    status = "pass" if unique_urls > 0 else "warn"
    detail = (
        f"region={region}, restaurant_url_rows={total_rows}, unique_urls={unique_urls}, "
        f"suppressed_candidates={suppressed_candidates}, families={dict(family_counts)}, preview={preview}"
    )
    recommendation = None
    if status == "warn":
        recommendation = "No eligible targets were returned. Confirm the region, skip window, and local DB sync before scraping."
    elif suppressed_candidates > 0:
        recommendation = (
            "The next queue still includes obvious non-first-party targets that the scraper will suppress. "
            "That does not block a run, but it is worth tracking if scrape budget is tight."
        )

    return CheckResult(
        name="target_query",
        status=status,
        detail=detail,
        recommendation=recommendation,
    )


def check_remote_ssh(remote_host: str) -> CheckResult:
    """Optionally verify BatchMode SSH connectivity to a remote scrape host."""
    ssh_bin = shutil.which("ssh")
    if ssh_bin is None:
        return CheckResult(
            name="remote_ssh",
            status="fail",
            detail="`ssh` executable not found on PATH.",
            recommendation="Install or expose `ssh` on PATH before relying on a remote scrape runner.",
        )

    proc = subprocess.run(
        [ssh_bin, "-o", "BatchMode=yes", "-o", "ConnectTimeout=5", remote_host, "true"],
        capture_output=True,
        text=True,
    )
    if proc.returncode == 0:
        return CheckResult(
            name="remote_ssh",
            status="pass",
            detail=f"remote SSH reachable for {remote_host}.",
        )

    stderr = (proc.stderr or "").strip().splitlines()
    last_line = stderr[-1] if stderr else f"exit_code={proc.returncode}"
    return CheckResult(
        name="remote_ssh",
        status="fail",
        detail=f"remote SSH check failed for {remote_host}: {last_line}",
        recommendation="Fix remote SSH access or switch to a local dry-run canary before attempting a remote scrape.",
    )


def build_canary_command(*, region: str, canary_sites: int, skip_checked_days: int | None) -> str:
    skip_value = "0" if skip_checked_days is None else str(skip_checked_days)
    return (
        f"PYTHONPATH=. .venv/bin/python collectors/meal_deals/website_scraper.py "
        f"--max-sites {canary_sites} --skip-checked-days {skip_value} --dry-run --region {region}"
    )


def build_preflight_report(
    *,
    region: str = "austin_tx",
    max_sites: int = 10,
    skip_checked_days: int | None = 0,
    preview_targets: int = 3,
    canary_sites: int = 5,
    remote_host: str | None = None,
    registry_path: Path | str | None = None,
    cache_dir: Path = CACHE_DIR,
    debug_dir: Path = WEBSITE_SCRAPE_DEBUG_DIR,
) -> dict[str, Any]:
    checks = [
        check_imports(),
        check_cache_paths(cache_dir=cache_dir, debug_dir=debug_dir),
        check_hint_registry(registry_path=registry_path),
        check_target_query(
            region=region,
            max_sites=max_sites,
            skip_checked_days=skip_checked_days,
            preview_targets=preview_targets,
        ),
    ]
    if remote_host:
        checks.append(check_remote_ssh(remote_host))

    blocking = [check for check in checks if check.status == "fail"]
    manual_steps = [
        "Run the local pre-flight checker until there are no blocking failures.",
        f"Run a dry-run canary: {build_canary_command(region=region, canary_sites=canary_sites, skip_checked_days=skip_checked_days)}",
        "Inspect the newest debug bundles for render_decisions and render_budget on fetched first-party pages before any live run.",
        "Inspect menu_persistence_summary and hint_audit when the canary actually materializes sidecar structure or hint-driven exploration.",
        "If menu_persistence_summary is present, confirm fk_violations stays at 0. If a known menu-rich canary site still lacks it, treat that as a structure-coverage follow-up before widening the run.",
        "Only start a non-dry-run scrape after the canary confirms the new bundle fields and hint provenance behave as expected.",
    ]
    if remote_host:
        manual_steps.insert(
            1,
            f"If the scrape will run remotely, confirm code parity and SSH reachability for {remote_host} before launching the canary.",
        )

    return {
        "ready": not blocking,
        "blocking_failures": len(blocking),
        "checks": [asdict(check) for check in checks],
        "manual_steps": manual_steps,
    }


def _print_report(report: dict[str, Any]) -> None:
    ready_label = "YES" if report["ready"] else "NO"
    print(f"Website Scrape Pre-flight Ready: {ready_label}")
    print("")
    for check in report["checks"]:
        status = check["status"].upper().ljust(4)
        print(f"[{status}] {check['name']}: {check['detail']}")
        if check.get("recommendation"):
            print(f"       next: {check['recommendation']}")
    print("")
    print("Manual steps:")
    for index, step in enumerate(report["manual_steps"], start=1):
        print(f"  {index}. {step}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Check website scrape pre-flight readiness")
    parser.add_argument("--region", default="austin_tx")
    parser.add_argument("--max-sites", type=int, default=10)
    parser.add_argument(
        "--skip-checked-days",
        type=int,
        default=0,
        help="Mirror the next scrape run. Use 0 to see the full currently eligible queue.",
    )
    parser.add_argument("--preview-targets", type=int, default=3)
    parser.add_argument("--canary-sites", type=int, default=5)
    parser.add_argument("--remote-host", default=None, help="Optional remote host to verify with BatchMode SSH")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    report = build_preflight_report(
        region=args.region,
        max_sites=args.max_sites,
        skip_checked_days=args.skip_checked_days,
        preview_targets=args.preview_targets,
        canary_sites=args.canary_sites,
        remote_host=args.remote_host,
    )

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        _print_report(report)

    raise SystemExit(0 if report["ready"] else 1)


if __name__ == "__main__":
    main()