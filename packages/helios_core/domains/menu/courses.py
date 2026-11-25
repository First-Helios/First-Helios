"""Read contract for the Silver course labels (ADR-0016 §3, Amendment 3 items 3–4).

The published read side of ``menu.section_course``: the pin (which labeller
version is current and which courses pass), the sections a labeller still has
to label, and the labels Gold projects. Gold reads labels through
:func:`section_courses` only, never the table (ADR-0004 §7). Writes are
:func:`~packages.helios_core.domains.menu.commands.record_section_courses`.

**The pin** (``config/course_pin.json``) names the labeller version, its file
and that file's sha256, and the courses that passed the gate. The version
string ends in the file's sha256 prefix, so the pin is refused when the file
no longer hashes to it (Amendment 3 item 3).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from sqlalchemy import exists, select

from packages.helios_core.domains.menu.models import (
    COURSE_LABELS,
    MenuSection,
    MenuSectionCourse,
)

if TYPE_CHECKING:
    from collections.abc import Collection

    from sqlalchemy.orm import Session

PIN_PATH = Path(__file__).resolve().parents[4] / "config" / "course_pin.json"


@dataclass(frozen=True, slots=True)
class CoursePin:
    labeller: str  # the labeller version every row of this pin carries
    file: Path  # the lexicon or weights file the version names
    passing: tuple[str, ...]  # the courses that become index rows


def load_course_pin(path: Path = PIN_PATH) -> CoursePin:
    """The pin, refused when its file's hash or its courses don't hold."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    file = path.parent / str(raw["file"])
    digest = hashlib.sha256(file.read_bytes()).hexdigest()
    labeller, passing = str(raw["labeller"]), tuple(str(c) for c in raw["passing"])
    if digest != raw["sha256"] or not labeller.endswith("@" + digest[:12]):
        raise ValueError(f"{path}: {file.name} no longer hashes to the pinned version")
    if not set(passing) <= set(COURSE_LABELS) - {"other"}:
        raise ValueError(f"{path}: passing courses must be indexable labels")
    return CoursePin(labeller=labeller, file=file, passing=passing)


@dataclass(frozen=True, slots=True)
class SectionToLabel:
    section_id: int
    page_id: int
    name: str


def sections_to_label(
    session: Session, labeller_version: str, page_ids: Collection[int]
) -> list[SectionToLabel]:
    """Named, directly asserted sections of the pages with no row at ``labeller_version``.

    The structural ``Unsectioned`` grouping and inherited or suppressed sections
    (no name of their own) are never labelled. Ordered by section id.
    """
    if not page_ids:
        return []
    labelled = exists().where(
        MenuSectionCourse.section_id == MenuSection.id,
        MenuSectionCourse.labeller_version == labeller_version,
    )
    rows = session.execute(
        select(MenuSection.id, MenuSection.page_id, MenuSection.name)
        .where(
            MenuSection.page_id.in_(sorted(set(page_ids))),
            MenuSection.support_kind == "direct",
            MenuSection.effect == "replace",
            MenuSection.name.is_not(None),
            ~labelled,
        )
        .order_by(MenuSection.id)
    )
    return [SectionToLabel(section_id, page_id, str(name)) for section_id, page_id, name in rows]


def section_courses(
    session: Session, labeller_version: str, page_ids: Collection[int]
) -> dict[tuple[int, str], str | None]:
    """Labels at ``labeller_version`` by ``(page id, section native key)``, the key Gold holds.

    A value of ``None`` means the labeller abstained; a missing key means the
    section has no row at that version. Read-only.
    """
    if not page_ids:
        return {}
    rows = session.execute(
        select(MenuSection.page_id, MenuSection.source_native_key, MenuSectionCourse.course)
        .join(MenuSectionCourse, MenuSectionCourse.section_id == MenuSection.id)
        .where(
            MenuSection.page_id.in_(sorted(set(page_ids))),
            MenuSection.source_native_key.is_not(None),
            MenuSectionCourse.labeller_version == labeller_version,
        )
    )
    return {(page_id, str(key)): course for page_id, key, course in rows}
