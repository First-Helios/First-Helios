"""Inputs of the stage [1] page classifier (ADR-0013 §1): page text and page features.

The classifier embeds :func:`page_text` and appends :func:`layout_features`
and, from ``classifier-v3`` on, :func:`page_signals` (ADR-0013 Amendment 24).
All are frozen per classifier version, so changing any needs a new version
(and a re-trained weights file). :func:`page_text` and :func:`layout_features`
are ported from ``spikes/menu_model/classify.py``; :func:`page_signals` from
the P5-28 survey's ``signals.py``.
"""

from __future__ import annotations

import json
import math
import re
from html.parser import HTMLParser
from typing import TYPE_CHECKING
from urllib.parse import urljoin, urlsplit

from packages.helios_parsing.prices import price_tokens_v4
from packages.helios_parsing.segment import SKIP_TAGS

if TYPE_CHECKING:
    from packages.helios_parsing.segment import Block

PAGE_TEXT_CHARS = 2000
_SHORT_BLOCK_CHARS = 40
_TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_WS = re.compile(r"\s+")

FEATURE_NAMES = (
    "log_body_blocks",
    "priced_block_share",
    "log_money_tokens",
    "log_priced_blocks",
    "words_per_block",
    "short_block_share",
    "heuristic_menu_signal",
)


def page_text(html: str, url: str, blocks: list[Block]) -> str:
    """Title, URL path, headings, then body text (chrome blocks dropped), truncated."""
    match = _TITLE.search(html)
    title = _WS.sub(" ", match.group(1)).strip() if match else ""
    body = [block for block in blocks if not block.in_chrome]
    heads = " | ".join(block.text for block in body if block.heading)[:400]
    text = " | ".join(block.text for block in body)
    return f"{title}\n{urlsplit(url).path}\n{heads}\n{text}"[:PAGE_TEXT_CHARS]


def layout_features(blocks: list[Block], *, heuristic_signal: bool) -> list[float]:
    """The seven layout features, in :data:`FEATURE_NAMES` order.

    ``heuristic_signal`` is the S4 menu-word check on the page (its URL path,
    title or first heading), computed by the caller: this package cannot import
    the discovery app.
    """
    prices = price_tokens_v4(blocks)  # frozen with classifier-v2
    body = [index for index, block in enumerate(blocks) if not block.in_chrome]
    priced = [index for index in body if prices[index]]
    money = sum(1 for index in body for token in prices[index] if token.kind == "money")
    count = max(len(body), 1)
    words = sum(len(blocks[index].text.split()) for index in body)
    short = sum(1 for index in body if len(blocks[index].text) < _SHORT_BLOCK_CHARS)
    return [
        math.log1p(len(body)),
        len(priced) / count,
        math.log1p(money),
        math.log1p(len(priced)),
        words / count,
        short / count,
        float(heuristic_signal),
    ]


# Generic page signals (classifier-v3): links, landmarks, price tokens, schema.org /
# Open Graph types and two shop phrases. No site, platform or brand rule.
PAGE_SIGNAL_NAMES = (
    "link_text_share",  # visible text inside <a>, share of all visible text
    "log_anchors",
    "anchors_per_block",  # anchors per body block (capped at 3)
    "chrome_block_share",  # blocks inside nav/header/footer/aside/form/button/select
    "money_per_100_words",  # money tokens per 100 body words (capped at 20)
    "child_link_share",  # same-host anchors one level below this page's path, share of anchors
    "log_child_links",
    "cart_markup",  # add-to-cart / add-to-bag text or attribute tokens
    "product_markup",  # schema.org Product, og:type product
    "article_markup",  # og:type article, schema.org Article/BlogPosting/NewsArticle, rel=author
    "log_article_tags",  # <article> and <time> elements
)
_MAX_ANCHORS_PER_BLOCK = 3.0
_MAX_MONEY_PER_100_WORDS = 20.0
_CART = re.compile(r"add[\s_-]?to[\s_-]?(cart|bag|basket)", re.IGNORECASE)
_ARTICLE_TYPES = frozenset({"article", "blogposting", "newsarticle", "posting"})
_LD_TYPE = re.compile(r'"@type"\s*:\s*(\[[^\]]*\]|"[^"]*")')
_TOKEN_ATTRS = frozenset({"class", "id", "name", "data-action"})


