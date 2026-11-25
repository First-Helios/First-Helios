"""Trace frozen venue prices from captured menu URLs to GET /v1/venues/{id}/menu.

Read a restored database after extraction and Gold refresh. A manifest names
independently labelled prices, their venue and menu state. Bundle digests pin
field inputs. The report compares exact USD item/variant/minor-unit triples on
the labelled source URL. A state anchor is a visible content block, typically a
service-time line absent from navigation. Each price is labelled in one state
per URL; ambiguous repeats require separate source pages.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any
from unittest.mock import patch

from fastapi.testclient import TestClient
from pydantic import BaseModel, Field
from sqlalchemy import text

from apps.api.db import get_session
from apps.api.main import app
from apps.api.schemas import VenueMenuResponse
from apps.menu_pipeline.bundle import BundleStore
from apps.menu_pipeline.extraction import OutputStore, page_html
from apps.menu_pipeline.menu_writes import ROOT_KEY
from apps.menu_pipeline.spot_check import EXTRACTOR_PARTS
from packages.helios_core.db.session import get_sessionmaker
from packages.helios_parsing.chunking import chunks
from packages.helios_parsing.jsonld import menu_items, validator_rows
from packages.helios_parsing.output import parse_output, rows_of
from packages.helios_parsing.page_template import llm_stream
from packages.helios_parsing.validator import Row, parse_amount, validate

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

type Price = tuple[str, str, int]


def normalized(value: str | None) -> str:
    return " ".join((value or "").casefold().split())


class Label(BaseModel):
    item: str
    baseline: str
    variant: str | None = None
    variant_aliases: list[str] = Field(default_factory=list)
    usd_minor: int = Field(ge=0)

    @property
    def keys(self) -> set[Price]:
        return {
            (normalized(self.item), normalized(v), self.usd_minor)
            for v in [self.variant, *self.variant_aliases]
        }


class State(BaseModel):
    name: str
    anchor: str
    prices: list[Label] = Field(min_length=1)


class Page(BaseModel):
    url: str
    bundle_sha256: str | None = None
    reference_body_sha256: str | None = None
    other_location_urls: list[str] = Field(default_factory=list)
    states: list[State] = Field(min_length=1)


class Venue(BaseModel):
    venue: str
    gers: str
    template: str
    pages: list[Page] = Field(min_length=1)


class Manifest(BaseModel):
    cohort: str
    venues: list[Venue] = Field(min_length=1)


# The archive records actual discovery/fetch results. Each saved menu record
# can have many historical versions; only its latest version is the input.
_CAPTURED = text("""
 select distinct on (r.id) r.id as record_id, v.id as version_id, c.bundle_path,
        v.source_payload->>'menu_url' as url, v.source_payload->>'text_hash' as text_hash
 from bronze.source_record r join bronze.source s on s.id=r.source_id
 join bronze.source_record_version v on v.source_record_id=r.id
 join bronze.capture c on c.id=v.capture_id
 where s.namespace='menu-page' and split_part(r.external_key,'|',1)=:gers
 order by r.id,v.observed_at desc,v.id desc
""")
_DISCOVERED = text("""
 select distinct on (r.id) v.source_payload->>'menu_url' from bronze.source_record r
 join bronze.source s on s.id=r.source_id
 join identity.current_resolution cr on cr.source_record_id=r.id and cr.state='resolved'
 join identity.subject_currentness sc on sc.subject_id=cr.subject_id and sc.is_current
 join bronze.source_record_version v on v.source_record_id=r.id
 where s.namespace='menu-url-discovery' and split_part(r.external_key,'|',1)=:gers
 order by r.id,v.observed_at desc,v.id desc
""")
_LAST_FETCH = text("""
 select c.outcome,c.reason_code from bronze.capture c
 join bronze.source_endpoint e on e.id=c.source_endpoint_id
 join bronze.source s on s.id=c.source_id where s.namespace='menu-page' and e.canonical_uri=:url
 order by c.fetched_at desc,c.id desc limit 1
""")
_VENUE = text("""
 select e.subject_id,e.organization_subject_id from identity.establishment e
 join identity.current_resolution cr on cr.subject_id=e.subject_id and cr.state='resolved'
 join bronze.source_record r on r.id=cr.source_record_id
 join bronze.source s on s.id=r.source_id where s.namespace='overture' and r.external_key=:gers
""")
_HEADS = text("""
 select distinct on (source_kind) id,source_kind,method_version,state,source_record_version_id
 from menu.menu_page where source_record_id=:record and root_key=:root
 order by source_kind,stream_revision desc
