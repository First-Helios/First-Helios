"""CLI: the swap gate (ADR-0030 D3): the master's Gold against public, and a verdict::

    python -m apps.menu_pipeline.swap_gate [--public helios] [--master helios_work] [--out FILE]

Run it after the master's sweeps, rescore and Gold refresh. Both databases are on the
``DATABASE_URL`` server and are only read. Prints one JSON document (and writes it to
``--out``); exits 0 when the gate passes and 1 when it stops (stop and ask the owner).

The gate passes when all three hold:

- ``gold.current_menu`` rows fall less than :data:`ROW_DROP_MAX` against public;
- venues with a menu (the API's own ``_has_menu``) fall less than :data:`VENUE_DROP_MAX`;
- every venue that loses its menu is classified (:func:`classify`).

A lost venue is classified through the menu-page records behind its public Gold rows,
read in the master. Each record gets the first kind that fits, in this order:

1. ``r4_withdrawal``: the newest llm page is a withdrawal (R4: not a menu, JavaScript
   only, a withdrawal rule);
2. ``site_change``: the newest llm page has no priced row and the record has more Versions
   than in public (the site's text changed);
3. ``re_extracted_to_zero``: the newest llm page has no priced row on unchanged text;
4. ``unsectioned``: every priced row of the newest llm page is Unsectioned, which never
   reaches Gold (a design rule, #177 Q1);
5. ``jsonld_precedence``: the newest llm page has sectioned prices and a published jsonld
   page hides it (the bug #176 fixed; kept so that a regression shows).

A record that fits none, or a venue with no record, is ``unclassified`` and stops the gate
until a page check explains it. The citywide median shift is reported without a bar.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from apps.api.routes.venues import _has_menu
from packages.helios_core.config import get_database_url
from packages.helios_core.identity.models import Establishment

ROW_DROP_MAX = 0.05
VENUE_DROP_MAX = 0.05
UNCLASSIFIED = "unclassified"
KINDS = (
    "r4_withdrawal",
    "site_change",
    "re_extracted_to_zero",
    "unsectioned",
    "jsonld_precedence",
)


@dataclass(frozen=True, slots=True)
class GoldFacts:
    """One database's Gold, as the gate reads it."""

    current_menu_rows: int
    price_index_rows: int
    median_minor: int | None
    priced_count: int | None
    index_venue_count: int | None
    venues: frozenset[int]  # establishments with a menu


@dataclass(frozen=True, slots=True)
class RecordFacts:
    """A menu-page record behind a lost venue's public Gold rows, read in the master."""

    key: str
    menu_url: str | None
    public_versions: int
    master_versions: int
    latest_capture: str | None
    llm_operation: str | None  # the newest llm page's operation; None: no llm page
    llm_priced: int
    llm_sectioned_priced: int  # of those, priced rows outside the Unsectioned section
    jsonld_published: bool  # the newest jsonld page is published


def classify(record: RecordFacts) -> str:
    """The record's lost-venue kind (module docstring), or :data:`UNCLASSIFIED`."""
    if record.llm_operation is None:
        return UNCLASSIFIED
    if record.llm_operation == "withdrawal":
        return "r4_withdrawal"
    if record.llm_priced == 0:
        changed = record.master_versions > record.public_versions
        return "site_change" if changed else "re_extracted_to_zero"
    if record.llm_sectioned_priced == 0:
        return "unsectioned"
    if record.jsonld_published:
        return "jsonld_precedence"
    return UNCLASSIFIED


def venue_kinds(records: list[RecordFacts]) -> list[str]:
    """The venue's kinds, sorted; ``[unclassified]`` when any record (or none) is."""
    kinds = {classify(record) for record in records}
    if not kinds or UNCLASSIFIED in kinds:
        return [UNCLASSIFIED]
    return sorted(kinds)


def change(before: int, after: int) -> float:
    """Relative change, ``0.0`` from an empty start."""
    return (after - before) / before if before else 0.0


def verdict(
    public: GoldFacts, master: GoldFacts, lost: dict[int, list[str]]
) -> tuple[bool, list[str]]:
    """``(passed, reasons it stops)`` for the three bars."""
    reasons = []
    rows = change(public.current_menu_rows, master.current_menu_rows)
    if rows <= -ROW_DROP_MAX:
        reasons.append(f"current_menu rows fall {-rows:.2%} (bar: under {ROW_DROP_MAX:.0%})")
    venues = change(len(public.venues), len(master.venues))
    if venues <= -VENUE_DROP_MAX:
        reasons.append(f"venues with a menu fall {-venues:.2%} (bar: under {VENUE_DROP_MAX:.0%})")
    unclassified = sorted(subject for subject, kinds in lost.items() if UNCLASSIFIED in kinds)
    if unclassified:
        reasons.append(f"{len(unclassified)} lost venues unclassified: {unclassified}")
    return not reasons, reasons


def gold_facts(session: Session) -> GoldFacts:
    index = session.execute(
        text(
            "select median_minor, priced_count, venue_count from gold.price_index "
            "where area_kind = 'all' and category_kind = 'all'"
        )
    ).one_or_none()
    return GoldFacts(
        current_menu_rows=session.scalar(text("select count(*) from gold.current_menu")) or 0,
        price_index_rows=session.scalar(text("select count(*) from gold.price_index")) or 0,
        median_minor=index.median_minor if index else None,
        priced_count=index.priced_count if index else None,
        index_venue_count=index.venue_count if index else None,
        venues=frozenset(session.scalars(select(Establishment.subject_id).where(_has_menu()))),
    )


