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

Scope of this first full-catalog unit (deliberately bounded; see ADR-0006,
"Full-catalog refresh follow-up accepted"):

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
* **JSON-LD precedence per dish (ADR-0006 Amendment 2).** When a subject's live
  ``jsonld`` head prices a dish, the same dish on its ``llm`` head is not
  enumerated: the two streams key their dishes differently, so the selector's
  kind rank never compares them. A dish is a price target's item (the target
  itself, or a variant's or modifier's parent item); dishes match on their
  normalized name only (:func:`dish_key`). The llm stream's other dishes stay.
* **One dish once across a venue's own-site pages (ADR-0022 point 4).** A venue
  keeps up to three own-site menu pages, the ``menu-page`` records keyed
  ``<gers>`` and ``<gers>|<path>``. Those families are ranked ``<gers>`` first,
  then by key, whichever subject each is scoped to (one venue's pages may sit on
  its Organization and its Establishment); a dish on a later family whose dish key
  **and** price set equal a dish of an earlier family is not enumerated. The same
  name at other prices (lunch and dinner) stays, and platform families
  (``<gers>|<host>``) are not part of the rule.
"""

from __future__ import annotations

import re
import unicodedata
from typing import TYPE_CHECKING, Literal, cast

from sqlalchemy import select

from packages.helios_core.domains.menu.models import MenuPage, PriceObservation
from packages.helios_core.domains.menu.selection import (
    ContextRef,
    SelectionRequest,
    TargetRef,
    _canonical_native_path,
    _contains_instant,
    _current_gate,
    _effective_context,
    _graph,
    _price_target_column,
    _stream_heads,
    _subject_heads,
)
from packages.helios_core.provenance.contracts import get_record_version

if TYPE_CHECKING:
    from datetime import datetime

    from sqlalchemy.orm import Session

    from packages.helios_core.domains.menu.contracts import NodeKind
    from packages.helios_core.domains.menu.selection import _Node, _PageGraph

_Channel = Literal["unspecified", "dine_in", "takeaway"]
_Scope = Literal["organization", "establishment"]

# The validator's name normalization (``helios_parsing.validator.norm_tokens``),
# restated: helios_core does not import helios_parsing.
_WORD = re.compile(r"\w+", re.UNICODE)
_IGNORED = frozenset({"and", "the", "a", "of", "with", "w", "n"})
# ``apps.menu_pipeline.page_bronze.MENU_PAGE_NAMESPACE``, restated: helios_core does
# not import apps. Its keys are the menu-URL keys (ADR-0011 §7, ADR-0022 point 1).
MENU_PAGE_NAMESPACE = "menu-page"


def dish_key(name: str | None) -> frozenset[str] | None:
    """A dish name as an order-free word set (NFKC, lower case, "&" read as "and")."""
    if not name:
        return None
    text = unicodedata.normalize("NFKC", name).lower().replace("&", " and ")
    words = frozenset(word for word in _WORD.findall(text) if word not in _IGNORED)
    return words or None


def _dish(graph: _PageGraph, node: _Node) -> frozenset[str] | None:
    """The normalized name of a price target's item: itself, or its parent item."""
    if node.kind == "item":
        return dish_key(node.name)
    if node.parent_kind == "item" and node.parent_id is not None:
        item = graph.nodes.get(("item", node.parent_id))
        return dish_key(item.name) if item is not None else None
    return None


def _jsonld_dishes(session: Session, heads: dict[str, MenuPage]) -> frozenset[frozenset[str]]:
    """The dishes a subject's live ``jsonld`` head prices; empty without one."""
    page = heads.get("jsonld")
    if page is None or page.operation == "withdrawal":
        return frozenset()
    graph = _graph(session, page.id)
    dishes: set[frozenset[str]] = set()
    for price in session.scalars(
        select(PriceObservation).where(
            PriceObservation.page_id == page.id, PriceObservation.price_state == "priced"
        )
    ):
        node = graph.nodes.get(_price_target_column(price))
        if node is not None and node.effect != "suppress":
            dish = _dish(graph, node)
            if dish is not None:
                dishes.add(dish)
    return frozenset(dishes)


_Dish = tuple[frozenset[str], frozenset[tuple[int, str]]]  # (dish key, its price set)


