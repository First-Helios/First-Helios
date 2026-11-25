"""Label current sections with the pinned course labeller (ADR-0016 §3, Amendment 3 item 4).

Owner-run batch step after extraction and before ``apps.gold.refresh``. It reads
the pin (``config/course_pin.json``), finds every named, directly asserted
section of the current Menu pages (the selector's heads and live-Identity gate,
``current_page_summaries``) that has no ``menu.section_course`` row at the
pinned version, labels it, and inserts the rows. Without ``--commit`` it writes
nothing and only prints the counts::

    python -m apps.menu_pipeline.label_courses            # dry run
    python -m apps.menu_pipeline.label_courses --commit   # insert the rows

The pinned labeller is the lexicon (pure Python, so this runs in the plain
runtime image); a pin naming another kind of file is refused. Writes only
``menu.section_course``, insert-only; re-running inserts nothing new.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from packages.helios_core.db.session import get_sessionmaker
from packages.helios_core.domains.menu.commands import record_section_courses
from packages.helios_core.domains.menu.courses import (
    PIN_PATH,
    load_course_pin,
    sections_to_label,
)
from packages.helios_core.domains.menu.enumeration import current_page_summaries
from packages.helios_parsing.course_lexicon import Lexicon

if TYPE_CHECKING:
    from pathlib import Path

    from sqlalchemy.orm import Session

ABSTAINED = "abstained"


def label_current_sections(
    session: Session, *, at: datetime, pin_path: Path = PIN_PATH, commit: bool = False
) -> Counter[str]:
    """Label the unlabelled current sections at the pin; counts by course (and abstained)."""
    pin = load_course_pin(pin_path)
    if "rules" not in json.loads(pin.file.read_text(encoding="utf-8")):
        raise ValueError(f"{pin.file.name}: only a lexicon pin can be labelled here")
    lexicon = Lexicon.load(pin.file)
    if lexicon.version != pin.labeller:
        raise ValueError(f"{pin.file.name} is {lexicon.version}, the pin names {pin.labeller}")
    pages = [page.page_id for page in current_page_summaries(session, effective_instant=at)]
    sections = sections_to_label(session, pin.labeller, pages)
    labels = [(s.section_id, lexicon.label(s.name)) for s in sections]
    counts = Counter(course or ABSTAINED for _, course in labels)
    if commit:
        inserted = record_section_courses(
            session,
            pin.labeller,
            [(sid, course, None if course is None else Decimal(1)) for sid, course in labels],
        )
        counts["inserted"] = inserted
    return counts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m apps.menu_pipeline.label_courses")
    parser.add_argument("--commit", action="store_true", help="insert the rows (default: dry run)")
    args = parser.parse_args(argv)
    with get_sessionmaker()() as session:
        counts = label_current_sections(session, at=datetime.now(UTC), commit=args.commit)
        if args.commit:
            session.commit()
        else:
            session.rollback()
    labelled = sum(n for key, n in counts.items() if key != "inserted")
    print(json.dumps({"sections": labelled, **dict(sorted(counts.items()))}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