_RECORDS = text(
    """
    select distinct r.id, r.external_key
    from gold.current_menu g
    join menu.menu_page p on p.id in (g.price_page_id, g.content_page_id)
    join bronze.source_record r on r.id = p.source_record_id
    where g.subject_id = :subject
       or g.subject_id = (select organization_subject_id from identity.establishment
                          where subject_id = :subject)
    order by r.id
    """
)
_VERSIONS = text("select count(*) from bronze.source_record_version where source_record_id = :rid")
# A price's section: its own, its item's (directly or through a variant or modifier), or its
# modifier's. Unsectioned is the one structural section (menu.menu_section's shape check).
_MASTER_RECORD = text(
    """
    with llm as (
      select p.id, p.operation from menu.menu_page p
       where p.source_record_id = :rid and p.source_kind = 'llm'
       order by p.id desc limit 1
    ), priced as (
      select s.section_key
        from menu.price_observation o
        left join menu.menu_variant v on v.id = o.variant_id
        left join menu.menu_modifier m on m.id = o.modifier_id
        left join menu.menu_item i on i.id = coalesce(o.item_id, v.item_id, m.item_id)
        join menu.menu_section s on s.id = coalesce(o.section_id, i.section_id, m.section_id)
       where o.page_id = (select id from llm) and o.amount_minor is not null
    )
    select
      (select count(*) from bronze.source_record_version v
        where v.source_record_id = :rid) as versions,
      (select v.source_payload->>'menu_url' from bronze.source_record_version v
        where v.source_record_id = :rid order by v.id desc limit 1) as menu_url,
      (select c.outcome || '/' || coalesce(c.reason_code, '') || ' ' || c.fetched_at::date
         from bronze.source_record r
         join bronze.source_record_version v on v.source_record_id = r.id
         join bronze.capture c on c.source_endpoint_id = (
           select c2.source_endpoint_id from bronze.capture c2 where c2.id = v.capture_id)
        where r.id = :rid order by c.fetched_at desc limit 1) as latest_capture,
      (select operation from llm) as llm_operation,
      (select count(*) from priced) as llm_priced,
      (select count(*) from priced where section_key <> 'Unsectioned') as llm_sectioned_priced,
      coalesce((select j.state = 'published' from menu.menu_page j
                 where j.source_record_id = :rid and j.source_kind = 'jsonld'
                 order by j.id desc limit 1), false) as jsonld_published
    """
)


def lost_records(public: Session, master: Session, subject: int) -> list[RecordFacts]:
    """The records behind ``subject``'s public Gold rows, with their facts in the master."""
    records = []
    for rid, key in public.execute(_RECORDS, {"subject": subject}).all():
        row = master.execute(_MASTER_RECORD, {"rid": rid}).one()
        records.append(
            RecordFacts(
                key=key,
                menu_url=row.menu_url,
                public_versions=public.scalar(_VERSIONS, {"rid": rid}) or 0,
                master_versions=row.versions,
                latest_capture=row.latest_capture,
                llm_operation=row.llm_operation,
                llm_priced=row.llm_priced,
                llm_sectioned_priced=row.llm_sectioned_priced,
                jsonld_published=row.jsonld_published,
            )
        )
    return records


def _summary(facts: GoldFacts) -> dict[str, Any]:
    out = asdict(facts)
    out["venues_with_menu"] = len(out.pop("venues"))
    return out


def gate_report(public: Session, master: Session) -> dict[str, Any]:
    """The gate's JSON document (module docstring)."""
    pub, mst = gold_facts(public), gold_facts(master)
    lost = []
    kinds_by_subject: dict[int, list[str]] = {}
    for subject in sorted(pub.venues - mst.venues):
        records = lost_records(public, master, subject)
        kinds_by_subject[subject] = venue_kinds(records)
        lost.append(
            {
                "subject_id": subject,
                "kinds": kinds_by_subject[subject],
                "records": [asdict(r) | {"kind": classify(r)} for r in records],
            }
        )
    passed, reasons = verdict(pub, mst, kinds_by_subject)
    counts: dict[str, int] = {}
    for kinds in kinds_by_subject.values():
        for kind in kinds:
            counts[kind] = counts.get(kind, 0) + 1
    median_shift = (
        change(pub.median_minor, mst.median_minor)
        if pub.median_minor is not None and mst.median_minor is not None
        else None
    )
    return {
        "passed": passed,
        "stop_reasons": reasons,
        "public": _summary(pub),
        "master": _summary(mst),
        "rows_change": round(change(pub.current_menu_rows, mst.current_menu_rows), 4),
        "venues_change": round(change(len(pub.venues), len(mst.venues)), 4),
        "median_shift": None if median_shift is None else round(median_shift, 4),
        "gained": len(mst.venues - pub.venues),
        "lost_by_kind": dict(sorted(counts.items())),
        "lost": lost,
    }


def _read_only(dbname: str) -> Session:
    url = make_url(get_database_url()).set(database=dbname)
    session = Session(create_engine(url))
    session.execute(text("SET TRANSACTION READ ONLY"))
    return session


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="python -m apps.menu_pipeline.swap_gate",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--public", default="helios", help="the database the API serves")
    parser.add_argument("--master", default="helios_work", help="the pipeline's master")
    parser.add_argument("--out", type=Path, help="also write the report here")
    args = parser.parse_args()
    with _read_only(args.public) as public, _read_only(args.master) as master:
        report = gate_report(public, master)
    document = json.dumps(report, indent=1, default=str)
    if args.out is not None:
        args.out.write_text(document + "\n", encoding="utf-8")
    print(document)  # noqa: T201 - CLI output
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
