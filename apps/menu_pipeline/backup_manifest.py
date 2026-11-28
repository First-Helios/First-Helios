"""The facts a backup is checked against: the nightly manifest and the restore drills (ADR-0031).

    python -m apps.menu_pipeline.backup_manifest --db helios --db helios_work
    python -m apps.menu_pipeline.backup_manifest --db helios_drill --expect manifest.json --as helios

Prints one JSON object keyed by database name. Each database gets its ``alembic_version``,
its ``gold.current_menu`` row count, its venues with a menu (the API's own ``_has_menu``,
counted as the swap gate counts them) and its newest Gold ``effective_instant``. Read-only.

``backup.sh`` writes the first form into each night's manifest (D1). A drill restores that
night's dump and runs the second form: ``--expect`` reads the manifest, compares this
database's facts with the manifest's entry for ``--as`` (default: the same name), and exits 1
on any difference. That is drill A's check and drill B's clock stop (D2, Q10).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sqlalchemy import text

from apps.menu_pipeline.swap_gate import _read_only, gold_facts

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


def facts(session: Session) -> dict[str, Any]:
    """One database's manifest entry."""
    gold = gold_facts(session)
    newest = session.scalar(text("select max(effective_instant) from gold.current_menu"))
    return {
        "alembic_version": session.scalar(text("select version_num from alembic_version")),
        "current_menu_rows": gold.current_menu_rows,
        "venues_with_menu": len(gold.venues),
        "newest_effective": newest.isoformat() if newest is not None else None,
    }


def differences(found: dict[str, Any], expected: dict[str, Any]) -> list[str]:
    """``key: found != expected`` for each manifest key that differs."""
    return [
        f"{key}: {found.get(key)!r} != {expected.get(key)!r}"
        for key in sorted(set(found) | set(expected))
        if found.get(key) != expected.get(key)
    ]


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="python -m apps.menu_pipeline.backup_manifest",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--db", action="append", required=True, help="a database (repeatable)")
    parser.add_argument("--expect", type=Path, help="a night's manifest.json to compare with")
    parser.add_argument("--as", dest="as_name", help="the manifest entry to compare with")
    args = parser.parse_args(argv)
    if args.expect is not None and len(args.db) != 1:
        parser.error("--expect compares one --db")
    found: dict[str, dict[str, Any]] = {}
    for name in args.db:
        with _read_only(name) as session:
            found[name] = facts(session)
    print(json.dumps(found, indent=1, sort_keys=True))  # noqa: T201 - CLI output
    if args.expect is None:
        return
    manifest = json.loads(args.expect.read_text(encoding="utf-8"))
    entry = args.as_name or args.db[0]
    expected = manifest["databases"].get(entry)
    if expected is None:
        raise SystemExit(f"{args.expect} has no database {entry!r}")
    diff = differences(found[args.db[0]], expected)
    for line in diff:
        print(f"mismatch {line}")  # noqa: T201 - CLI output
    if diff:
        raise SystemExit(1)
    print(f"match: {args.db[0]} equals {entry} in {args.expect}")  # noqa: T201 - CLI output


if __name__ == "__main__":
    main()
