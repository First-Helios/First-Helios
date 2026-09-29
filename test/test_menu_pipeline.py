"""Page classifier runtime and model files (ADR-0013 §1, §3); no model, no network."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import replace
from typing import TYPE_CHECKING

import httpx
import pytest

from apps.menu_pipeline.classifier import (
    ClassifierWeights,
    PageClassifier,
    page_vector_inputs,
)
from apps.menu_pipeline.models import (
    ModelFile,
    ModelFileError,
    ModelSpec,
    download,
    load_manifest,
    verified_model_dir,
)
from packages.helios_parsing.page_features import FEATURE_NAMES

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

_MENU = "<title>Menu</title><h1>Dinner</h1><p>Taco $3.50</p><p>Queso $7.00</p>"
_HOME = "<title>Welcome</title><h1>About us</h1><p>Family owned since 1986.</p>"


def _embed(texts: Sequence[str]) -> list[list[float]]:
    """A two-dimensional fake embedding: does the text say "menu"?"""
    return [[1.0 if "menu" in text.lower() else 0.0, 0.5] for text in texts]


def _weights(threshold: float = 0.5) -> ClassifierWeights:
    size = 2 + len(FEATURE_NAMES)
    return ClassifierWeights(
        version="classifier-test",
        model="potion-base-8M",
        mean=(0.5,) * size,
        scale=(0.5,) * size,
        coef=(3.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0),
        intercept=-1.0,
        threshold=threshold,
    )


def test_shipped_weights_match_this_code() -> None:
    weights = ClassifierWeights.load()
    assert (weights.version, weights.model) == ("classifier-v1", "potion-base-8M")
    assert len(weights.coef) == 256 + len(FEATURE_NAMES)  # potion-base-8M is 256-d
    assert 0.0 < weights.threshold < 1.0
    assert weights.model in load_manifest()


def test_weights_with_other_layout_features_are_refused(tmp_path: Path) -> None:
    from apps.menu_pipeline.classifier import WEIGHTS_PATH

    raw = json.loads(WEIGHTS_PATH.read_text())
    raw["layout_features"] = raw["layout_features"][:-1]
    path = tmp_path / "weights.json"
    path.write_text(json.dumps(raw))
    with pytest.raises(ValueError, match="layout features"):
        ClassifierWeights.load(path)


def test_classifier_scores_a_standardized_logistic_regression() -> None:
    classifier = PageClassifier(_weights(), _embed)
    text, layout = page_vector_inputs(_MENU, "https://k.com/dinner")
    features = [*_embed([text])[0], *layout]
    weights = _weights()
    score = weights.intercept + sum(
        c * (v - m) / s
        for v, m, s, c in zip(features, weights.mean, weights.scale, weights.coef, strict=True)
    )
    assert classifier.probability(_MENU, "https://k.com/dinner") == pytest.approx(
        1 / (1 + math.exp(-score))
    )
    assert classifier.name == "classifier-test"
    assert classifier.is_menu(_MENU, "https://k.com/dinner", trust_path=False)
    assert not classifier.is_menu(_HOME, "https://k.com/about", trust_path=True)


def test_classifier_threshold_decides_and_a_wrong_embedding_size_is_an_error() -> None:
    strict = PageClassifier(_weights(threshold=0.9999), _embed)
    assert not strict.is_menu(_MENU, "https://k.com/dinner", trust_path=False)
    wrong = PageClassifier(_weights(), lambda texts: [[1.0] for _ in texts])
    with pytest.raises(ValueError, match="wrong embedding model"):
        wrong.probability(_MENU, "https://k.com/dinner")


def test_extreme_scores_do_not_overflow() -> None:
    low = replace(_weights(), intercept=-5000.0)
    assert PageClassifier(low, _embed).probability(_MENU, "https://k.com/") == 0.0


def _spec(files: dict[str, bytes]) -> ModelSpec:
    return ModelSpec(
        name="tiny",
        embedding_model="org/tiny",
        source="https://models.example/org/tiny",
        revision="abc123",
        licence="MIT",
        files=tuple(
            ModelFile(name, hashlib.sha256(body).hexdigest(), len(body))
            for name, body in files.items()
        ),
    )


def test_verified_model_dir_refuses_missing_or_changed_files(tmp_path: Path) -> None:
    spec = _spec({"model.onnx": b"weights", "tokenizer.json": b"{}"})
    with pytest.raises(ModelFileError, match="missing"):
        verified_model_dir(spec, tmp_path)
    (tmp_path / "tiny").mkdir()
    (tmp_path / "tiny" / "model.onnx").write_bytes(b"weights")
    (tmp_path / "tiny" / "tokenizer.json").write_bytes(b"[]")
    with pytest.raises(ModelFileError, match="does not match"):
        verified_model_dir(spec, tmp_path)
    (tmp_path / "tiny" / "tokenizer.json").write_bytes(b"{}")
    assert verified_model_dir(spec, tmp_path) == tmp_path / "tiny"


def test_download_keeps_only_files_matching_the_manifest(tmp_path: Path) -> None:
    served = {"model.onnx": b"weights", "tokenizer.json": b"{}"}
    requested: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requested.append(request.url.path)
        return httpx.Response(200, content=served[request.url.path.rsplit("/", 1)[1]])

    spec = _spec({"model.onnx": b"weights", "tokenizer.json": b"{}"})
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        assert download(spec, tmp_path, client=client) == tmp_path / "tiny"
        assert requested == [
            "/org/tiny/resolve/abc123/model.onnx",
            "/org/tiny/resolve/abc123/tokenizer.json",
        ]
        download(spec, tmp_path, client=client)
    assert len(requested) == 2, "files that already match are not fetched again"  # noqa: PLR2004
    assert (tmp_path / "tiny" / "model.onnx").stat().st_mode & 0o777 == 0o644  # noqa: PLR2004

    served["model.onnx"] = b"tampered"
    (tmp_path / "tiny" / "model.onnx").unlink()
    with (
        httpx.Client(transport=httpx.MockTransport(handle)) as client,
        pytest.raises(ModelFileError, match="does not match"),
    ):
        download(spec, tmp_path, client=client)
    assert sorted(p.name for p in (tmp_path / "tiny").iterdir()) == ["tokenizer.json"]


def test_shipped_manifest_pins_every_file() -> None:
    (spec,) = load_manifest().values()
    assert spec.licence == "MIT"
    assert {file.name for file in spec.files} >= {"model.onnx", "tokenizer.json"}
    assert all(len(file.sha256) == 64 and file.size > 0 for file in spec.files)  # noqa: PLR2004
    assert spec.url(spec.files[0]).startswith(f"{spec.source}/resolve/{spec.revision}/")
