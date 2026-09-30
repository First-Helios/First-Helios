"""Menu writes for extracted ``menu-page`` Versions (ADR-0013 §5, §6; slice 5).

Which pages are due (session P5-4, X3): the latest Version of every resolved
``menu-page`` record whose ``llm`` stream has no page for that Version at the
current pipeline version. Never-extracted records come first, then records
with a new Version, then re-interpretations (a pipeline-version bump), ties by
record key (§5's queue order).

What one page writes (X4, N1, N2), through :func:`persist_menu`:

- An ``llm`` page aggregate on every extracted Version, empty when nothing was
  kept, so the Version is done at this pipeline version and an older head's
  prices stop being current. A ``jsonld`` page beside it when the page's
  schema.org JSON-LD has items, or when the ``jsonld`` stream's head still has
  items (an empty successor, so JSON-LD that disappeared stops outranking the
  LLM). The two are separate streams of one record (ADR-0005 §5); selection
  ranks ``jsonld`` above ``llm`` per target.
- Lifecycle: the first page of a stream is ``initial``; a page on a newer Version
  is an ``observation``; a new interpretation of the same Version (a pipeline
  version bump) is a ``correction``.
- Nodes carry version-local native keys ``v<version id>:<block>:<normalized
  text>`` (N1): Gold projects them, and nothing claims a dish is the same one
  across Versions or across the two streams by its name (the Menu proposal's
  key rules). The structural ``Unsectioned`` grouping has no native key, and
  a native key needs a stable ancestor path, so its items and variants carry
  none: they are stored but not projected to Gold.
- Evidence: the page and its one applicability (channel ``unspecified``) cite
  the Version's own Evidence (``$.text_hash``); sections, items, variants and
  prices cite Capture-targeted ``blocks:`` spans in the Version's bundle.
- Trust (§6, Q6): price confidence is :data:`PRICE_CONFIDENCE`, or
  :data:`FLAGGED_PRICE_CONFIDENCE` on a page flagged ``unlabeled_price_runs``;
  page confidence is the page classifier's probability.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING, Literal

from sqlalchemy import func, select

from apps.menu_pipeline.page_bronze import MENU_PAGE_NAMESPACE
from packages.helios_core.domains.menu.commands import persist_menu
from packages.helios_core.domains.menu.contracts import (
    ApplicabilityInput,
    ItemInput,
    MenuAggregate,
    Operation,
    PageInput,
    PriceInput,
    SectionInput,
    SourceKind,
    Target,
    VariantInput,
)
from packages.helios_core.domains.menu.models import MenuItem, MenuPage
from packages.helios_core.identity.models import CurrentResolution, Subject
from packages.helios_core.provenance.contracts import record_capture_evidence
from packages.helios_core.provenance.models import (
    Capture,
    Evidence,
    Source,
    SourceRecord,
    SourceRecordVersion,
)

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping, Sequence
    from datetime import datetime

    from sqlalchemy.orm import Session

    from packages.helios_parsing.menu_shape import ShapedPrice, ShapedSection
    from packages.helios_parsing.segment import Block
    from packages.helios_parsing.validator import Evidence as SpanEvidence

ROOT_KEY = "page"  # one menu per menu-page record
METHOD = "menu-pipeline"
PRICE_CONFIDENCE = Decimal("0.9800")  # measured exact-price accuracy on accepted rows (§8)
FLAGGED_PRICE_CONFIDENCE = Decimal("0.9000")  # pages printing unlabeled size-price runs
APPLICABILITY_KEY = "unspecified"
UNSECTIONED = "Unsectioned"
_MAX_KEY = 512

DueReason = Literal["new", "changed", "reinterpret"]
_ORDER: dict[DueReason, int] = {"new": 0, "changed": 1, "reinterpret": 2}


@dataclass(frozen=True, slots=True)
class DuePage:
    """One ``menu-page`` Version to extract, with its scope and evidence handles."""

    key: str
    reason: DueReason
    source_record_id: int
    version_id: int
    observed_at: datetime
    text_hash: str
    evidence_id: int  # the Version's own Evidence ($.text_hash)
    capture_id: int  # the Capture whose bundle holds the Version's blocks
    bundle_path: str
    subject_id: int
    subject_kind: str
    resolution_event_id: int


@dataclass(frozen=True, slots=True)
class _Head:
    page_id: int
    stream_revision: int
    version_id: int
    method_version: str


def _head(session: Session, source_record_id: int, kind: SourceKind) -> _Head | None:
    row = session.execute(
        select(
            MenuPage.id,
            MenuPage.stream_revision,
            MenuPage.source_record_version_id,
            MenuPage.method_version,
        )
        .where(
            MenuPage.source_record_id == source_record_id,
            MenuPage.root_key == ROOT_KEY,
            MenuPage.source_kind == kind,
        )
        .order_by(MenuPage.stream_revision.desc())
        .limit(1)
    ).one_or_none()
    return None if row is None else _Head(*row)


def due_pages(session: Session, method_version: str) -> tuple[list[DuePage], dict[str, int]]:
    """The due pages in queue order, and counts of the records that are not due."""
    latest = (
        select(
            SourceRecord.id.label("record_id"),
            SourceRecord.external_key.label("key"),
            SourceRecordVersion.id.label("version_id"),
            SourceRecordVersion.observed_at.label("observed_at"),
            SourceRecordVersion.source_payload.label("payload"),
            SourceRecordVersion.capture_id.label("capture_id"),
        )
        .join(Source, Source.id == SourceRecord.source_id)
        .join(SourceRecordVersion, SourceRecordVersion.source_record_id == SourceRecord.id)
        .where(Source.namespace == MENU_PAGE_NAMESPACE)
        .distinct(SourceRecord.id)
        .order_by(
            SourceRecord.id, SourceRecordVersion.observed_at.desc(), SourceRecordVersion.id.desc()
        )
        .subquery()
    )
    rows = session.execute(
        select(
            latest.c.record_id,
            latest.c.key,
            latest.c.version_id,
            latest.c.observed_at,
            latest.c.payload,
            latest.c.capture_id,
            Capture.bundle_path,
            func.min(Evidence.id),
            CurrentResolution.state,
            CurrentResolution.subject_id,
            CurrentResolution.last_event_id,
            Subject.kind,
        )
        .join(Capture, Capture.id == latest.c.capture_id)
        .join(Evidence, Evidence.source_record_version_id == latest.c.version_id)
        .outerjoin(CurrentResolution, CurrentResolution.source_record_id == latest.c.record_id)
        .outerjoin(Subject, Subject.id == CurrentResolution.subject_id)
        .group_by(
            latest.c.record_id,
            latest.c.key,
            latest.c.version_id,
            latest.c.observed_at,
            latest.c.payload,
            latest.c.capture_id,
            Capture.bundle_path,
            CurrentResolution.state,
            CurrentResolution.subject_id,
            CurrentResolution.last_event_id,
            Subject.kind,
        )
    ).all()
    skipped = {"up_to_date": 0, "needs_review": 0, "no_bundle": 0}
    due: list[DuePage] = []
    for (
        record_id,
        key,
        version_id,
        observed_at,
        payload,
        capture_id,
        bundle_path,
        evidence_id,
        state,
        subject_id,
        event_id,
        subject_kind,
    ) in rows:
        if state != "resolved" or subject_id is None or event_id is None:
            skipped["needs_review"] += 1
            continue
        if bundle_path is None:
            skipped["no_bundle"] += 1
            continue
        head = _head(session, record_id, "llm")
        reason: DueReason
        if head is None:
            reason = "new"
        elif head.version_id != version_id:
            reason = "changed"
        elif head.method_version != method_version:
            reason = "reinterpret"
        else:
            skipped["up_to_date"] += 1
            continue
        due.append(
            DuePage(
                key=key,
                reason=reason,
                source_record_id=record_id,
                version_id=version_id,
                observed_at=observed_at,
                text_hash=str(payload.get("text_hash")),
                evidence_id=evidence_id,
                capture_id=capture_id,
                bundle_path=bundle_path,
                subject_id=subject_id,
                subject_kind=subject_kind,
                resolution_event_id=event_id,
            )
        )
    due.sort(key=lambda page: (_ORDER[page.reason], page.key))
    return due, skipped


def _native(version_id: int, key: str) -> str:
    """A version-local native key (N1); hashed when a long name would pass the column."""
    native = f"v{version_id}:{key}"
    if len(native) <= _MAX_KEY:
        return native
    return f"v{version_id}:sha256:{hashlib.sha256(key.encode('utf-8')).hexdigest()}"


@dataclass(slots=True)
class PageWrite:
    """What one stream's page wrote (for the run report)."""

    items: int = 0
    prices: int = 0
    unsectioned_items: int = 0


