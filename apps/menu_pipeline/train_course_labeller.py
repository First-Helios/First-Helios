"""Train arm B of the course comparison and write its weights file (ADR-0016 §4).

Not a runtime dependency path: it needs scikit-learn and numpy, which the
project does not install. Run with the ``menu`` extra plus an ephemeral
scikit-learn, on a label set's **training split only**::

    uv run --extra menu --with scikit-learn==1.9.1 \\
        python -m apps.menu_pipeline.train_course_labeller \\
        --labels var/course-labels/set-1 --out config/course_labeller_v1.json \\
        --report var/course-eval/set-1/train-course-labeller-v1.json

The section text (:func:`~apps.menu_pipeline.course_labellers.section_text`) is
embedded with ``potion-base-8M``, standardized, and fitted with a multinomial
logistic regression over the nine labels. ``C`` and the abstain threshold are
chosen together by venue-grouped cross-validation on the training split: for
each pair, out-of-fold predictions are scored like the gate (item-weighted
precision per indexable course, readable at the harness's section and venue
floors), and the pair covering the most items with passing courses wins (ties:
higher threshold, then smaller ``C``). The shipped weights are refit on the
whole training split. The test split is never read.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import GroupKFold
from sklearn.preprocessing import StandardScaler

from apps.menu_pipeline.classifier import load_embedding
from apps.menu_pipeline.course_eval import read_jsonl
from apps.menu_pipeline.course_labellers import section_text
from apps.menu_pipeline.models import DEFAULT_ROOT
from packages.helios_parsing.course_eval import (
    COURSES,
    INDEXABLE,
    MIN_PRECISION,
    MIN_SECTIONS,
    MIN_VENUES,
    section,
)

MODEL = "potion-base-8M"
FOLDS = 5
C_GRID = (0.03, 0.1, 0.3, 1.0, 3.0)
THRESHOLDS = tuple(round(0.30 + 0.05 * i, 2) for i in range(14))  # 0.30 .. 0.95


def _fit(x: Any, y: Any, c: float) -> tuple[Any, Any]:  # noqa: ANN401 - sklearn objects
    scaler = StandardScaler().fit(x)
    model = LogisticRegression(C=c, max_iter=5000).fit(scaler.transform(x), y)
    return scaler, model


def _oof(x: Any, y: Any, groups: Any, c: float) -> Any:  # noqa: ANN401 - numpy arrays
    """Out-of-fold class probabilities, columns in :data:`COURSES` order."""
    out = np.zeros((len(y), len(COURSES)))
    for train, test in GroupKFold(n_splits=FOLDS).split(x, y, groups):
        scaler, model = _fit(x[train], y[train], c)
        probabilities = model.predict_proba(scaler.transform(x[test]))
        for j, cls in enumerate(model.classes_):
            out[test, COURSES.index(cls)] = probabilities[:, j]
    return out


def _gate(
    probabilities: Any,  # noqa: ANN401 - numpy array
    y: list[str],
    items: list[int],
    venues: list[str],
    threshold: float,
) -> dict[str, Any]:
    predicted_items: dict[str, int] = defaultdict(int)
    correct: dict[str, int] = defaultdict(int)
    sections: dict[str, int] = defaultdict(int)
    venue_sets: dict[str, set[str]] = defaultdict(set)
    for row, gold, weight, venue in zip(probabilities, y, items, venues, strict=True):
        best = int(np.argmax(row))
        if row[best] < threshold:
            continue
        course = COURSES[best]
        predicted_items[course] += weight
        sections[course] += 1
        venue_sets[course].add(venue)
        correct[course] += weight if course == gold else 0
    courses: dict[str, dict[str, Any]] = {}
    for course in INDEXABLE:
        n = predicted_items[course]
        precision = correct[course] / n if n else None
        readable = sections[course] >= MIN_SECTIONS and len(venue_sets[course]) >= MIN_VENUES
        courses[course] = {
            "items": n,
            "precision": precision,
            "sections": sections[course],
            "venues": len(venue_sets[course]),
            "passes": bool(readable and precision is not None and precision >= MIN_PRECISION),
        }
    covered = sum(c["items"] for c in courses.values() if c["passes"])
    return {"threshold": threshold, "covered": covered, "courses": courses}


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m apps.menu_pipeline.train_course_labeller")
    parser.add_argument("--labels", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--version", default="course-labeller-v1")
    parser.add_argument("--model-root", type=Path, default=DEFAULT_ROOT)
    args = parser.parse_args()

    rows = [section(raw) for raw in read_jsonl(args.labels / "sections.jsonl")]
    train = [r for r in rows if r.split == "train"]
    if any(r.label is None for r in train):
        raise SystemExit("the training split has unlabelled sections")
    embed = load_embedding(MODEL, args.model_root)
    x = np.array(embed([section_text(r.name_path) for r in train]))
    y = np.array([r.label for r in train])
    groups = np.array([r.venue for r in train])
    items = [r.priced_items for r in train]
    venues = [r.venue for r in train]

    trials = []
    for c in C_GRID:
        probabilities = _oof(x, y, groups, c)
        for threshold in THRESHOLDS:
            trial = _gate(probabilities, list(y), items, venues, threshold)
            trials.append({"C": c, **trial})
    best = max(trials, key=lambda t: (t["covered"], t["threshold"], -t["C"]))
    scaler, model = _fit(x, y, best["C"])
    classes = [str(c) for c in model.classes_]
    weights = {
        "version": args.version,
        "derived_from": (
            f"{args.labels.name} training split ({len(train)} sections, "
            f"{len(set(venues))} venues); C and threshold by {FOLDS}-fold venue-grouped CV"
        ),
        "model": MODEL,
        "text": "section name path, ' > '-joined",
        "classes": classes,
        "C": best["C"],
        "threshold": best["threshold"],
        "mean": [round(float(v), 8) for v in scaler.mean_],
        "scale": [round(float(v), 8) for v in scaler.scale_],
        "coef": [[round(float(v), 8) for v in row] for row in model.coef_],
        "intercept": [round(float(v), 8) for v in model.intercept_],
    }
    args.out.write_text(json.dumps(weights, indent=1) + "\n", encoding="utf-8")
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(
            {
                "trained_at": datetime.now(UTC).isoformat(),
                "labels": str(args.labels),
                "train_sections": len(train),
                "chosen": best,
                "trials": trials,
            },
            indent=1,
        )
        + "\n",
        encoding="utf-8",
    )
    passing = [c for c, s in best["courses"].items() if s["passes"]]
    print(
        f"C={best['C']} threshold={best['threshold']} oof covered={best['covered']}/{sum(items)} "
        f"passing={passing}"
    )


if __name__ == "__main__":
    main()
