"""Course labellers (ADR-0016 §4, slice 1b): the lexicon's normalizer and resolution, the
checked-in lexicon, arm B's weights file and scoring, predictions, and the owner's
review TSV (``course_eval confirm``). No model files: arm B is scored with synthetic
weights and a fake embedding."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import pytest

from apps.menu_pipeline import course_eval as cli
from apps.menu_pipeline.course_labellers import (
    LEXICON_PATH,
    CourseWeights,
    ModelLabeller,
    predict_rows,
    section_text,
)
from packages.helios_parsing.course_eval import (
    LabelSetError,
    Section,
    draw_label_set,
    exclusions_digest,
    split_of,
)
from packages.helios_parsing.course_lexicon import Lexicon, normalize

if TYPE_CHECKING:
    from pathlib import Path


def _lexicon(tmp_path: Path, rules: dict[str, list[str]]) -> Lexicon:
    path = tmp_path / "lexicon.json"
    path.write_text(json.dumps({"version": "lex-test", "rules": rules}), encoding="utf-8")
    return Lexicon.load(path)


def test_normalize_folds_accents_apostrophes_punctuation_and_plurals() -> None:
    assert normalize("Entrées") == ("entree",)
    assert normalize("Kid's  Menu!") == ("kid", "menu")
    assert normalize("Soups & Salads") == ("soup", "salad")
    assert normalize("Glass") == ("glass",)  # a double s is no plural


def test_longer_phrases_win_and_resolution_follows_the_guide(tmp_path: Path) -> None:
    lexicon = _lexicon(
        tmp_path,
        {
            "other": ["extra", "family"],
            "kids": ["kids"],
            "non_alcoholic": ["zero proof"],
            "alcohol": ["cocktail", "beer"],
            "drink": ["drink"],
            "breakfast": ["brunch", "breakfast"],
            "dessert": ["dessert", "ice cream"],
            "side": ["side", "extra side"],
            "appetizer": ["soup"],
            "entree": ["taco", "cream"],
        },
    )
    assert lexicon.version.startswith("lex-test@")
    assert lexicon.label("Extra Sides") == "side"  # "extra side" uses both tokens
    assert lexicon.label("Extras") == "other"
    assert lexicon.label("Ice Cream") == "dessert"  # not the shorter "cream"
    assert lexicon.label("Family Tacos") == "other"  # other wins outright
    assert lexicon.label("Kids Drinks") == "kids"
    assert lexicon.label("Zero Proof Cocktails") == "drink"
    assert lexicon.label("Brunch Cocktails") == "alcohol"  # breakfast yields to a drink word
    assert lexicon.label("Breakfast Sides") == "breakfast"
    assert lexicon.label("Sides & Desserts") is None  # a mixed heading abstains
    assert lexicon.label("Drinks & Beer") is None
    assert lexicon.label("Featured Items") is None
    assert lexicon.label("Soups & Soups") == "appetizer"


def test_a_lexicon_refuses_unknown_courses_and_conflicting_phrases(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="not a course"):
        _lexicon(tmp_path, {"mains": ["entree"]})
    with pytest.raises(ValueError, match="two courses"):
        _lexicon(tmp_path, {"side": ["Sides"], "other": ["side"]})


def test_the_checked_in_lexicon_loads_and_reads_plain_names() -> None:
    lexicon = Lexicon.load(LEXICON_PATH)
    assert lexicon.version.startswith("course-lexicon-v1@")
    expected = {
        "Appetizers": "appetizer",
        "Entrées": "entree",
        "Desserts": "dessert",
        "Kids Menu": "kids",
        "Draft Beer": "alcohol",
        "Hot Beverages": "drink",
        "Breakfast Tacos": "breakfast",
        "Sides": "side",
        "Add-Ons": "other",
        "Menu": None,
    }
    assert {name: lexicon.label(name) for name in expected} == expected


def _weights(tmp_path: Path, **change: Any) -> Path:
    raw = {
        "version": "cl-test",
        "model": "potion-base-8M",
        "classes": ["drink", "entree"],
        "mean": [0.0, 0.0],
        "scale": [1.0, 1.0],
        "coef": [[2.0, 0.0], [0.0, 2.0]],
        "intercept": [0.0, 0.0],
        "threshold": 0.8,
        **change,
    }
    path = tmp_path / "weights.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    return path


def test_weights_score_softmax_and_abstain_below_the_threshold(tmp_path: Path) -> None:
    weights = CourseWeights.load(_weights(tmp_path))
    assert weights.version.startswith("cl-test@")
    course, confidence = weights.label([2.0, 0.0])  # e^4 / (e^4 + 1)
    assert course == "drink" and confidence == pytest.approx(0.98201, abs=1e-5)
    assert weights.label([0.1, 0.0])[0] is None  # 0.55 < 0.8
    assert sum(weights.probabilities([0.3, -1.0])) == pytest.approx(1.0)
    with pytest.raises(ValueError, match="wrong model"):
        weights.probabilities([1.0])
    labeller = ModelLabeller(weights, lambda texts: [[0.0, 3.0] for _ in texts])
    assert labeller.predict([("Mains",)])[0][0] == "entree"


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"classes": ["drink", "mains"]}, "outside the vocabulary"),
        ({"intercept": [0.0]}, "differ in length"),
        ({"coef": [[1.0], [1.0]]}, "differ in length"),
    ],
)
def test_weights_refuse_a_malformed_file(
    tmp_path: Path, change: dict[str, Any], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        CourseWeights.load(_weights(tmp_path, **change))


def test_section_text_and_lexicon_predictions() -> None:
    assert section_text(("Drinks", "Beer")) == "Drinks > Beer"
    rows = predict_rows("lexicon", [("Desserts",), ("Menu",)], ["v1:b1:a", "v1:b2:b"])
    assert [(r["course"], r["confidence"]) for r in rows] == [("dessert", 1.0), (None, None)]
    assert len({r["labeller"] for r in rows}) == 1


# --- the owner's review (``course_eval confirm``) ---------------------------------------------


def _labelled_set(tmp_path: Path) -> tuple[Path, Path, list[Section]]:
    candidates = [
        Section(f"gers-{v}", v, f"v{v}:b1:x", f"Name {v}", (f"Name {v}",), ("Dish", "Plate"), 4)
        for v in range(40)
    ]
    manifest, rows = draw_label_set(
        candidates, frozenset(), set_name="s", seed=5, venues=40, method_version="m"
    )
    directory = tmp_path / "s"
    directory.mkdir()
    (directory / "manifest.json").write_text(json.dumps(manifest.to_json()), encoding="utf-8")
    labelled = [
        Section(
            **{
                **r.to_json(),
                "name_path": r.name_path,
                "items": r.items,
                "agent_label": "entree",
                "label": "entree",
                "labeller": "agent:t",
            }
        )
        for r in rows
    ]
    with (directory / "sections.jsonl").open("w", encoding="utf-8") as handle:
        for row in labelled:
            handle.write(json.dumps(row.to_json()) + "\n")
    exclude = tmp_path / "exclude.txt"
    exclude.write_text("", encoding="utf-8")
    assert manifest.exclusions_sha256 == exclusions_digest(frozenset())
    return directory, exclude, labelled


def test_confirm_applies_the_review_to_pending_disagreements_only(tmp_path: Path) -> None:
    directory, exclude, rows = _labelled_set(tmp_path)
    test = [r for r in rows if r.split == "test" and split_of(5, r.venue) == "test"]
    a, b, c = test[0], test[1], test[2]
    predictions = tmp_path / "arm.jsonl"
    with predictions.open("w", encoding="utf-8") as handle:
        for row in rows:
            course = {a.section_key: "drink", b.section_key: "side", c.section_key: "side"}.get(
                row.section_key, "entree"
            )
            handle.write(
                json.dumps(
                    {
                        "section_key": row.section_key,
                        "course": course,
                        "confidence": 1.0,
                        "labeller": "arm",
                    }
                )
                + "\n"
            )
    review = tmp_path / "review.tsv"
    common = ["--labels", str(directory), "--exclude", str(exclude)]
    assert cli.main(["disagreements", *common, "--review-out", str(review), str(predictions)]) == 0
    lines = review.read_text(encoding="utf-8").splitlines()
    assert lines[0].split("\t") == list(cli.REVIEW_COLUMNS) and len(lines) == 4
    filled = [lines[0]]
    for line in lines[1:]:
        key = line.split("\t")[0]
        decision = {a.section_key: "drink", b.section_key: "="}.get(key, "")
        filled.append(line + decision)  # the confirmed column is last and empty
    review.write_text("\n".join(filled) + "\n", encoding="utf-8")
    assert cli.main(["confirm", *common, "--review", str(review), str(predictions)]) == 0
    after = {r.section_key: r for r in cli.load_label_set(directory, frozenset())[1]}
    assert (after[a.section_key].label, after[a.section_key].agent_label) == ("drink", "entree")
    assert after[a.section_key].owner_confirmed and after[b.section_key].owner_confirmed
    assert after[b.section_key].label == "entree"
    assert not after[c.section_key].owner_confirmed  # left blank: still pending

    review.write_text(f"section_key\tconfirmed\n{rows[0].section_key}x\tside\n", encoding="utf-8")
    assert cli.main(["confirm", *common, "--review", str(review), str(predictions)]) == 2
    review.write_text(f"section_key\tconfirmed\n{c.section_key}\tmains\n", encoding="utf-8")
    with pytest.raises(LabelSetError, match="not a course"):
        cli.confirm_rows(list(after.values()), {c.section_key}, {c.section_key: "mains"})
