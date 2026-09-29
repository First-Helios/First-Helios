"""Reviewed Identity corrections: duplicate-venue merges and non-venue retirements.

``config/identity_corrections.yaml`` lists venue corrections a human reviewed
(the gate 1a location correction plan), keyed by Overture GERS id rather than
Subject id so the file survives a rebuild:

- a **merge** names a survivor record and the other records of the same outlet;
- a **retirement** names the record of something that is not a venue.

``python -m apps.discovery.corrections --actor <reviewer>`` applies the file
through the published Identity commands, with one Adjudication per entry that
changes anything plus the Evidence of the records' winning Overture Versions
(ADR-0004 §5-6):

- merge: an unresolved or ``needs_review`` record of the cluster is assigned to
  the survivor's Establishment; every record resolved to a merged-away
  Establishment is remapped to it, then the Establishments merge. A merged-away
  Organization or Place merges into the survivor's (its records, e.g. website
  and menu URLs, remapped first) when no current Establishment still uses it;
  otherwise it stays and is reported.
- retirement: the Establishment's records are unassigned to ``needs_review``,
  so discovery never re-mints them, and it retires. Its Place and Organization
  stay current: the address and the operator still exist.

Applying is state-based and idempotent: an entry already in effect writes
nothing and counts as ``satisfied``, so re-running after a rebuild (a fresh
discovery on a new database) re-applies exactly what is missing. It takes the
lifecycle lock, so it never interleaves with a discovery run. A merged venue
owns several Overture records, so the lifecycle leaves it alone (ADR-0012's
shared-source rule): a merged-away record's point never relocates the
survivor, and the venue closes only when every record is absent.

The file fails closed like the location overrides: a malformed entry raises
before anything is written, and CI validates the committed file.
"""

from __future__ import annotations

import argparse
import hashlib
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml
from sqlalchemy import select

from apps.discovery.lifecycle import (
    LifecycleReport,
    lock_lifecycle,
    refresh_readiness,
    winning_version,
)
from packages.helios_core.db.session import get_sessionmaker
from packages.helios_core.identity.commands import (
    DecisionMetadata,
    assign_source_record,
    create_adjudication,
    record_subject_change,
    remap_source_record,
    unassign_source_record,
)
from packages.helios_core.identity.models import (
    CurrentResolution,
    Establishment,
    Subject,
    SubjectCurrentness,
)
from packages.helios_core.provenance.contracts import canonicalize_http_url
from packages.helios_core.provenance.models import Evidence, Source, SourceRecord

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sqlalchemy.orm import Session

DEFAULT_PATH = Path(__file__).resolve().parents[2] / "config" / "identity_corrections.yaml"
METHOD_VERSION = "1"
_MERGE_KEYS = frozenset({"id", "survivor", "merge", "rationale", "evidence_url"})
_RETIRE_KEYS = frozenset({"id", "gers_id", "rationale", "evidence_url"})
# The Adjudication rationale (at most 4000) also carries the file provenance.
_MAX_RATIONALE = 2000


@dataclass(frozen=True, slots=True)
class Merge:
    """Records of one outlet: ``merged`` join the survivor's venue."""

    id: str
    survivor: str
    merged: tuple[str, ...]
    rationale: str
    evidence_url: str


@dataclass(frozen=True, slots=True)
class Retirement:
    """The record of something that is not a venue."""

    id: str
    gers_id: str
    rationale: str
    evidence_url: str


@dataclass(frozen=True, slots=True)
class CorrectionFile:
    """The validated file plus the provenance its Adjudications cite."""

    merges: tuple[Merge, ...] = ()
    retirements: tuple[Retirement, ...] = ()
    content_hash: str = ""
    source_url: str | None = "repo:config/identity_corrections.yaml"


@dataclass
class CorrectionReport:
    """What one application did; an entry is merged, retired, satisfied or skipped."""

    merged: int = 0
    retired: int = 0
    satisfied: int = 0
    assigned: int = 0
    remapped: int = 0
    unassigned: int = 0
    parents_merged: int = 0
    unmatched: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    parents_kept: list[str] = field(default_factory=list)


