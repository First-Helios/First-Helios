"""One page-structure model per page (ADR-0021 D1; ADR-0013 Amendment 33; session P8-21).

Generic and stdlib only: no per-site or per-platform rule, no class-name vocabulary, no
learned classifier. Built from the re-parse [5c] and [5d] already share
(``dom_sections.placed_blocks``) and from the model's accepted rows on the page (*seeds*:
an accepted row's name block and price block), and recomputed per page and per run:

- **Per block:** the block-level node chain, the class signature
  (``dom_sections.signature``, unchanged), the tag path (its tags) and one text shape
  (:func:`shape`).
- **Title signature.** The most common class signature of the seeds' name blocks whose
  price is in another block. It is trusted with at least :data:`MIN_SUPPORT` such seeds
  and when at least :data:`ROLE_AGREE` of the seed-role blocks carrying it are titles
  (ADR-0021 D2, level 2), not price blocks or description lines.
- **Record depth.** The most common number of block levels from those seeds' name blocks
  up to the lowest common ancestor with their price blocks.
- **Records.** Each unpriced, non-chrome block of the title signature whose text is no
  description is a record title; its record is the title's container at the record depth,
  the contiguous blocks inside it around the title. A container holding a second block of
  the title signature (a flat list) is no record, and its blocks fall back to positional
  rules.
- **Price slot.** The most common class signature of the title-signature seeds' price
  blocks, with at least :data:`MIN_SUPPORT` seeds. A record *holds the slot* when one of
  its blocks of that signature prints a price alone (shape :data:`PRICE`); a label line
  styled like the slot ("Salsa Verde $1.50") does not hold it. The page is *slotted* when at least
  :data:`SLOT_NORMAL` of its priced records hold the slot: a dish card on that page
  normally prints its price in the slot (ADR-0021 Q3 (a)).

When the re-parse differs from the Version's blocks, or nothing is trusted, there is no
structure and every stage behaves as before. Nothing here is stored: the Version's blocks,
``segment-v2``, ``text_hash``, Bronze bundles and Evidence locators are unchanged.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from typing import TYPE_CHECKING

from packages.helios_parsing.dom_sections import signature
from packages.helios_parsing.output import _description_like
from packages.helios_parsing.segment import BLOCK_TAGS
from packages.helios_parsing.validator import is_addon

if TYPE_CHECKING:
    from collections.abc import Sequence

    from packages.helios_parsing.dom_sections import Placed, Signature
    from packages.helios_parsing.prices import PriceToken
    from packages.helios_parsing.segment import Block

MIN_SUPPORT = 3  # seeds a title signature or a price slot needs ([5d]'s MIN_SUPPORT)
ROLE_AGREE = 0.8  # share of a signature's seed-role blocks that must be titles ([5d]'s GATE_AGREE)
SLOT_NORMAL = 0.8  # share of priced records that hold the price slot on a slotted page
LABEL_WORDS = 8  # a priced line with at most this many words is a label line
TITLE_WORDS = 6  # an unpriced line with at most this many words reads as a title

ADDON_LINE = re.compile(r"\s*(?:\+|add\b|extra\b|sub\b|substitute\b)", re.IGNORECASE)
_LETTER = re.compile(r"[^\W\d_]")

# Text shapes: one shared classifier for every structural rule.
PRICE = "price"  # prices only ("$12", "12.99 / 15.99")
ADDON = "addon"  # a modifier price ("+$2", "Add avocado $1")
LABEL = "label"  # a short label and its price ("Large $15", "Chicken / Bistec $14.99")
PRICED = "priced"  # a longer line with a price
TITLE = "title"  # a short unpriced line
DESCRIPTION = "description"  # a sentence or ingredient list (``output._description_like``)
TEXT = "text"  # a longer unpriced line that is no description
SYMBOLS = "symbols"  # no letter and no price


def shape(block: Block, toks: Sequence[PriceToken]) -> str:
    """One block's text shape."""
    text = block.text
    if toks:
        if ADDON_LINE.match(text) or any(is_addon(block, t) for t in toks):
            return ADDON
        if not _LETTER.search(text[: min(t.start for t in toks)]):
            return PRICE  # nothing printed before the price ("$12", "$360.00/48pcs")
        return LABEL if len(text.split()) <= LABEL_WORDS else PRICED
    if not _LETTER.search(text):
        return SYMBOLS
    if _description_like(text):
        return DESCRIPTION
    return TITLE if len(text.split()) <= TITLE_WORDS else TEXT


def chain(placed: Placed) -> tuple[int, ...]:
    """The node ids of a block's block-level ancestors, outermost first."""
    return tuple(
        n for n, (t, _) in zip(placed.node_ids, placed.stack, strict=True) if t in BLOCK_TAGS
    )


def _common(a: Sequence[int], b: Sequence[int]) -> int:
    k = 0
    while k < min(len(a), len(b)) and a[k] == b[k]:
        k += 1
    return k


@dataclass(frozen=True, slots=True)
class Record:
    """A dish card: its title block and the other blocks of its container, in page order."""

    title: int
    members: tuple[int, ...]  # title excluded
    slot: bool  # a block of a price-slot signature in it prints a price


