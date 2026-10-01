"""Course-label comparison harness: label set, venue split, per-course gate, winner (ADR-0016).

Slice 1a of ADR-0016 (Amendment 1): everything that needs no data. Pure: the
label set and the arms' predictions are read by ``apps.menu_pipeline.course_eval``
from gitignored ``var/``; tests use synthetic fixtures only. How sections are
labelled is ``docs/course-labelling-guide.md``.

**Label set** (``var/course-labels/<set>/``): ``manifest.json`` (:class:`Manifest`)
and ``sections.jsonl``, one object per Gold-reaching named section::

    {"venue": "<GERS id>", "version_id": 4711, "section_key": "v4711:b0012:tacos",
     "name": "Tacos", "name_path": ["Tacos"], "items": ["Al Pastor", …],
     "priced_items": 7, "split": "test", "agent_label": "entree", "label": "entree",
     "labeller": "agent:g-4", "owner_confirmed": false}

``section_key`` is the section's version-local native key (ADR-0013 Amendment 7
item 5), unique across venues. ``priced_items`` counts the section's priced Gold
rows (item and variant targets with a price), the unit the index aggregates.
``agent_label`` is the agent's blind label, ``label`` the final one: the
agent's unless the owner changed it (``owner_confirmed``).

**Split.** A venue is in the test split when ``sha256("<seed>:<venue>")`` falls
in the lowest :data:`TEST_SHARE`: it doesn't depend on sample order or size, and
the loader refuses a row whose recorded split differs.

**Exclusions.** The P5-5 held-out venues (and, for later versions, venues
already labelled) are never sampled; a label set holding one is refused.

**Predictions** (one JSONL file per arm): ``{"section_key", "course",
"confidence", "labeller"}``, ``course`` null when the arm abstains.

**Scoring** (test split, weighted by ``priced_items``): per indexable course,
precision = items in sections predicted *c* whose label is *c*, over items
predicted *c*; a course is *readable* with at least :data:`MIN_SECTIONS`
predicted sections from :data:`MIN_VENUES` venues, and *passes* when readable
with precision ≥ :data:`MIN_PRECISION`. Coverage = items whose section is
predicted a passing course, over all test items. The arm covering more items
wins; an exact tie goes to the baseline.
"""

from __future__ import annotations

import hashlib
import random
from collections import Counter
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

COURSES = (
    "appetizer",
    "entree",
    "side",
    "dessert",
    "drink",
    "alcohol",
    "breakfast",
    "kids",
    "other",
)
INDEXABLE = tuple(c for c in COURSES if c != "other")  # `other` never becomes an index row
ABSTAIN = "abstain"  # confusion-table column for a section the arm left unlabelled
GUIDE_VERSION = "course-guide-v1"
TEST_SHARE = 0.4
MIN_PRECISION = 0.95
MIN_SECTIONS = 20  # predicted test sections a course needs to be read at all
MIN_VENUES = 10  # ... from at least this many venues

Split = Literal["train", "test"]
SPLITS: tuple[Split, ...] = ("train", "test")


class LabelSetError(ValueError):
    """A label set, exclusion list or predictions file that the harness refuses."""


@dataclass(frozen=True, slots=True)
class Manifest:
    """How a label set was drawn; ``sections.jsonl`` beside it holds the rows."""

    set: str
    seed: int
    venues: int  # requested
    sampled_venues: int
    test_share: float
    exclusions_sha256: str
    excluded_venues: int
    guide: str
    method_version: str  # the extraction's method_version the sections come from
    unsectioned_priced_items: dict[str, int] | None  # per sampled venue, if exported

    @classmethod
    def from_json(cls, raw: Mapping[str, Any]) -> Manifest:
        unsectioned = raw.get("unsectioned_priced_items")
        return cls(
            set=str(raw["set"]),
            seed=int(raw["seed"]),
            venues=int(raw["venues"]),
            sampled_venues=int(raw["sampled_venues"]),
            test_share=float(raw["test_share"]),
            exclusions_sha256=str(raw["exclusions_sha256"]),
            excluded_venues=int(raw["excluded_venues"]),
            guide=str(raw["guide"]),
            method_version=str(raw["method_version"]),
            unsectioned_priced_items=(
                None if unsectioned is None else {str(k): int(v) for k, v in unsectioned.items()}
            ),
        )

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class Section:
    """One row of ``sections.jsonl``; candidates are rows without labels."""

    venue: str
    version_id: int
    section_key: str
    name: str
    name_path: tuple[str, ...]
    items: tuple[str, ...]
    priced_items: int
    split: Split | None = None
    agent_label: str | None = None
    label: str | None = None
    labeller: str | None = None
    owner_confirmed: bool = False

    def to_json(self) -> dict[str, Any]:
        out = asdict(self)
        out["name_path"], out["items"] = list(self.name_path), list(self.items)
        return out


