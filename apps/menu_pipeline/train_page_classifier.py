"""Train and evaluate the page classifier; write its weights file (ADR-0013 §1, §8).

Not a runtime dependency path: it needs scikit-learn and numpy, which the
project does not install. Run with the ``menu`` extra plus an ephemeral
scikit-learn, against the spike's gitignored pages and its page labels::

    git archive origin/spike/menu-model spikes/menu_model/labels | tar -x -C var/
    uv run --extra menu --with scikit-learn==1.9.1 \\
        python -m apps.menu_pipeline.train_page_classifier \\
        --data var/spikes/menu-model --labels var/spikes/menu_model/labels/pages \\
        --out config/page_classifier_v1.json --report var/classifier-v1-report.json

Evaluation (§8: a set not used to tune the version): the configuration (model,
features, C, the precision-0.95 threshold rule) was fixed by the spike on the
first candidate export. It is measured by venue-grouped nested cross-validation
there, then trained on the first export and scored on the second export
(venues the spike never tuned on): recall on its labelled menus, and the pages
it calls a menu, listed for a precision check by hand. The shipped weights are
then refit on every labelled page with the same configuration.
"""

from __future__ import annotations

import argparse
import csv
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import GroupKFold
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from apps.discovery.menu_url import page_menu_signal
from apps.menu_pipeline.classifier import (
    ClassifierWeights,
    PageClassifier,
    load_embedding,
    page_vector_inputs,
)
from apps.menu_pipeline.models import DEFAULT_ROOT
from packages.helios_parsing.page_features import FEATURE_NAMES

VERSION = "classifier-v1"
MODEL = "potion-base-8M"
FOLDS = 5
TARGET_PRECISION = 0.95
C = 0.5


def _lr() -> Any:  # noqa: ANN401 - an sklearn Pipeline
    return make_pipeline(StandardScaler(), LogisticRegression(max_iter=3000, C=C))


def _threshold_for_precision(y: Any, p: Any) -> float:  # noqa: ANN401 - numpy arrays
    """Lowest threshold whose precision on (y, p) reaches the target (else above the max)."""
    for threshold in sorted(set(p.tolist())):
        predicted = p >= threshold
        if predicted.sum() and (y[predicted] == 1).mean() >= TARGET_PRECISION:
            return float(threshold)
    return float(p.max()) + 1e-9


def _scores(y: Any, predicted: Any) -> dict[str, float]:  # noqa: ANN401 - numpy arrays
    tp = int(((predicted == 1) & (y == 1)).sum())
    fp = int(((predicted == 1) & (y == 0)).sum())
    fn = int(((predicted == 0) & (y == 1)).sum())
    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "precision": tp / (tp + fp) if tp + fp else 0.0,
        "recall": tp / (tp + fn) if tp + fn else 0.0,
    }


def _oof(x: Any, y: Any, groups: Any) -> Any:  # noqa: ANN401 - numpy arrays
    out = np.zeros(len(y))
    for train, test in GroupKFold(n_splits=FOLDS).split(x, y, groups):
        out[test] = _lr().fit(x[train], y[train]).predict_proba(x[test])[:, 1]
    return out


def _nested_cv(x: Any, y: Any, groups: Any) -> dict[str, float]:  # noqa: ANN401
    predicted = np.zeros(len(y), dtype=int)
    for train, test in GroupKFold(n_splits=FOLDS).split(x, y, groups):
        threshold = _threshold_for_precision(y[train], _oof(x[train], y[train], groups[train]))
        probability = _lr().fit(x[train], y[train]).predict_proba(x[test])[:, 1]
        predicted[test] = (probability >= threshold).astype(int)
    return _scores(y, predicted)


def _weights(model: Any, threshold: float) -> dict[str, Any]:  # noqa: ANN401
    scaler, regression = (
        model.named_steps["standardscaler"],
        model.named_steps["logisticregression"],
    )
    return {
        "version": VERSION,
        "model": MODEL,
        "text": "page_text",
        "layout_features": list(FEATURE_NAMES),
        "mean": scaler.mean_.tolist(),
        "scale": scaler.scale_.tolist(),
        "coef": regression.coef_[0].tolist(),
        "intercept": float(regression.intercept_[0]),
        "threshold": threshold,
    }


