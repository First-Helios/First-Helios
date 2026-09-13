"""Published transaction contracts for the Bronze provenance module."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select

from packages.helios_core.provenance.models import SourceRecord

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


def lock_source_record(session: Session, source_record_id: int) -> bool:
    """Lock a Source Record for a same-transaction downstream decision.

    Identity resolution serializes on the durable Bronze record rather than
    on a mutable Silver projection.  Keeping that lookup here lets Identity
    depend on a provenance contract instead of importing provenance ORM
    models directly.
    """
    return (
        session.scalar(
            select(SourceRecord.id)
            .where(SourceRecord.id == source_record_id)
            .with_for_update(key_share=True)
        )
        is not None
    )
