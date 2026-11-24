from pathlib import Path

from apps.menu_pipeline.card_shadow import benchmark, inspect_cards


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
