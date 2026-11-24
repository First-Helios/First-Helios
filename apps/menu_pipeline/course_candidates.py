"""Export the course-label candidates: every Gold-reaching named section (ADR-0016 Amendment 2).

The input of ``course_eval sample``. Read-only; reads through published
contracts only (Amendment 2 item 5): Gold ``current_sections`` for the
sections, Menu ``current_page_summaries`` (at Gold's instant) for each current
page's record version, method version and Unsectioned prices, and provenance
``get_record_version`` for the venue (the GERS id before ``|`` in the page
record's key)::

    uv run python -m apps.menu_pipeline.course_candidates --out var/course-labels/candidates-<date>

writes ``candidates.jsonl`` (one row per section, Amendment 1 item 4's fields
without split or labels), ``unsectioned.json`` (priced item/variant prices under
``Unsectioned`` per venue, for ``sample --unsectioned``) and ``meta.json``
(instant, counts, and the ``--method-version`` string for ``sample``). It never
overwrites an export.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from packages.helios_core.db.session import get_sessionmaker
from packages.helios_core.domains.menu.enumeration import current_page_summaries
from packages.helios_core.gold.menu_read import current_sections
from packages.helios_core.provenance.contracts import get_record_version

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from sqlalchemy.orm import Session

    from packages.helios_core.domains.menu.enumeration import CurrentPageSummary
    from packages.helios_core.gold.menu_read import CurrentSection


def venue_of(external_key: str) -> str:
    """The venue (GERS id) of a menu-page record key: ``<gers>``, ``<gers>|<path or host>``."""
    return external_key.split("|", 1)[0]


@dataclass(frozen=True, slots=True)
class Export:
    candidates: list[dict[str, Any]]
    unsectioned: dict[str, int]  # venue -> priced prices under Unsectioned
    meta: dict[str, Any]


def build_export(
    sections: Sequence[CurrentSection],
    pages: Sequence[CurrentPageSummary],
    record_keys: Mapping[int, str],  # record version id -> record external key
    instant: str | None,
) -> Export:
    """The candidate rows, Unsectioned counts and summary from the three reads (pure)."""
    by_page = {page.page_id: page for page in pages}
    candidates: list[dict[str, Any]] = []
    unnamed = 0
    behind: set[int] = set()  # current pages that have a candidate section
    for section in sections:
        page = by_page.get(section.page_id)
        if page is None:
            raise ValueError(
                f"Gold section {section.section_key!r} cites non-current page {section.page_id}"
            )
        if not section.name or not section.name.strip():
            unnamed += 1
            continue
        behind.add(page.page_id)
        candidates.append(
            {
                "venue": venue_of(record_keys[page.source_record_version_id]),
                "version_id": page.source_record_version_id,
                "section_key": section.section_key,
                "name": section.name,
                "name_path": [section.name],
                "items": list(section.items),
                "priced_items": section.priced_rows,
            }
        )
    unsectioned: Counter[str] = Counter()
    for page in pages:
        if page.unsectioned_priced:
            unsectioned[venue_of(record_keys[page.source_record_version_id])] += (
                page.unsectioned_priced
            )
    streams = Counter(f"{by_page[p].source_kind}={by_page[p].method_version}" for p in behind)
    priced = sum(c["priced_items"] for c in candidates)
    unsectioned_total = sum(unsectioned.values())
    meta = {
        "effective_instant": instant,
        "venues": len({c["venue"] for c in candidates}),
        "sections": len(candidates),
        "unnamed_sections": unnamed,
        "priced_items": priced,
        "current_pages": len(pages),
        "pages_with_candidates": len(behind),
        "unsectioned_priced_items": unsectioned_total,
        "unsectioned_share": (
            unsectioned_total / (priced + unsectioned_total) if priced + unsectioned_total else None
        ),
        "method_versions": dict(sorted(streams.items())),
        "method_version": " | ".join(sorted(streams)),
    }
    return Export(candidates, dict(sorted(unsectioned.items())), meta)


def export(session: Session) -> Export:
    """Read Gold, Menu and provenance; nothing is written."""
    instant, sections = current_sections(session)
    if instant is None:
        return build_export([], [], {}, None)
    pages = current_page_summaries(session, effective_instant=instant)
    keys = {
        version: get_record_version(session, version).external_key
        for version in sorted({page.source_record_version_id for page in pages})
    }
    return build_export(sections, pages, keys, instant.isoformat())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m apps.menu_pipeline.course_candidates")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    if (args.out / "candidates.jsonl").exists():
        parser.error(f"{args.out} already holds an export")
    with get_sessionmaker()() as session:
        result = export(session)
        session.rollback()
    args.out.mkdir(parents=True, exist_ok=True)
    with (args.out / "candidates.jsonl").open("w", encoding="utf-8") as handle:
        for row in result.candidates:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    (args.out / "unsectioned.json").write_text(
        json.dumps(result.unsectioned, indent=1) + "\n", encoding="utf-8"
    )
    (args.out / "meta.json").write_text(json.dumps(result.meta, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in result.meta.items() if k != "method_versions"}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
