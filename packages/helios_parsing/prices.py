"""Price occurrences in segmented blocks (the spike validator's v3 price tokens).

Ported from ``spikes/menu_model/validator.py`` (``MENU_SPIKE_VALIDATOR=v3``): a
"$19.5" price with one decimal digit is 19.50, a bare "11 / 44" block is a
glass/bottle pair, and a bare integer counts only as a block's last token.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from packages.helios_parsing.segment import Block

# $12 | $12.50 | $19.5 | $ 12,50 | 12.50 | 12,50 ; bare integers handled separately
_MONEY = re.compile(
    r"(?P<cur>\$)\s?(?P<a>\d{1,3}(?:,\d{3})*|\d+)(?:[.,](?P<c>\d{2})|\.(?P<c1>\d))?(?!\d)"
    r"|(?<![\w$.,])(?P<a2>\d{1,3})[.,](?P<c2>\d{2})(?![\d%])"
)
_BARE_PAIR = re.compile(r"\s*\d{1,3}(?:\s*/\s*\d{1,3})+\s*")  # "11 / 44"
_BARE_INT = re.compile(r"(?<![\w$.,:/-])(\d{1,3})(?![\w.,:%/])")


@dataclass(frozen=True, slots=True)
class PriceToken:
    block_index: int
    start: int
    end: int
    amount: Decimal
    kind: str  # "money" ($ or decimals) | "bare" (a trailing/sole integer)


def price_tokens(blocks: list[Block]) -> list[list[PriceToken]]:
    """Price occurrences per block, in block order."""
    out: list[list[PriceToken]] = []
    for index, block in enumerate(blocks):
        tokens: list[PriceToken] = []
        for match in _MONEY.finditer(block.text):
            whole = (match.group("a") or match.group("a2") or "0").replace(",", "")
            one = match.group("c1")
            cents = match.group("c") or match.group("c2") or (f"{one}0" if one else "00")
            tokens.append(
                PriceToken(index, match.start(), match.end(), Decimal(f"{whole}.{cents}"), "money")
            )
        if not tokens and _BARE_PAIR.fullmatch(block.text):
            tokens.extend(
                PriceToken(index, m.start(), m.end(), Decimal(m.group(0)), "bare")
                for m in re.finditer(r"\d{1,3}", block.text)
            )
        if not tokens:
            bare = list(_BARE_INT.finditer(block.text))
            if bare and not block.text[bare[-1].end() :].strip(" .-–—|"):
                last = bare[-1]
                tokens.append(
                    PriceToken(index, last.start(), last.end(), Decimal(last.group(1)), "bare")
                )
        out.append(tokens)
    return out