@dataclass(frozen=True, slots=True)
class PageStructure:
    """One page's structure (block indexes are positions in the Version's blocks)."""

    chains: tuple[tuple[int, ...], ...]
    signatures: tuple[Signature, ...]
    paths: tuple[tuple[str, ...], ...]
    shapes: tuple[str, ...]
    title_signature: Signature | None = None
    levels: int = 0
    price_slot: frozenset[Signature] = frozenset()
    slotted: bool = False
    records: tuple[Record, ...] = ()
    record_of: dict[int, int] | None = None  # member block (title excluded) -> record index

    def record(self, block: int) -> Record | None:
        """The record whose container holds ``block`` (not as its title), if any."""
        if self.record_of is None or block not in self.record_of:
            return None
        return self.records[self.record_of[block]]


def build(
    blocks: Sequence[Block],
    placed: Sequence[Placed],
    prices: Sequence[Sequence[PriceToken]],
    seeds: Sequence[tuple[int, int]],
) -> PageStructure | None:
    """The page's structure from its blocks with DOM context (``placed``, empty when the
    re-parse differs), their price tokens and its ``seeds`` (name block, price block)."""
    if not placed or len(placed) != len(blocks):
        return None
    chains = tuple(chain(p) for p in placed)
    sigs = tuple(signature(p) for p in placed)
    base = PageStructure(
        chains=chains,
        signatures=sigs,
        paths=tuple(tuple(t for t, _ in s) for s in sigs),
        shapes=tuple(shape(b, prices[j]) for j, b in enumerate(blocks)),
    )
    split = [(n, p) for n, p in seeds if n != p]
    if len(split) < MIN_SUPPORT:
        return base
    top, support = _most(Counter(sigs[n] for n, _ in split))
    if support < MIN_SUPPORT or _title_share(blocks, prices, sigs, chains, seeds, top) < ROLE_AGREE:
        return base
    depth: Counter[int] = Counter()
    slots: Counter[Signature] = Counter()
    for n, p in split:
        if sigs[n] == top:
            depth[len(chains[n]) - _common(chains[n], chains[p])] += 1
            slots[sigs[p]] += 1
    levels = _most(depth)[0]
    main, count = _most(slots)
    slot = frozenset({main}) if count >= MIN_SUPPORT else frozenset()
    records: list[Record] = []
    for t, b in enumerate(blocks):
        if sigs[t] != top or b.in_chrome or prices[t] or base.shapes[t] == DESCRIPTION:
            continue
        k = len(chains[t]) - levels - 1
        if k < 0:
            continue
        box = chains[t][k]
        lo, hi = t, t
        while lo > 0 and box in chains[lo - 1]:
            lo -= 1
        while hi + 1 < len(blocks) and box in chains[hi + 1]:
            hi += 1
        members = tuple(j for j in range(lo, hi + 1) if j != t)
        if any(sigs[j] == top for j in members):
            continue  # a flat list: two titles in one box
        # the slot prints the dish's price alone; a label line styled like it doesn't count
        holds = any(sigs[j] in slot and base.shapes[j] == PRICE for j in members)
        records.append(Record(title=t, members=members, slot=holds))
    priced = [r for r in records if any(prices[j] for j in r.members)]
    slotted = bool(priced) and sum(r.slot for r in priced) >= SLOT_NORMAL * len(priced)
    record_of = {j: i for i, r in enumerate(records) for j in r.members}
    return PageStructure(
        chains=chains,
        signatures=sigs,
        paths=base.paths,
        shapes=base.shapes,
        title_signature=top,
        levels=levels,
        price_slot=slot,
        slotted=slotted,
        records=tuple(records),
        record_of=record_of,
    )


def _most[T](counts: Counter[T]) -> tuple[T, int]:
    """The most common value and its count; ties go to the smallest value, so the answer
    never depends on the order of the model's rows."""
    return min(counts.items(), key=lambda kv: (-kv[1], kv[0]))


def _title_share(
    blocks: Sequence[Block],
    prices: Sequence[Sequence[PriceToken]],
    sigs: Sequence[Signature],
    chains: Sequence[tuple[int, ...]],
    seeds: Sequence[tuple[int, int]],
    top: Signature,
) -> float:
    """The share of seed-role blocks of signature ``top`` that are titles: seed name blocks
    are titles, their price blocks prices, and unpriced lettered blocks inside a seed's
    name/price container descriptions (ADR-0021 D3)."""
    role: dict[int, str] = {}
    for n, _ in seeds:
        role[n] = TITLE
    for n, p in seeds:
        if p != n:
            role.setdefault(p, PRICE)
    for n, p in seeds:
        k = _common(chains[n], chains[p])
        if p == n or not k:
            continue
        box = chains[n][k - 1]
        j = min(n, p) + 1
        while j < len(blocks) and box in chains[j]:
            if j not in role and not prices[j] and _LETTER.search(blocks[j].text):
                role[j] = DESCRIPTION
            j += 1
    mine = [r for j, r in role.items() if sigs[j] == top]
    return mine.count(TITLE) / len(mine) if mine else 0.0
