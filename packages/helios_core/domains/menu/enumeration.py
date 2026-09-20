"""Full-catalog enumeration of current selection requests (ADR-0006 follow-up).

The bounded Gold refresh projects a caller-supplied scope set; ADR-0006's Owner
decision deferred enumerating "all current eligible scopes and targets" across
the catalog. This module is that enumeration, kept in the Menu domain beside the
accepted selector so there is a *single* definition of correspondence, effective
context, and current eligibility: it reuses the selector's own helpers rather
than re-deriving native paths, applicability intersection, or the live
Identity/operating gate. It reads committed Menu/Identity/Bronze and returns
``SelectionRequest`` values; it performs no writes and never re-implements
selection precedence (that stays in :func:`select_price`).

Scope of this first full-catalog unit (deliberately bounded; see the Step 6
full-catalog review):

* **Price-driven.** One request per grain-unique ``(scope subject, source-local
  family, target, effective context, currency)`` that has a live
  ``PriceObservation`` on a current head page whose effective window contains the
  refresh instant ``E``. ``gold.current_menu`` is a per-``(target, context,
  currency)`` price projection (RFC-0001 §D2), so a target that carries only
  inherited content with no local price observation is not enumerated here.
* **Current, eligible, and operating only.** A scope whose live-Identity mapping
  is broken (remap/retire/pending lineage) or whose Establishment is not
  operating at ``E`` is excluded, so retired-predecessor facts never enter the
  current catalog (ADR-0004 §5). Shared Organization prices are enumerated as
  their own ``organization``-scoped rows, never merged into a local value.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal, cast

from sqlalchemy import select

from packages.helios_core.domains.menu.models import MenuPage, PriceObservation
from packages.helios_core.domains.menu.selection import (
    ContextRef,
    SelectionRequest,
    TargetRef,
    _canonical_native_path,
    _contains_instant,
    _effective_context,
    _graph,
    _live_scope,
    _operating_ok,
    _price_target_column,
    _stream_heads,
)

if TYPE_CHECKING:
    from datetime import datetime

    from sqlalchemy.orm import Session

    from packages.helios_core.domains.menu.contracts import NodeKind

_Channel = Literal["unspecified", "dine_in", "takeaway"]
_Scope = Literal["organization", "establishment"]


def _sort_key(request: SelectionRequest) -> tuple[str, ...]:
    """A total, deterministic order so ids and insert order are stable per run."""
    context = request.context
    return (
        request.subject_kind,
        f"{request.subject_id:020d}",
        f"{request.source_record_id:020d}",
        request.root_key,
        request.target.kind,
        repr(request.target.native_path),
        context.channel,
        context.service_period or "",
        context.valid_from.isoformat() if context.valid_from is not None else "",
        context.valid_to.isoformat() if context.valid_to is not None else "",
        request.currency_code,
    )


def enumerate_current_requests(
    session: Session, *, effective_instant: datetime
) -> list[SelectionRequest]:
    """Enumerate current-mode requests for the whole priced catalog at ``E``.

    For every source-local family, the current stream heads select the scope
    subjects; each scope is admitted through the same live-Identity/operating
    gate the selector uses, and only its priced targets whose effective window
    contains ``E`` become grain-unique :class:`SelectionRequest` values. The
    result is deterministic given committed Bronze/Identity/Menu.
    """
    session.flush()
    families = (
        session.execute(select(MenuPage.source_record_id, MenuPage.root_key).distinct())
        .tuples()
        .all()
    )
    requests: list[SelectionRequest] = []
    seen: set[
        tuple[
            int,
            str,
            int,
            str,
            str,
            tuple[tuple[str, str], ...],
            str,
            str | None,
            datetime | None,
            datetime | None,
            str,
        ]
    ] = set()
    for source_record_id, root_key in families:
        heads = _stream_heads(session, source_record_id, root_key, None)
        if not heads:
            continue
        subjects = {(page.subject_id, page.subject_kind) for page in heads.values()}
        for subject_id, subject_kind in sorted(subjects):
            gate_head = min(
                (page for page in heads.values() if page.subject_id == subject_id),
                key=lambda page: page.id,
            )
            scope = _live_scope(session, gate_head)
            if scope is None or not _operating_ok(scope, effective_instant):
                continue  # broken mapping or not operating at E: excluded from current
            scope_kind = cast("_Scope", subject_kind)
            for page in heads.values():
                if page.operation == "withdrawal" or page.subject_id != subject_id:
                    continue
                graph = _graph(session, page.id)
                for price in session.scalars(
                    select(PriceObservation).where(PriceObservation.page_id == page.id)
                ):
                    node_kind, node_id = _price_target_column(price)
                    node = graph.nodes.get((node_kind, node_id))
                    if node is None or node.effect == "suppress":
                        continue
                    native_path = _canonical_native_path(session, page, node)
                    if native_path is None:
                        continue
                    effective = _effective_context(
                        session, node_kind, node_id, price.applicability_id
                    )
                    if effective is None or not _contains_instant(effective, effective_instant):
                        continue
                    grain = (
                        subject_id,
                        subject_kind,
                        source_record_id,
                        root_key,
                        node_kind,
                        native_path,
                        effective.channel,
                        effective.service_period,
                        effective.valid_from,
                        effective.valid_to,
                        price.currency_code,
                    )
                    if grain in seen:
                        continue
                    seen.add(grain)
                    requests.append(
                        SelectionRequest(
                            subject_id=subject_id,
                            subject_kind=scope_kind,
                            source_record_id=source_record_id,
                            root_key=root_key,
                            target=TargetRef(
                                kind=cast("NodeKind", node_kind), native_path=native_path
                            ),
                            context=ContextRef(
                                channel=cast("_Channel", effective.channel),
                                service_period=effective.service_period,
                                valid_from=effective.valid_from,
                                valid_to=effective.valid_to,
                            ),
                            currency_code=price.currency_code,
                            effective_instant=effective_instant,
                        )
                    )
    requests.sort(key=_sort_key)
    return requests
