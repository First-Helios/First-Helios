"""Read contract over ``gold.current_menu`` for one venue's menu (ROADMAP Phase 7).

The read API serves a venue's current menu from this projection only (ADR-0008
§9), never from the Menu selector or raw observations. A caller names the scope
Subjects to read -- the venue's Establishment and, when the caller decides the
Organization stands for that one venue, its Organization -- and gets plain rows
back in a fixed order; no ORM object leaves this module.

Only source-asserted states are served (:data:`SERVED_PRICE_STATES`). The
derived no-value states (``absent``, ``withdrawn``, ``unresolved_*``,
``not_operating``) mean "no current local value" and stay internal to the
selector. The query is index-backed by ``ix_gold_current_menu_scope``.

A menu's source page URL (:func:`menu_source_urls`) is read at request time
from the rows' price Evidence through the provenance contract (ADR-0008
Amendment 4); Gold stores no URL.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import and_, exists, or_, select

from packages.helios_core.gold.models import CurrentMenu
from packages.helios_core.provenance.contracts import source_endpoints_for_evidence

if TYPE_CHECKING:
    from collections.abc import Iterable
    from decimal import Decimal

    from sqlalchemy import ColumnElement
    from sqlalchemy.orm import InstrumentedAttribute, Session

SERVED_PRICE_STATES = ("priced", "unknown", "unavailable")

#: One source menu: ``(subject kind, subject id, source record id, root key)``.
type MenuFamily = tuple[str, int, int, str]

_NEVER = datetime.min.replace(tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class CurrentMenuRow:
    """One served ``gold.current_menu`` row, with its target path decoded."""

    subject_id: int
    subject_kind: str
    source_record_id: int
    root_key: str
    target_kind: str
    target_path: tuple[tuple[str, str], ...]  # (node kind, native key), root first
    channel: str
    service_period: str | None
    valid_from: datetime | None
    valid_to: datetime | None
    currency_code: str
    effective_instant: datetime
    price_state: str
    amount_minor: int | None
    price_source_kind: str | None
    price_observed_at: datetime | None
    price_confidence: Decimal | None
    price_page_id: int | None
    price_evidence_ids: tuple[int, ...]
    content_name: str | None
    content_description: str | None
    section_name: str | None
    item_name: str | None


def _decode_path(encoded: str) -> tuple[tuple[str, str], ...]:
    """Inverse of the refresh's canonical ``target_path`` encoding."""
    return tuple((kind, key) for kind, key in json.loads(encoded))


def has_served_menu(
    subject_id: ColumnElement[int] | InstrumentedAttribute[int], subject_kind: str
) -> ColumnElement[bool]:
    """``EXISTS`` a served row for the scope ``(subject_id, subject_kind)``.

    The same rows :func:`current_menu_rows` returns, as a semi-join a caller can
    correlate to its own subject column. Index-backed by
    ``ix_gold_current_menu_scope``.
    """
    return exists().where(
        CurrentMenu.subject_id == subject_id,
        CurrentMenu.subject_kind == subject_kind,
        CurrentMenu.price_state.in_(SERVED_PRICE_STATES),
    )


