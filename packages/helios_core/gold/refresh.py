"""Full deterministic rebuild of the ``gold.current_menu`` projection (ADR-0006).

The accepted pure Menu selector is the single definition of "current": for each
caller-supplied :class:`SelectionRequest` this records ``select_price``'s result
as one ``gold.current_menu`` row. The refresh is a full rebuild over a bounded
input set of scopes -- it deletes the projection for every requested family and
re-inserts -- so a lost table is reconstructed from Identity + Menu (+ Bronze
provenance) without mutating them. Full-catalog enumeration is deferred
(ADR-0006 Owner decision). Selection precedence, lifecycle, applicability and
no-inferred-price rules are never re-implemented here.

Business columns are a deterministic function of committed input and the
request; ``refreshed_at`` is the only non-deterministic column and is excluded
from rebuild-equality checks. The command flushes; the caller owns the commit.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import delete, insert

from packages.helios_core.domains.menu.selection import (
    Selection,
    SelectionRequest,
    select_price,
)
from packages.helios_core.gold.models import CurrentMenu

if TYPE_CHECKING:
    from collections.abc import Iterable

    from sqlalchemy.orm import Session


def _encode_path(native_path: tuple[tuple[str, str], ...]) -> str:
    """Deterministic canonical encoding of the target's native-key path."""
    return json.dumps([[kind, key] for kind, key in native_path], separators=(",", ":"))


def _row_values(
    request: SelectionRequest, selection: Selection, refreshed_at: datetime
) -> dict[str, Any]:
    price = selection.local_price
    content = selection.content
    staleness: int | None = None
    if price.state == "priced" and price.observed_at is not None:
        staleness = int((request.effective_instant - price.observed_at).total_seconds())
    return {
        "subject_id": request.subject_id,
        "subject_kind": request.subject_kind,
        "source_record_id": request.source_record_id,
        "root_key": request.root_key,
        "target_kind": request.target.kind,
        "target_path": _encode_path(request.target.native_path),
        "channel": request.context.channel,
        "service_period": request.context.service_period,
        "valid_from": request.context.valid_from,
        "valid_to": request.context.valid_to,
        "currency_code": request.currency_code,
        "effective_instant": request.effective_instant,
        "price_state": price.state,
        "amount_minor": price.amount_minor,
        "price_scope_subject_id": price.scope_subject_id,
        "price_source_kind": price.source_kind,
        "price_observed_at": price.observed_at,
        "price_confidence": price.confidence,
        "price_page_id": price.page_id,
        "price_evidence_ids": list(price.evidence_ids),
        "staleness_seconds": staleness,
        "content_scope": content.scope if content is not None else None,
        "content_name": content.name if content is not None else None,
        "content_description": content.description if content is not None else None,
        "content_source_kind": content.source_kind if content is not None else None,
        "content_observed_at": content.observed_at if content is not None else None,
        "content_scope_subject_id": content.scope_subject_id if content is not None else None,
        "content_page_id": content.page_id if content is not None else None,
        "content_evidence_ids": list(content.evidence_ids) if content is not None else [],
        "organization_claim_count": len(selection.organization),
        "refreshed_at": refreshed_at,
    }


def refresh_current_menu(
    session: Session,
    requests: Iterable[SelectionRequest],
    *,
    refreshed_at: datetime | None = None,
) -> int:
    """Rebuild ``gold.current_menu`` for the requested bounded scope set.

    Every ``(subject, source record, root)`` family named by ``requests`` is
    fully cleared first, then one row per request is inserted from the selector
    result. Returns the number of rows written. Requests must be grain-unique;
    a duplicate grain is a caller error the unique constraint rejects.
    """
    ordered = list(requests)
    stamp = refreshed_at if refreshed_at is not None else datetime.now(UTC)

    families = sorted(
        {(r.subject_id, r.subject_kind, r.source_record_id, r.root_key) for r in ordered}
    )
    for subject_id, subject_kind, source_record_id, root_key in families:
        session.execute(
            delete(CurrentMenu).where(
                CurrentMenu.subject_id == subject_id,
                CurrentMenu.subject_kind == subject_kind,
                CurrentMenu.source_record_id == source_record_id,
                CurrentMenu.root_key == root_key,
            )
        )
    session.flush()

    rows = [_row_values(request, select_price(session, request), stamp) for request in ordered]
    if rows:
        session.execute(insert(CurrentMenu), rows)
    session.flush()
    return len(rows)
