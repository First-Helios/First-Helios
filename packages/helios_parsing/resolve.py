"""Stage [5b] price resolution: generic deterministic resolvers over the validator's
no-match downgrades (ADR-0013 Amendments 19-20; built in session P5-18).

It runs after the validator (:func:`judge`) and sees only rows the validator kept
unpriced because their amount matched no price it could bind to the item
(:data:`NO_MATCH`). The validator and every row it accepted are unchanged.

Production has no labels, so whatever [5b] accepts is stored as a true price:

- **refuse by default:** a row is accepted only when a resolver grounds it;
  otherwise it stays the validator's downgrade (the item kept, its price unknown);
- **no printed price, no accept:** an accept cites the span of the printed price
  it read as its Evidence, as the validator's accepts do;
- **its own reason:** an accepted row's reasons are the resolver's tag, then the
  validator's downgrade reason (``("resolved_name_pair", "variant_not_grounded")``),
  so the run report counts it and the Menu writer stores it with its own, lower,
  price confidence (``apps.menu_pipeline.menu_writes``).

Resolvers (generic, chosen per row by what the page prints, never by site); each is
kept only under Amendment 19 item 5's rule (no tuning set worse on any §8 bar, no
rise in accepted rows matching no label):

- ``resolved_name_pair`` (:func:`name_pair`): a slash-joined count pair in a dish's
  name ("3/6 Catfish Strips Dinner" over "$9.95/$17.99") grounds the same-order price
  pair: the row's variant is one count of the pair, and its amount is the price at
  the same position in the item's first slash-joined price group, printed right after
  the name (in its block or the next :data:`PAIR_SCAN`, before another item).

Amendment 19's section single-price rule was built and measured in P5-18 and not kept
(it failed the accepted-rows-matching-no-label gate); Amendment 20 records it.
"""

from __future__ import annotations

import re
from dataclasses import replace
from typing import TYPE_CHECKING

from packages.helios_parsing.prices import price_tokens
from packages.helios_parsing.validator import (
    Validation,
    Verdict,
    evidence,
    norm_tokens,
    parse_amount,
    validate,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from packages.helios_parsing.prices import PriceToken
    from packages.helios_parsing.segment import Block
    from packages.helios_parsing.validator import Row

RESOLVER_VERSION = "resolve-v1"  # part of the pipeline version
NO_MATCH = frozenset(
    {
        "price_not_grounded",
        "variant_not_grounded",
        "price_bound_to_other_item",
        "price_belongs_to_other_variant",
        "addon_price",
    }
)
NAME_PAIR = "resolved_name_pair"
PAIR_SCAN = 3  # blocks after the name searched for its price group

_COUNT_PAIR = re.compile(r"(?<![\d.$/])\d{1,3}(?:\s*/\s*\d{1,3})+(?![\d.%/])")  # "3/6"
_PAIR_SEP = re.compile(r"\s*/\s*")


class Page:
    """What the resolvers read of one page: its blocks, price tokens and item name blocks."""

    def __init__(self, blocks: Sequence[Block], verdicts: Sequence[Verdict]) -> None:
        self.blocks = blocks
        self.prices = price_tokens(list(blocks))
        self.index = {b.id: i for i, b in enumerate(blocks)}
        self.item_blocks = {
            self.index[v.name_evidence.block_id]
            for v in verdicts
            if v.decision != "reject" and v.name_evidence is not None
        }


if TYPE_CHECKING:
    Resolver = Callable[[Page, int, Verdict], PriceToken | None]


def pair_position(name: str, variant: str | None) -> tuple[int, int] | None:
    """(the variant's position, the pair's size) when the variant is one count of a
    slash-joined count pair in the dish's name ("3/6 Catfish Dinner", "6"), else None."""
    words = norm_tokens(variant or "")
    pair = _COUNT_PAIR.search(name)
    if len(words) != 1 or not words[0].isdigit() or pair is None:
        return None
    counts = [int(c) for c in _PAIR_SEP.split(pair.group(0).strip())]
    if len(set(counts)) != len(counts) or int(words[0]) not in counts:
        return None
    return counts.index(int(words[0])), len(counts)


def _price_group(page: Page, j: int, start: int, size: int) -> list[PriceToken] | None:
    """The first ``size`` prices from ``start`` in block ``j``, joined only by "/"."""
    toks = [t for t in page.prices[j] if t.start >= start][:size]
    text = page.blocks[j].text
    if len(toks) == size and all(
        _PAIR_SEP.fullmatch(text[a.end : b.start]) for a, b in zip(toks, toks[1:], strict=False)
    ):
        return toks
    return None


def name_pair(page: Page, nb: int, verdict: Verdict) -> PriceToken | None:
    """The price at the position of the row's count in a "3/6" pair in the dish's name."""
    row = verdict.row
    amount = parse_amount(row.amount)
    found = pair_position(row.item, row.variant)
    if amount is None or found is None:
        return None
    position, size = found
    name_span = verdict.name_evidence
    assert name_span is not None  # noqa: S101 - a downgrade always grounds its name
    for j in range(nb, min(nb + 1 + PAIR_SCAN, len(page.blocks))):
        if j != nb and j in page.item_blocks:
            return None
        start = name_span.end if j == nb else 0
        if not any(t.start >= start for t in page.prices[j]):
            continue
        group = _price_group(page, j, start, size)
        if group is None:
            return None  # the first prices after the name are not the pair's
        return group[position] if group[position].amount == amount else None
    return None


RESOLVERS: tuple[tuple[str, Resolver], ...] = ((NAME_PAIR, name_pair),)
_TAGS = frozenset(name for name, _ in RESOLVERS)


def resolved(verdict: Verdict) -> bool:
    """An accept [5b] made (its first reason is a resolver's tag)."""
    return verdict.decision == "accept" and bool(verdict.reasons) and verdict.reasons[0] in _TAGS


def resolve(
    blocks: Sequence[Block],
    validation: Validation,
    resolvers: Sequence[tuple[str, Resolver]] = RESOLVERS,
) -> Validation:
    """The validation with each no-match downgrade a resolver grounds turned into an accept."""
    candidates = [
        i
        for i, v in enumerate(validation.verdicts)
        if v.decision == "downgrade" and v.reasons and v.reasons[0] in NO_MATCH
    ]
    if not candidates or not resolvers:
        return validation
    page = Page(blocks, validation.verdicts)
    verdicts = list(validation.verdicts)
    for i in candidates:
        v = verdicts[i]
        assert v.name_evidence is not None  # noqa: S101 - a downgrade always grounds its name
        nb = page.index[v.name_evidence.block_id]
        for name, resolver in resolvers:
            tok = resolver(page, nb, v)
            if tok is not None:
                verdicts[i] = replace(
                    v,
                    decision="accept",
                    reasons=(name, *v.reasons),
                    price_evidence=evidence(blocks[tok.block_index], tok.start, tok.end),
                )
                break
    return replace(validation, verdicts=tuple(verdicts))


def judge(
    blocks: Sequence[Block],
    rows: list[Row],
    resolvers: Sequence[tuple[str, Resolver]] = RESOLVERS,
) -> Validation:
    """Stage [5] then [5b]: the validator's decisions, then price resolution."""
    return resolve(blocks, validate(list(blocks), rows), resolvers)