def _family_dishes(session: Session, heads: dict[str, MenuPage]) -> frozenset[_Dish]:
    """Each dish one subject's live heads in a family price, with its set of amounts."""
    prices: dict[frozenset[str], set[tuple[int, str]]] = {}
    for page in heads.values():
        if page.operation == "withdrawal":
            continue
        graph = _graph(session, page.id)
        for price in session.scalars(
            select(PriceObservation).where(
                PriceObservation.page_id == page.id, PriceObservation.price_state == "priced"
            )
        ):
            node = graph.nodes.get(_price_target_column(price))
            dish = _dish(graph, node) if node is not None and node.effect != "suppress" else None
            if dish is not None and price.amount_minor is not None:
                prices.setdefault(dish, set()).add((price.amount_minor, price.currency_code))
    return frozenset((dish, frozenset(amounts)) for dish, amounts in prices.items())


def _own_site_rank(session: Session, page: MenuPage) -> tuple[str, int, str] | None:
    """``(gers, rank, key)`` of an own-site ``menu-page`` family; ``None`` for any other."""
    version = get_record_version(session, page.source_record_version_id)
    if version.source_namespace != MENU_PAGE_NAMESPACE:
        return None
    gers, _, suffix = version.external_key.partition("|")
    if suffix and not suffix.startswith("/"):
        return None  # a platform page, <gers>|<host>
    return gers, 1 if suffix else 0, version.external_key


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
    subjects; each scope is checked with the same read-only live-Identity/
    operating gate the selector uses (over all of the subject's heads), and
    only its priced targets whose effective window contains ``E`` become
    grain-unique :class:`SelectionRequest` values, less the llm head's dishes
    that the subject's live jsonld head also prices, and less the dishes an
    earlier own-site page of the same venue already prices at the same amounts.
    The result is deterministic given committed Bronze/Identity/Menu.
    """
    session.flush()
    families = (
        session.execute(select(MenuPage.source_record_id, MenuPage.root_key).distinct())
        .tuples()
        .all()
    )
    family_heads = {
        family: heads
        for family in families
        if (heads := _stream_heads(session, family[0], family[1], None))
    }
    ranks = {
        family: _own_site_rank(session, next(iter(heads.values())))
        for family, heads in family_heads.items()
    }
    # A venue's own-site families in rank order, then every other family.
    ordered = sorted(
        family_heads,
        key=lambda family: (ranks[family] or ("~", 0, ""), family[0], family[1]),
    )
    earlier: dict[str, set[_Dish]] = {}  # gers -> dishes of its earlier own-site families
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
    for source_record_id, root_key in ordered:
        heads = family_heads[(source_record_id, root_key)]
        rank = ranks[(source_record_id, root_key)]
        # The venue's earlier pages, whichever subject each is scoped to: one venue's
        # pages may sit on its Organization and its Establishment.
        prior = earlier.setdefault(rank[0], set()) if rank is not None else set()
        family_dishes: set[_Dish] = set()
        subjects = {(page.subject_id, page.subject_kind) for page in heads.values()}
        for subject_id, subject_kind in sorted(subjects):
            owned = _subject_heads(heads, subject_id)
            if _current_gate(session, owned, effective_instant) is not None:
                continue  # broken mapping or not operating at E: excluded from current
            scope_kind = cast("_Scope", subject_kind)
            jsonld_dishes = _jsonld_dishes(session, owned)
            repeated: frozenset[frozenset[str]] = frozenset()
            if rank is not None:
                dishes = _family_dishes(session, owned)
                repeated = frozenset(dish for dish, amounts in dishes if (dish, amounts) in prior)
                family_dishes.update(dishes)
            for page in owned.values():
                if page.operation == "withdrawal":
                    continue
                graph = _graph(session, page.id)
                hidden = jsonld_dishes if page.source_kind == "llm" else frozenset()
                for price in session.scalars(
                    select(PriceObservation).where(PriceObservation.page_id == page.id)
                ):
                    node_kind, node_id = _price_target_column(price)
                    node = graph.nodes.get((node_kind, node_id))
                    if node is None or node.effect == "suppress":
                        continue
                    if hidden and _dish(graph, node) in hidden:
                        continue  # the subject's jsonld head prices this dish
                    if repeated and _dish(graph, node) in repeated:
                        continue  # an earlier own-site page prices it at the same amounts
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
        prior.update(family_dishes)
    requests.sort(key=_sort_key)
    return requests