class _SignalParser(HTMLParser):
    """One pass over the page: visible and link text, anchors, markup types."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.skip = 0
        self.in_a = 0
        self.in_ld = False
        self.text_chars = 0
        self.link_chars = 0
        self.hrefs: list[str] = []
        self.cart = False
        self.product = False
        self.article = False
        self.article_tags = 0
        self.ld: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key: (value or "") for key, value in attrs}
        if tag == "script" and "ld+json" in values.get("type", "").lower():
            self.in_ld = True
        if tag in SKIP_TAGS:
            self.skip += 1
        if tag == "a":
            self.in_a += 1
            if values.get("href"):
                self.hrefs.append(values["href"])
            if "author" in values.get("rel", "").lower().split():
                self.article = True
        if tag in {"article", "time"}:
            self.article_tags += 1
        if tag == "meta":
            prop = (values.get("property") or values.get("name") or "").lower()
            if prop == "og:type":
                content = values.get("content", "").lower()
                self.product |= content.startswith("product")
                self.article |= content == "article"
        itemtype = values.get("itemtype", "").lower().rstrip("/")
        if itemtype.endswith("/product"):
            self.product = True
        if itemtype.rsplit("/", 1)[-1] in _ARTICLE_TYPES:
            self.article = True
        tokens = " ".join(value for key, value in attrs if key in _TOKEN_ATTRS and value)
        if tokens and _CART.search(tokens):
            self.cart = True

    def handle_endtag(self, tag: str) -> None:
        if tag in SKIP_TAGS and self.skip:
            self.skip -= 1
        if tag == "script":
            self.in_ld = False
        if tag == "a" and self.in_a:
            self.in_a -= 1

    def handle_data(self, data: str) -> None:
        if self.in_ld:
            self.ld.append(data)
            return
        if self.skip:
            return
        chars = len(data.strip())
        self.text_chars += chars
        if self.in_a:
            self.link_chars += chars
        if chars and _CART.search(data):
            self.cart = True


def _ld_types(chunks: list[str]) -> set[str]:
    """Lower-cased JSON-LD ``@type`` values, read without parsing the whole document."""
    types: set[str] = set()
    for raw in _LD_TYPE.findall(" ".join(chunks)):
        try:
            value = json.loads(raw)
        except json.JSONDecodeError:
            continue
        for item in value if isinstance(value, list) else [value]:
            if isinstance(item, str):
                types.add(item.lower().rsplit("/", 1)[-1])
    return types


def page_signals(html: str, url: str, blocks: list[Block]) -> list[float]:
    """The eleven generic page signals, in :data:`PAGE_SIGNAL_NAMES` order.

    ``blocks`` is ``segment(html)``; ``url`` is the page's final URL (child links
    are same-host links below its path).
    """
    parser = _SignalParser()
    parser.feed(html)
    parser.close()
    types = _ld_types(parser.ld)
    prices = price_tokens_v4(blocks)  # frozen with layout_features
    body = [index for index, block in enumerate(blocks) if not block.in_chrome]
    money = sum(1 for index in body for token in prices[index] if token.kind == "money")
    words = sum(len(blocks[index].text.split()) for index in body)
    base = urlsplit(url)
    path = base.path.rstrip("/")
    child = 0
    for href in parser.hrefs:
        try:
            target = urlsplit(urljoin(url, href))
        except ValueError:  # page markup: a stray "[" in an href is skipped, never fatal
            continue
        if (target.hostname or "") != (base.hostname or ""):
            continue
        tail = target.path.rstrip("/")
        if tail.startswith(path + "/") and tail != path:
            child += 1
    anchors = len(parser.hrefs)
    return [
        parser.link_chars / parser.text_chars if parser.text_chars else 0.0,
        math.log1p(anchors),
        min(anchors / max(len(body), 1), _MAX_ANCHORS_PER_BLOCK),
        (len(blocks) - len(body)) / len(blocks) if blocks else 0.0,
        min(100 * money / words, _MAX_MONEY_PER_100_WORDS) if words else 0.0,
        child / anchors if anchors else 0.0,
        math.log1p(child),
        float(parser.cart),
        float(parser.product or "product" in types),
        float(parser.article or bool(types & _ARTICLE_TYPES)),
        math.log1p(parser.article_tags),
    ]