def _spans(sections: Sequence[ShapedSection]) -> Iterator[SpanEvidence]:
    for section in sections:
        if section.evidence is not None:
            yield section.evidence
        for item in section.items:
            yield item.evidence
            for price in item.prices:
                yield from price.evidence
            for variant in item.variants:
                yield variant.evidence
                for price in variant.prices:
                    yield from price.evidence


def record_span_evidence(
    session: Session,
    page: DuePage,
    blocks: Sequence[Block],
    shapes: Sequence[Sequence[ShapedSection]],
) -> dict[str, int]:
    """Persist the Capture-targeted Evidence every shaped node cites; locator → Evidence id.

    Menu admission accepts only committed Evidence (ADR-0005 §7), so the caller
    commits these before :func:`write_page`. Evidence is immutable and reused
    per locator, so a page whose Menu write then fails leaves nothing to undo.
    """
    text = {block.id: block.text for block in blocks}
    ids: dict[str, int] = {}
    for sections in shapes:
        for span in _spans(sections):
            if span.locator not in ids:
                ids[span.locator] = record_capture_evidence(
                    session,
                    capture_id=page.capture_id,
                    locator=span.locator,
                    block_text=text[span.block_id],
                )
    return ids


def head_has_items(session: Session, source_record_id: int, kind: SourceKind) -> bool:
    head = _head(session, source_record_id, kind)
    if head is None:
        return False
    return (
        session.scalar(select(MenuItem.id).where(MenuItem.page_id == head.page_id).limit(1))
        is not None
    )


