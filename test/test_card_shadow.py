import json
from pathlib import Path

from apps.menu_pipeline.card_shadow import benchmark, inspect_cards, price_matches
from packages.helios_parsing.evaluation import gold_page


def test_simple_cards_have_local_evidence_and_variants_stay_in_the_residual() -> None:
    html = (Path(__file__).parent / "fixtures/menu-review/pages/cards.html").read_text()
    result = inspect_cards(html)
    assert [(v["row"]["item"], v["row"]["amount"]) for v in result["rows"]] == [
        ("Bean Taco", "3.50"),
        ("Potato Taco", "4.00"),
    ]
    (chunk,) = result["residual_chunks"]
    assert all(text in chunk for text in ("Lunch", "Lime Soda", "Small", "Large"))
    assert "Bean Taco" not in chunk


def test_frozen_corpus_counts() -> None:
    folder = Path(__file__).parent / "fixtures/menu-review"
    assert benchmark(folder)["totals"] == {
        "expected": 4,
        "proposed": 2,
        "matched": 2,
        "full_chunks": 1,
        "residual_chunks": 1,
    }


def test_paired_score_counts_duplicate_prices_and_missing_variants_separately() -> None:
    label = gold_page(
        json.loads((Path(__file__).parent / "fixtures/menu-review/labels/cards.json").read_text())
    )
    assert price_matches(
        label,
        [
            ("Bean Taco", None, "3.5"),
            ("bean taco", None, "3.50"),
            ("Lime Soda", "large", "3.00"),
        ],
    ) == {"proposed": 3, "matched": 2, "expected": 4, "omitted": 2, "unmatched": 1}
