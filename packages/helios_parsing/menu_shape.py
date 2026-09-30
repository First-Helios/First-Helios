"""Validated rows → the shape of a Menu page: sections, items, variants and prices.

Pure grouping for ADR-0013 §6 (session P5-4 answers N2): the Menu writer turns
this into a ``MenuAggregate``. Only what the validator kept is shaped, and every
node carries the Capture-targeted Evidence of the text it states:

- **Rows kept.** ``accept`` rows give an item and a price; ``downgrade`` rows
  give the item alone (its price is ADR-0005's derived unknown); ``reject`` rows
  are dropped (the caller counts them).
- **Sections.** A section the extractor named is kept when its name is printed
  on the page at or before its first item: the nearest non-chrome block whose
  words are exactly the name's ("Tacos"), or a heading block containing them.
  Otherwise its items go to the structural ``Unsectioned`` grouping, which
  states no heading of its own.
- **Items.** One item per (section, name block, normalized name): the rows of
  one printed item (its sizes, its prices) share it; the same dish in two
  sections is two items. The name is the extractor's copy, grounded by the
  validator; its Evidence is the name's span.
- **Variants.** An accepted row with a size/variant label ("Large", "Glass")
  prices a variant of that label (the validator checked the label is printed
  with the price). A row without a label prices the item itself; several such
  prices stay separate price rows, since nothing on the page names them.
- **Prices.** Integer minor units (USD), with the price span and the name span
  as Evidence.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from packages.helios_parsing.validator import (
    Evidence,
    name_evidence,
    norm_tokens,
    parse_amount,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from packages.helios_parsing.segment import Block
    from packages.helios_parsing.validator import Verdict

MAX_TEXT = 512  # Menu name and label columns


@dataclass(frozen=True, slots=True)
class ShapedPrice:
    amount_minor: int
    evidence: tuple[Evidence, ...]  # the price span, then the item's name span


@dataclass(frozen=True, slots=True)
class ShapedVariant:
    key: str  # normalized label, unique within its item
    label: str
    evidence: Evidence  # the first price span printed with the label
    prices: tuple[ShapedPrice, ...]


@dataclass(frozen=True, slots=True)
class ShapedItem:
    key: str  # "<name block>:<normalized name>", unique within its section
    name: str
    evidence: Evidence
    prices: tuple[ShapedPrice, ...]  # prices printed without a label
    variants: tuple[ShapedVariant, ...]


@dataclass(frozen=True, slots=True)
class ShapedSection:
    key: str | None  # "<heading block>:<normalized name>"; None = ``Unsectioned``
    name: str | None
    evidence: Evidence | None
    items: tuple[ShapedItem, ...]


@dataclass(slots=True)
class _Item:
    name: str
    evidence: Evidence
    prices: list[ShapedPrice] = field(default_factory=list)
    variants: dict[str, tuple[str, Evidence, list[ShapedPrice]]] = field(default_factory=dict)
    seen: set[str] = field(default_factory=set)  # price locators, one row per printed price


def _norm(text: str) -> str:
    return " ".join(norm_tokens(text))


def _clip(text: str) -> str:
    return text.strip()[:MAX_TEXT].strip()


def _section_block(blocks: Sequence[Block], name: str, before: int) -> int | None:
    """The nearest block at or before ``before`` that prints the section name."""
    words = set(norm_tokens(name))
    if not words:
        return None
    for j in range(min(before, len(blocks) - 1), -1, -1):
        block = blocks[j]
        if block.in_chrome:
            continue
        tokens = set(norm_tokens(block.text))
        if tokens == words or (block.heading and words <= tokens):
            return j
    return None


def shape(blocks: Sequence[Block], verdicts: Sequence[Verdict]) -> tuple[ShapedSection, ...]:
    """The page's sections in reading order; ``Unsectioned`` (if any) first."""
    index = {b.id: i for i, b in enumerate(blocks)}
    kept = [v for v in verdicts if v.decision != "reject" and v.name_evidence is not None]

    # Ground each named section at its first item.
    first_block: dict[str, int] = {}
    for v in kept:
        assert v.name_evidence is not None  # noqa: S101 - filtered above
        first_block.setdefault(v.row.section or "", index[v.name_evidence.block_id])
    grounded: dict[str, tuple[str, str, Evidence]] = {}  # model name -> (key, name, evidence)
    for name, at in first_block.items():
        j = _section_block(blocks, name, at) if name.strip() else None
        if j is not None:
            span = name_evidence(blocks[j], name)
            printed = _clip(blocks[j].text[span.start : span.end])
            grounded[name] = (f"{blocks[j].id}:{_norm(name)}", printed or _clip(name), span)

    sections: dict[str | None, tuple[str | None, Evidence | None, dict[str, _Item]]] = {}
    for v in kept:
        assert v.name_evidence is not None  # noqa: S101 - filtered above
        row = v.row
        found = grounded.get(row.section or "")
        section_key = found[0] if found else None
        if section_key not in sections:
            sections[section_key] = (found[1], found[2], {}) if found else (None, None, {})
        items = sections[section_key][2]
        block = blocks[index[v.name_evidence.block_id]]
        item_key = f"{block.id}:{_norm(row.item)}"
        item = items.get(item_key)
        if item is None:
            item = items[item_key] = _Item(_clip(row.item), name_evidence(block, row.item))
        if v.decision != "accept" or v.price_evidence is None:
            continue
        amount = parse_amount(row.amount)
        if amount is None or v.price_evidence.locator in item.seen:
            continue
        item.seen.add(v.price_evidence.locator)
        price = ShapedPrice(int(amount * 100), (v.price_evidence, item.evidence))
        label = _clip(row.variant or "")
        variant_key = _norm(label)
        if not variant_key:
            item.prices.append(price)
            continue
        if variant_key not in item.variants:
            item.variants[variant_key] = (label, v.price_evidence, [])
        item.variants[variant_key][2].append(price)

    ordered = sorted(sections.items(), key=lambda kv: kv[0] is not None)  # stable: reading order
    return tuple(
        ShapedSection(
            key=key,
            name=name,
            evidence=evidence,
            items=tuple(
                ShapedItem(
                    key=item_key,
                    name=item.name,
                    evidence=item.evidence,
                    prices=tuple(item.prices),
                    variants=tuple(
                        ShapedVariant(vkey, label, ev, tuple(prices))
                        for vkey, (label, ev, prices) in item.variants.items()
                    ),
                )
                for item_key, item in items.items()
            ),
        )
        for key, (name, evidence, items) in ordered
    )
