"""Pure current/accepted-history Menu selection and ranking (read side).

This is the read complement of the accepted immutable writer. It reads already
committed Menu aggregates and returns deterministic selections; it never writes,
commits, extracts, matches fuzzily, or projects Gold. Two modes are explicit:

* **current** — live Identity eligibility, the originally accepted resolution
  event still current, and operating availability at ``E``. A stale mapping,
  ineligible/retired scope, pending lineage, or a closed/out-of-interval
  Establishment yields no local value with an explicit reason, never a guess.
* **history** — accepted-claim reconstruction under a knowledge cutoff ``K``, an
  optional observation cutoff ``O``, and effective instant ``E``. The stream
  head is chosen at ``K`` *before* observation/context filtering; a filtered
  head never revives a predecessor, and a tombstone visible by ``K`` still
  blocks older pages even when its observation time exceeds ``O``.

Ranking is by interpretation kind (``jsonld > dom > pdf > llm``), then later
observation time, then confidence (page confidence for content, price
confidence for prices), then ascending canonical Bronze business key. Local and
mapped-base ancestor restrictions are intersected before any comparison;
overlapping-but-unequal effective tuples stay distinct, ``unspecified`` is not a
channel wildcard, and ``E`` filters half-open window membership. Shared and
sibling prices are never inferred as a local price: an absent local price
returns a derived unknown with no invented Evidence, while an explicitly
observed unknown/unavailable price keeps its own observation and support.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from sqlalchemy import select, text

from packages.helios_core.domains.menu.models import (
    EvidenceLink,
    MenuApplicability,
    MenuItem,
    MenuModifier,
    MenuPage,
    MenuSection,
    MenuVariant,
    PriceObservation,
)
from packages.helios_core.identity.contracts import (
    ResolvedScope,
    ResolvedScopeRequest,
    current_resolved_scopes,
)
from packages.helios_core.provenance.contracts import get_record_version

if TYPE_CHECKING:
    from collections.abc import Iterable
    from datetime import datetime
    from decimal import Decimal

    from sqlalchemy.orm import Session

    from packages.helios_core.domains.menu.contracts import NodeKind

KIND_RANK: dict[str, int] = {"jsonld": 0, "dom": 1, "pdf": 2, "llm": 3}

# Reasons a local value is absent or withheld. ``priced``/``unknown``/
# ``unavailable`` mirror stored ``price_state``; the rest are derived read-side.
# ``unresolved_scope`` is the single boundary-respecting reason for any failed
# live-Identity check (stale mapping, retired/ineligible scope, pending lineage,
# or unmapped record): the specific cause is an Identity-module concern that the
# published scope guard deliberately does not expose to a vertical.
LocalState = Literal[
    "priced",
    "unknown",
    "unavailable",
    "absent",
    "withdrawn",
    "unresolved_base",
    "unresolved_scope",
    "not_operating",
]


@dataclass(frozen=True, slots=True)
class TargetRef:
    """A stable target identity: the native-key path from root to the leaf node.

    Each element is ``(node_kind, source_native_key)``. Correspondence follows
    base links and native keys, never names or positions, so JSON-LD and DOM
    claims that carry the same genuine native IDs compete for one target.
    """

    kind: NodeKind
    native_path: tuple[tuple[str, str], ...]


@dataclass(frozen=True, slots=True)
class ContextRef:
    """One exact effective context to match after ancestor/base intersection."""

    channel: Literal["unspecified", "dine_in", "takeaway"]
    service_period: str | None = None
    valid_from: datetime | None = None
    valid_to: datetime | None = None


@dataclass(frozen=True, slots=True)
class SelectionRequest:
    """Inputs for one selection over a single source-local family and target."""

    subject_id: int
    subject_kind: Literal["organization", "establishment"]
    source_record_id: int
    root_key: str
    target: TargetRef
    context: ContextRef
    currency_code: str
    effective_instant: datetime
    knowledge_cutoff: datetime | None = None
    observation_cutoff: datetime | None = None


@dataclass(frozen=True, slots=True)
class ContentResult:
    """The selected item/section content and the scope that actually asserted it."""

    page_id: int
    scope: Literal["local", "organization"]
    scope_subject_id: int
    source_kind: str
    name: str | None
    description: str | None
    observed_at: datetime
    evidence_ids: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class PriceResult:
    """The local price value (or the explicit reason there is none)."""

    state: LocalState
    scope_subject_id: int | None
    amount_minor: int | None = None
    currency_code: str | None = None
    page_id: int | None = None
    source_kind: str | None = None
    observed_at: datetime | None = None
    confidence: Decimal | None = None
    evidence_ids: tuple[int, ...] = ()


@dataclass(frozen=True, slots=True)
class OrganizationClaim:
    """A shared Organization price, shown separately and never merged as local."""

    origin: Literal["pinned", "head"]
    page_id: int
    subject_id: int
    price_state: str
    amount_minor: int | None
    currency_code: str
    observed_at: datetime
    source_kind: str
    confidence: Decimal
    evidence_ids: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class Selection:
    """The complete deterministic result of one selection request."""

    mode: Literal["current", "history"]
    content: ContentResult | None
    local_price: PriceResult
    organization: tuple[OrganizationClaim, ...]


# --------------------------------------------------------------------------- #
# Internal in-memory graph of one committed page.
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class _Node:
    kind: str
    id: int
    page_id: int
    parent_kind: str | None
    parent_id: int | None
    base_id: int | None
    applicability_id: int | None
    native_key: str | None
    effect: str
    support_kind: str
    name: str | None
    description: str | None


def _node_from_row(kind: str, row: MenuSection | MenuItem | MenuVariant | MenuModifier) -> _Node:
    if isinstance(row, MenuSection):
        parent_kind, parent_id = "section", row.parent_section_id
        base_id, name, description = row.base_section_id, row.name, None
    elif isinstance(row, MenuItem):
        parent_kind, parent_id = "section", row.section_id
        base_id, name, description = row.base_item_id, row.name, row.description
    elif isinstance(row, MenuVariant):
        parent_kind, parent_id = "item", row.item_id
        base_id, name, description = row.base_variant_id, row.label, None
    else:
        parent_kind = "item" if row.item_id is not None else "section"
        parent_id = row.item_id if row.item_id is not None else row.section_id
        base_id, name, description = row.base_modifier_id, row.label, None
    return _Node(
        kind=kind,
        id=row.id,
        page_id=row.page_id,
        parent_kind=parent_kind,
        parent_id=parent_id,
        base_id=base_id,
        applicability_id=row.applicability_id,
        native_key=row.source_native_key,
        effect=row.effect,
        support_kind=row.support_kind,
        name=name,
        description=description,
    )


class _PageGraph:
    """All nodes of one page, indexed by ``(kind, id)`` for read-side traversal."""

    def __init__(self, session: Session, page_id: int) -> None:
        self.page_id = page_id
        self.nodes: dict[tuple[str, int], _Node] = {}
        for section in session.scalars(select(MenuSection).where(MenuSection.page_id == page_id)):
            self.nodes[("section", section.id)] = _node_from_row("section", section)
        for item in session.scalars(select(MenuItem).where(MenuItem.page_id == page_id)):
            self.nodes[("item", item.id)] = _node_from_row("item", item)
        for variant in session.scalars(select(MenuVariant).where(MenuVariant.page_id == page_id)):
            self.nodes[("variant", variant.id)] = _node_from_row("variant", variant)
        for modifier in session.scalars(
            select(MenuModifier).where(MenuModifier.page_id == page_id)
        ):
            self.nodes[("modifier", modifier.id)] = _node_from_row("modifier", modifier)

    def of_kind(self, kind: str) -> Iterable[_Node]:
        return (node for (k, _), node in self.nodes.items() if k == kind)


_GRAPH_CACHE_KEY = "_menu_page_graphs"


def _graph(session: Session, page_id: int) -> _PageGraph:
    cache: dict[int, _PageGraph] = session.info.setdefault(_GRAPH_CACHE_KEY, {})
    graph = cache.get(page_id)
    if graph is None:
        graph = _PageGraph(session, page_id)
        cache[page_id] = graph
    return graph


# --------------------------------------------------------------------------- #
# Correspondence: canonical native path following base links, never names.
# --------------------------------------------------------------------------- #


def _canonical_native_path(
    session: Session, page: MenuPage, node: _Node
) -> tuple[tuple[str, str], ...] | None:
    """Return the stable ``(kind, native_key)`` path, or ``None`` if version-local.

    A node with no own native key but a typed base link resolves through the
    base node (in the pinned page) to the base's identity, so an inherited
    reference and its shared base collapse to one correspondence. A node that
    is neither directly named nor base-linked has only a version-local locator.
    """
    if node.native_key is None:
        if node.base_id is None or page.base_organization_page_id is None:
            return None
        base_graph = _graph(session, page.base_organization_page_id)
        base_node = base_graph.nodes.get((node.kind, node.base_id))
        if base_node is None:
            return None
        base_page = session.get(MenuPage, page.base_organization_page_id)
        if base_page is None:
            return None
        return _canonical_native_path(session, base_page, base_node)
    graph = _graph(session, page.id)
    prefix: tuple[tuple[str, str], ...] = ()
    if node.parent_id is not None and node.parent_kind is not None:
        parent = graph.nodes.get((node.parent_kind, node.parent_id))
        if parent is not None:
            resolved = _canonical_native_path(session, page, parent)
            if resolved is None:
                return None
            prefix = resolved
    return (*prefix, (node.kind, node.native_key))


def _target_node(session: Session, page: MenuPage, target: TargetRef) -> _Node | None:
    """Find the node in ``page`` whose canonical native path equals the target."""
    graph = _graph(session, page.id)
    for node in graph.of_kind(target.kind):
        if _canonical_native_path(session, page, node) == target.native_path:
            return node
    return None


# --------------------------------------------------------------------------- #
# Effective applicability: intersect the full local+base ancestor path.
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class _Effective:
    channel: str
    service_period: str | None
    valid_from: datetime | None
    valid_to: datetime | None


def _path_applicability_ids(session: Session, kind: str, node_id: int) -> list[int]:
    rows = session.execute(
        text(
            "SELECT applicability_id FROM menu.node_path(:kind, :id) "
            "WHERE applicability_id IS NOT NULL"
        ),
        {"kind": kind, "id": node_id},
    )
    return [row[0] for row in rows]


def _effective_context(
    session: Session, kind: str, node_id: int, extra_applicability_id: int | None
) -> _Effective | None:
    """Intersect every restriction on the node's path (and an optional price
    context). Returns ``None`` when the intersection is empty/incompatible.
    """
    ids = _path_applicability_ids(session, kind, node_id)
    if extra_applicability_id is not None:
        ids.append(extra_applicability_id)
    if not ids:
        return _Effective("unspecified", None, None, None)
    rows = list(
        session.scalars(select(MenuApplicability).where(MenuApplicability.id.in_(sorted(set(ids)))))
    )
    channels = {row.channel for row in rows}
    if len(channels) > 1:
        return None
    periods = {row.service_period for row in rows if row.service_period is not None}
    if len(periods) > 1:
        return None
    lowers = [row.valid_from for row in rows if row.valid_from is not None]
    uppers = [row.valid_to for row in rows if row.valid_to is not None]
    valid_from = max(lowers) if lowers else None
    valid_to = min(uppers) if uppers else None
    if valid_from is not None and valid_to is not None and valid_from >= valid_to:
        return None
    return _Effective(
        channel=next(iter(channels)),
        service_period=next(iter(periods)) if periods else None,
        valid_from=valid_from,
        valid_to=valid_to,
    )


def _matches_context(effective: _Effective, context: ContextRef) -> bool:
    return (
        effective.channel == context.channel
        and effective.service_period == context.service_period
        and effective.valid_from == context.valid_from
        and effective.valid_to == context.valid_to
    )


def _contains_instant(effective: _Effective, instant: datetime) -> bool:
    return (effective.valid_from is None or effective.valid_from <= instant) and (
        effective.valid_to is None or instant < effective.valid_to
    )


# --------------------------------------------------------------------------- #
# Stream head selection at the acceptance cutoff K, before any factual filter.
# --------------------------------------------------------------------------- #


def _stream_heads(
    session: Session, source_record_id: int, root_key: str, cutoff: datetime | None
) -> dict[str, MenuPage]:
    """Return the visible head page per interpretation kind for one family.

    The head is the greatest stream revision whose ``accepted_at <= K`` (all
    committed rows in current mode). Lifecycle is resolved here, before O/E/
    context filtering, so a later filter never resurrects a predecessor. Rows
    are read in ``(stream_revision, id)`` order so the result, including its
    iteration order, never depends on the query plan.
    """
    stmt = select(MenuPage).where(
        MenuPage.source_record_id == source_record_id, MenuPage.root_key == root_key
    )
    if cutoff is not None:
        stmt = stmt.where(MenuPage.accepted_at <= cutoff)
    stmt = stmt.order_by(MenuPage.stream_revision, MenuPage.id)
    heads: dict[str, MenuPage] = {}
    for page in session.scalars(stmt):
        current = heads.get(page.source_kind)
        if current is None or page.stream_revision > current.stream_revision:
            heads[page.source_kind] = page
    return heads


# --------------------------------------------------------------------------- #
# Ranking keys.
# --------------------------------------------------------------------------- #


def _business_key(session: Session, page: MenuPage, claim_locator: str) -> str:
    version = get_record_version(session, page.source_record_version_id)
    return repr((version.canonical_key, claim_locator))


def _rank_key(
    session: Session,
    page: MenuPage,
    observed_at: datetime,
    confidence: Decimal,
    claim_locator: str,
) -> tuple[int, float, float, str]:
    return (
        KIND_RANK.get(page.source_kind, len(KIND_RANK)),
        -observed_at.timestamp(),
        -float(confidence),
        _business_key(session, page, claim_locator),
    )


# --------------------------------------------------------------------------- #
# Evidence lookups.
# --------------------------------------------------------------------------- #


def _link_evidence(
    session: Session, page_id: int, column: str, row_id: int | None
) -> tuple[int, ...]:
    stmt = select(EvidenceLink.evidence_id).where(EvidenceLink.page_id == page_id)
    if column == "page":
        stmt = stmt.where(EvidenceLink.page_target.is_(True))
    else:
        stmt = stmt.where(getattr(EvidenceLink, column) == row_id)
    return tuple(sorted(session.scalars(stmt)))


# --------------------------------------------------------------------------- #
# Base (pin) validity.
# --------------------------------------------------------------------------- #


def _base_withdrawn(session: Session, base: MenuPage, cutoff: datetime | None) -> bool:
    stmt = select(MenuPage).where(
        MenuPage.source_record_id == base.source_record_id,
        MenuPage.root_key == base.root_key,
        MenuPage.source_kind == base.source_kind,
        MenuPage.operation == "withdrawal",
        MenuPage.stream_revision > base.stream_revision,
    )
    if cutoff is not None:
        stmt = stmt.where(MenuPage.accepted_at <= cutoff)
    return session.scalar(stmt.limit(1)) is not None


def _scope_request(page: MenuPage) -> ResolvedScopeRequest:
    return ResolvedScopeRequest(page.subject_id, page.source_record_id, page.resolution_event_id)


def _live_scope(session: Session, page: MenuPage) -> ResolvedScope | None:
    """Re-check one page's accepted scope through Identity's read-only check.

    Returns the current ``ResolvedScope`` when the same subject/record/event
    mapping is still live and eligible, else ``None``. Reasons (remap, retire,
    pending lineage) stay inside Identity; the vertical only learns pass/fail.
    The check takes no locks and never aborts the caller's transaction, so a
    read can neither block nor break an Identity or Menu writer.
    """
    return current_resolved_scopes(session, [_scope_request(page)])[0]


def _base_valid(
    session: Session,
    request: SelectionRequest,
    base: MenuPage,
) -> bool:
    """A pin is usable when the base page is a published Organization page,
    visible by K, its observation passes O, and (current mode) its scope is
    still eligible and currently mapped.
    """
    if base.state != "published" or base.operation == "withdrawal":
        return False
    if request.observation_cutoff is not None and base.observed_at > request.observation_cutoff:
        return False
    if _base_withdrawn(session, base, request.knowledge_cutoff):
        return False
    if request.knowledge_cutoff is None:  # current mode: live checks on the base scope
        return _live_scope(session, base) is not None
    return True


# --------------------------------------------------------------------------- #
# Current-mode Identity gate through the published scope guard.
# --------------------------------------------------------------------------- #


def _operating_ok(scope: ResolvedScope, instant: datetime) -> bool:
    """Establishment scopes must be operating at ``E``; Organizations always are."""
    if scope.kind != "establishment":
        return True
    if scope.operating_status == "closed":
        return False
    if scope.valid_from is not None and scope.valid_from > instant:
        return False
    return scope.valid_to is None or instant < scope.valid_to


# --------------------------------------------------------------------------- #
# Content and price contenders.
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class _ContentCandidate:
    page: MenuPage
    node: _Node


def _content_candidates(
    session: Session, request: SelectionRequest, heads: dict[str, MenuPage]
) -> list[_ContentCandidate]:
    candidates: list[_ContentCandidate] = []
    for page in heads.values():
        if page.operation == "withdrawal":
            continue
        if request.observation_cutoff is not None and page.observed_at > request.observation_cutoff:
            continue
        node = _target_node(session, page, request.target)
        if node is None or node.effect == "suppress":
            continue
        candidates.append(_ContentCandidate(page, node))
    return candidates


def _resolve_content(
    session: Session, request: SelectionRequest, candidate: _ContentCandidate
) -> ContentResult | None:
    """Produce the content view, following an inherit reference to its base."""
    page, node = candidate.page, candidate.node
    if node.support_kind == "structural":
        return None
    if node.effect == "inherit":
        base_page_id = page.base_organization_page_id
        if base_page_id is None or node.base_id is None:
            return None
        base_page = session.get(MenuPage, base_page_id)
        if base_page is None or not _base_valid(session, request, base_page):
            return None
        base_node = _graph(session, base_page_id).nodes.get((node.kind, node.base_id))
        if base_node is None:
            return None
        if (
            request.observation_cutoff is not None
            and base_page.observed_at > request.observation_cutoff
        ):
            return None
        return ContentResult(
            page_id=base_page.id,
            scope="organization",
            scope_subject_id=base_page.subject_id,
            source_kind=base_page.source_kind,
            name=base_node.name,
            description=base_node.description,
            observed_at=base_page.observed_at,
            evidence_ids=_link_evidence(session, base_page.id, f"{node.kind}_id", base_node.id),
        )
    return ContentResult(
        page_id=page.id,
        scope="local",
        scope_subject_id=page.subject_id,
        source_kind=page.source_kind,
        name=node.name,
        description=node.description,
        observed_at=page.observed_at,
        evidence_ids=_link_evidence(session, page.id, f"{node.kind}_id", node.id),
    )


def _select_content(
    session: Session, request: SelectionRequest, heads: dict[str, MenuPage]
) -> ContentResult | None:
    candidates = _content_candidates(session, request, heads)
    ranked = sorted(
        candidates,
        key=lambda c: _rank_key(
            session, c.page, c.page.observed_at, c.page.confidence, f"content:{c.node.id}"
        ),
    )
    for candidate in ranked:
        content = _resolve_content(session, request, candidate)
        if content is not None:
            return content
    return None


@dataclass(frozen=True, slots=True)
class _PriceCandidate:
    page: MenuPage
    price: PriceObservation
    node: _Node


def _price_target_column(price: PriceObservation) -> tuple[str, int]:
    for kind in ("section", "item", "variant", "modifier"):
        value = getattr(price, f"{kind}_id")
        if value is not None:
            return kind, value
    raise ValueError("price has no typed target")  # pragma: no cover - schema XOR guarantees one


def _price_contenders(
    session: Session, request: SelectionRequest, heads: dict[str, MenuPage]
) -> list[_PriceCandidate]:
    """Local prices whose target corresponds to the requested target, whose
    effective context equals the request, and whose window contains ``E``.
    """
    contenders: list[_PriceCandidate] = []
    for page in heads.values():
        if page.operation == "withdrawal":
            continue
        if request.observation_cutoff is not None and page.observed_at > request.observation_cutoff:
            continue
        graph = _graph(session, page.id)
        for price in session.scalars(
            select(PriceObservation).where(PriceObservation.page_id == page.id)
        ):
            if price.currency_code != request.currency_code:
                continue
            kind, node_id = _price_target_column(price)
            node = graph.nodes.get((kind, node_id))
            if node is None or node.effect == "suppress":
                continue
            if _canonical_native_path(session, page, node) != request.target.native_path:
                continue
            effective = _effective_context(session, kind, node_id, price.applicability_id)
            if effective is None or not _matches_context(effective, request.context):
                continue
            if not _contains_instant(effective, request.effective_instant):
                continue
            contenders.append(_PriceCandidate(page, price, node))
    return contenders


def _price_result(session: Session, page: MenuPage, price: PriceObservation) -> PriceResult:
    state: LocalState = price.price_state  # type: ignore[assignment]
    return PriceResult(
        state=state,
        scope_subject_id=page.subject_id,
        amount_minor=price.amount_minor,
        currency_code=price.currency_code,
        page_id=page.id,
        source_kind=page.source_kind,
        observed_at=page.observed_at,
        confidence=price.confidence,
        evidence_ids=_link_evidence(session, page.id, "price_id", price.id),
    )


def _depends_on_base(session: Session, page: MenuPage, node: _Node) -> bool:
    """True when the target rides an inherit/base correspondence rather than a
    fully independent, directly supported local addition.
    """
    graph = _graph(session, page.id)
    current: _Node | None = node
    while current is not None:
        if current.base_id is not None or current.effect == "inherit":
            return True
        if current.parent_id is None or current.parent_kind is None:
            break
        current = graph.nodes.get((current.parent_kind, current.parent_id))
    return False


def _select_local_price(
    session: Session,
    request: SelectionRequest,
    heads: dict[str, MenuPage],
) -> PriceResult:
    contenders = _price_contenders(session, request, heads)
    if not contenders:
        # No local price row exists: a derived unknown, with no invented
        # Evidence and no shared/sibling fallback.
        return PriceResult(state="absent", scope_subject_id=request.subject_id)
    resolvable: list[_PriceCandidate] = []
    for candidate in contenders:
        if not _depends_on_base(session, candidate.page, candidate.node):
            resolvable.append(candidate)
            continue
        base_id = candidate.page.base_organization_page_id
        base = session.get(MenuPage, base_id) if base_id is not None else None
        if base is not None and _base_valid(session, request, base):
            resolvable.append(candidate)
    if not resolvable:
        # Only base-dependent contenders existed and the pin is unresolved: keep
        # history but return no resolved local price. No sibling/base fallback.
        return PriceResult(state="unresolved_base", scope_subject_id=request.subject_id)
    ranked = sorted(
        resolvable,
        key=lambda c: _rank_key(
            session, c.page, c.page.observed_at, c.price.confidence, c.price.observation_key
        ),
    )
    winner = ranked[0]
    return _price_result(session, winner.page, winner.price)


# --------------------------------------------------------------------------- #
# Organization (shared) claims, always separate from the local value.
# --------------------------------------------------------------------------- #


def _org_claim(
    session: Session,
    request: SelectionRequest,
    page: MenuPage,
    origin: Literal["pinned", "head"],
) -> OrganizationClaim | None:
    node = _target_node(session, page, request.target)
    if node is None or node.effect in {"suppress", "inherit"}:
        return None
    kind, node_id = node.kind, node.id
    for price in session.scalars(
        select(PriceObservation).where(PriceObservation.page_id == page.id)
    ):
        target = _price_target_column(price)
        if target != (kind, node_id) or price.currency_code != request.currency_code:
            continue
        effective = _effective_context(session, kind, node_id, price.applicability_id)
        if effective is None or not _matches_context(effective, request.context):
            continue
        if not _contains_instant(effective, request.effective_instant):
            continue
        return OrganizationClaim(
            origin=origin,
            page_id=page.id,
            subject_id=page.subject_id,
            price_state=price.price_state,
            amount_minor=price.amount_minor,
            currency_code=price.currency_code,
            observed_at=page.observed_at,
            source_kind=page.source_kind,
            confidence=price.confidence,
            evidence_ids=_link_evidence(session, page.id, "price_id", price.id),
        )
    return None


def _organization_claims(
    session: Session,
    request: SelectionRequest,
    content: ContentResult | None,
) -> tuple[OrganizationClaim, ...]:
    """Surface shared claims from the pinned base page and the Organization
    stream head, each labelled and never merged into the local value.
    """
    if content is None or content.scope != "organization":
        return ()
    claims: list[OrganizationClaim] = []
    pinned = session.get(MenuPage, content.page_id)
    if pinned is None:
        return ()
    pinned_claim = _org_claim(session, request, pinned, "pinned")
    if pinned_claim is not None:
        claims.append(pinned_claim)
    org_heads = _stream_heads(
        session, pinned.source_record_id, pinned.root_key, request.knowledge_cutoff
    )
    head = org_heads.get(pinned.source_kind)
    if head is not None and head.id != pinned.id:
        head_claim = _org_claim(session, request, head, "head")
        if head_claim is not None:
            claims.append(head_claim)
    return tuple(claims)


# --------------------------------------------------------------------------- #
# Public entrypoint.
# --------------------------------------------------------------------------- #


def select_price(session: Session, request: SelectionRequest) -> Selection:
    """Select the deterministic current or accepted-history price for one target.

    ``knowledge_cutoff`` present selects history mode; absent selects current
    mode. The caller owns a read transaction; this performs no writes or commits.
    """
    session.flush()
    mode: Literal["current", "history"] = (
        "history" if request.knowledge_cutoff is not None else "current"
    )
    heads = _stream_heads(
        session, request.source_record_id, request.root_key, request.knowledge_cutoff
    )

    if mode == "current":
        # Heads are chosen over the whole family first, then only the requested
        # subject's own heads count: a remapped or retired predecessor's page
        # never supplies a successor's current value (ADR-0004 §5).
        heads = _subject_heads(heads, request.subject_id)
        # Current mode gates on live Identity/operating before any factual read.
        if heads:
            gate = _current_gate(session, heads, request.effective_instant)
            if gate is not None:
                return Selection(mode, None, PriceResult(gate, request.subject_id), ())

    content = _select_content(session, request, heads)
    local_price = _select_local_price(session, request, heads)

    if content is None and local_price.state == "absent" and _has_withdrawn_head(heads):
        # A tombstone (per stream) blocks its predecessors; distinguish this
        # deliberate withdrawal from a plain missing price.
        local_price = PriceResult("withdrawn", request.subject_id)

    organization = _organization_claims(session, request, content)
    return Selection(mode, content, local_price, organization)


def _has_withdrawn_head(heads: dict[str, MenuPage]) -> bool:
    return any(page.operation == "withdrawal" for page in heads.values())


def _subject_heads(heads: dict[str, MenuPage], subject_id: int) -> dict[str, MenuPage]:
    """The family's stream heads owned by one subject, in head iteration order."""
    return {kind: page for kind, page in heads.items() if page.subject_id == subject_id}


def _current_gate(
    session: Session, heads: dict[str, MenuPage], instant: datetime
) -> LocalState | None:
    """Live Identity + operating checks over one subject's current heads.

    Shared by the selector and full-catalog enumeration so both admit exactly
    the same scopes. Every head's own subject/record/event mapping must still
    be current and eligible, so a remap, retirement, or pending lineage that
    breaks any accepted head's mapping withholds the current value, whatever
    order the heads were read in. Returns the failure reason, or ``None`` when
    the scope is usable at ``instant``.
    """
    requests = sorted(
        {_scope_request(page) for page in heads.values()},
        key=lambda r: (r.subject_id, r.source_record_id, r.resolution_event_id),
    )
    scopes = current_resolved_scopes(session, requests)
    live = [scope for scope in scopes if scope is not None]
    if len(live) != len(scopes):
        return "unresolved_scope"
    if not all(_operating_ok(scope, instant) for scope in live):
        return "not_operating"
    return None
