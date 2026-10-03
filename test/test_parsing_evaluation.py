"""Evaluation harness (ADR-0013 §8) on synthetic gold labels and pages: the gold-label
format with the ``promo`` mark (Amendment 3) and promo entries (Amendment 5), extraction scores, loss buckets,
corruption injection and the ``apps.menu_pipeline.evaluate`` file side."""

from __future__ import annotations

import json
import sys
from typing import TYPE_CHECKING, Any

import pytest

from apps.menu_pipeline import evaluate
from packages.helios_parsing.evaluation import (
    GoldPage,
    PromoCondition,
    PromoTerm,
    corruption_eval,
    corruption_metrics,
    gold_page,
    gold_rows,
    loss_page,
    match,
    metrics,
    score_page,
)
from packages.helios_parsing.segment import segment
from packages.helios_parsing.validator import Row

if TYPE_CHECKING:
    from pathlib import Path

PAGE = """
<h2>Tacos</h2>
<p>Carne Asada $3.50</p>
<p>Al Pastor $3.75</p>
<p>Fish Taco $4.25</p>
<h2>Plates</h2>
<p>Enchiladas $12.50</p>
<p>Fajitas $15.95</p>
<p>Happy Hour Margarita $5</p>
"""


def _item(
    name: str, block: str, section: str, *amounts: str, promo: bool = False
) -> dict[str, Any]:
    item: dict[str, Any] = {
        "name": name,
        "block": block,
        "section": section,
        "description": None,
        "prices": [{"amount": a, "variant": None} for a in amounts],
    }
    if promo:
        item["promo"] = True
    return item


LABEL: dict[str, Any] = {
    "page_id": "page1",
    "url": "https://example.test/menu",  # extra keys are ignored
    "page_label": "menu",
    "format": "html_list",
    "reviewed": True,
    "items": [
        _item("Carne Asada", "b0002", "Tacos", "3.50"),
        _item("Al Pastor", "b0003", "Tacos", "3.75"),
        _item("Fish Taco", "b0004", "Tacos", "4.25"),
        _item("Enchiladas", "b0006", "Plates", "12.50"),
        _item("Fajitas", "b0007", "Plates", "15.95"),
        _item("Happy Hour Margarita", "b0008", "Plates", "5", promo=True),
    ],
}


def _gold() -> GoldPage:
    return gold_page(LABEL)


def test_gold_page_reads_the_label_format_and_the_promo_mark() -> None:
    page = _gold()
    assert page.scorable
    assert [it.promo for it in page.items] == [False] * 5 + [True]
    assert page.items[0].prices[0].amount == "3.50"
    assert gold_rows(page)[0] == Row("Carne Asada", "3.50", None, "Tacos", "USD", "b0002")
    unpriced = gold_page({**LABEL, "items": [_item("Taco", "b0002", "Tacos")]})
    assert not unpriced.scorable
    assert not gold_page({**LABEL, "reviewed": False}).scorable


PROMO: dict[str, Any] = {
    "text": "Happy Hour Margarita $5",
    "scope": {"kind": "items", "targets": ["Happy Hour Margarita"]},
    "terms": [{"kind": "fixed_price", "value": "5"}],
    "conditions": [{"kind": "hours", "text": "Happy Hour"}],
    "locators": ["blocks:segment-v2:b0008[0:23]"],
}


def test_gold_page_reads_promo_entries_and_refuses_unknown_kinds() -> None:
    assert _gold().promos == ()
    (promo,) = gold_page({**LABEL, "promos": [PROMO]}).promos
    assert (promo.scope, promo.targets) == ("items", ("Happy Hour Margarita",))
    assert promo.terms == (PromoTerm("fixed_price", "5"),)
    assert promo.conditions == (PromoCondition("hours", "Happy Hour"),)
    menu_wide = {**PROMO, "scope": {"kind": "menu"}, "terms": [{"kind": "bogo"}]}
    assert gold_page({**LABEL, "promos": [menu_wide]}).promos[0].targets == ()
    for bad in (
        {**PROMO, "scope": {"kind": "venue"}},
        {**PROMO, "terms": [{"kind": "half_off"}]},
        {**PROMO, "conditions": [{"kind": "weather", "text": "rain"}]},
        {**PROMO, "locators": []},
        {**PROMO, "locators": ["b0008"]},
    ):
        with pytest.raises(ValueError, match="promo"):
            gold_page({**LABEL, "promos": [bad]})
    counts = score_page(gold_page({**LABEL, "promos": [PROMO]}), segment(PAGE), [])
    assert counts["gold_promos"] == 1


def test_match_prefers_same_name_nearest_the_claim_then_a_block_subset() -> None:
    items = gold_page(
        {
            **LABEL,
            "items": [_item("Taco", "b0002", "Lunch", "3"), _item("Taco", "b0020", "Dinner", "4")],
        }
    ).items
    assert match(Row("taco", "4", claimed_block="b0019"), items) == 1
    assert match(Row("Taco", "3"), items) == 0
    assert match(Row("Fish Taco", "3", claimed_block="b0002"), items) == 0, (
        "superset in the claimed block"
    )
    assert match(Row("Burrito", "3", claimed_block="b0002"), items) is None


