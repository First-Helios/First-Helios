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
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING

from sqlalchemy import and_, or_, select

from packages.helios_core.gold.models import CurrentMenu

if TYPE_CHECKING:
    from collections.abc import Iterable
    from datetime import datetime
    from decimal import Decimal

    from sqlalchemy.orm import Session

SERVED_PRICE_STATES = ("priced", "unknown", "unavailable")


@dataclass(frozen=True, slots=True)
class CurrentMenuRow:
    """One served ``gold.current_menu`` row, with its target path decoded."""

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
    content_name: str | None
    content_description: str | None


def _decode_path(encoded: str) -> tuple[tuple[str, str], ...]:
    """Inverse of the refresh's canonical ``target_path`` encoding."""
    return tuple((kind, key) for kind, key in json.loads(encoded))


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
            CurrentMenu.content_name,
            CurrentMenu.content_description,
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
            content_name=row.content_name,
            content_description=row.content_description,
        )
        for row in session.execute(statement)
    ]