@dataclass(frozen=True, slots=True)
class Prediction:
    section_key: str
    course: str | None  # None: the arm abstained
    confidence: float | None


def _course(value: object, where: str) -> str | None:
    if value is None:
        return None
    if value not in COURSES:
        raise LabelSetError(f"{where}: {value!r} is not one of the {len(COURSES)} courses")
    return str(value)


def section(raw: Mapping[str, Any], where: str = "section") -> Section:
    """A label-set or candidate row from its JSON object, checked field by field."""
    try:
        venue, key, name = str(raw["venue"]), str(raw["section_key"]), str(raw["name"])
        version_id, priced = int(raw["version_id"]), int(raw["priced_items"])
        name_path = tuple(str(n) for n in raw.get("name_path") or [name])
        items = tuple(str(n) for n in raw["items"])
    except (KeyError, TypeError, ValueError) as exc:
        raise LabelSetError(f"{where}: malformed row ({exc!r})") from exc
    if not venue or not name.strip():
        raise LabelSetError(f"{where}: empty venue or section name")
    if not key.startswith(f"v{version_id}:"):
        raise LabelSetError(f"{where}: {key!r} is not a native key of Version {version_id}")
    if priced < 0:
        raise LabelSetError(f"{where}: negative priced_items")
    split = raw.get("split")
    if split is not None and split not in SPLITS:
        raise LabelSetError(f"{where}: split {split!r} is not train/test")
    row = Section(
        venue=venue,
        version_id=version_id,
        section_key=key,
        name=name,
        name_path=name_path,
        items=items,
        priced_items=priced,
        split=split,
        agent_label=_course(raw.get("agent_label"), where),
        label=_course(raw.get("label"), where),
        labeller=raw.get("labeller"),
        owner_confirmed=bool(raw.get("owner_confirmed", False)),
    )
    if row.agent_label is None and (row.label is not None or row.owner_confirmed):
        raise LabelSetError(f"{where}: a final label without the agent's blind label")
    if row.agent_label is not None and (row.label is None or not row.labeller):
        raise LabelSetError(f"{where}: an agent label needs a final label and a labeller")
    return row


def exclusion_ids(lines: Iterable[str]) -> frozenset[str]:
    """Venue ids from an exclusion file: one GERS id per line; blanks and ``#`` comments skipped."""
    return frozenset(stripped for line in lines if (stripped := line.split("#", 1)[0].strip()))


def exclusions_digest(excluded: Iterable[str]) -> str:
    """The sha256 a manifest records for its exclusion list (sorted, one id per line)."""
    return hashlib.sha256("\n".join(sorted(set(excluded))).encode("utf-8")).hexdigest()


def split_of(seed: int, venue: str, test_share: float = TEST_SHARE) -> Split:
    """The venue's split: test when its seeded hash falls in the lowest ``test_share``."""
    digest = hashlib.sha256(f"{seed}:{venue}".encode()).digest()
    return "test" if int.from_bytes(digest[:8]) / 2**64 < test_share else "train"


def sample_venues(
    eligible: Iterable[str], excluded: frozenset[str], seed: int, n: int
) -> list[str]:
    """``n`` venues at random (all if fewer), never an excluded one; sorted."""
    pool = sorted(set(eligible) - excluded)
    rng = random.Random(seed)  # noqa: S311 - reproducible sampling, not security
    return sorted(rng.sample(pool, min(n, len(pool))))


def draw_label_set(
    candidates: Sequence[Section],
    excluded: frozenset[str],
    *,
    set_name: str,
    seed: int,
    venues: int,
    method_version: str,
    unsectioned: Mapping[str, int] | None = None,
    test_share: float = TEST_SHARE,
) -> tuple[Manifest, list[Section]]:
    """A new label set: every candidate section of ``venues`` sampled venues, split recorded."""
    keys = Counter(c.section_key for c in candidates)
    if duplicate := next((k for k, n in keys.items() if n > 1), None):
        raise LabelSetError(f"candidate section {duplicate!r} appears twice")
    chosen = sample_venues((c.venue for c in candidates), excluded, seed, venues)
    split = {venue: split_of(seed, venue, test_share) for venue in chosen}
    rows = [
        Section(
            venue=c.venue,
            version_id=c.version_id,
            section_key=c.section_key,
            name=c.name,
            name_path=c.name_path,
            items=c.items,
            priced_items=c.priced_items,
            split=split[c.venue],
        )
        for c in sorted(candidates, key=lambda c: c.venue)  # stable: page order per venue
        if c.venue in split
    ]
    manifest = Manifest(
        set=set_name,
        seed=seed,
        venues=venues,
        sampled_venues=len(chosen),
        test_share=test_share,
        exclusions_sha256=exclusions_digest(excluded),
        excluded_venues=len(excluded),
        guide=GUIDE_VERSION,
        method_version=method_version,
        unsectioned_priced_items=(
            None if unsectioned is None else {v: int(unsectioned.get(v, 0)) for v in chosen}
        ),
    )
    return manifest, rows