def current_menu_rows(session: Session, scopes: Iterable[tuple[int, str]]) -> list[CurrentMenuRow]:
    """Served rows of the given ``(subject id, subject kind)`` scopes.

    Ordered by scope kind (``establishment`` before ``organization``), source
    record, root key, target path, then context and currency, so a response
    built from them is deterministic. Read-only; takes no locks.
    """
    pairs = sorted(set(scopes))
    if not pairs:
        return []
    statement = (
        select(
            CurrentMenu.subject_id,
            CurrentMenu.subject_kind,
            CurrentMenu.source_record_id,
            CurrentMenu.root_key,
            CurrentMenu.target_kind,
            CurrentMenu.target_path,
            CurrentMenu.channel,
            CurrentMenu.service_period,
            CurrentMenu.valid_from,
            CurrentMenu.valid_to,
            CurrentMenu.currency_code,
            CurrentMenu.effective_instant,
            CurrentMenu.price_state,
            CurrentMenu.amount_minor,
            CurrentMenu.price_source_kind,
            CurrentMenu.price_observed_at,
            CurrentMenu.price_confidence,
            CurrentMenu.price_page_id,
            CurrentMenu.price_evidence_ids,
            CurrentMenu.content_name,
            CurrentMenu.content_description,
            CurrentMenu.section_name,
            CurrentMenu.item_name,
        )
        .where(
            or_(
                *(
                    and_(CurrentMenu.subject_id == subject_id, CurrentMenu.subject_kind == kind)
                    for subject_id, kind in pairs
                )
            ),
            CurrentMenu.price_state.in_(SERVED_PRICE_STATES),
        )
        .order_by(
            CurrentMenu.subject_kind,
            CurrentMenu.source_record_id,
            CurrentMenu.root_key,
            CurrentMenu.target_path,
            CurrentMenu.channel,
            CurrentMenu.service_period.nulls_first(),
            CurrentMenu.valid_from.nulls_first(),
            CurrentMenu.valid_to.nulls_first(),
            CurrentMenu.currency_code,
        )
    )
    return [
        CurrentMenuRow(
            subject_id=row.subject_id,
            subject_kind=row.subject_kind,
            source_record_id=row.source_record_id,
            root_key=row.root_key,
            target_kind=row.target_kind,
            target_path=_decode_path(row.target_path),
            channel=row.channel,
            service_period=row.service_period,
            valid_from=row.valid_from,
            valid_to=row.valid_to,
            currency_code=row.currency_code,
            effective_instant=row.effective_instant,
            price_state=row.price_state,
            amount_minor=row.amount_minor,
            price_source_kind=row.price_source_kind,
            price_observed_at=row.price_observed_at,
            price_confidence=row.price_confidence,
            price_page_id=row.price_page_id,
            price_evidence_ids=tuple(row.price_evidence_ids),
            content_name=row.content_name,
            content_description=row.content_description,
            section_name=row.section_name,
            item_name=row.item_name,
        )
        for row in session.execute(statement)
    ]


def menu_family(row: CurrentMenuRow) -> MenuFamily:
    """The source menu a served row belongs to."""
    return (row.subject_kind, row.subject_id, row.source_record_id, row.root_key)


def menu_source_urls(
    session: Session, rows: Iterable[CurrentMenuRow]
) -> dict[MenuFamily, str | None]:
    """Each family's source page URL, ``None`` when none of its Evidence resolves.

    The URL is the Source Endpoint of the family's most recent price Evidence
    (ADR-0008 Amendment 4): the greatest ``(price_observed_at, Capture
    fetched_at, Evidence id)`` over the Evidence of the family's rows that
    reaches a Capture, a null ``price_observed_at`` lowest.

    Every price Evidence of one Menu page cites that page's own Capture, so
    only each page's leader -- its greatest ``(price_observed_at, Evidence id)``
    -- is resolved: one provenance query for one or two ids per family, however
    many prices it holds. A page whose leader does not resolve has all its
    Evidence resolved in a second query. A row with no page is its own group
    per Evidence.
    """
    groups: dict[tuple[MenuFamily, int | None, int | None], list[tuple[datetime, int]]] = {}
    for row in rows:
        family, observed = menu_family(row), row.price_observed_at or _NEVER
        for evidence_id in row.price_evidence_ids:
            group = (
                family,
                row.price_page_id,
                None if row.price_page_id is not None else evidence_id,
            )
            groups.setdefault(group, []).append((observed, evidence_id))
        groups.setdefault((family, None, None), [])  # every family gets a URL entry
    leaders = {group: max(candidates) for group, candidates in groups.items() if candidates}
    endpoints = source_endpoints_for_evidence(session, (eid for _, eid in leaders.values()))
    unresolved = [group for group, (_, eid) in leaders.items() if eid not in endpoints]
    if unresolved:
        endpoints |= source_endpoints_for_evidence(
            session, (eid for group in unresolved for _, eid in groups[group])
        )
    best: dict[MenuFamily, tuple[datetime, datetime, int]] = {}
    urls: dict[MenuFamily, str | None] = {}
    for (family, _, _), candidates in groups.items():
        urls.setdefault(family, None)
        for observed, evidence_id in candidates:
            endpoint = endpoints.get(evidence_id)
            if endpoint is None:
                continue
            key = (observed, endpoint.fetched_at, evidence_id)
            if family not in best or key > best[family]:
                best[family] = key
                urls[family] = endpoint.source_url
    return urls