""")
_PRICES = text("""
 select i.name, v.label, p.amount_minor from menu.price_observation p
 left join menu.menu_variant v on v.id=p.variant_id
 join menu.menu_item i on i.id=coalesce(v.item_id,p.item_id)
 where p.page_id=:page and p.price_state='priced' and p.currency_code='USD'
""")
_GOLD = text("""
 select item_name, case when target_kind='variant' then content_name end, amount_minor
 from gold.current_menu where source_record_id=:record and target_kind in ('item','variant')
 and subject_id in (:venue,:organization) and price_state='priced' and currency_code='USD'
""")


@dataclass
class Trace:
    blocks: set[str] = field(default_factory=set)
    raw: set[Price] = field(default_factory=set)
    proposed: list[Row] = field(default_factory=list)
    rejected: dict[Price, str] = field(default_factory=dict)
    stored: set[Price] = field(default_factory=set)
    selected: set[Price] = field(default_factory=set)
    published: set[Price] = field(default_factory=set)
    interpreted: bool = False


def row_price(row: Row) -> Price | None:
    amount = parse_amount(row.amount)
    if amount is None or not amount.is_finite() or row.currency != "USD":
        return None
    return normalized(row.item), normalized(row.variant), int(amount * 100)


def api_prices(response: VenueMenuResponse) -> dict[str, set[Price]]:
    served: defaultdict[str, set[Price]] = defaultdict(set)
    for menu in response.menus:
        for section in menu.sections:
            for item in section.items:
                for name, prices in [
                    (None, item.prices),
                    *((v.name, v.prices) for v in item.variants),
                ]:
                    for p in prices:
                        if (
                            p.state == "priced"
                            and p.currency_code == "USD"
                            and p.amount_minor is not None
                        ):
                            served[menu.source_url or ""].add(
                                (normalized(item.name), normalized(name), p.amount_minor)
                            )
    return served


def trace_page(
    session: Session,
    record: Any,
    page: Page,
    base: Path,
    served: dict[str, set[Price]],
    scopes: tuple[int, int],
) -> Trace:
    bundle = BundleStore(base).read(record.bundle_path)
    if page.bundle_sha256 and hashlib.sha256(bundle.to_json()).hexdigest() != page.bundle_sha256:
        raise ValueError(f"Frozen capture differs for {page.url}")
    if (
        page.reference_body_sha256
        and hashlib.sha256(bundle.body or b"").hexdigest() != page.reference_body_sha256
    ):
        raise ValueError(f"Capture differs from the independent label source for {page.url}")
    blocks = list(bundle.blocks)
    html = page_html(bundle)
    trace = Trace(blocks={normalized(b.text) for b in blocks if not b.in_chrome})
    trace.published = served.get(bundle.url, set()) | served.get(page.url, set())
    for name, variant, amount in session.execute(
        _GOLD, {"record": record.record_id, "venue": scopes[0], "organization": scopes[1]}
    ):
        trace.selected.add((normalized(name), normalized(variant), amount))
    structured = validator_rows(menu_items(html))
    trace.proposed.extend(structured)
    verdicts = list(validate(blocks, structured).verdicts)
    for head in session.execute(_HEADS, {"record": record.record_id, "root": ROOT_KEY}):
        if head.source_record_version_id != record.version_id or head.state != "published":
            continue
        for name, variant, amount in session.execute(_PRICES, {"page": head.id}):
            trace.stored.add((normalized(name), normalized(variant), amount))
        if head.source_kind == "llm":
            trace.interpreted = True
            extractor = ";".join(head.method_version.split(";")[:EXTRACTOR_PARTS])
            saved = OutputStore(base).read_record(extractor, record.text_hash)
            if saved is None or len(saved["chunks"]) != len(chunks(blocks)):
                raise ValueError(f"Incomplete saved answers for {page.url}")
            parsed = [parse_output(c["raw"]) for c in saved["chunks"]]
            for output in parsed:
                for section in output.sections:
                    for raw in section.rows:
                        price = row_price(Row(raw.name, raw.price, variant=raw.variant))
                        if price is not None:
                            trace.raw.add(price)
            trace.proposed.extend(rows_of(parsed, blocks))
            verdicts.extend(llm_stream(blocks, parsed, html).validation.verdicts)
    for verdict in verdicts:
        key = row_price(verdict.row)
        if key is not None and verdict.decision != "accept":
            trace.rejected[key] = ", ".join(verdict.reasons)
    return trace


def first_loss(trace: Trace, state: State, label: Label) -> tuple[str, str]:
    if normalized(state.anchor) not in trace.blocks:
        return "state_missing", state.anchor
    keys = label.keys
    if keys & trace.published:
        return "served", ""
    if keys & trace.selected:
        return "publication_loss", ""
    if keys & trace.stored:
        return "selection_loss", ""
    if not trace.interpreted:
        return "no_current_extraction", ""
    for key in sorted(keys):
        if key in trace.rejected:
            return "price_rejected", trace.rejected[key]
    if keys & trace.raw and not any(row_price(r) in keys for r in trace.proposed):
        return "answer_repair_loss", "exact raw answer absent after repair and stitching"
    candidates = [r for r in trace.proposed if normalized(r.item) == normalized(label.item)]
    if not candidates:
        return "item_omitted", ""
    if not any(normalized(r.variant) in {k[1] for k in keys} for r in candidates):
        return "variant_omitted", ""
    if any(row_price(r) in keys for r in candidates):
        return "extraction_loss", "proposed exact price absent from stored rows"
    return "price_mismatch_or_omitted", ""


def measure(session: Session, client: TestClient, base: Path, venue: Venue) -> dict[str, Any]:
    subject, organization = session.execute(_VENUE, {"gers": venue.gers}).one()
    response = client.get(f"/v1/venues/{subject}/menu")
    response.raise_for_status()
    served = api_prices(VenueMenuResponse.model_validate(response.json()))
    captures = session.execute(_CAPTURED, {"gers": venue.gers}).all()
    by_url = {r.url: r for r in captures}
    if len(by_url) != len(captures):
        raise ValueError(f"Ambiguous records for {venue.venue}")
    other_urls = {url for page in venue.pages for url in page.other_location_urls}
    wrong = sorted(other_urls & by_url.keys())
    discovered = set(session.execute(_DISCOVERED, {"gers": venue.gers}).scalars())
    rows = []
    for page in venue.pages:
        rec = by_url.get(page.url)
        trace = (
            trace_page(session, rec, page, base, served, (subject, organization)) if rec else None
        )
        missing = ("discovery_miss", "no resolved menu URL")
        if trace is None and page.url in discovered:
            fetch = session.execute(_LAST_FETCH, {"url": page.url}).one_or_none()
            missing = ("capture_missing", "no saved menu version")
            if fetch is not None:
                missing = ("capture_missing", fetch.reason_code or fetch.outcome)
        elif trace is None and set(page.other_location_urls) & set(wrong):
            missing = ("wrong_location", "captured labelled alternate location")
        seen: set[Price] = set()
        for state in page.states:
            for label in state.prices:
                if label.keys & seen:
                    raise ValueError(f"Ambiguous price label on {page.url}: {label}")
                seen.update(label.keys)
                loss, reason = first_loss(trace, state, label) if trace is not None else missing
                rows.append(
                    {
                        "url": page.url,
                        "state": state.name,
                        **label.model_dump(),
                        "first_loss": loss,
                        "reason": reason,
                    }
                )
    counts = Counter(r["first_loss"] for r in rows)
    gained = sum(r["baseline"] != "served" and r["first_loss"] == "served" for r in rows)
    lost = sum(r["baseline"] == "served" and r["first_loss"] != "served" for r in rows)
    return {
        "venue": venue.venue,
        "template": venue.template,
        "expected": len(rows),
        "served": counts["served"],
        "gained": gained,
        "lost": lost,
        "counts": dict(counts),
        "prices": rows,
        "wrong_location_captures": wrong,
        "wrong_location_published": sorted(other_urls & served.keys()),
    }


def report(manifest: Manifest, session: Session, base: Path) -> dict[str, Any]:
    with (
        patch.dict(app.dependency_overrides, {get_session: lambda: session}),
        TestClient(app) as client,
    ):
        venues = [measure(session, client, base, venue) for venue in manifest.venues]
    return {
        "cohort": manifest.cohort,
        "venues": venues,
        "venue_macro_recall": sum(v["served"] / v["expected"] for v in venues) / len(venues),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--base-dir", type=Path, default=Path())
    args = parser.parse_args()
    manifest = Manifest.model_validate_json(args.manifest.read_text())
    with get_sessionmaker()() as session:
        session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"))
        print(json.dumps(report(manifest, session, args.base_dir), indent=2))


if __name__ == "__main__":
    main()
