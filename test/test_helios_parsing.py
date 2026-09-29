"""Pure parsing stages: segmentation, text hash and the classifier's features (ADR-0013 §1-2, §5)."""

from __future__ import annotations

import math
from decimal import Decimal

from packages.helios_parsing.page_features import FEATURE_NAMES, layout_features, page_text
from packages.helios_parsing.prices import price_tokens
from packages.helios_parsing.segment import SEGMENTER_VERSION, segment, text_hash

_PAGE = """<html><head><title>Kitchen  Menu</title><script>var x = "$99.99";</script></head>
<body><nav><a href="/">Home</a> <a href="/menu">Menu</a></nav>
<h1>Our Menu</h1>
<div>Carne Asada Taco</div><div>$3.50</div>
<p>Queso ....... $7.5</p>
<p>Wine 11 / 44</p><p>11 / 44</p>
<p>Open 7 days a week</p>
<footer>Call 512-555-0100</footer></body></html>"""


def test_segment_splits_blocks_and_flags_headings_and_chrome() -> None:
    blocks = segment(_PAGE)
    texts = [block.text for block in blocks]
    assert "Carne Asada Taco" in texts and "$3.50" in texts
    assert not [text for text in texts if "99.99" in text], "scripts are skipped"
    assert not [text for text in texts if "Kitchen" in text], "the <title> is not body text"
    heading = next(block for block in blocks if block.text == "Our Menu")
    assert heading.heading and not heading.in_chrome
    assert all(block.in_chrome for block in blocks if block.text in {"Home", "Menu"})
    assert [block.id for block in blocks] == [f"b{n:04d}" for n in range(1, len(blocks) + 1)]


def test_price_tokens_read_money_one_decimal_pairs_and_trailing_integers() -> None:
    blocks = segment(_PAGE)
    by_text = dict(zip((b.text for b in blocks), price_tokens(blocks), strict=True))
    assert [t.amount for t in by_text["$3.50"]] == [Decimal("3.50")]
    assert [t.amount for t in by_text["Queso ....... $7.5"]] == [Decimal("7.50")]
    assert [(t.amount, t.kind) for t in by_text["11 / 44"]] == [
        (Decimal(11), "bare"),
        (Decimal(44), "bare"),
    ]
    assert [t.amount for t in by_text["Wine 11 / 44"]] == [Decimal(44)], "only a last integer"
    assert by_text["Open 7 days a week"] == []


def test_page_text_puts_title_path_and_headings_first_without_chrome() -> None:
    text = page_text(_PAGE, "https://k.com/menu", segment(_PAGE))
    title, path, heads, body = text.split("\n", 3)
    assert (title, path, heads) == ("Kitchen Menu", "/menu", "Our Menu")
    assert body.startswith("Our Menu | Carne Asada Taco | $3.50")
    assert "Home" not in body and "512-555" not in body


def test_layout_features_are_the_seven_named_values() -> None:
    blocks = segment(_PAGE)
    body = [block for block in blocks if not block.in_chrome]
    features = layout_features(blocks, heuristic_signal=True)
    assert len(features) == len(FEATURE_NAMES) == 7  # noqa: PLR2004
    values = dict(zip(FEATURE_NAMES, features, strict=True))
    assert values["log_body_blocks"] == math.log1p(len(body))
    assert values["log_money_tokens"] == math.log1p(2)  # $3.50 and $7.5
    assert values["log_priced_blocks"] == math.log1p(4)
    assert values["heuristic_menu_signal"] == 1.0
    assert layout_features([], heuristic_signal=False) == [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]


def test_segment_skips_dialogs_but_not_other_hidden_content() -> None:
    """A consent dialog is not page content (S6f: Toast's rendered pages start with one);
    a hidden tab panel is, since tabbed menus hide every panel but one."""
    html = (
        '<body><div role="alertdialog" aria-hidden="true"><h2>Manage your consent</h2>'
        "<p>Essential cookies</p><img alt='x'></div>"
        '<div aria-modal="true"><p>Sign in</p></div>'
        '<div role="dialog"><p>Item details</p></div>'
        '<section aria-hidden="true" style="display:none"><p>Tacos $3.50</p></section>'
        "<h1>Menu</h1><p>Burrito $9.00</p></body>"
    )
    assert [block.text for block in segment(html)] == ["Tacos $3.50", "Menu", "Burrito $9.00"]


def test_text_hash_ignores_markup_and_follows_text_and_structure() -> None:
    """ADR-0013 §5: the change signal is the segmented text, not the raw body."""
    page = "<body><h2>Tacos</h2><div>Carne Asada</div><div>$3.50</div><footer>Hours</footer></body>"
    churned = (
        '<body class="v9"><script>var csrf = "a1b2";</script><h2 id="t">Tacos</h2>'
        '<div class="x"><span>Carne   Asada</span></div><div>$3.50</div><footer>Hours</footer></body>'
    )
    base = text_hash(segment(page))
    assert base.startswith("sha256:") and len(base) == len("sha256:") + 64
    assert text_hash(segment(churned)) == base
    assert text_hash(segment(page.replace("$3.50", "$3.75"))) != base, "a price change"
    assert text_hash(segment(page.replace("h2", "p"))) != base, "a heading became body text"
    assert text_hash(segment(page.replace("Hours", "Hours 9-5"))) != base, "chrome text counts"
    decomposed = page.replace("Carne", "Café")  # "é" as e + combining accent
    assert text_hash(segment(decomposed)) == text_hash(segment(page.replace("Carne", "Café")))
    assert SEGMENTER_VERSION == "segment-v2"
