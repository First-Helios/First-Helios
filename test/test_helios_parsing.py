"""Pure parsing stages: segmentation, text hash and the classifier's features (ADR-0013 §1-2, §5)."""

from __future__ import annotations

import math
from decimal import Decimal

from packages.helios_parsing.page_features import (
    FEATURE_NAMES,
    PAGE_SIGNAL_NAMES,
    layout_features,
    page_signals,
    page_text,
)
from packages.helios_parsing.prices import price_tokens, price_tokens_v4, read_amount, read_money
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


def _read(text: str) -> list[tuple[str, Decimal]]:
    return [(text[start:end], amount) for start, end, amount in read_money(text)]


def test_v5_reader_reads_currency_words_cents_and_glued_prices() -> None:
    assert _read("12.5 USD") == [("12.5 USD", Decimal("12.50"))]
    assert _read("USD 12") == [("USD 12", Decimal("12.00"))]
    assert _read("Price: 7.5 Dollars") == [("7.5 Dollars", Decimal("7.50"))]
    assert _read("From4.5 USD") == [("4.5 USD", Decimal("4.50"))], "the glued word is outside"
    assert _read("Extra $.40") == [("$.40", Decimal("0.40"))]
    assert _read("cheddar 50¢ each | bacon .65¢") == [
        ("50¢", Decimal("0.50")),
        (".65¢", Decimal("0.65")),
    ]
    assert _read("Patacones_12 Linguini_19.5") == [
        ("12", Decimal("12.00")),
        ("19.5", Decimal("19.50")),
    ], "the underscore is outside the span"
    assert _read("$12 USD") == [("$12", Decimal("12.00"))], "one price, not two"
    assert _read("$ 5.99 | 12,50") == [("$ 5.99", Decimal("5.99")), ("12,50", Decimal("12.50"))]


def test_v5_reader_leaves_unmarked_one_decimal_numbers() -> None:
    for text in ("6.2", "7.5 % ABV", "Serving Size: 0.5 pounds", "WCAG 2.1", "Fat: 2.5g"):
        assert read_money(text) == [], text


def test_v5_read_amount_is_one_printed_price_or_none() -> None:
    assert read_amount(" 12.5 USD ") == Decimal("12.50")
    assert read_amount("$.40") == Decimal("0.40")
    assert read_amount("12") is None, "a bare integer is not a marked price"
    assert read_amount("Large $5") is None


def test_v4_tokens_stay_frozen_for_the_classifier() -> None:
    blocks = segment("<p>Veg Fried Rice</p><p>12.5 USD</p><p>Queso $7.5</p>")
    assert [len(t) for t in price_tokens(blocks)] == [0, 1, 1]
    assert [len(t) for t in price_tokens_v4(blocks)] == [0, 0, 1], "classifier-v2 features"


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


_SHOP = """<html><head><title>Menu</title>
<meta property="og:type" content="product.item">
<script type="application/ld+json">{"@type": ["BlogPosting", "Thing"]}</script></head>
<body><nav><a href="/menu/lunch">Lunch</a> <a href="/menu/dinner/">Dinner</a></nav>
<h1>Our Menu</h1>
<p>Taco $3.50 and queso $7.00</p>
<p><a href="https://other.com/menu/x">Elsewhere</a> plain text here</p>
<button class="btn add-to-cart">Order</button>
<article><time>Today</time></article></body></html>"""


