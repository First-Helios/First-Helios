"""Menu writes for extracted ``menu-page`` Versions (ADR-0013 §5, §6; slice 5).

Which pages are due (session P5-4, X3): the latest Version of every resolved
``menu-page`` record whose ``llm`` stream has no page for that Version at the
current pipeline version. Never-extracted records come first, then records
with a new Version, then restorations, then re-interpretations (a
pipeline-version bump), ties by record key (§5's queue order).

R4 (Amendment 24 item 5, Amendment 27) takes a record out of the queue when:

- ``menu_url_withdrawn``: its menu URL was withdrawn, i.e. the menu-URL record
  with the same key is in ``needs_review`` (ADR-0015);
- ``fetch_rejected``: the latest fetch of its page that read the page is a
  classifier rejection, a skipped ``not_menu`` / ``js_only`` Capture. A §4
  render is a later Capture than the static fetch it follows, so its verdict
  is the one read. Failed fetches and other skips say nothing about the page
  and are passed over (as ADR-0015 keeps a URL on them);
- ``withdrawn``: its ``llm`` head is a ``withdrawal`` on its latest Version and
  no fetch has accepted the page since. A new Version, or an accepted fetch
  after the withdrawal, makes it due again, and its pages are then written as
  a ``restoration``.

:func:`withdraw_streams` writes the withdrawals (:mod:`.retraction`).

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
  version bump) is a ``correction``; a page after a ``withdrawal`` is a
  ``restoration``.
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
  a price [5b] price resolution accepted (Amendment 19) takes
  :data:`RESOLVED_PRICE_CONFIDENCE`, or the flagged one when that is lower, so
  downstream can rank or filter it apart from the validator's accepts;
  page confidence is the page classifier's probability.
"""

from __future__ import annotations

import hashlib
from collections import Counter
from dataclasses import dataclass, field
from decimal import Decimal
from typing import TYPE_CHECKING, Literal

from sqlalchemy import func, select

