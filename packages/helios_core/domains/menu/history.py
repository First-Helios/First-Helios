"""Accepted price history of one Gold target, through the selector (ADR-0018 §B).

``gold.current_menu`` holds current answers only (ADR-0006 D5.3), so the trail
behind a price is read here, from committed Menu, through the selector's history
mode (ADR-0008 Amendment 3). This module is a pure read beside
:mod:`enumeration`: it reuses the selector's correspondence and context helpers
and leaves every precedence decision to :func:`select_price`.

* **Contexts.** One trail per effective context and currency the scope itself
  ever priced the target in: every price observation on the scope's own pages
  of the family whose node is the target (the selector's ``_target_node`` rule).
* **Points.** The answer can change only when a page of the family is accepted,
  so the candidate knowledge cutoffs are the family's ``accepted_at`` instants,
  from the first acceptance of a scope page pricing the target in the context
  (earlier instants would only report the not-yet-existing target ``absent``).
  For each ``K`` in ascending order, ``select_price`` runs with
  ``knowledge_cutoff = effective_instant = K``; a point is emitted when
  ``(state, amount, page)`` differs from the previous point.
* **Own claims only.** History-mode heads are family-wide (ADR-0005 §9). An
  instant whose answer comes from another subject's page (the record was mapped
  elsewhere before or after a remap) is that subject's history and emits no
  point; so does a derived no-value answer unless every head at ``K`` is the
  scope's own. Organization claims are never mixed into a local trail.

Under version-local native keys (ADR-0013 N1) a trail is short: accepted,
perhaps corrected, then ``absent`` once a newer Version's page is accepted or
``withdrawn`` after a tombstone. No continuity across Versions is claimed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, cast

from sqlalchemy import select

from packages.helios_core.domains.menu.models import MenuPage, PriceObservation
from packages.helios_core.domains.menu.selection import (
    ContextRef,
    SelectionRequest,
    _effective_context,
    _price_target_column,
    _stream_heads,
    _target_node,
    select_price,
)

if TYPE_CHECKING:
    from datetime import datetime
    from decimal import Decimal

    from sqlalchemy.orm import Session

    from packages.helios_core.domains.menu.selection import LocalState, TargetRef

_Channel = Literal["unspecified", "dine_in", "takeaway"]


@dataclass(frozen=True, slots=True)
class HistoryPoint:
    """The accepted local answer from ``known_from`` until the next point."""

    known_from: datetime
    state: LocalState
    amount_minor: int | None
    observed_at: datetime | None
    source_kind: str | None
    confidence: Decimal | None


@dataclass(frozen=True, slots=True)
class PriceTrail:
    """The points of one effective context and currency, oldest first."""

    context: ContextRef
    currency_code: str
    points: tuple[HistoryPoint, ...]


def _context_key(trail: tuple[ContextRef, str]) -> tuple[str, ...]:
    context, currency = trail
    return (
        context.channel,
        context.service_period or "",
        context.valid_from.isoformat() if context.valid_from is not None else "",
        context.valid_to.isoformat() if context.valid_to is not None else "",
        currency,
    )


def _claimed_contexts(
    session: Session, pages: list[MenuPage], target: TargetRef
) -> list[tuple[ContextRef, str, datetime]]:
    """Every ``(context, currency)`` the pages price ``target`` in, with the
    ``accepted_at`` of the first such page (``pages`` are in acceptance order).
    """
    found: dict[tuple[ContextRef, str], datetime] = {}
    for page in pages:
        if page.operation == "withdrawal":
            continue
        node = _target_node(session, page, target)
        if node is None or node.effect == "suppress":
            continue
        for price in session.scalars(
            select(PriceObservation)
            .where(PriceObservation.page_id == page.id)
            .order_by(PriceObservation.id)
        ):
            kind, node_id = _price_target_column(price)
            if (kind, node_id) != (node.kind, node.id):
                continue
            effective = _effective_context(session, kind, node_id, price.applicability_id)
            if effective is None:
                continue
            context = ContextRef(
                channel=cast("_Channel", effective.channel),
                service_period=effective.service_period,
                valid_from=effective.valid_from,
                valid_to=effective.valid_to,
            )
            found.setdefault((context, price.currency_code), page.accepted_at)
    return [(*trail, found[trail]) for trail in sorted(found, key=_context_key)]


def price_history(
    session: Session,
    *,
    subject_id: int,
    subject_kind: Literal["organization", "establishment"],
    source_record_id: int,
    root_key: str,
    target: TargetRef,
) -> list[PriceTrail] | None:
    """The scope's accepted trail per context for one target, or ``None``.

    ``None`` means the scope never priced the target in that family. A trail may
    have no points when no acceptance instant made it the scope's answer (for
    example a context whose window never contains its own acceptance instant).
    Read-only; the caller owns the read transaction.
    """
    session.flush()
    pages = list(
        session.scalars(
            select(MenuPage)
            .where(MenuPage.source_record_id == source_record_id, MenuPage.root_key == root_key)
            .order_by(MenuPage.accepted_at, MenuPage.id)
        )
    )
    own = [
        page for page in pages if (page.subject_id, page.subject_kind) == (subject_id, subject_kind)
    ]
    contexts = _claimed_contexts(session, own, target)
    if not contexts:
        return None
    instants = sorted({page.accepted_at for page in pages})
    owned_at = {
        instant: _owns_heads(session, source_record_id, root_key, instant, subject_id)
        for instant in instants
    }
    trails: list[PriceTrail] = []
    for context, currency, first_claim in contexts:
        points: list[HistoryPoint] = []
        last: tuple[str, int | None, int | None] | None = None
        for instant in instants:
            if instant < first_claim:
                continue  # before the scope first priced it, the target did not exist yet
            price = select_price(
                session,
                SelectionRequest(
                    subject_id=subject_id,
                    subject_kind=subject_kind,
                    source_record_id=source_record_id,
                    root_key=root_key,
                    target=target,
                    context=context,
                    currency_code=currency,
                    effective_instant=instant,
                    knowledge_cutoff=instant,
                ),
            ).local_price
            if price.page_id is not None:
                if price.scope_subject_id != subject_id:
                    continue  # another subject's page answers at K: not this scope's claim
            elif not owned_at[instant]:
                continue  # a derived answer over heads that are not all this scope's
            key = (price.state, price.amount_minor, price.page_id)
            if key == last:
                continue
            last = key
            points.append(
                HistoryPoint(
                    known_from=instant,
                    state=price.state,
                    amount_minor=price.amount_minor,
                    observed_at=price.observed_at,
                    source_kind=price.source_kind,
                    confidence=price.confidence,
                )
            )
        trails.append(PriceTrail(context, currency, tuple(points)))
    return trails


def _owns_heads(
    session: Session, source_record_id: int, root_key: str, instant: datetime, subject_id: int
) -> bool:
    """Whether every family stream head visible at ``instant`` is the scope's own."""
    heads = _stream_heads(session, source_record_id, root_key, instant)
    return bool(heads) and all(page.subject_id == subject_id for page in heads.values())