def test_page_signals_read_links_markup_and_prices() -> None:
    blocks = segment(_SHOP)
    body = [block for block in blocks if not block.in_chrome]
    words = sum(len(block.text.split()) for block in body)
    values = dict(
        zip(PAGE_SIGNAL_NAMES, page_signals(_SHOP, "https://k.com/menu", blocks), strict=True)
    )
    assert len(values) == 11  # noqa: PLR2004
    # Visible text only (no title, no JSON-LD): 79 characters, 20 of them in links.
    assert values["link_text_share"] == 20 / 79
    assert values["log_anchors"] == math.log1p(3)
    assert values["anchors_per_block"] == 3 / len(body)
    assert values["chrome_block_share"] == (len(blocks) - len(body)) / len(blocks)
    assert values["money_per_100_words"] == 100 * 2 / words  # $3.50 and $7.00
    # Two same-host links below /menu; the off-site /menu/x link doesn't count.
    assert values["child_link_share"] == 2 / 3
    assert values["log_child_links"] == math.log1p(2)
    assert values["cart_markup"] == values["product_markup"] == values["article_markup"] == 1.0
    assert values["log_article_tags"] == math.log1p(2)


def test_page_signals_skip_an_href_urllib_cannot_parse() -> None:
    # A stray "[" makes urljoin raise "Invalid IPv6 URL": page markup, never fatal.
    html = '<p><a href="http://[broken/x">x</a> <a href="/menu/lunch">Lunch</a></p>'
    values = dict(
        zip(PAGE_SIGNAL_NAMES, page_signals(html, "https://k.com/menu", segment(html)), strict=True)
    )
    assert values["child_link_share"] == 1.0 / 2  # the parseable child link, of both anchors


def test_page_signals_caps_and_other_markup() -> None:
    links = "".join(f'<a href="/p{i}">x</a> ' for i in range(20))
    html = (
        f'<body><p>{links}</p><a rel="author" href="/me">me</a>'
        '<div itemtype="https://schema.org/Product/"><span>Add to bag</span></div></body>'
    )
    values = dict(
        zip(PAGE_SIGNAL_NAMES, page_signals(html, "https://k.com/", segment(html)), strict=True)
    )
    assert values["anchors_per_block"] == 3.0  # noqa: PLR2004 - capped
    prices = "<p>$1.00 $2.00 $3.00</p>"
    money = page_signals(prices, "https://k.com/", segment(prices))
    assert money[PAGE_SIGNAL_NAMES.index("money_per_100_words")] == 20.0  # noqa: PLR2004 - capped
    assert values["cart_markup"] == values["product_markup"] == values["article_markup"] == 1.0
    assert page_signals("", "https://k.com/", []) == [0.0] * 11


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


def test_v11_table_cells_need_repeated_labelled_rows_of_six_or_more() -> None:
    def page(rows: int, width: int, gap: str = "") -> str:
        return "".join(
            f"<p>Dish {chr(65 + r)}</p>{gap}"
            + "".join(f"<p>{r * 10 + c}</p>" for c in range(width))
            for r in range(rows)
        )

    def bare(html: str) -> int:
        return sum(t.kind == "bare" for r in price_tokens(segment(html)) for t in r)

    assert bare(page(3, 6)) == 0, "three labelled rows of six cells are a table"
    assert bare(page(2, 6)) == 12, "two rows are not a table: every cell still reads"
    assert bare(page(3, 5)) == 15, "five columns: a size or glass/bottle table"
    assert bare(page(3, 6, gap="<p>served with rice and beans</p>")) == 18, "two blocks between"
    assert bare(page(3, 6, gap="<p>✓</p><p></p>")) == 0, "a mark cell or a blank is skipped"
    # a price column printed after its section's dishes is one run, not labelled rows
    dishes = "".join(f"<p>Dish {n}</p><p>with ponzu</p>" for n in "ABCDEFGH")
    column = "".join(f"<p>{p}</p>" for p in (19, 16, 8, 30, 20, 16, 14, 12))
    assert bare(dishes + column + "<h2>Rolls</h2>" + dishes + column) == 16
    # money in a table's cells keeps reading: only bare readings are dropped
    money = "".join(f"<p>Wrap {n}</p>" + "<p>9.50</p>" * 6 for n in "ABC")
    assert sum(t.kind == "money" for r in price_tokens(segment(money)) for t in r) == 18
