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
    VERIFIER_NAME,
    VERIFIER_WEIGHTS,
    AllOfClassifiers,
    ClassifierWeights,
    PageClassifier,
    load_embedding,
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
from packages.helios_parsing.page_features import FEATURE_NAMES, PAGE_SIGNAL_NAMES, page_signals
from packages.helios_parsing.segment import segment

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
    assert (weights.version, weights.model) == ("classifier-v2", "potion-base-8M")
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


def test_v3_weights_name_the_page_signals() -> None:
    """ADR-0013 Amendment 24: classifier-v3 adds the generic page signals."""
    from apps.menu_pipeline.classifier import WEIGHTS_PATH

    assert WEIGHTS_PATH.name == "page_classifier_v2.json"
    v3 = ClassifierWeights.load(WEIGHTS_PATH.with_name("page_classifier_v3.json"))
    assert (v3.version, v3.model) == ("classifier-v3", "potion-base-8M")
    assert v3.features == FEATURE_NAMES + PAGE_SIGNAL_NAMES
    assert len(v3.coef) == 256 + len(FEATURE_NAMES) + len(PAGE_SIGNAL_NAMES)
    assert round(v3.threshold, 3) == 0.674  # noqa: PLR2004 - the P5-28 survey's value
    assert ClassifierWeights.load().features == FEATURE_NAMES


def test_the_live_verifier_is_classifier_v2_and_v3() -> None:
    """Amendment 27: a page must pass both; the new name re-verifies every saved URL."""
    assert VERIFIER_NAME == "classifier-v2+v3"
    v2, v3 = (ClassifierWeights.load(path) for path in VERIFIER_WEIGHTS)
    assert (v2.version, v3.version) == ("classifier-v2", "classifier-v3")
    assert v2.model == v3.model


def _signal_weights(threshold: float) -> ClassifierWeights:
    """A v3-shaped classifier that reads one page signal: add-to-cart markup is a non-menu."""
    names = FEATURE_NAMES + PAGE_SIGNAL_NAMES
    size = 2 + len(names)
    coef = [0.0] * size
    coef[2 + names.index("cart_markup")] = -4.0
    return ClassifierWeights(
        version="classifier-signals",
        model="potion-base-8M",
        mean=(0.0,) * size,
        scale=(1.0,) * size,
        coef=tuple(coef),
        intercept=1.0,
        threshold=threshold,
        features=names,
    )


def test_all_of_classifiers_accepts_a_page_only_when_both_do() -> None:
    calls: list[int] = []

    def embed(texts: Sequence[str]) -> list[list[float]]:
        calls.append(len(texts))
        return _embed(texts)

    first, second = _weights(), _signal_weights(threshold=0.6)
    both = AllOfClassifiers("classifier-a+b", [first, second], embed)
    shop = _MENU + '<button class="add-to-cart">Add</button>'
    alone = [PageClassifier(w, _embed) for w in (first, second)]

    assert both.name == "classifier-a+b"
    for html in (_MENU, shop, _HOME):
        expected = tuple(c.probability(html, "https://k.com/dinner") for c in alone)
        assert both.probabilities(html, "https://k.com/dinner") == pytest.approx(expected)
        assert both.probability(html, "https://k.com/dinner") == pytest.approx(min(expected))
        assert both.is_menu(html, "https://k.com/dinner", trust_path=True) == all(
            c.is_menu(html, "https://k.com/dinner", trust_path=False) for c in alone
        )
    # each classifier alone: the menu passes both, the shop only the first, home neither
    assert both.is_menu(_MENU, "https://k.com/dinner", trust_path=False)
    assert alone[0].is_menu(shop, "https://k.com/dinner", trust_path=False)
    assert not both.is_menu(shop, "https://k.com/dinner", trust_path=False)
    assert not both.is_menu(_HOME, "https://k.com/about", trust_path=False)
    assert set(calls) == {1}  # one embedding per page, shared by both classifiers


def test_all_of_classifiers_needs_one_embedding_model() -> None:
    other = replace(_signal_weights(0.5), model="another-embedding")
    with pytest.raises(ValueError, match="one embedding model"):
        AllOfClassifiers("x", [_weights(), other], _embed)


def test_weights_with_other_page_signals_are_refused(tmp_path: Path) -> None:
    from apps.menu_pipeline.classifier import WEIGHTS_PATH

    raw = json.loads(WEIGHTS_PATH.with_name("page_classifier_v3.json").read_text())
    raw["page_signals"] = raw["page_signals"][::-1]
    path = tmp_path / "weights.json"
    path.write_text(json.dumps(raw))
    with pytest.raises(ValueError, match="page signals"):
        ClassifierWeights.load(path)