def check_label_set(manifest: Manifest, rows: Sequence[Section], excluded: frozenset[str]) -> None:
    """Refuse a label set that isn't the one drawn: exclusions, splits, keys."""
    if exclusions_digest(excluded) != manifest.exclusions_sha256:
        raise LabelSetError("the exclusion list differs from the one the set was drawn with")
    seen: set[str] = set()
    for row in rows:
        where = f"{manifest.set}/{row.section_key}"
        if row.venue in excluded:
            raise LabelSetError(f"{where}: venue {row.venue} is on the exclusion list")
        if row.section_key in seen:
            raise LabelSetError(f"{where}: section appears twice")
        seen.add(row.section_key)
        if row.split != split_of(manifest.seed, row.venue, manifest.test_share):
            raise LabelSetError(f"{where}: split {row.split!r} is not the venue's seeded split")


def prediction(raw: Mapping[str, Any], where: str = "prediction") -> tuple[str, Prediction]:
    """An arm's prediction and its labeller version."""
    try:
        key, labeller = str(raw["section_key"]), str(raw["labeller"])
    except KeyError as exc:
        raise LabelSetError(f"{where}: missing {exc}") from exc
    confidence = raw.get("confidence")
    return labeller, Prediction(
        key, _course(raw.get("course"), where), None if confidence is None else float(confidence)
    )


def predictions_of(rows: Iterable[Mapping[str, Any]]) -> tuple[str, dict[str, Prediction]]:
    """One arm's predictions by section key; every row must name the same labeller."""
    labellers: set[str] = set()
    out: dict[str, Prediction] = {}
    for n, raw in enumerate(rows, 1):
        labeller, p = prediction(raw, f"prediction {n}")
        labellers.add(labeller)
        if p.section_key in out:
            raise LabelSetError(f"prediction {n}: {p.section_key!r} predicted twice")
        out[p.section_key] = p
    if len(labellers) != 1:
        raise LabelSetError(f"a predictions file names {len(labellers)} labellers, not one")
    return labellers.pop(), out


def disagreements(
    rows: Sequence[Section], arms: Sequence[Mapping[str, Prediction]], split: Split = "test"
) -> list[tuple[Section, tuple[str | None, ...]]]:
    """Rows the owner must review: an arm predicted a course other than the agent's label.

    An abstention claims nothing, so it is not a disagreement. Rows the owner
    already confirmed are not listed again.
    """
    out = []
    for row in rows:
        if row.split != split or row.owner_confirmed:
            continue
        predicted = tuple(p.course if (p := arm.get(row.section_key)) else None for arm in arms)
        if any(c is not None and c != row.agent_label for c in predicted):
            out.append((row, predicted))
    return out


@dataclass(frozen=True, slots=True)
class CourseScore:
    course: str
    predicted_items: int
    correct_items: int
    predicted_sections: int
    predicted_venues: int
    labelled_items: int  # test items whose final label is the course (recall's base)

    @property
    def precision(self) -> float | None:
        return self.correct_items / self.predicted_items if self.predicted_items else None

    @property
    def readable(self) -> bool:
        return self.predicted_sections >= MIN_SECTIONS and self.predicted_venues >= MIN_VENUES

    @property
    def passes(self) -> bool:
        precision = self.precision
        return self.readable and precision is not None and precision >= MIN_PRECISION


def _test_rows(rows: Sequence[Section], arm: Mapping[str, Prediction]) -> list[Section]:
    keys = {row.section_key for row in rows}
    if unknown := sorted(set(arm) - keys):
        raise LabelSetError(f"{len(unknown)} predictions for sections not in the set: {unknown[0]}")
    test = [row for row in rows if row.split == "test"]
    if unlabelled := [row for row in test if row.label is None]:
        raise LabelSetError(f"{len(unlabelled)} test sections have no label")
    if missing := [row for row in test if row.section_key not in arm]:
        raise LabelSetError(f"{len(missing)} test sections have no prediction (abstain is null)")
    if unconfirmed := disagreements(test, [arm]):
        raise LabelSetError(f"{len(unconfirmed)} disagreements await the owner's confirmation")
    return test


