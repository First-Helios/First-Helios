"""Extractor output → validator rows: parsing, truncated-output recovery and row repairs.

Ported from ``spikes/menu_model/extract.py`` (``parse_output``, ``rows_of`` with
``repair=True``) with process v2 and stitch v3 hard-wired (ADR-0013 §1).

``parse_output`` reads one chunk's generated text. Grammar-constrained output is
compact JSON (``prompt.GRAMMAR``); a generation cut off by the token cap leaves
it unterminated, and the rows it completed before that are still real
extractions, so they are recovered in order and the output is marked
``recovered``.

``rows_of`` turns a page's chunk outputs into ``validator.Row``s, applying the
generic repairs in the spike's order:

1. a price printed in the variant slot with the price slot empty moves to the
   price (small models lose the key order; v5: any form ``prices`` reads,
   "12.5 USD");
2. a variant with no letters ("4") is dropped: a bare number is not a size;
3. stitch v3 (``stitch.stitch``): split lines re-assembled into items, price
   fill, variant completion;
4. a variant whose words are all in the item name ("(L)" copied from "Orange
   Chicken (L)") is dropped: it was not printed with the price;
4b. (v4) a variant that is no price's printed label near the item ("chilled, hot,
   or spicy": a description put in the variant slot) is dropped
   (``drop_unprinted_variants``; v5: the validator's labels, column headers
   included);
4c. (v6) a row named by a whole list of names printed in its block ("Deep Eddy,
   Tito's Handmade Vodka, Absolut Vodka") becomes one row per name, each with the
   row's price and variant (``split_listed``); a choice ("Mango, Peach or Guava")
   stays one row;
4d. (v7) a row named by its description takes the short title line printed right
   above it (``name_by_title``);
5. exact duplicates (same name tokens, variant, amount, section, claimed block)
   collapse to one; a dish printed again in another inline menu is kept (v4).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any

from packages.helios_parsing.prices import price_tokens, read_amount
from packages.helios_parsing.stitch import FILL_GAP, stitch
from packages.helios_parsing.validator import (
    Row,
    block_tokens,
    label_tokens,
    list_names,
    list_price,
    norm_tokens,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from packages.helios_parsing.segment import Block

# ``rows_of``'s repairs and stitch v3 together; part of the pipeline version.
REPAIRS_VERSION = "repairs-v7"

_SECTION = re.compile(r'"section"\s*:\s*("(?:[^"\\]|\\.)*")')
_ITEM = re.compile(r'\{\s*"b"\s*:[^{}]*\}')
_AMOUNT_ONLY = re.compile(r"^\$?\s?\d{1,4}(?:[.,]\d{1,2})?$")


@dataclass(frozen=True, slots=True)
class OutputRow:
    """One generated item, as the model wrote it: ``{"b","n","p","v"}``."""

    block: str
    name: str
    price: str
    variant: str


@dataclass(frozen=True, slots=True)
class OutputSection:
    section: str
    rows: tuple[OutputRow, ...]


@dataclass(frozen=True, slots=True)
class ExtractorOutput:
    """One chunk's parsed output."""

    sections: tuple[OutputSection, ...]
    recovered: bool = False  # not valid JSON; the complete rows were recovered in order

    @property
    def priced_rows(self) -> int:
        return sum(1 for section in self.sections for row in section.rows if row.price)


def _row_of_item(item: dict[str, Any]) -> OutputRow:
    return OutputRow(
        block=str(item.get("b", "")),
        name=str(item.get("n", "")),
        price=str(item.get("p", "")),
        variant=str(item.get("v", "")),
    )


def _from_json(value: dict[str, Any]) -> ExtractorOutput:
    sections = value.get("sections")
    out: list[OutputSection] = []
    for section in sections if isinstance(sections, list) else []:
        if not isinstance(section, dict):
            continue
        items = section.get("items")
        rows = tuple(
            _row_of_item(item)
            for item in (items if isinstance(items, list) else [])
            if isinstance(item, dict)
        )
        out.append(OutputSection(str(section.get("section") or ""), rows))
    return ExtractorOutput(tuple(out))


