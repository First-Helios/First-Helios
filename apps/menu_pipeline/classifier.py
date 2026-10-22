"""Stage [1] page classifier (ADR-0013 §1), used as discovery's page verifier (§7).

A static embedding of :func:`~packages.helios_parsing.page_features.page_text`
plus the plain features its weights file names, scored by a logistic regression
whose standardization, coefficients and threshold are a checked-in weights file.
``classifier-v2`` (``config/page_classifier_v2.json``) names the seven layout
features; ``classifier-v3`` (``config/page_classifier_v3.json``, Amendment 24)
adds the eleven generic page signals. Scoring is plain Python: scikit-learn is
only needed to re-train (``apps.menu_pipeline.train_page_classifier``).

The live verifier (Amendment 27) is :data:`VERIFIER_NAME`, ``classifier-v2``
AND ``classifier-v3`` (:class:`AllOfClassifiers`, :func:`load_verifier`): a
page is a menu only when both accept it. It is discovery's menu-URL verifier
and the menu-page classifier, and its name is the pipeline version's
classifier part, so shipping it re-verifies every saved menu URL (ADR-0015)
and re-scores every stored page (R4, :mod:`.retraction`).

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
from packages.helios_parsing.page_features import (
    FEATURE_NAMES,
    PAGE_SIGNAL_NAMES,
    layout_features,
    page_signals,
    page_text,
)
from packages.helios_parsing.segment import segment

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

_CONFIG = Path(__file__).resolve().parents[2] / "config"
# classifier-v2 (S6f) keeps classifier-v1's coefficients; its inputs changed:
# segmentation skips dialogs (consent prompts), which rendered Toast pages open with.
WEIGHTS_PATH = _CONFIG / "page_classifier_v2.json"
# (Amendment 27) the live verifier: a page must pass both classifiers
VERIFIER_NAME = "classifier-v2+v3"
VERIFIER_WEIGHTS = (WEIGHTS_PATH, _CONFIG / "page_classifier_v3.json")


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
    features: tuple[str, ...] = FEATURE_NAMES  # the plain features after the embedding

    @classmethod
    def load(cls, path: Path = WEIGHTS_PATH) -> ClassifierWeights:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if tuple(raw["layout_features"]) != FEATURE_NAMES:
            raise ValueError(f"{path}: layout features differ from this code's")
        signals = tuple(raw.get("page_signals", ()))
        if signals not in ((), PAGE_SIGNAL_NAMES):
            raise ValueError(f"{path}: page signals differ from this code's")
        weights = cls(
            version=str(raw["version"]),
            model=str(raw["model"]),
            mean=tuple(float(v) for v in raw["mean"]),
            scale=tuple(float(v) for v in raw["scale"]),
            coef=tuple(float(v) for v in raw["coef"]),
            intercept=float(raw["intercept"]),
            threshold=float(raw["threshold"]),
            features=FEATURE_NAMES + signals,
        )
        if not len(weights.mean) == len(weights.scale) == len(weights.coef):
            raise ValueError(f"{path}: mean, scale and coef differ in length")
        return weights


def page_vector_inputs(
    html: str, url: str, features: tuple[str, ...] = FEATURE_NAMES
) -> tuple[str, list[float]]:
    """The text to embed and the named plain features, exactly as the weights were trained."""
    text, values = _page_inputs(html, url, features)
    return text, [values[name] for name in features]


def _page_inputs(html: str, url: str, features: tuple[str, ...]) -> tuple[str, dict[str, float]]:
    blocks = segment(html)
    # The S4 signal is a feature as trained: URL path included (trust_path=True).
    values = dict(
        zip(
            FEATURE_NAMES,
            layout_features(blocks, heuristic_signal=page_menu_signal(html, url)),
            strict=True,
        )
    )
    if not set(features) <= values.keys():
        values.update(zip(PAGE_SIGNAL_NAMES, page_signals(html, url, blocks), strict=True))
    return page_text(html, url, blocks), values


def _score(weights: ClassifierWeights, embedding: list[float], plain: list[float]) -> float:
    features = [*embedding, *plain]
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
        text, plain = page_vector_inputs(html, url, self._weights.features)
        (embedding,) = self._embed([text])
        return _score(self._weights, embedding, plain)

    def is_menu(self, html: str, url: str, *, trust_path: bool) -> bool:
        """``trust_path`` is the S4 check's knob; the classifier's inputs are fixed."""
        del trust_path
        return self.probability(html, url) >= self._weights.threshold


class AllOfClassifiers:
    """A :class:`~apps.discovery.web_client.PageVerifier` that accepts a page only when
    every classifier does (Amendment 27: ``classifier-v2`` AND ``classifier-v3``).

    The page is segmented and embedded once, as the classifiers share one
    embedding model. Its probability, the page confidence of the pages it
    accepts (§6), is the lowest of theirs.
    """

    def __init__(
        self,
        name: str,
        weights: Sequence[ClassifierWeights],
        embed: Callable[[Sequence[str]], list[list[float]]],
    ) -> None:
        if not weights or len({w.model for w in weights}) != 1:
            raise ValueError("the classifiers must share one embedding model")
        self._name = name
        self._weights = tuple(weights)
        self._embed = embed
        self._features = tuple(dict.fromkeys(f for w in weights for f in w.features))

    @property
    def name(self) -> str:
        return self._name

    def probabilities(self, html: str, url: str) -> tuple[float, ...]:
        """Each classifier's probability, in the order of its weights."""
        text, values = _page_inputs(html, url, self._features)
        (embedding,) = self._embed([text])
        return tuple(
            _score(w, embedding, [values[name] for name in w.features]) for w in self._weights
        )

    def probability(self, html: str, url: str) -> float:
        return min(self.probabilities(html, url))

    def is_menu(self, html: str, url: str, *, trust_path: bool) -> bool:
        """``trust_path`` is the S4 check's knob; the classifiers' inputs are fixed."""
        del trust_path
        return all(
            p >= w.threshold
            for p, w in zip(self.probabilities(html, url), self._weights, strict=True)
        )


def load_embedding(
    model: str, model_root: Path = DEFAULT_ROOT
) -> Callable[[Sequence[str]], list[list[float]]]:
    """Embed texts with a manifest model on checksum-verified files (the ``menu`` extra)."""
    spec = load_manifest()[model]
    if spec.embedding_model is None:
        raise ValueError(f"{model} is not an embedding model in config/models.yaml")
    from fastembed import TextEmbedding  # noqa: PLC0415 - optional extra, loaded on demand

    directory = verified_model_dir(spec, model_root)
    embedding = TextEmbedding(spec.embedding_model, specific_model_path=str(directory))

    def embed(texts: Sequence[str]) -> list[list[float]]:
        return [[float(value) for value in vector] for vector in embedding.embed(list(texts))]

    return embed


def load_page_classifier(
    *, weights_path: Path = WEIGHTS_PATH, model_root: Path = DEFAULT_ROOT
) -> PageClassifier:
    """One classifier by its weights file; refuses model files that differ from the manifest."""
    weights = ClassifierWeights.load(weights_path)
    return PageClassifier(weights, load_embedding(weights.model, model_root))


def load_verifier(*, model_root: Path = DEFAULT_ROOT) -> AllOfClassifiers:
    """The live verifier (:data:`VERIFIER_NAME`); refuses model files that differ from the manifest."""
    weights = [ClassifierWeights.load(path) for path in VERIFIER_WEIGHTS]
    return AllOfClassifiers(VERIFIER_NAME, weights, load_embedding(weights[0].model, model_root))