def score(
    manifest: Manifest, rows: Sequence[Section], labeller: str, arm: Mapping[str, Prediction]
) -> dict[str, Any]:
    """One arm's report on the test split (JSON-ready); refuses an incomplete set."""
    test = _test_rows(rows, arm)
    items = sum(row.priced_items for row in test)
    confusion_items: dict[str, Counter[str]] = {c: Counter() for c in COURSES}
    confusion_sections: dict[str, Counter[str]] = {c: Counter() for c in COURSES}
    venues: dict[str, set[str]] = {c: set() for c in COURSES}
    for row in test:
        assert row.label is not None  # noqa: S101 - _test_rows refuses unlabelled rows
        predicted = arm[row.section_key].course or ABSTAIN
        confusion_items[row.label][predicted] += row.priced_items
        confusion_sections[row.label][predicted] += 1
        if predicted != ABSTAIN:
            venues[predicted].add(row.venue)
    courses = [
        CourseScore(
            course=c,
            predicted_items=sum(confusion_items[gold][c] for gold in COURSES),
            correct_items=confusion_items[c][c],
            predicted_sections=sum(confusion_sections[gold][c] for gold in COURSES),
            predicted_venues=len(venues[c]),
            labelled_items=sum(confusion_items[c].values()),
        )
        for c in INDEXABLE
    ]
    passing = [c.course for c in courses if c.passes]
    covered = sum(confusion_items[gold][c] for gold in COURSES for c in passing)

    def predicted_share(column: str) -> dict[str, float | None]:
        n_items = sum(confusion_items[gold][column] for gold in COURSES)
        n_sections = sum(confusion_sections[gold][column] for gold in COURSES)
        return {
            "items": n_items / items if items else None,
            "sections": n_sections / len(test) if test else None,
        }

    unsectioned = manifest.unsectioned_priced_items
    unsectioned_items = (
        None
        if unsectioned is None
        else sum(
            n
            for venue, n in unsectioned.items()
            if split_of(manifest.seed, venue, manifest.test_share) == "test"
        )
    )
    confirmed = [row for row in test if row.owner_confirmed]
    return {
        "labeller": labeller,
        "set": manifest.set,
        "seed": manifest.seed,
        "guide": manifest.guide,
        "method_version": manifest.method_version,
        "test_set_sha256": split_digest(test),
        "test_sections": len(test),
        "test_venues": len({row.venue for row in test}),
        "test_items": items,
        "courses": {
            c.course: {
                "predicted_items": c.predicted_items,
                "correct_items": c.correct_items,
                "predicted_sections": c.predicted_sections,
                "predicted_venues": c.predicted_venues,
                "labelled_items": c.labelled_items,
                "precision": c.precision,
                "readable": c.readable,
                "passes": c.passes,
            }
            for c in courses
        },
        "passing": passing,
        "covered_items": covered,
        "coverage": covered / items if items else None,
        "section_accuracy": (
            sum(confusion_sections[c][c] for c in COURSES) / len(test) if test else None
        ),
        "abstain_rate": predicted_share(ABSTAIN),
        "other_rate": predicted_share("other"),
        "unsectioned_share": (
            None
            if unsectioned_items is None or not items + unsectioned_items
            else unsectioned_items / (items + unsectioned_items)
        ),
        "confusion_items": {gold: dict(row) for gold, row in confusion_items.items() if row},
        "confusion_sections": {gold: dict(row) for gold, row in confusion_sections.items() if row},
        "owner_review": {
            "confirmed": len(confirmed),
            "changed": sum(1 for row in confirmed if row.label != row.agent_label),
        },
    }


def split_digest(test: Sequence[Section]) -> str:
    """Identifies the scored test split: its section keys and final labels."""
    lines = sorted(f"{row.section_key}\t{row.label}" for row in test)
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


def winner(baseline: Mapping[str, Any], model: Mapping[str, Any]) -> str | None:
    """The labeller that ships: more covered items wins, an exact tie goes to the baseline.

    ``None`` when neither arm passes any course (no course rows ship). Refuses
    reports scored on different test splits.
    """
    if baseline["test_set_sha256"] != model["test_set_sha256"]:
        raise LabelSetError("the two reports were scored on different test splits")
    if not baseline["passing"] and not model["passing"]:
        return None
    if int(model["covered_items"]) > int(baseline["covered_items"]):
        return str(model["labeller"])
    return str(baseline["labeller"])