def _recover(content: str) -> ExtractorOutput:
    """Every complete section name and item in ``content``, in order."""
    events = sorted(
        [(m.start(), True, m) for m in _SECTION.finditer(content)]
        + [(m.start(), False, m) for m in _ITEM.finditer(content)],
        key=lambda event: event[0],
    )
    sections: list[tuple[str, list[OutputRow]]] = []
    for _, is_section, match in events:
        if is_section:
            try:
                name = json.loads(match.group(1))
            except ValueError:
                continue
            sections.append((str(name), []))
            continue
        if not sections:
            sections.append(("", []))
        try:
            item = json.loads(match.group(0))
        except ValueError:
            continue
        if isinstance(item, dict):
            sections[-1][1].append(_row_of_item(item))
    return ExtractorOutput(
        tuple(OutputSection(name, tuple(rows)) for name, rows in sections), recovered=True
    )


def parse_output(content: str) -> ExtractorOutput:
    """One chunk's generated text; unterminated or malformed JSON is recovered row by row."""
    try:
        value = json.loads(content)
    except ValueError:
        return _recover(content)
    return _from_json(value) if isinstance(value, dict) else _recover(content)


def rows_of(outputs: Sequence[ExtractorOutput], blocks: Sequence[Block]) -> list[Row]:
    """A page's rows from its chunk outputs (in chunk order), repaired and stitched."""
    rows: list[Row] = []
    for output in outputs:
        for section in output.sections:
            for raw in section.rows:
                block, name, price, variant = (
                    raw.block.strip(),
                    raw.name.strip(),
                    raw.price.strip(),
                    raw.variant.strip(),
                )
                if not price and (_AMOUNT_ONLY.match(variant) or read_amount(variant)):
                    price, variant = variant, ""
                if variant and not any(ch.isalpha() for ch in variant):
                    variant = ""
                if name:
                    rows.append(
                        Row(
                            item=name,
                            amount=price or None,
                            variant=variant or None,
                            section=section.section or None,
                            claimed_block=block or None,
                        )
                    )
    # stitch before dedupe: identical price lines repeat; after it, "$7.50/Medium"
    # must still have read as a price line there
    rows = stitch(rows, blocks)
    rows = [
        replace(row, variant=None)
        if row.variant and set(norm_tokens(row.variant)) <= set(norm_tokens(row.item))
        else row
        for row in rows
    ]
    rows = drop_unprinted_variants(rows, blocks)
    rows = split_listed(rows, blocks)
    rows = name_by_title(rows, blocks)
    seen: set[tuple[str, str | None, str | None, str | None, str | None]] = set()
    unique: list[Row] = []
    for row in rows:
        key = (
            " ".join(norm_tokens(row.item)),
            row.variant,
            row.amount,
            row.section,
            row.claimed_block,
        )
        if key not in seen:
            seen.add(key)
            unique.append(row)
    return unique


def drop_unprinted_variants(rows: Sequence[Row], blocks: Sequence[Block]) -> list[Row]:
    """Rows whose variant isn't the label of any price printed near the item lose it.

    The prompt asks for the size/variant word printed next to the price; a small
    model sometimes copies the description there instead, and the validator then
    downgrades a correctly priced row (``variant_not_grounded``). Near = the claimed
    block from 2 above to ``FILL_GAP`` below. Kept when nothing near prints a price
    (a shared section price) or the claimed block is unknown.
    """
    index = {b.id: i for i, b in enumerate(blocks)}
    prices = price_tokens(list(blocks))
    out: list[Row] = []
    for row in rows:
        pos = index.get(row.claimed_block or "")
        if not row.variant or pos is None:
            out.append(row)
            continue
        labels = [
            label_tokens(list(blocks), prices, t)
            for j in range(max(0, pos - 2), min(len(blocks), pos + FILL_GAP + 1))
            for t in prices[j]
        ]
        own = set(norm_tokens(row.variant))
        printed = not labels or any(own <= label for label in labels)
        out.append(row if printed else replace(row, variant=None))
    return out


_BAR_SEP = re.compile(r"\s*[|•·]\s*")
_COMMA_SEP = re.compile(r"\s*,\s*")
_CHOICE = re.compile(r"(?i)(?:or|and)\b")
_LONG_PAREN = re.compile(r"\([^()]{5,}\)")  # "(red lentils)": a description, not a tag "(GF)"