def main() -> None:  # noqa: PLR0915 - one linear training + evaluation script
    parser = argparse.ArgumentParser(prog="python -m apps.menu_pipeline.train_page_classifier")
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--labels", type=Path, required=True)
    parser.add_argument("--model-root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()

    pages = {
        str(row["page_id"]): row
        for row in (json.loads(line) for line in (args.data / "pages.jsonl").open())
    }
    with (args.data / "candidates-2.csv").open() as handle:
        second_export = {row["gers_id"] for row in csv.DictReader(handle)}
    labels = {
        path.stem: str(json.loads(path.read_text())["page_label"])
        for path in args.labels.glob("*.json")
    }

    def url(page_id: str) -> str:
        return str(pages[page_id]["final_url"] or pages[page_id]["url"])

    def html(page_id: str) -> str:
        return str((args.data / "pages" / f"{page_id}.html").read_text(encoding="utf-8"))

    def labelled(second: bool) -> list[str]:
        return sorted(
            page_id
            for page_id, label in labels.items()
            if label in {"menu", "not_menu"}
            and (pages[page_id]["gers_id"] in second_export) == second
        )

    first, second = labelled(False), labelled(True)
    unlabelled = sorted(
        page_id
        for page_id, row in pages.items()
        if row["gers_id"] in second_export
        and page_id not in labels
        and (args.data / "pages" / f"{page_id}.html").is_file()
    )
    embed = load_embedding(MODEL, args.model_root)
    cache: dict[str, list[float]] = {}

    def vectors(ids: list[str]) -> Any:  # noqa: ANN401 - numpy array
        todo = [page_id for page_id in ids if page_id not in cache]
        inputs = [page_vector_inputs(html(page_id), url(page_id)) for page_id in todo]
        for page_id, (_text, layout), embedding in zip(
            todo, inputs, embed([text for text, _ in inputs]), strict=True
        ):
            cache[page_id] = [*embedding, *layout]
        return np.array([cache[page_id] for page_id in ids], dtype=np.float64)

    def target(ids: list[str]) -> Any:  # noqa: ANN401 - numpy array
        return np.array([1 if labels[page_id] == "menu" else 0 for page_id in ids])

    def venue(ids: list[str]) -> Any:  # noqa: ANN401 - numpy array
        return np.array([str(pages[page_id]["gers_id"]) for page_id in ids])

    x1, y1, g1 = vectors(first), target(first), venue(first)
    heuristic = np.array([int(page_menu_signal(html(p), url(p))) for p in first])
    report: dict[str, Any] = {
        "version": VERSION,
        "trained_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "first_export": {"pages": len(first), "menus": int(y1.sum())},
        "nested_cv_first_export": _nested_cv(x1, y1, g1),
        "s4_heuristic_first_export": _scores(y1, heuristic),
    }

    held_model = _lr().fit(x1, y1)
    held_threshold = _threshold_for_precision(y1, _oof(x1, y1, g1))
    x2, y2 = vectors(second), target(second)
    second_predicted = (held_model.predict_proba(x2)[:, 1] >= held_threshold).astype(int)
    report["second_export_labelled"] = {"pages": len(second), **_scores(y2, second_predicted)}
    report["second_export_s4_heuristic"] = _scores(
        y2, np.array([int(page_menu_signal(html(p), url(p))) for p in second])
    )
    xu = vectors(unlabelled)
    called = xu.shape[0] and held_model.predict_proba(xu)[:, 1] >= held_threshold
    report["second_export_unlabelled"] = {
        "pages": len(unlabelled),
        "called_menu": [
            {"page_id": page_id, "url": url(page_id)}
            for page_id, hit in zip(unlabelled, called, strict=True)
            if hit
        ],
        "s4_called_menu": sum(page_menu_signal(html(p), url(p)) for p in unlabelled),
    }

    every = first + second
    x, y, g = vectors(every), target(every), venue(every)
    final = _lr().fit(x, y)
    weights = _weights(final, _threshold_for_precision(y, _oof(x, y, g)))
    report["shipped"] = {
        "pages": len(every),
        "menus": int(y.sum()),
        "threshold": weights["threshold"],
    }

    # The plain-Python scorer must reproduce scikit-learn's probabilities.
    args.out.write_text(json.dumps(weights, indent=1) + "\n", encoding="utf-8")
    scorer = PageClassifier(ClassifierWeights.load(args.out), embed)
    for page_id, expected in zip(every[:20], final.predict_proba(x[:20])[:, 1], strict=True):
        if abs(scorer.probability(html(page_id), url(page_id)) - expected) > 1e-6:  # noqa: PLR2004
            raise RuntimeError(f"scorer disagrees with scikit-learn on {page_id}")
    args.report.write_text(json.dumps(report, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "second_export_unlabelled"}))  # noqa: T201


if __name__ == "__main__":
    main()