def _text(raw: dict[str, Any], key: str, label: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ValueError(f"correction {label}: {key!r} must be a nonblank trimmed string")
    return value


def _common(raw: Any, keys: frozenset[str], label: str) -> tuple[str, str, str]:  # noqa: ANN401 - raw YAML
    if not isinstance(raw, dict):
        raise ValueError(f"correction {label} must be a mapping")
    if unknown := set(raw) - keys:
        raise ValueError(f"correction {label}: unknown keys {sorted(unknown)}")
    if missing := keys - set(raw):
        raise ValueError(f"correction {label}: missing keys {sorted(missing)}")
    rationale = _text(raw, "rationale", label)
    if len(rationale) > _MAX_RATIONALE:
        raise ValueError(f"correction {label}: 'rationale' exceeds {_MAX_RATIONALE} characters")
    try:
        evidence_url = canonicalize_http_url(_text(raw, "evidence_url", label))
    except ValueError as exc:
        raise ValueError(f"correction {label}: 'evidence_url' is not HTTP(S)") from exc
    return _text(raw, "id", label), rationale, evidence_url


def _merge(raw: Any, index: int) -> Merge:  # noqa: ANN401 - raw YAML
    label = f"merge {index}"
    entry_id, rationale, evidence_url = _common(raw, _MERGE_KEYS, label)
    survivor = _text(raw, "survivor", label)
    merged = raw["merge"]
    if not isinstance(merged, list) or not merged:
        raise ValueError(f"correction {label}: 'merge' must be a nonempty list of GERS ids")
    for value in merged:
        if not isinstance(value, str) or not value.strip() or value != value.strip():
            raise ValueError(f"correction {label}: 'merge' ids must be nonblank trimmed strings")
    return Merge(entry_id, survivor, tuple(merged), rationale, evidence_url)


def _retirement(raw: Any, index: int) -> Retirement:  # noqa: ANN401 - raw YAML
    label = f"retirement {index}"
    entry_id, rationale, evidence_url = _common(raw, _RETIRE_KEYS, label)
    return Retirement(entry_id, _text(raw, "gers_id", label), rationale, evidence_url)


def _entries(document: dict[str, Any], key: str) -> list[Any]:
    value = document.get(key) or []
    if not isinstance(value, list):
        raise ValueError(f"'{key}' must be a list")
    return value


def parse_corrections(document: Any) -> tuple[tuple[Merge, ...], tuple[Retirement, ...]]:  # noqa: ANN401 - raw YAML
    """Validate a parsed YAML document. Each id and GERS id appears once in the file."""
    if document is None:
        return (), ()
    if not isinstance(document, dict) or set(document) - {"merges", "retirements"}:
        raise ValueError("correction file must be a mapping of 'merges' and 'retirements' lists")
    merges = tuple(_merge(raw, i) for i, raw in enumerate(_entries(document, "merges")))
    retirements = tuple(
        _retirement(raw, i) for i, raw in enumerate(_entries(document, "retirements"))
    )
    ids: set[str] = set()
    gers_ids: set[str] = set()
    entries: tuple[Merge | Retirement, ...] = (*merges, *retirements)
    for entry in entries:
        if entry.id in ids:
            raise ValueError(f"correction {entry.id!r}: duplicate id")
        ids.add(entry.id)
        keys = (entry.survivor, *entry.merged) if isinstance(entry, Merge) else (entry.gers_id,)
        for gers in keys:
            if gers in gers_ids:
                raise ValueError(f"correction {entry.id!r}: GERS id {gers!r} appears twice")
            gers_ids.add(gers)
    return merges, retirements


def load_corrections(path: Path = DEFAULT_PATH) -> CorrectionFile:
    """Read and validate the correction file. A missing file raises."""
    raw = path.read_bytes()
    merges, retirements = parse_corrections(yaml.safe_load(raw))
    try:
        relative = path.resolve().relative_to(DEFAULT_PATH.parents[1])
        source_url: str | None = f"repo:{relative.as_posix()}"
    except ValueError:
        source_url = None
    return CorrectionFile(
        merges=merges,
        retirements=retirements,
        content_hash="sha256:" + hashlib.sha256(raw).hexdigest(),
        source_url=source_url,
    )


# --- application ------------------------------------------------------------------


def _is_current(session: Session, subject_id: int) -> bool:
    return (
        session.scalar(
            select(SubjectCurrentness.is_current).where(SubjectCurrentness.subject_id == subject_id)
        )
        is True
    )


def _record(session: Session, gers_id: str) -> tuple[int, str | None, int | None] | None:
    """``(record id, resolution state, Subject id)`` of the Overture record, if any."""
    row = session.execute(
        select(SourceRecord.id, CurrentResolution.state, CurrentResolution.subject_id)
        .join(Source, Source.id == SourceRecord.source_id)
        .outerjoin(CurrentResolution, CurrentResolution.source_record_id == SourceRecord.id)
        .where(Source.namespace == "overture", SourceRecord.external_key == gers_id)
    ).one_or_none()
    return None if row is None else (row[0], row[1], row[2])


def _venue(session: Session, state: str | None, subject_id: int | None) -> Establishment | None:
    """The current Establishment a record resolves to, if any."""
    if state != "resolved" or subject_id is None or not _is_current(session, subject_id):
        return None
    return session.get(Establishment, subject_id, populate_existing=True)


def _resolved_records(session: Session, subject_id: int) -> list[int]:
    return list(
        session.scalars(
            select(CurrentResolution.source_record_id)
            .where(
                CurrentResolution.subject_id == subject_id,
                CurrentResolution.state == "resolved",
            )
            .order_by(CurrentResolution.source_record_id)
        )
    )


def _version_evidence(session: Session, record_ids: Sequence[int]) -> list[int]:
    evidence: list[int] = []
    for record_id in record_ids:
        version = winning_version(session, record_id)
        if version is not None:
            evidence.extend(
                session.scalars(
                    select(Evidence.id)
                    .where(Evidence.source_record_version_id == version.id)
                    .order_by(Evidence.id)
                )
            )
    return list(dict.fromkeys(evidence))


def _user(session: Session, column: Any, parent_id: int) -> int | None:  # noqa: ANN401 - ORM column
    """A current Establishment that still uses this Organization or Place."""
    return session.scalar(
        select(Establishment.subject_id)
        .join(SubjectCurrentness, SubjectCurrentness.subject_id == Establishment.subject_id)
        .where(SubjectCurrentness.is_current.is_(True), column == parent_id)
        .order_by(Establishment.subject_id)
        .limit(1)
    )


class _Applier:
    def __init__(
        self,
        session: Session,
        corrections: CorrectionFile,
        *,
        actor: str,
        decided_at: datetime,
    ) -> None:
        self.session = session
        self.corrections = corrections
        self.actor = actor
        self.decided_at = decided_at
        self.report = CorrectionReport()

    def _support(self, entry: Merge | Retirement) -> int:
        adjudication = create_adjudication(
            self.session,
            actor=self.actor,
            rationale=(
                f"{self.corrections.source_url} ({self.corrections.content_hash}) "
                f"entry {entry.id}: {entry.rationale} Evidence: {entry.evidence_url}"
            ),
            decided_at=self.decided_at,
        )
        return adjudication.id

    def _decision(self, operation: str) -> DecisionMetadata:
        return DecisionMetadata(
            confidence=Decimal("1"),
            method=f"identity-correction-{operation}",
            method_version=METHOD_VERSION,
            actor_class="human",
            decided_at=self.decided_at,
            effective_at=self.decided_at,
        )

    def merge(self, entry: Merge) -> None:
        session, report = self.session, self.report
        survivor_record = _record(session, entry.survivor)
        if survivor_record is None:
            report.unmatched.append(entry.survivor)
            report.skipped.append(f"{entry.id}: survivor {entry.survivor} has no Overture record")
            return
        survivor = _venue(session, *survivor_record[1:])
        if survivor is None:
            report.skipped.append(f"{entry.id}: survivor {entry.survivor} is on no current venue")
            return
        record_ids = [survivor_record[0]]
        to_assign: list[int] = []
        venues: dict[int, Establishment] = {}
        problems = False
        for gers in entry.merged:
            found = _record(session, gers)
            if found is None:
                report.unmatched.append(gers)
                continue
            record_id, state, subject_id = found
            record_ids.append(record_id)
            if state == "resolved" and subject_id == survivor.subject_id:
                continue
            if state in {"unresolved", "needs_review"}:
                to_assign.append(record_id)
                continue
            venue = _venue(session, state, subject_id)
            if venue is None:
                problems = True
                report.skipped.append(
                    f"{entry.id}: {gers} is {state or 'not in Identity'}"
                    + (f" on retired Subject {subject_id}" if state == "resolved" else "")
                )
                continue
            venues[venue.subject_id] = venue
        if not to_assign and not venues:
            report.satisfied += int(not problems)
            return

        adjudication_id = self._support(entry)
        evidence_ids = _version_evidence(session, record_ids)
        decision = self._decision("merge")
        for record_id in to_assign:
            assign_source_record(
                session,
                source_record_id=record_id,
                to_subject_id=survivor.subject_id,
                decision=decision,
                evidence_ids=evidence_ids,
                adjudication_id=adjudication_id,
            )
            report.assigned += 1
        losers = [venues[subject_id] for subject_id in sorted(venues)]
        self._absorb(
            survivor.subject_id,
            [venue.subject_id for venue in losers],
            decision=decision,
            evidence_ids=evidence_ids,
            adjudication_id=adjudication_id,
        )
        for kind, column in (
            ("organization", Establishment.organization_subject_id),
            ("place", Establishment.place_subject_id),
        ):
            target = getattr(survivor, column.key)
            parents: list[int] = []
            for venue in losers:
                parent = getattr(venue, column.key)
                if parent == target or parent in parents or not _is_current(session, parent):
                    continue
                if (user := _user(session, column, parent)) is not None:
                    report.parents_kept.append(
                        f"{entry.id}: {kind} {parent} is still used by venue {user}"
                    )
                    continue
                parents.append(parent)
            if parents and not _is_current(session, target):
                report.parents_kept.append(f"{entry.id}: survivor {kind} {target} is retired")
            elif parents:
                self._absorb(
                    target,
                    parents,
                    decision=decision,
                    evidence_ids=evidence_ids,
                    adjudication_id=adjudication_id,
                )
                report.parents_merged += len(parents)
        refresh_readiness(
            session, report=LifecycleReport(), organization_id=survivor.organization_subject_id
        )
        report.merged += 1

    def _absorb(
        self,
        target: int,
        inputs: Sequence[int],
        *,
        decision: DecisionMetadata,
        evidence_ids: Sequence[int],
        adjudication_id: int,
    ) -> None:
        """Remap every record of ``inputs`` to ``target``, then merge them into it."""
        if not inputs:
            return
        for subject_id in inputs:
            for record_id in _resolved_records(self.session, subject_id):
                remap_source_record(
                    self.session,
                    source_record_id=record_id,
                    from_subject_id=subject_id,
                    to_subject_id=target,
                    decision=decision,
                    evidence_ids=evidence_ids,
                    adjudication_id=adjudication_id,
                )
                self.report.remapped += 1
        record_subject_change(
            self.session,
            operation="merge",
            input_subject_ids=[target, *inputs],
            output_subject_ids=[target],
            decision=decision,
            evidence_ids=evidence_ids,
            adjudication_id=adjudication_id,
        )

    def retire(self, entry: Retirement) -> None:
        session, report = self.session, self.report
        found = _record(session, entry.gers_id)
        if found is None:
            report.unmatched.append(entry.gers_id)
            report.skipped.append(f"{entry.id}: {entry.gers_id} has no Overture record")
            return
        record_id, state, subject_id = found
        if state == "needs_review":
            report.satisfied += 1
            return
        venue = _venue(session, state, subject_id)
        if venue is None:
            report.skipped.append(
                f"{entry.id}: {entry.gers_id} is {state or 'not in Identity'}"
                + (f" on retired Subject {subject_id}" if state == "resolved" else "")
            )
            return
        records = _resolved_records(session, venue.subject_id)
        adjudication_id = self._support(entry)
        evidence_ids = _version_evidence(session, records)
        decision = self._decision("retire")
        for record in records:
            unassign_source_record(
                session,
                source_record_id=record,
                from_subject_id=venue.subject_id,
                decision=decision,
                evidence_ids=evidence_ids,
                adjudication_id=adjudication_id,
            )
            report.unassigned += 1
        record_subject_change(
            session,
            operation="retire",
            input_subject_ids=[venue.subject_id],
            output_subject_ids=[],
            decision=decision,
            evidence_ids=evidence_ids,
            adjudication_id=adjudication_id,
        )
        refresh_readiness(
            session, report=LifecycleReport(), organization_id=venue.organization_subject_id
        )
        report.retired += 1


def apply_corrections(
    session: Session,
    corrections: CorrectionFile,
    *,
    actor: str,
    decided_at: datetime,
) -> CorrectionReport:
    """Apply every entry that is not yet in effect. Flushes; the caller commits."""
    if (corrections.merges or corrections.retirements) and not (
        corrections.content_hash and corrections.source_url
    ):
        raise ValueError("correction provenance requires file bytes and a repo-relative path")
    lock_lifecycle(session)
    applier = _Applier(session, corrections, actor=actor, decided_at=decided_at)
    for merge in corrections.merges:
        applier.merge(merge)
    for retirement in corrections.retirements:
        applier.retire(retirement)
    session.flush()
    return applier.report


def show_gers(session: Session, subject_ids: Sequence[int]) -> list[dict[str, object]]:
    """Read-only: each Subject's kind, currentness and resolved Overture GERS ids."""
    rows: list[dict[str, object]] = []
    for subject_id in subject_ids:
        kind = session.scalar(select(Subject.kind).where(Subject.id == subject_id))
        gers = session.scalars(
            select(SourceRecord.external_key)
            .join(Source, Source.id == SourceRecord.source_id)
            .join(CurrentResolution, CurrentResolution.source_record_id == SourceRecord.id)
            .where(
                Source.namespace == "overture",
                CurrentResolution.state == "resolved",
                CurrentResolution.subject_id == subject_id,
            )
            .order_by(SourceRecord.external_key)
        ).all()
        rows.append(
            {
                "subject_id": subject_id,
                "kind": kind,
                "current": kind is not None and _is_current(session, subject_id),
                "gers_ids": list(gers),
            }
        )
    return rows


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m apps.discovery.corrections", description=__doc__
    )
    parser.add_argument("--file", type=Path, default=DEFAULT_PATH, help="the reviewed file")
    parser.add_argument("--actor", help="the human who reviewed the file (Adjudication actor)")
    parser.add_argument(
        "--dry-run", action="store_true", help="report what would change, then roll back"
    )
    parser.add_argument(
        "--show-gers",
        type=int,
        nargs="+",
        metavar="SUBJECT_ID",
        help="read-only: print the Overture GERS ids of these Subjects, apply nothing",
    )
    args = parser.parse_args()
    if args.show_gers is None and not args.actor:
        parser.error("--actor is required to apply corrections")
    return args


def main() -> None:
    args = _parse_args()
    with get_sessionmaker()() as session:
        if args.show_gers is not None:
            for row in show_gers(session, args.show_gers):
                print(row)  # noqa: T201 - CLI output
            return
        corrections = load_corrections(args.file)
        report = apply_corrections(
            session, corrections, actor=args.actor, decided_at=datetime.now(UTC)
        )
        if args.dry_run:
            session.rollback()
        else:
            session.commit()
    print(("dry run (rolled back): " if args.dry_run else "applied: ") + str(asdict(report)))  # noqa: T201


if __name__ == "__main__":
    main()