def _names(item: str) -> list[str]:
    """The names a row's name lists: split on "|" / "•" (two or more), else on commas
    (three or more: "Sausage, Egg & Cheese" and "Chardonnay, CA" are one name)."""
    sep = _BAR_SEP if _BAR_SEP.search(item) else _COMMA_SEP
    parts = [p.strip() for p in sep.split(item) if p.strip()]
    return parts if len(parts) >= (2 if sep is _BAR_SEP else 3) else []


def split_listed(rows: Sequence[Row], blocks: Sequence[Block]) -> list[Row]:
    """(v6) A row named by a list of names printed in its claimed block becomes one row
    per name: the model read "Bud Light, Coors Light, Shiner Bock" (under one price)
    as one item, and each is an item (P5-8 label convention). Every name must be
    capitalized and in the block, and the block must be a price-less list of names
    with its price printed once right above or below it (``validator.list_price``'s
    layout); a choice ("or", "and" before a name), names described in parentheses
    ("Misir (red lentils), Kik (yellow split-pea)": a dish's parts; a tag like "(GF)"
    is fine) and a description's ingredients ("sausage, pork ribs") stay one row."""
    index = {b.id: i for i, b in enumerate(blocks)}
    prices = price_tokens(list(blocks))
    out: list[Row] = []
    for row in rows:
        pos = index.get(row.claimed_block or "")
        parts = _names(row.item)
        if (
            pos is None
            or not parts
            or _LONG_PAREN.search(row.item)
            or any(_CHOICE.match(p) or not p[0].isupper() for p in parts)
            or len(list_names(blocks[pos].text)) != len(parts)
            or list_price(list(blocks), prices, pos, norm_tokens(parts[0]), set()) is None
            or not all(set(norm_tokens(p)) <= block_tokens(blocks[pos].text) for p in parts)
        ):
            out.append(row)
            continue
        out.extend(replace(row, item=p) for p in parts)
    return out


_TITLE_MAX_WORDS = 6
_DESCRIPTION_WORDS = 8


def _description_like(text: str) -> bool:
    """A sentence or ingredient list, not a dish's title: two or more commas, a final
    period, or a long run of words."""
    text = text.strip()
    return text.count(",") >= 2 or text.endswith(".") or len(text.split()) >= _DESCRIPTION_WORDS


def name_by_title(rows: Sequence[Row], blocks: Sequence[Block]) -> list[Row]:
    """(v7) A row named by its description takes the title line printed right above it.

    A small model drifts into naming dishes by the line just before the price when a
    description sits between the title and the price ("Lasagna Roll" / "Baked crab,
    avocado, cream cheese and sweet sauce." / "$11"). When the row's name is
    description-like and is its claimed block's text (prices aside), and the nearest
    non-blank block above is a short unpriced title line (at most six words, not
    description-like, outside page chrome, no section name the model gave) that no
    other row names, the row is renamed to that line and claims its block."""
    index = {b.id: i for i, b in enumerate(blocks)}
    prices = price_tokens(list(blocks))
    named = {row.claimed_block for row in rows if not _description_like(row.item)}
    sections = {frozenset(norm_tokens(row.section)) for row in rows if row.section}
    out: list[Row] = []
    for row in rows:
        pos = index.get(row.claimed_block or "")
        if pos is None or not _description_like(row.item):
            out.append(row)
            continue
        text = blocks[pos].text
        printed = set(norm_tokens(text)) - {
            t for tok in prices[pos] for t in norm_tokens(text[tok.start : tok.end])
        }
        above = pos - 1
        while above >= 0 and not blocks[above].text.strip(" ​ "):
            above -= 1
        title = blocks[above].text.strip() if above >= 0 else ""
        if (
            set(norm_tokens(row.item)) != printed
            or not title
            or prices[above]
            or blocks[above].in_chrome
            or frozenset(norm_tokens(title)) in sections
            or len(title.split()) > _TITLE_MAX_WORDS
            or _description_like(title)
            or blocks[above].id in named
        ):
            out.append(row)
            continue
        named.add(blocks[above].id)
        out.append(replace(row, item=title, claimed_block=blocks[above].id))
    return out
