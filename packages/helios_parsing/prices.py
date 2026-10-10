"""Price occurrences in segmented blocks: the pipeline's price reader (v5) and the frozen v4 one.

``price_tokens`` is the reader the validator, stitch and the row repairs share
(pipeline v5, ADR-0013 Amendment 11), so a printed price reads the same way at
every step. It reads the original block text, never a rewritten copy: each
token's span is a span of ``block.text`` (the Evidence locator's), covering the
amount and its currency mark as printed ("$12", "12.5 USD", "50¢").

Printed forms, all layout-generic:

- ``$`` amounts: "$12", "$12.50", "$19.5" (= 19.50), "$ 12,50", "$.40" (v5);
- decimal amounts without a mark: "12.50", "12,50" (two decimal digits);
- (v5) a currency word before or after the amount: "12.5 USD", "USD 12",
  "7.5 Dollars"; a word glued to it stays outside the span ("From4.5 USD");
- (v5) cents: "50¢", ".65¢" (= 0.50, 0.65);
- (v5) an amount glued to a word by an underscore ("Patacones_12",
  "Shrimp_6.50": image alt text), the underscore outside the span;
- bare integers, as v4: a "11 / 44" block is a glass/bottle pair, and otherwise
  a bare integer counts only as a block's last token.

A one-decimal amount needs a mark ("$", a currency word, an underscore): an
unmarked "6.2", "0.5 pounds" or "WCAG 2.1" is not a price.

``price_tokens_v4`` is the spike validator's v3 tokenizer, unchanged: the page
classifier's layout features (``page_features``) are frozen per classifier
version and still read prices that way.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

    from packages.helios_parsing.segment import Block

    Reader = Callable[[str], list[tuple[int, int, Decimal]]]

# --- v4, frozen for the page classifier (classifier-v2) ---
# $12 | $12.50 | $19.5 | $ 12,50 | 12.50 | 12,50 ; bare integers handled separately
_MONEY = re.compile(
    r"(?P<cur>\$)\s?(?P<a>\d{1,3}(?:,\d{3})*|\d+)(?:[.,](?P<c>\d{2})|\.(?P<c1>\d))?(?!\d)"
    r"|(?<![\w$.,])(?P<a2>\d{1,3})[.,](?P<c2>\d{2})(?![\d%])"
)
_BARE_PAIR = re.compile(r"\s*\d{1,3}(?:\s*/\s*\d{1,3})+\s*")  # "11 / 44"
_BARE_INT = re.compile(r"(?<![\w$.,:/-])(\d{1,3})(?![\w.,:%/])")

# --- v5 additions: each pattern's groups are the whole part "w" and cents "c" ---
_AMOUNT = r"(?P<w>\d{1,3}(?:,\d{3})+|\d+)(?:[.,](?P<c>\d{2})|\.(?P<c1>\d))?"
_CURRENCY_WORD = r"(?:USD|[Dd]ollars?|DOLLARS?)"
_V5_FORMS = (
    re.compile(rf"(?<![\d.,]){_AMOUNT}\s?{_CURRENCY_WORD}\b"),  # "12.5 USD", "From4.5 USD"
    re.compile(rf"\b(?:USD|US\$)\s?{_AMOUNT}(?![\d.,]?\d)"),  # "USD 12"
    re.compile(r"\$\s?\.(?P<c>\d{2})(?!\d)"),  # "$.40"
    re.compile(r"(?<![\d.,])(?P<cents>\d{1,2})\s?¢"),  # "50¢"
    re.compile(r"(?<![\d.,])\.(?P<cents>\d{2})\s?¢"),  # ".65¢"
    re.compile(rf"(?<=[^\W\d_]_){_AMOUNT}(?![\d%]|[.,]\d)"),  # "Patacones_12"
)


@dataclass(frozen=True, slots=True)
class PriceToken:
    block_index: int
    start: int
    end: int
    amount: Decimal
    kind: str  # "money" (a mark or decimals) | "bare" (a trailing/sole integer)


def _money(text: str) -> list[tuple[int, int, Decimal]]:
    """v4's money matches in ``text``: (start, end, amount)."""
    out = []
    for match in _MONEY.finditer(text):
        whole = (match.group("a") or match.group("a2") or "0").replace(",", "")
        one = match.group("c1")
        cents = match.group("c") or match.group("c2") or (f"{one}0" if one else "00")
        out.append((match.start(), match.end(), Decimal(f"{whole}.{cents}")))
    return out


def _v5_amount(match: re.Match[str]) -> Decimal:
    groups = match.groupdict()
    if groups.get("cents") is not None:
        return Decimal(f"0.{int(groups['cents']):02d}")
    whole = (groups.get("w") or "0").replace(",", "")
    one = groups.get("c1")
    cents = groups.get("c") or (f"{one}0" if one else "00")
    return Decimal(f"{whole}.{cents}")


def read_money(text: str) -> list[tuple[int, int, Decimal]]:
    """Every marked or decimal price printed in ``text`` (v5): (start, end, amount).

    Overlapping readings keep the earliest, then the longest: "12.50 USD" is one
    price spanning its currency word, "$12 USD" one spanning from the "$".
    """
    found = _money(text)
    for pattern in _V5_FORMS:
        found.extend((m.start(), m.end(), _v5_amount(m)) for m in pattern.finditer(text))
    out: list[tuple[int, int, Decimal]] = []
    for start, end, amount in sorted(found, key=lambda f: (f[0], -f[1])):
        if out and start < out[-1][1]:
            continue
        out.append((start, end, amount))
    return out


def read_amount(text: str) -> Decimal | None:
    """The amount when ``text`` is one printed price and nothing else ("12.5 USD", "$.40")."""
    text = text.strip()
    found = read_money(text)
    if len(found) == 1 and found[0][0] == 0 and found[0][1] == len(text):
        return found[0][2]
    return None


def _tokens(blocks: list[Block], money: Reader) -> list[list[PriceToken]]:
    out: list[list[PriceToken]] = []
    for index, block in enumerate(blocks):
        tokens = [
            PriceToken(index, start, end, amount, "money")
            for start, end, amount in money(block.text)
        ]
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


def price_tokens(blocks: list[Block]) -> list[list[PriceToken]]:
    """Price occurrences per block, in block order (the pipeline's v5 reader)."""
    return _tokens(blocks, read_money)


def price_tokens_v4(blocks: list[Block]) -> list[list[PriceToken]]:
    """The v4 reader, frozen for the page classifier's features (classifier-v2)."""
    return _tokens(blocks, _money)