from apps.discovery.url_pipeline import MENU_URL_NAMESPACE
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
from packages.helios_core.identity.contracts import SubjectNotEligibleError
from packages.helios_core.identity.models import CurrentResolution, Subject
from packages.helios_core.provenance.contracts import (
    canonicalize_http_url,
    record_capture_evidence,
)
from packages.helios_core.provenance.models import (
    Capture,
    Evidence,
    Source,
    SourceEndpoint,
    SourceRecord,
    SourceRecordVersion,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator, Mapping, Sequence
    from datetime import datetime

    from sqlalchemy.orm import Session

    from packages.helios_parsing.menu_shape import ShapedPrice, ShapedSection
    from packages.helios_parsing.segment import Block
    from packages.helios_parsing.validator import Evidence as SpanEvidence

ROOT_KEY = "page"  # one menu per menu-page record
METHOD = "menu-pipeline"
PRICE_CONFIDENCE = Decimal("0.9800")  # measured exact-price accuracy on accepted rows (§8)
FLAGGED_PRICE_CONFIDENCE = Decimal("0.9000")  # pages printing unlabeled size-price runs
# (Amendment 21) [5b] accepts: the 95 % Wilson lower bound of their measured exact-price
# accuracy on the tuning sets, rounded down (resolve-v2: 26 of 26 exact, 0.871)
RESOLVED_PRICE_CONFIDENCE = Decimal("0.8700")
# (R4) a withdrawal is a rule's outcome, not a menu probability: full confidence
WITHDRAWAL_CONFIDENCE = Decimal("1.0000")
APPLICABILITY_KEY = "unspecified"
UNSECTIONED = "Unsectioned"
_MAX_KEY = 512
# (R4) the skipped menu-page Captures that are the page classifier's verdict
REJECTED_FETCH = frozenset({"not_menu", "js_only"})
STREAMS: tuple[SourceKind, ...] = ("llm", "jsonld")

DueReason = Literal["new", "changed", "restore", "reinterpret"]
_ORDER: dict[DueReason, int] = {"new": 0, "changed": 1, "restore": 2, "reinterpret": 3}
Rejection = Literal["menu_url_withdrawn", "fetch_rejected"]


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
class PageState:
    """A ``menu-page`` record's latest Version, its scope and its R4 standing."""

    key: str
    source_record_id: int
    version_id: int
    observed_at: datetime
    text_hash: str
    evidence_id: int  # the Version's own Evidence ($.text_hash)
    capture_id: int  # the Capture whose bundle holds the Version's blocks
    bundle_path: str | None
    resolution: str | None  # the record's CurrentResolution state
    subject_id: int | None
    subject_kind: str | None
    resolution_event_id: int | None
    rejection: Rejection | None
    accepted_at: datetime | None  # when the latest fetch that accepted the page was stored

    @property
    def resolved(self) -> bool:
        return (
            self.resolution == "resolved"
            and self.subject_id is not None
            and self.resolution_event_id is not None
        )


@dataclass(frozen=True, slots=True)
class _Head:
    page_id: int
    stream_revision: int
    version_id: int
    method_version: str
    state: str
    accepted_at: datetime


def _head(session: Session, source_record_id: int, kind: SourceKind) -> _Head | None:
    row = session.execute(
        select(
            MenuPage.id,
            MenuPage.stream_revision,
            MenuPage.source_record_version_id,
            MenuPage.method_version,
            MenuPage.state,
            MenuPage.accepted_at,
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


@dataclass(frozen=True, slots=True)
class _Verdicts:
    """One endpoint's fetches that read the page: whether the latest rejected it, and
    when the latest accepting one was stored (the database clock, as a Menu page's
    ``accepted_at``)."""

    latest_at: datetime
    rejected: bool
    accepted_at: datetime | None


def _verdicts(session: Session) -> dict[str, _Verdicts]:
    """Per ``menu-page`` endpoint, its Captures that read the page (R4)."""
    rows = session.execute(
        select(
            SourceEndpoint.canonical_uri, Capture.fetched_at, Capture.ingested_at, Capture.outcome
        )
        .join(Source, Source.id == Capture.source_id)
        .join(SourceEndpoint, SourceEndpoint.id == Capture.source_endpoint_id)
        .where(
            Source.namespace == MENU_PAGE_NAMESPACE,
            (Capture.outcome == "succeeded")
            | ((Capture.outcome == "skipped") & Capture.reason_code.in_(sorted(REJECTED_FETCH))),
        )
        .order_by(Capture.fetched_at, Capture.id)
    ).all()
    out: dict[str, _Verdicts] = {}
    for uri, fetched_at, ingested_at, outcome in rows:
        prior = out.get(uri)
        accepted = prior.accepted_at if prior else None
        if outcome == "succeeded":
            accepted = ingested_at if accepted is None else max(accepted, ingested_at)
        out[uri] = _Verdicts(
            latest_at=fetched_at, rejected=outcome != "succeeded", accepted_at=accepted
        )
    return out


def _menu_urls(session: Session) -> dict[str, tuple[str | None, object]]:
    """Menu-URL record key → its resolution state and latest saved menu URL."""
    rows = session.execute(
        select(
            SourceRecord.external_key, CurrentResolution.state, SourceRecordVersion.source_payload
        )
        .join(Source, Source.id == SourceRecord.source_id)
        .join(SourceRecordVersion, SourceRecordVersion.source_record_id == SourceRecord.id)
        .outerjoin(CurrentResolution, CurrentResolution.source_record_id == SourceRecord.id)
        .where(Source.namespace == MENU_URL_NAMESPACE)
        .distinct(SourceRecord.id)
        .order_by(
            SourceRecord.id, SourceRecordVersion.observed_at.desc(), SourceRecordVersion.id.desc()
        )
    ).all()
    return {
        str(key): (state, payload.get("menu_url") if isinstance(payload, dict) else None)
        for key, state, payload in rows
    }


def _canonical(url: object) -> str | None:
    if not isinstance(url, str):
        return None
    try:
        return canonicalize_http_url(url)
    except ValueError:
        return None


def page_states(session: Session) -> list[PageState]:
    """Every ``menu-page`` record's latest Version, scope and R4 standing."""
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
            SourceEndpoint.canonical_uri,
            func.min(Evidence.id),
            CurrentResolution.state,
            CurrentResolution.subject_id,
            CurrentResolution.last_event_id,
            Subject.kind,
        )
        .join(Capture, Capture.id == latest.c.capture_id)
        .join(SourceEndpoint, SourceEndpoint.id == Capture.source_endpoint_id)
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
            SourceEndpoint.canonical_uri,
            CurrentResolution.state,
            CurrentResolution.subject_id,
            CurrentResolution.last_event_id,
            Subject.kind,
        )
    ).all()
    menu_urls = _menu_urls(session)
    verdicts = _verdicts(session)
    states: list[PageState] = []
    for (
        record_id,
        key,
        version_id,
        observed_at,
        payload,
        capture_id,
        bundle_path,
        endpoint,
        evidence_id,
        state,
        subject_id,
        event_id,
        subject_kind,
    ) in rows:
        menu_url_state, saved_url = menu_urls.get(key, (None, None))
        # the page's fetches: its Version's endpoint, its URL, and the URL saved now
        endpoints = {endpoint, _canonical(payload.get("menu_url")), _canonical(saved_url)}
        seen = [verdicts[uri] for uri in endpoints if uri is not None and uri in verdicts]
        last = max(seen, key=lambda v: v.latest_at, default=None)
        rejection: Rejection | None = None
        if menu_url_state == "needs_review":
            rejection = "menu_url_withdrawn"
        elif last is not None and last.rejected:
            rejection = "fetch_rejected"
        states.append(
            PageState(
                key=key,
                source_record_id=record_id,
                version_id=version_id,
                observed_at=observed_at,
                text_hash=str(payload.get("text_hash")),
                evidence_id=evidence_id,
                capture_id=capture_id,
                bundle_path=bundle_path,
                resolution=state,
                subject_id=subject_id,
                subject_kind=subject_kind,
                resolution_event_id=event_id,
                rejection=rejection,
                accepted_at=max(
                    (v.accepted_at for v in seen if v.accepted_at is not None), default=None
                ),
            )
        )
    return states


