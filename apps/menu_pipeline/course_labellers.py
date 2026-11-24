"""The two course labellers of ADR-0016 §4 and their predictions for ``course_eval``.

* **Arm A, lexicon** (``packages.helios_parsing.course_lexicon``,
  ``config/course_lexicon_v1.json``): word rules on the section name; pure Python.
* **Arm B, embedding + multinomial LR** (``config/course_labeller_v1.json``): the
  section name embedded with ``potion-base-8M`` (checksum-verified files, via
  :func:`~apps.menu_pipeline.classifier.load_embedding`; the ``menu`` extra),
  standardized, scored by a checked-in multinomial logistic regression, and
  abstaining below the weights file's threshold. Trained by
  ``apps.menu_pipeline.train_course_labeller`` (ephemeral scikit-learn).

Both read the name only (v1, §4). ``predict`` writes one JSONL row per section
of a label set, the format ``course_eval disagreements``/``score`` read::

    uv run --extra menu python -m apps.menu_pipeline.course_labellers predict \\
        --labels var/course-labels/set-1 --arm model --out var/course-eval/set-1/model.jsonl
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from apps.menu_pipeline.classifier import load_embedding
from apps.menu_pipeline.course_eval import read_jsonl
from apps.menu_pipeline.models import DEFAULT_ROOT
from packages.helios_parsing.course_eval import COURSES, section
from packages.helios_parsing.course_lexicon import Lexicon

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

_CONFIG = Path(__file__).resolve().parents[2] / "config"
LEXICON_PATH = _CONFIG / "course_lexicon_v1.json"
MODEL_PATH = _CONFIG / "course_labeller_v1.json"


def section_text(name_path: Sequence[str]) -> str:
    """What arm B embeds: the section's name path, outermost first."""
    return " > ".join(name_path)


@dataclass(frozen=True, slots=True)
class CourseWeights:
    """A trained arm-B version: model, standardization, one coefficient row per class."""

    version: str  # the labeller version, `<name>@<file sha256 prefix>`
    model: str
    classes: tuple[str, ...]
    mean: tuple[float, ...]
    scale: tuple[float, ...]
    coef: tuple[tuple[float, ...], ...]
    intercept: tuple[float, ...]
    threshold: float  # abstain when the top probability is below it

    @classmethod
    def load(cls, path: Path = MODEL_PATH) -> CourseWeights:
        data = path.read_bytes()
        raw = json.loads(data)
        weights = cls(
            version=f"{raw['version']}@{hashlib.sha256(data).hexdigest()[:12]}",
            model=str(raw["model"]),
            classes=tuple(str(c) for c in raw["classes"]),
            mean=tuple(float(v) for v in raw["mean"]),
            scale=tuple(float(v) for v in raw["scale"]),
            coef=tuple(tuple(float(v) for v in row) for row in raw["coef"]),
            intercept=tuple(float(v) for v in raw["intercept"]),
            threshold=float(raw["threshold"]),
        )
        if not set(weights.classes) <= set(COURSES):
            raise ValueError(f"{path}: classes outside the vocabulary")
        if not len(weights.classes) == len(weights.coef) == len(weights.intercept):
            raise ValueError(f"{path}: classes, coef and intercept differ in length")
        if any(len(row) != len(weights.mean) for row in weights.coef) or len(weights.mean) != len(
            weights.scale
        ):
            raise ValueError(f"{path}: coefficient rows and standardization differ in length")
        return weights

    def probabilities(self, embedding: Sequence[float]) -> list[float]:
        """Softmax over the classes for one embedding."""
        if len(embedding) != len(self.mean):
            raise ValueError(f"{len(embedding)} features for {len(self.mean)}: wrong model")
        x = [(v - m) / s for v, m, s in zip(embedding, self.mean, self.scale, strict=True)]
        scores = [
            b + sum(c * v for c, v in zip(row, x, strict=True))
            for row, b in zip(self.coef, self.intercept, strict=True)
        ]
        top = max(scores)
        exps = [math.exp(s - top) for s in scores]
        total = sum(exps)
        return [e / total for e in exps]

    def label(self, embedding: Sequence[float]) -> tuple[str | None, float]:
        """The course (``None`` below the threshold) and the top probability."""
        probabilities = self.probabilities(embedding)
        best = max(range(len(probabilities)), key=probabilities.__getitem__)
        confidence = probabilities[best]
        return (self.classes[best] if confidence >= self.threshold else None), confidence


class ModelLabeller:
    def __init__(
        self, weights: CourseWeights, embed: Callable[[Sequence[str]], list[list[float]]]
    ) -> None:
        self.weights, self._embed = weights, embed

    def predict(self, name_paths: Sequence[Sequence[str]]) -> list[tuple[str | None, float]]:
        vectors = self._embed([section_text(path) for path in name_paths])
        return [self.weights.label(vector) for vector in vectors]


def load_model_labeller(
    *, weights_path: Path = MODEL_PATH, model_root: Path = DEFAULT_ROOT
) -> ModelLabeller:
    weights = CourseWeights.load(weights_path)
    return ModelLabeller(weights, load_embedding(weights.model, model_root))


def predict_rows(
    arm: str, name_paths: Sequence[Sequence[str]], keys: Sequence[str], **kw: Path
) -> list[dict[str, object]]:
    """One prediction row per section (``course`` null to abstain)."""
    if arm == "lexicon":
        lexicon = Lexicon.load(kw.get("weights_path", LEXICON_PATH))
        labels = [lexicon.label(path[-1]) for path in name_paths]
        return [
            {
                "section_key": k,
                "course": c,
                "confidence": None if c is None else 1.0,
                "labeller": lexicon.version,
            }
            for k, c in zip(keys, labels, strict=True)
        ]
    labeller = load_model_labeller(**kw)
    return [
        {
            "section_key": k,
            "course": c,
            "confidence": round(p, 4),
            "labeller": labeller.weights.version,
        }
        for k, (c, p) in zip(keys, labeller.predict(name_paths), strict=True)
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m apps.menu_pipeline.course_labellers")
    commands = parser.add_subparsers(dest="command", required=True)
    predict = commands.add_parser("predict", help="predict every section of a label set")
    predict.add_argument("--labels", type=Path, required=True)
    predict.add_argument("--arm", choices=["lexicon", "model"], required=True)
    predict.add_argument("--weights", type=Path)
    predict.add_argument("--model-root", type=Path, default=DEFAULT_ROOT)
    predict.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    rows = [section(raw) for raw in read_jsonl(args.labels / "sections.jsonl")]
    kw: dict[str, Path] = {}
    if args.weights:
        kw["weights_path"] = args.weights
    if args.arm == "model":
        kw["model_root"] = args.model_root
    out = predict_rows(args.arm, [r.name_path for r in rows], [r.section_key for r in rows], **kw)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as handle:
        for row in out:
            handle.write(json.dumps(row) + "\n")
    abstained = sum(1 for row in out if row["course"] is None)
    print(f"{out[0]['labeller'] if out else '-'}: {len(out)} sections, {abstained} abstained")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
