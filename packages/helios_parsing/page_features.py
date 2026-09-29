"""Inputs of the stage [1] page classifier (ADR-0013 §1): page text and layout features.

The classifier embeds :func:`page_text` and appends :func:`layout_features`;
both are frozen per classifier version, so changing either needs a new version
(and a re-trained weights file). Ported from ``spikes/menu_model/classify.py``.
"""

from __future__ import annotations

import math
import re
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

from packages.helios_parsing.prices import price_tokens

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
    prices = price_tokens(blocks)
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