def due_pages(session: Session, method_version: str) -> tuple[list[DuePage], dict[str, int]]:
    """The due pages in queue order, and counts of the records that are not due."""
    skipped = {
        "up_to_date": 0,
        "needs_review": 0,
        "no_bundle": 0,
        "menu_url_withdrawn": 0,
        "fetch_rejected": 0,
        "withdrawn": 0,
    }
    due: list[DuePage] = []
    for page in page_states(session):
        if not page.resolved:
            skipped["needs_review"] += 1
            continue
        if page.rejection is not None:
            skipped[page.rejection] += 1
            continue
        if page.bundle_path is None:
            skipped["no_bundle"] += 1
            continue
        head = _head(session, page.source_record_id, "llm")
        reason: DueReason
        if head is None:
            reason = "new"
        elif head.version_id != page.version_id:
            reason = "changed"
        elif head.state == "withdrawn":
            if page.accepted_at is None or page.accepted_at <= head.accepted_at:
                skipped["withdrawn"] += 1
                continue
            reason = "restore"
        elif head.method_version != method_version:
            reason = "reinterpret"
        else:
            skipped["up_to_date"] += 1
            continue
        due.append(_due(page, reason))
    due.sort(key=lambda page: (_ORDER[page.reason], page.key))
    return due, skipped


def _due(page: PageState, reason: DueReason) -> DuePage:
    if page.subject_id is None or page.resolution_event_id is None or page.bundle_path is None:
        raise ValueError(f"{page.key} has no scope or bundle")
    return DuePage(
        key=page.key,
        reason=reason,
        source_record_id=page.source_record_id,
        version_id=page.version_id,
        observed_at=page.observed_at,
        text_hash=page.text_hash,
        evidence_id=page.evidence_id,
        capture_id=page.capture_id,
        bundle_path=page.bundle_path,
        subject_id=page.subject_id,
        subject_kind=str(page.subject_kind),
        resolution_event_id=page.resolution_event_id,
    )


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


