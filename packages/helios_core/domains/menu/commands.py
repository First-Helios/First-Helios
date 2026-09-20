"""Complete immutable writes and exact replay. The caller owns the transaction.

Input Bronze and resolution decisions must already be committed. Submit a
complete aggregate; no draft/patch API or implicit lifecycle intent is offered.
SQLSTATE 40001/40P01 requires rollback and retry of the WHOLE transaction.
"""

from __future__ import annotations

from dataclasses import asdict, fields
from typing import TYPE_CHECKING, Any, cast

from sqlalchemy import select, text

from packages.helios_core.domains.menu.contracts import (
    ApplicabilityInput,
    ItemInput,
    MemberIdentity,
    MenuAggregate,
    MenuConflictError,
    ModifierInput,
    NodeKind,
    PageInput,
    PersistedMenu,
    PriceInput,
    SectionInput,
    Target,
    VariantInput,
)
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
from packages.helios_core.identity.contracts import ResolvedScopeRequest, require_resolved_scopes
from packages.helios_core.provenance.contracts import (
    evidence_supports_version,
    get_evidence,
    get_record_version,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

_PARTS = (
    ("applicability", "applicability", MenuApplicability, ApplicabilityInput),
    ("sections", "section", MenuSection, SectionInput),
    ("items", "item", MenuItem, ItemInput),
    ("variants", "variant", MenuVariant, VariantInput),
    ("modifiers", "modifier", MenuModifier, ModifierInput),
    ("prices", "price", PriceObservation, PriceInput),
)


def _canonical(session: Session, aggregate: MenuAggregate) -> dict[str, Any]:
    value = asdict(aggregate)
    value["page"]["source_record_version_id"] = get_record_version(
        session, aggregate.page.source_record_version_id
    ).canonical_key
    for part, rows in value.items():
        members = [rows] if part == "page" else rows
        for row in members:
            if any(
                not evidence_supports_version(session, eid, aggregate.page.source_record_version_id)
                for eid in row["evidence_ids"]
            ):
                raise MenuConflictError("replay support must belong to its exact version/capture")
            row["evidence_ids"] = tuple(
                sorted({get_evidence(session, eid).canonical_key for eid in row["evidence_ids"]})
            )
            if row.get("dietary_tags") is not None:
                row["dietary_tags"] = tuple(sorted(row["dietary_tags"]))
        if part != "page":
            value[part] = sorted(members, key=lambda row: repr(sorted(row.items())))
    return value


def read_aggregate(session: Session, page_id: int) -> tuple[MenuAggregate, PersistedMenu]:
    """Inspect stored claims; transaction-visible lookup, never a commit certificate."""
    page = session.get(MenuPage, page_id)
    if page is None:
        raise ValueError(f"unknown Menu page {page_id}")
    links = list(session.scalars(select(EvidenceLink).where(EvidenceLink.page_id == page_id)))

    def evidence(kind: str, row_id: int) -> tuple[int, ...]:
        return tuple(
            sorted(
                link.evidence_id
                for link in links
                if (link.page_target if kind == "page" else getattr(link, f"{kind}_id") == row_id)
            )
        )

    page_fields: dict[str, Any] = {
        f.name: evidence("page", page_id) if f.name == "evidence_ids" else getattr(page, f.name)
        for f in fields(PageInput)
    }
    page_input = PageInput(**page_fields)
    loaded: dict[str, list[Any]] = {
        kind: list(session.scalars(select(model).where(model.page_id == page_id)))
        for _, kind, model, _ in _PARTS
    }
    keys: dict[str, dict[int, str]] = {
        kind: {
            row.id: getattr(row, "observation_key" if kind == "price" else f"{kind}_key")
            for row in rows
        }
        for kind, rows in loaded.items()
    }
    identities: list[MemberIdentity] = []
    values: dict[str, Any] = {"page": page_input}
    for part, kind, model, dto in _PARTS:
        inputs = []
        for row in loaded[kind]:
            data: dict[str, Any] = {}
            for field in fields(dto):
                name = field.name
                if name == "evidence_ids":
                    data[name] = evidence(kind, row.id)
                elif name == "target":
                    target_kind = next(
                        k
                        for k in ("section", "item", "variant", "modifier")
                        if getattr(row, f"{k}_id") is not None
                    )
                    target_id = getattr(row, f"{target_kind}_id")
                    item_key = None
                    if target_kind == "variant":
                        variant = next(v for v in loaded["variant"] if v.id == target_id)
                        item_key = keys["item"][variant.item_id]
                    data[name] = Target(
                        kind=cast("NodeKind", target_kind),
                        key=keys[target_kind][target_id],
                        item_key=item_key,
                    )
                elif name.endswith("_key") and not hasattr(row, name):
                    target_kind = name.removesuffix("_key").removeprefix("parent_")
                    row_id = getattr(row, name.removesuffix("_key") + "_id")
                    data[name] = None if row_id is None else keys[target_kind][row_id]
                else:
                    value = getattr(row, name)
                    data[name] = (
                        tuple(value) if name == "dietary_tags" and value is not None else value
                    )
            inputs.append(dto(**data))
            key = (
                (keys["item"][row.item_id], row.variant_key)
                if kind == "variant"
                else (keys[kind][row.id],)
            )
            identities.append(MemberIdentity(model.__tablename__, key, row.id))
        values[part] = tuple(inputs)
    identities.extend(MemberIdentity("evidence_link", (str(link.id),), link.id) for link in links)
    return MenuAggregate(**values), PersistedMenu(
        page_id, tuple(sorted(identities, key=lambda x: (x.table, x.key))), False
    )


def _replay(session: Session, aggregate: MenuAggregate, record_id: int) -> PersistedMenu | None:
    p = aggregate.page
    version_key = get_record_version(session, p.source_record_version_id).canonical_key
    candidates = session.scalars(
        select(MenuPage).where(
            MenuPage.source_record_id == record_id,
            MenuPage.root_key == p.root_key,
            MenuPage.source_kind == p.source_kind,
            (MenuPage.stream_revision == p.stream_revision)
            | (MenuPage.interpretation_revision == p.interpretation_revision),
        )
    )
    pages = [
        page
        for page in candidates
        if page.stream_revision == p.stream_revision
        or get_record_version(session, page.source_record_version_id).canonical_key == version_key
    ]
    if not pages:
        return None
    if len(pages) != 1:
        raise MenuConflictError("stream and version revision keys refer to different aggregates")
    stored, result = read_aggregate(session, pages[0].id)
    if _canonical(session, stored) != _canonical(session, aggregate):
        raise MenuConflictError(
            "existing Menu revision has different payload, membership, or support"
        )
    session.execute(text("SELECT menu.check_aggregate(:id)"), {"id": result.page_id})
    return PersistedMenu(result.page_id, result.members, True)


def persist_menu(session: Session, aggregate: MenuAggregate) -> PersistedMenu:
    """Flush a whole initial/observation/correction/withdrawal/restoration aggregate.

    Exact replay returns original IDs without admission or new writes, even
    after remap/retirement. All other writes receive the full provider batch
    before Menu locks. Integrity exceptions require caller rollback.
    """
    session.flush()
    # A caller may catch a shape/reference error. Never leave a supported prefix
    # of the requested aggregate available for accidental outer commit.
    with session.begin_nested():
        return _persist_menu(session, aggregate)


def _persist_menu(session: Session, aggregate: MenuAggregate) -> PersistedMenu:
    p = aggregate.page
    version = get_record_version(session, p.source_record_version_id)
    replay = _replay(session, aggregate, version.source_record_id)
    if replay is not None:
        return replay
    requests = [ResolvedScopeRequest(p.subject_id, version.source_record_id, p.resolution_event_id)]
    if p.base_organization_page_id is not None:
        base = session.get(MenuPage, p.base_organization_page_id)
        if base is None:
            raise ValueError("unknown base Menu page")
        requests.append(
            ResolvedScopeRequest(base.subject_id, base.source_record_id, base.resolution_event_id)
        )
    require_resolved_scopes(session, requests)
    session.execute(text("SELECT menu.lock_admission()"))
    # A competing identical writer can have committed while the batch waited.
    replay = _replay(session, aggregate, version.source_record_id)
    if replay is not None:
        return replay
    page_values = asdict(p)
    page_values.pop("evidence_ids")
    page = MenuPage(
        **page_values,
        source_record_id=version.source_record_id,
        observed_at=version.observed_at,
        state="withdrawn" if p.operation == "withdrawal" else "published",
    )
    session.add(page)
    session.flush()
    ids: dict[str, dict[tuple[str, ...], int]] = {kind: {} for _, kind, _, _ in _PARTS}

    def resolve(kind: str, key: str | None, item_key: str | None = None) -> int | None:
        if key is None:
            return None
        lookup = (item_key, key) if kind == "variant" else (key,)
        if lookup not in ids[kind]:
            raise ValueError(f"unknown {kind} reference {lookup!r}")
        return ids[kind][lookup]  # type: ignore[index]

    def link(kind: str, row_id: int, evidence_ids: tuple[int, ...]) -> None:
        for evidence_id in sorted(set(evidence_ids)):
            values = {} if kind == "page" else {f"{kind}_id": row_id}
            session.add(
                EvidenceLink(
                    page_id=page.id, evidence_id=evidence_id, page_target=kind == "page", **values
                )
            )
        session.flush()

    link("page", page.id, p.evidence_ids)
    for part, kind, model, _ in _PARTS:
        pending = list(getattr(aggregate, part))
        while pending:
            progress = False
            for row in list(pending):
                if (
                    kind == "section"
                    and row.parent_section_key is not None
                    and (row.parent_section_key,) not in ids[kind]
                ):
                    continue
                data = asdict(row)
                evidence_ids = data.pop("evidence_ids")
                key = (
                    (row.item_key, row.variant_key)
                    if kind == "variant"
                    else (data["observation_key" if kind == "price" else f"{kind}_key"],)
                )
                if key in ids[kind]:
                    raise ValueError(f"duplicate {kind} key {key!r}")
                if kind == "price":
                    data.pop("target")
                    target = row.target
                    if (target.kind == "variant") != (target.item_key is not None):
                        raise ValueError("only variant targets require an item key")
                    data[f"{target.kind}_id"] = resolve(target.kind, target.key, target.item_key)
                for name in list(data):
                    if name.endswith("_key") and not hasattr(model, name):
                        target_kind = name.removesuffix("_key").removeprefix("parent_")
                        data[name.removesuffix("_key") + "_id"] = resolve(
                            target_kind, data.pop(name)
                        )
                instance = model(page_id=page.id, **data)
                session.add(instance)
                session.flush()
                ids[kind][key] = instance.id
                link(kind, instance.id, evidence_ids)
                pending.remove(row)
                progress = True
            if not progress:
                raise ValueError("section parent path is missing or cyclic")
    session.flush()
    session.execute(text("SELECT menu.check_aggregate(:id)"), {"id": page.id})
    return read_aggregate(session, page.id)[1]
