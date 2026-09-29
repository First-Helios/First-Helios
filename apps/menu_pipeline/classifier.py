"""Stage [1] page classifier (ADR-0013 §1), used as discovery's page verifier (§7).

A static embedding of :func:`~packages.helios_parsing.page_features.page_text`
plus the seven layout features, scored by a logistic regression whose
standardization, coefficients and threshold are a checked-in weights file
(``config/page_classifier_v2.json``). Scoring is plain Python: scikit-learn is
only needed to re-train (``apps.menu_pipeline.train_page_classifier``).

The embedding runs through ``fastembed`` (the ``menu`` extra) on model files
verified against ``config/models.yaml``. :class:`PageClassifier` takes the
embedding as a function, so tests run without the model.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from apps.discovery.menu_url import page_menu_signal
from apps.menu_pipeline.models import DEFAULT_ROOT, load_manifest, verified_model_dir
from packages.helios_parsing.page_features import FEATURE_NAMES, layout_features, page_text
from packages.helios_parsing.segment import segment

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

# classifier-v2 (S6f) keeps classifier-v1's coefficients; its inputs changed:
# segmentation skips dialogs (consent prompts), which rendered Toast pages open with.
WEIGHTS_PATH = Path(__file__).resolve().parents[2] / "config" / "page_classifier_v2.json"


@dataclass(frozen=True, slots=True)
class ClassifierWeights:
    """A trained classifier version: which model, which features, which scores."""

    version: str
    model: str
    mean: tuple[float, ...]
    scale: tuple[float, ...]
    coef: tuple[float, ...]
    intercept: float
    threshold: float

    @classmethod
    def load(cls, path: Path = WEIGHTS_PATH) -> ClassifierWeights:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if tuple(raw["layout_features"]) != FEATURE_NAMES:
            raise ValueError(f"{path}: layout features differ from this code's")
        weights = cls(
            version=str(raw["version"]),
            model=str(raw["model"]),
            mean=tuple(float(v) for v in raw["mean"]),
            scale=tuple(float(v) for v in raw["scale"]),
            coef=tuple(float(v) for v in raw["coef"]),
            intercept=float(raw["intercept"]),
            threshold=float(raw["threshold"]),
        )
        if not len(weights.mean) == len(weights.scale) == len(weights.coef):
            raise ValueError(f"{path}: mean, scale and coef differ in length")
        return weights


def page_vector_inputs(html: str, url: str) -> tuple[str, list[float]]:
    """The text to embed and the layout features, exactly as the weights were trained."""
    blocks = segment(html)
    # The S4 signal is a feature as trained: URL path included (trust_path=True).
    return page_text(html, url, blocks), layout_features(
        blocks, heuristic_signal=page_menu_signal(html, url)
    )


class PageClassifier:
    """A :class:`~apps.discovery.web_client.PageVerifier` named after its weights version."""

    def __init__(
        self, weights: ClassifierWeights, embed: Callable[[Sequence[str]], list[list[float]]]
    ) -> None:
        self._weights = weights
        self._embed = embed

    @property
    def name(self) -> str:
        return self._weights.version

    @property
    def threshold(self) -> float:
        return self._weights.threshold

    def probability(self, html: str, url: str) -> float:
        text, layout = page_vector_inputs(html, url)
        (embedding,) = self._embed([text])
        features = [*embedding, *layout]
        weights = self._weights
        if len(features) != len(weights.coef):
            raise ValueError(
                f"{len(features)} features for {len(weights.coef)} weights: wrong embedding model"
            )
        score = weights.intercept + sum(
            coef * (value - mean) / scale
            for value, mean, scale, coef in zip(
                features, weights.mean, weights.scale, weights.coef, strict=True
            )
        )
        if score >= 0:
            return 1.0 / (1.0 + math.exp(-score))
        exp = math.exp(score)  # the same sigmoid, without overflowing exp(-score)
        return exp / (1.0 + exp)

    def is_menu(self, html: str, url: str, *, trust_path: bool) -> bool:
        """``trust_path`` is the S4 check's knob; the classifier's inputs are fixed."""
        del trust_path
        return self.probability(html, url) >= self._weights.threshold


def load_embedding(
    model: str, model_root: Path = DEFAULT_ROOT
) -> Callable[[Sequence[str]], list[list[float]]]:
    """Embed texts with a manifest model on checksum-verified files (the ``menu`` extra)."""
    from fastembed import TextEmbedding  # noqa: PLC0415 - optional extra, loaded on demand

    spec = load_manifest()[model]
    directory = verified_model_dir(spec, model_root)
    embedding = TextEmbedding(spec.embedding_model, specific_model_path=str(directory))

    def embed(texts: Sequence[str]) -> list[list[float]]:
        return [[float(value) for value in vector] for vector in embedding.embed(list(texts))]

    return embed


def load_page_classifier(
    *, weights_path: Path = WEIGHTS_PATH, model_root: Path = DEFAULT_ROOT
) -> PageClassifier:
    """The shipped classifier; refuses model files that differ from the manifest."""
    weights = ClassifierWeights.load(weights_path)
    return PageClassifier(weights, load_embedding(weights.model, model_root))
