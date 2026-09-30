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
   price (small models lose the key order);
2. a variant with no letters ("4") is dropped: a bare number is not a size;
3. stitch v3 (``stitch.stitch``): split lines re-assembled into items, price
   fill, variant completion;
4. a variant whose words are all in the item name ("(L)" copied from "Orange
   Chicken (L)") is dropped: it was not printed with the price;
5. exact duplicates (same name tokens, variant, amount, section) collapse to one.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any

from packages.helios_parsing.stitch import stitch
from packages.helios_parsing.validator import Row, norm_tokens

if TYPE_CHECKING:
    from collections.abc import Sequence

    from packages.helios_parsing.segment import Block

# ``rows_of``'s repairs and stitch v3 together; part of the pipeline version.
REPAIRS_VERSION = "repairs-v3"

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
                if not price and _AMOUNT_ONLY.match(variant):
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
    seen: set[tuple[str, str | None, str | None, str | None]] = set()
    unique: list[Row] = []
    for row in rows:
        key = (" ".join(norm_tokens(row.item)), row.variant, row.amount, row.section)
        if key not in seen:
            seen.add(key)
            unique.append(row)
    return unique