def test_scorer_inputs_follow_the_weights_feature_list() -> None:
    names = FEATURE_NAMES + PAGE_SIGNAL_NAMES
    text, plain = page_vector_inputs(_MENU, "https://k.com/dinner", names)
    _, layout = page_vector_inputs(_MENU, "https://k.com/dinner")
    assert plain == [*layout, *page_signals(_MENU, "https://k.com/dinner", segment(_MENU))]
    assert text.startswith("Menu\n/dinner")
    size = 2 + len(names)
    cart = [0.0] * size
    cart[2 + names.index("cart_markup")] = 4.0
    weights = replace(
        _weights(), mean=(0.0,) * size, scale=(1.0,) * size, coef=tuple(cart), features=names
    )
    classifier = PageClassifier(weights, _embed)
    shop = _MENU + '<button class="add-to-cart">Add</button>'
    assert classifier.probability(_MENU, "https://k.com/") == pytest.approx(1 / (1 + math.exp(1)))
    assert classifier.probability(shop, "https://k.com/") == pytest.approx(1 / (1 + math.exp(-3)))


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
    manifest = load_manifest()
    assert set(manifest) == {"potion-base-8M", "Qwen3-4B-Instruct-2507-Q4_0"}
    for spec in manifest.values():
        assert spec.licence in {"MIT", "Apache-2.0"}
        assert len(spec.revision) == 40  # a commit, never a branch  # noqa: PLR2004
        assert all(len(file.sha256) == 64 and file.size > 0 for file in spec.files)  # noqa: PLR2004
        assert spec.url(spec.files[0]).startswith(f"{spec.source}/resolve/{spec.revision}/")
    classifier = manifest["potion-base-8M"]
    assert classifier.embedding_model == "minishlab/potion-base-8M"
    assert {file.name for file in classifier.files} >= {"model.onnx", "tokenizer.json"}


def test_shipped_manifest_pins_the_spike_extraction_model() -> None:
    """ADR-0013 §1: the spike's Q4_0 GGUF, byte for byte, and not an embedding model."""
    spec = load_manifest()["Qwen3-4B-Instruct-2507-Q4_0"]
    assert spec.embedding_model is None
    assert spec.files == (
        ModelFile(
            "Qwen3-4B-Instruct-2507-Q4_0.gguf",
            "e0ba675d86ab277c61701c6793659b2ae801d95e3be791464c321e6fbf613be2",
            2_375_773_280,
        ),
    )
    assert spec.url(spec.files[0]) == (
        "https://huggingface.co/unsloth/Qwen3-4B-Instruct-2507-GGUF/resolve/"
        "a06e946bb6b655725eafa393f4a9745d460374c9/Qwen3-4B-Instruct-2507-Q4_0.gguf"
    )
    with pytest.raises(ValueError, match="not an embedding model"):
        load_embedding("Qwen3-4B-Instruct-2507-Q4_0")


def test_manifest_entry_without_embedding_model(tmp_path: Path) -> None:
    body = b"GGUF weights"
    manifest = tmp_path / "models.yaml"
    manifest.write_text(
        "tiny-llm:\n"
        "  licence: Apache-2.0\n"
        "  source: https://models.example/org/tiny-llm/\n"
        "  revision: abc123\n"
        "  files:\n"
        "    tiny.gguf:\n"
        f"      sha256: {hashlib.sha256(body).hexdigest()}\n"
        f"      size: {len(body)}\n",
        encoding="utf-8",
    )
    (spec,) = load_manifest(manifest).values()
    assert (spec.name, spec.embedding_model, spec.licence) == ("tiny-llm", None, "Apache-2.0")
    assert spec.url(spec.files[0]) == "https://models.example/org/tiny-llm/resolve/abc123/tiny.gguf"
    (tmp_path / "tiny-llm").mkdir()
    (tmp_path / "tiny-llm" / "tiny.gguf").write_bytes(b"GGUF weightz")
    with pytest.raises(ModelFileError, match="does not match"):
        verified_model_dir(spec, tmp_path)
    (tmp_path / "tiny-llm" / "tiny.gguf").write_bytes(body)
    assert verified_model_dir(spec, tmp_path) == tmp_path / "tiny-llm"