def _next_interpretation(session: Session, version_id: int, kind: SourceKind) -> int:
    return 1 + (
        session.scalar(
            select(func.coalesce(func.max(MenuPage.interpretation_revision), 0)).where(
                MenuPage.source_record_version_id == version_id,
                MenuPage.root_key == ROOT_KEY,
                MenuPage.source_kind == kind,
            )
        )
        or 0
    )


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
    resolved_confidence = min(price_confidence, RESOLVED_PRICE_CONFIDENCE)
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
                    confidence=resolved_confidence if price.resolved else price_confidence,
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
        if head.state == "withdrawn":
            operation = "restoration"
        else:
            same_version = head.version_id == page.version_id
            operation = "correction" if same_version else "observation"
        stream_revision, supersedes = head.stream_revision + 1, head.page_id
    interpretation_revision = _next_interpretation(session, page.version_id, kind)
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


def withdraw_streams(
    session: Session, page: DuePage | PageState, *, method_versions: Mapping[SourceKind, str]
) -> list[SourceKind]:
    """Append a ``withdrawal`` to each of the record's published streams (R4); flushes.

    The tombstone is the Menu domain's own (ADR-0005 §6): no graph, the record's
    latest Version and its Evidence, the record's current scope. Nothing is
    deleted, and a stream already withdrawn is left as it is. Returns the
    streams withdrawn; the caller commits.
    """
    if page.subject_id is None or page.resolution_event_id is None:
        raise ValueError(f"{page.key} has no resolved scope to withdraw under")
    withdrawn: list[SourceKind] = []
    for kind in STREAMS:
        head = _head(session, page.source_record_id, kind)
        if head is None or head.state == "withdrawn":
            continue
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
                    method_version=method_versions[kind],
                    stream_revision=head.stream_revision + 1,
                    interpretation_revision=_next_interpretation(session, page.version_id, kind),
                    confidence=WITHDRAWAL_CONFIDENCE,
                    operation="withdrawal",
                    evidence_ids=(page.evidence_id,),
                    supersedes_page_id=head.page_id,
                )
            ),
        )
        withdrawn.append(kind)
    return withdrawn


@dataclass(slots=True)
class Withdrawals:
    """What R4 withdrew: records by reason, withdrawal pages by stream."""

    records: Counter[str] = field(default_factory=Counter)  # a Rejection, or "rescored"
    pages: Counter[str] = field(default_factory=Counter)  # llm / jsonld
    not_eligible: int = 0  # records whose scope can't take a Menu write now

    def summary(self) -> dict[str, object]:
        return {
            "records": dict(sorted(self.records.items())),
            "pages": dict(sorted(self.pages.items())),
            "not_eligible": self.not_eligible,
        }


def withdraw(  # noqa: PLR0913 - one record's withdrawal and its bookkeeping
    session: Session,
    page: DuePage | PageState,
    reason: str,
    *,
    method_versions: Mapping[SourceKind, str],
    withdrawals: Withdrawals,
    commit: Callable[[], None] | None,
) -> bool:
    """Withdraw one record's published streams, then commit; False when nothing was written."""
    try:
        with session.begin_nested():
            kinds = withdraw_streams(session, page, method_versions=method_versions)
    except SubjectNotEligibleError:
        withdrawals.not_eligible += 1
        return False
    if not kinds:
        return False
    withdrawals.records[reason] += 1
    withdrawals.pages.update(kinds)
    if commit is not None:
        commit()
    return True


def retract_rejected(
    session: Session,
    *,
    method_versions: Mapping[SourceKind, str],
    withdrawals: Withdrawals,
    commit: Callable[[], None] | None,
) -> None:
    """Withdraw every resolved record whose menu URL was withdrawn or whose latest fetch
    was a classifier rejection (R4; reads no bundle)."""
    for page in page_states(session):
        if page.rejection is not None and page.resolved:
            withdraw(
                session,
                page,
                page.rejection,
                method_versions=method_versions,
                withdrawals=withdrawals,
                commit=commit,
            )