def write_page(  # noqa: PLR0913 - one page's inputs
    session: Session,
    page: DuePage,
    *,
    kind: SourceKind,
    sections: Sequence[ShapedSection],
    evidence_ids: Mapping[str, int],
    flagged: bool,
    page_confidence: Decimal,
    method_version: str,
) -> PageWrite:
    """Persist one stream's page aggregate for ``page`` (flushes; the caller commits).

    ``evidence_ids`` maps every locator the sections cite to its committed
    Evidence (:func:`record_span_evidence`).
    """

    def evidence(span: SpanEvidence) -> int:
        return evidence_ids[span.locator]

    price_confidence = FLAGGED_PRICE_CONFIDENCE if flagged else PRICE_CONFIDENCE
    vid = page.version_id
    written = PageWrite()
    section_inputs: list[SectionInput] = []
    item_inputs: list[ItemInput] = []
    variant_inputs: list[VariantInput] = []
    price_inputs: list[PriceInput] = []

    def prices_of(target: Target, target_key: str, prices: Sequence[ShapedPrice]) -> None:
        for price in prices:
            price_span = price.evidence[0]
            price_inputs.append(
                PriceInput(
                    observation_key=(f"{target_key}|{APPLICABILITY_KEY}|USD|{price_span.locator}"),
                    target=target,
                    applicability_key=APPLICABILITY_KEY,
                    price_kind="absolute",
                    price_state="priced",
                    amount_minor=price.amount_minor,
                    currency_code="USD",
                    confidence=price_confidence,
                    evidence_ids=tuple(sorted({evidence(e) for e in price.evidence})),
                )
            )

    for s_pos, section in enumerate(sections):
        if section.key is None:
            section_key = UNSECTIONED
            section_inputs.append(
                SectionInput(
                    section_key=UNSECTIONED,
                    name=UNSECTIONED,
                    position=0,
                    effect="replace",
                    support_kind="structural",
                )
            )
            written.unsectioned_items += len(section.items)
        else:
            assert section.evidence is not None and section.name  # noqa: S101 - shaped so
            section_key = f"s{s_pos}"
            section_inputs.append(
                SectionInput(
                    section_key=section_key,
                    source_native_key=_native(vid, section.key),
                    name=section.name,
                    position=s_pos,
                    effect="replace",
                    support_kind="direct",
                    evidence_ids=(evidence(section.evidence),),
                )
            )
        # a native key needs a stable ancestor path; Unsectioned has none (not in Gold)
        native = section.key is not None
        for i_pos, item in enumerate(section.items):
            item_key = f"{section_key}.i{i_pos}"
            item_inputs.append(
                ItemInput(
                    item_key=item_key,
                    section_key=section_key,
                    source_native_key=_native(vid, item.key) if native else None,
                    name=item.name,
                    dietary_tags=(),  # required on a replacement item; none are read (N2)
                    position=i_pos,
                    effect="replace",
                    support_kind="direct",
                    evidence_ids=(evidence(item.evidence),),
                )
            )
            written.items += 1
            prices_of(Target(kind="item", key=item_key), item_key, item.prices)
            for v_pos, variant in enumerate(item.variants):
                variant_key = f"v{v_pos}"
                variant_inputs.append(
                    VariantInput(
                        variant_key=variant_key,
                        item_key=item_key,
                        source_native_key=_native(vid, variant.key) if native else None,
                        label=variant.label,
                        position=v_pos,
                        effect="replace",
                        support_kind="direct",
                        evidence_ids=(evidence(variant.evidence),),
                    )
                )
                prices_of(
                    Target(kind="variant", key=variant_key, item_key=item_key),
                    f"{item_key}.{variant_key}",
                    variant.prices,
                )
    written.prices = len(price_inputs)

    head = _head(session, page.source_record_id, kind)
    operation: Operation
    if head is None:
        operation, stream_revision, supersedes = "initial", 1, None
    else:
        same_version = head.version_id == page.version_id
        operation = "correction" if same_version else "observation"
        stream_revision, supersedes = head.stream_revision + 1, head.page_id
    interpretation_revision = 1 + (
        session.scalar(
            select(func.coalesce(func.max(MenuPage.interpretation_revision), 0)).where(
                MenuPage.source_record_version_id == page.version_id,
                MenuPage.root_key == ROOT_KEY,
                MenuPage.source_kind == kind,
            )
        )
        or 0
    )
    page_evidence = (page.evidence_id,)
    persist_menu(
        session,
        MenuAggregate(
            page=PageInput(
                subject_id=page.subject_id,
                subject_kind=page.subject_kind,  # type: ignore[arg-type]
                source_record_version_id=page.version_id,
                resolution_event_id=page.resolution_event_id,
                root_key=ROOT_KEY,
                source_kind=kind,
                method=METHOD,
                method_version=method_version,
                stream_revision=stream_revision,
                interpretation_revision=interpretation_revision,
                confidence=page_confidence,
                operation=operation,
                evidence_ids=page_evidence,
                supersedes_page_id=supersedes,
            ),
            sections=tuple(section_inputs),
            items=tuple(item_inputs),
            variants=tuple(variant_inputs),
            applicability=(
                (
                    ApplicabilityInput(
                        applicability_key=APPLICABILITY_KEY,
                        channel="unspecified",
                        evidence_ids=page_evidence,
                    ),
                )
                if price_inputs
                else ()
            ),
            prices=tuple(price_inputs),
        ),
    )
    return written
