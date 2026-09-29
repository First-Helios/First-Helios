"""Score a page-classifier weights file on the labelled pages (ADR-0013 §8).

No training and no scikit-learn: runs the shipped scorer on the spike's
labelled static pages (first and second candidate export), lists what it calls
a menu among the second export's unlabelled pages, and scores ``measure_render``
directories whose ``labels.json`` labels the rendered pages (rendered file →
``menu``/``not_menu``; anything else is excluded), split by their ``set``::

    uv run --extra menu python -m apps.menu_pipeline.evaluate_page_classifier \\
        --weights config/page_classifier_v2.json \\
        --data var/spikes/menu-model --labels var/spikes/menu_model/labels/pages \\
        --rendered var/render-measure/laptop --report var/classifier-v2-evaluation.json

Page bodies and labels stay in gitignored ``var/``; the recorded numbers live in
``docs/reviews/``.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

from apps.menu_pipeline.classifier import load_page_classifier
from apps.menu_pipeline.models import DEFAULT_ROOT

_LABELS = frozenset({"menu", "not_menu"})


def scores(outcomes: list[tuple[bool, bool]]) -> dict[str, Any]:
    """``(is a menu, called a menu)`` pairs → counts, precision and recall."""
    tp = sum(1 for truth, called in outcomes if truth and called)
    fp = sum(1 for truth, called in outcomes if called and not truth)
    fn = sum(1 for truth, called in outcomes if truth and not called)
    return {
        "pages": len(outcomes),
        "menus": sum(1 for truth, _ in outcomes if truth),
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "precision": round(tp / (tp + fp), 3) if tp + fp else None,
        "recall": round(tp / (tp + fn), 3) if tp + fn else None,
    }


def rendered_pages(directory: Path) -> list[dict[str, Any]]:
    """Labelled rendered rows of a ``measure_render`` run, with their HTML."""
    labels = json.loads((directory / "labels.json").read_text(encoding="utf-8"))
    rows = []
    for line in (directory / "measure.jsonl").open(encoding="utf-8"):
        row = json.loads(line)
        label = labels.get(row.get("html"))
        if row.get("outcome") == "rendered" and label in _LABELS:
            html = (directory / "rendered" / row["html"]).read_text(encoding="utf-8")
            rows.append({**row, "label": label, "body": html})
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m apps.menu_pipeline.evaluate_page_classifier")
    parser.add_argument("--weights", type=Path, required=True)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--labels", type=Path, required=True)
    parser.add_argument("--rendered", type=Path, action="append", default=[])
    parser.add_argument("--model-root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()

    classifier = load_page_classifier(weights_path=args.weights, model_root=args.model_root)
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

    def called(page_id: str) -> bool:
        row = pages[page_id]
        html = (args.data / "pages" / f"{page_id}.html").read_text(encoding="utf-8")
        return classifier.is_menu(html, str(row["final_url"] or row["url"]), trust_path=False)

    report: dict[str, Any] = {"version": classifier.name}
    for name, second in (("static_first_export", False), ("static_second_export", True)):
        ids = sorted(
            page_id
            for page_id, label in labels.items()
            if label in _LABELS and (pages[page_id]["gers_id"] in second_export) == second
        )
        report[name] = scores([(labels[page_id] == "menu", called(page_id)) for page_id in ids])
    unlabelled = sorted(
        page_id
        for page_id, row in pages.items()
        if row["gers_id"] in second_export
        and page_id not in labels
        and (args.data / "pages" / f"{page_id}.html").is_file()
    )
    report["static_second_export_unlabelled_called_menu"] = [
        str(pages[page_id]["final_url"] or pages[page_id]["url"])
        for page_id in unlabelled
        if called(page_id)
    ]
    for directory in args.rendered:
        by_set: dict[str, list[dict[str, Any]]] = {}
        for row in rendered_pages(directory):
            by_set.setdefault(str(row.get("set", "rendered")), []).append(row)
        for name, rows in sorted(by_set.items()):
            verdicts = [
                (
                    row,
                    classifier.probability(row["body"], row["final_url"]),
                )
                for row in rows
            ]
            threshold = classifier.threshold
            report[f"rendered_{name}"] = {
                **scores([(row["label"] == "menu", p >= threshold) for row, p in verdicts]),
                "errors": [
                    {"url": row["final_url"], "label": row["label"], "probability": round(p, 4)}
                    for row, p in verdicts
                    if (row["label"] == "menu") != (p >= threshold)
                ],
            }
    args.report.write_text(json.dumps(report, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if "unlabelled" not in k}))  # noqa: T201


if __name__ == "__main__":
    main()