def test_score_page_counts_recall_usable_accuracy_validator_and_promo() -> None:
    rows = [
        Row("Carne Asada", "3.50", claimed_block="b0002"),  # correct, accepted
        Row("Al Pastor", "3.50", claimed_block="b0003"),  # wrong amount, caught
        Row("Fish Taco", None, claimed_block="b0004"),  # unpriced
        Row("Enchiladas", "12.50", claimed_block="b0006"),  # correct, accepted
        Row("Chile Relleno", "9.00"),  # not on the page: rejected, wrong
        Row("Happy Hour Margarita", "5", claimed_block="b0008"),  # promo stored as a price
    ]
    counts = score_page(_gold(), segment(PAGE), rows)
    assert counts["found_raw"] == 5 and counts["gold_items"] == 6
    assert counts["found_price"] == 3 and counts["gold_prices"] == 6
    assert (counts["accepted_price_exact"], counts["accepted_matched_priced"]) == (3, 3)
    assert (counts["correct"], counts["false_reject"]) == (3, 0)
    assert (counts["wrong"], counts["caught"]) == (2, 2)
    assert counts["unpriced_rows"] == 1
    assert (counts["promo_rows_stored"], counts["gold_promo_items"]) == (1, 1)
    assert metrics(counts) == {
        "item_recall": 5 / 6,
        "item_recall_kept": 5 / 6,
        "usable_prices": 3 / 6,
        "price_accuracy": 1.0,
        "validator_false_reject": 0.0,
        "validator_catch": 1.0,
    }


def test_loss_page_puts_every_gold_price_in_one_bucket() -> None:
    rows = [
        Row("Carne Asada", "3.50", claimed_block="b0002"),
        Row("Al Pastor", "3.50", claimed_block="b0003"),
        Row("Fish Taco", None, claimed_block="b0004"),
        Row("Enchiladas", "12.50", variant="Large", claimed_block="b0006"),
        Row("Happy Hour Margarita", "5", claimed_block="b0008"),
    ]
    assert dict(loss_page(_gold(), segment(PAGE), rows)) == {
        "accepted": 2,
        "wrong_amount": 1,
        "row_unpriced": 1,
        "not_accepted:variant_not_grounded": 1,
        "item_missed": 1,
    }


OTHER_LABEL: dict[str, Any] = {
    **LABEL,
    "page_id": "page2",
    "items": [
        _item("Pho Tai", "b0001", "Soups", "11.00"),
        _item("Banh Mi", "b0002", "Sandwiches", "8.00"),
    ],
}
OTHER_PAGE = "<p>Pho Tai $11.00</p><p>Banh Mi $8.00</p>"


def test_corruption_eval_is_seeded_and_catches_injected_errors() -> None:
    pages = [(_gold(), segment(PAGE)), (gold_page(OTHER_LABEL), segment(OTHER_PAGE))]
    counts = corruption_eval(pages)
    assert counts == corruption_eval(pages), "one seed, one result"
    assert counts["correct_rows"] == 8 and counts["false_reject"] == 0
    kinds = {k.split(":", 1)[1] for k in counts if k.startswith("n:")}
    assert kinds == {"mutated_price", "swapped_prices", "invented_item", "other_section_price"}
    assert corruption_metrics(counts) == {"false_reject": 0.0, "catch": 1.0}


def _write_fixture(root: Path) -> tuple[Path, Path]:
    data, labels = root / "data", root / "labels"
    (data / "pages").mkdir(parents=True)
    (data / "extract" / "t1").mkdir(parents=True)
    labels.mkdir()
    (data / "pages" / "page1.html").write_text(PAGE, encoding="utf-8")
    (labels / "page1.json").write_text(json.dumps(LABEL), encoding="utf-8")
    raw = json.dumps(
        {
            "sections": [
                {
                    "section": "Tacos",
                    "items": [
                        {"b": "b0002", "n": "Carne Asada", "p": "3.50"},
                        {"b": "b0003", "n": "Al Pastor", "p": "3.75"},
                    ],
                }
            ]
        },
        separators=(",", ":"),
    )
    record = {"page_id": "page1", "chunks": [{"raw": raw}, {"raw": '{"sections":[{"section":"Pl'}]}
    (data / "extract" / "t1" / "page1.json").write_text(json.dumps(record), encoding="utf-8")
    return data, labels


def test_evaluate_cli_scores_saved_output(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    data, labels = _write_fixture(tmp_path)
    splits = tmp_path / "splits.json"
    splits.write_text(json.dumps({"none": [], "one": ["page1"]}), encoding="utf-8")
    assert list(evaluate.load_gold(labels, splits, "none")) == []

    common = [
        "--data",
        str(data),
        "--labels",
        str(labels),
        "--splits",
        str(splits),
        "--split",
        "one",
    ]
    monkeypatch.setattr(sys, "argv", ["evaluate", "compare", "t1", *common])
    evaluate.main()
    out = capsys.readouterr().out
    assert "pages=1 (of 1 gold)" in out
    assert "t1                 0.333  0.333  1.000  0.000    n/a      2     0" in out

    monkeypatch.setattr(sys, "argv", ["evaluate", "loss", "t1", "--pages", *common])
    evaluate.main()
    out = capsys.readouterr().out
    assert "item_missed                              4" in out and "page1 n=   6 lost=   4" in out

    monkeypatch.setattr(sys, "argv", ["evaluate", "corrupt", *common])
    evaluate.main()
    assert "false_reject=0 rate=0.000" in capsys.readouterr().out
