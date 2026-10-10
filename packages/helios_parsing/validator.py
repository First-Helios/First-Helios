"""Stage [5] validator v5: static grounding checks on extracted rows (ADR-0013 §1, §5).

Ported from ``spikes/menu_model/validator.py`` as frozen at spike commit
``e6e4e1f`` with ``MENU_SPIKE_VALIDATOR=v3``; the per-row decisions are the
spike's, with the v4 changes tuned on the P5-5 findings (session P5-7) and the
v5 changes tuned on the P5-8 findings (session P5-9) marked below. Prices are
read by ``prices.price_tokens`` (v5: currency words, cents, "$.40", "_12"). Every row (one item, at most one price) gets one decision:

- ``accept``: the name and the price are grounded on the page, the price is
  bound to this item, and the row passes the sanity checks;
- ``downgrade``: the name is grounded but the price is not; the item is kept
  and its price becomes unknown (a priced row is never invented);
- ``reject``: the name is not on the page, or the row is a duplicate, has an
  implausible amount or a foreign currency.

Checks:

1. **Name grounding.** The name's word tokens (case/punctuation-insensitive, a
   few connector words ignored, a dietary mark glued on allowed: "Eggplantv")
   are a subset of one block's tokens; (v5) an underscore separates words
   ("Patacones_12"), and a name printed again right below (image alt text, then
   a card's heading) is grounded at its last copy.
2. **Price grounding.** The amount occurs as a price token in the item's own
   region: its block after the name, then the nearest run of price blocks after
   it before the next extracted item or a price-less heading; or a price-only
   block just before it (price-first layouts); or the nearest preceding section
   heading with words (a shared "all tacos $3" price). (v4) A price printed
   with a leading plus ("+$2") is a modifier's and grounds no item price
   (``addon_price``); on pages that print each price above the name and again
   below it, the run ends after the item's own lower copy. (v5) "add $.95" is a
   modifier's price too and starts no run, unless the row is that add-on on its own
   line ("Add Sauerkraut +1"); a "/" or "—" block inside a run doesn't end it
   ("9" "/" "11"); names joined by "," / "&" in a one-price row share the price
   ("sidral, sangría, topo chico $3.25").
3. **Binding.** The nearest matching occurrence in document order, one
   occurrence per item unless it sits in a heading. A row's variant ("SM",
   "Large") must be the label printed with its price; (v4) a spaced unit suffix
   is a label too ("$18.00 / LB.", "$32.00 / 12 pcs"); (v5) so are a label in
   parentheses after the price ("$6.99 (Sm)"), a unit glued to it ("$9gl") and a
   column header printed over a section's price columns ("16oz / 20oz /
   Pitcher" over "$8 / $9.95 / $24.95").
4. **Sanity.** USD only; 0.10 <= amount <= 500; no duplicate (item, variant,
   price, section, name block) rows: a dish printed again in another inline menu is
   another placement (v4).

Each grounded field carries a Capture-targeted Evidence locator
``blocks:<segmenter version>:<block id>[<start>:<end>]`` and its ``excerpt_hash``
(ADR-0013 §5). The page flag ``unlabeled_price_runs`` marks pages that print
unlabeled size-price runs, where swapped prices can't be told apart by text.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Literal

from packages.helios_parsing.prices import PriceToken, price_tokens, read_amount
from packages.helios_parsing.segment import SEGMENTER_VERSION

if TYPE_CHECKING:
    from packages.helios_parsing.segment import Block

VALIDATOR_VERSION = "validator-v5"  # part of the pipeline version
SCAN = 15  # max blocks scanned after a name for its nearest price run
MIN_AMOUNT, MAX_AMOUNT = Decimal("0.10"), Decimal("500")
IGNORED_TOKENS = frozenset({"and", "the", "a", "of", "with", "w", "n"})

# Unpriced extracted "items" that are really description or nutrition lines ("an even
# better twist on the classic", "Calories: 260", "Alergens:") don't end a price scan.
_NOT_ITEM = re.compile(
    r"^[a-z]|:$|^(?i:calories|fat|carbohydrates|protein|allergens?|alergens)\b"
    r"|^(?:\S+\s+){5,}\S+\.$"  # a 6+ word sentence ending in "."
)
_BARE_PAIR = re.compile(r"\s*\d{1,3}(?:\s*/\s*\d{1,3})+\s*")  # "11 / 44"
_DIET_MARKS = ("v", "vg", "gf", "df")  # glued to a name, "Classicv"
_JOINED = re.compile(r"\s*(?:,|&|\band\b)\s*", re.IGNORECASE)  # "A, B & C $3"; not "A or B"
_WORD = re.compile(r"\w+", re.UNICODE)
_LETTER = re.compile(r"[^\W\d_]")

Decision = Literal["accept", "downgrade", "reject"]


@dataclass(frozen=True, slots=True)
class Row:
    """One extracted row: an item with at most one price."""

    item: str
    amount: str | None  # as extracted, e.g. "12.50"; None = no price extracted
    variant: str | None = None
    section: str | None = None
    currency: str = "USD"
    claimed_block: str | None = None  # the extractor's own block claim, a hint only


@dataclass(frozen=True, slots=True)
class Evidence:
    """A character span in one segmented block, citable from the Capture's bundle."""

    block_id: str
    start: int
    end: int
    locator: str
    excerpt_hash: str


@dataclass(frozen=True, slots=True)
class Verdict:
    row: Row
    decision: Decision
    reasons: tuple[str, ...] = ()
    name_evidence: Evidence | None = None
    price_evidence: Evidence | None = None


@dataclass(frozen=True, slots=True)
class Validation:
    verdicts: tuple[Verdict, ...]  # one per input row, in input order
    unlabeled_price_runs: bool


def evidence(block: Block, start: int, end: int) -> Evidence:
    """The Capture-targeted locator and excerpt hash of ``block.text[start:end]``."""
    excerpt = block.text[start:end]
    return Evidence(
        block_id=block.id,
        start=start,
        end=end,
        locator=f"blocks:{SEGMENTER_VERSION}:{block.id}[{start}:{end}]",
        excerpt_hash="sha256:" + hashlib.sha256(excerpt.encode("utf-8")).hexdigest(),
    )


def name_evidence(block: Block, name: str) -> Evidence:
    """The span of ``name``'s words in ``block``, as the validator cites a grounded name.

    Falls back to the whole block when normalization moved the offsets past the
    block's text (a ligature that NFKC expands), so a locator always fits its block.
    """
    start, end = _name_span(block, norm_tokens(name))
    if not 0 <= start < end <= len(block.text):
        start, end = 0, len(block.text)
    return evidence(block, start, end)


def norm_tokens(text: str) -> list[str]:
    text = unicodedata.normalize("NFKC", text).lower().replace("&", " and ")
    return [t for t in _WORD.findall(text) if t not in IGNORED_TOKENS]


def block_tokens(text: str) -> set[str]:
    """A block's name-grounding tokens; (v5) an underscore separates words, as it
    separates a price ("Patacones_12": image alt text)."""
    return set(norm_tokens(text.replace("_", " ")))


def parse_amount(value: str | None) -> Decimal | None:
    if value is None:
        return None
    cleaned = value.strip().replace("$", "").replace(" ", "")
    if re.fullmatch(r"\d+,\d{2}", cleaned):
        cleaned = cleaned.replace(",", ".")
    cleaned = cleaned.replace(",", "")
    try:
        return Decimal(cleaned).quantize(Decimal("0.01"))
    except InvalidOperation:
        pass
    amount = read_amount(value)  # (v5) a printed form: "12.5 USD", "50¢", "$.40"
    return amount.quantize(Decimal("0.01")) if amount is not None else None


def _grounds(name_toks: list[str], block_toks: set[str]) -> bool:
    if not name_toks:
        return False
    for t in name_toks:
        if t in block_toks or any(t + mark in block_toks for mark in _DIET_MARKS):
            continue
        return False
    return True


def _name_span(block: Block, name_toks: list[str]) -> tuple[int, int]:
    # Offsets into the NFKC-lowered text, as the spike computed them; they equal
    # offsets into ``block.text`` unless normalization changes the length.
    low = unicodedata.normalize("NFKC", block.text).lower()
    starts = [low.find(t) for t in name_toks if low.find(t) >= 0]
    ends = [low.find(t) + len(t) for t in name_toks if low.find(t) >= 0]
    return (min(starts), max(ends)) if starts else (0, len(block.text))


def _is_price_only(block: Block, toks: list[PriceToken]) -> bool:
    rest = block.text
    for t in sorted(toks, key=lambda t: -t.start):
        rest = rest[: t.start] + rest[t.end :]
    return bool(toks) and len(_LETTER.findall(rest)) <= 12  # "Small", "Lg"


# (v5) a label in parentheses right after a price: "$6.99 (Sm)", "29.95 (½ lb.)"
_PAREN_LABEL = re.compile(r"\s*\(\s*([^()$]*?[^\W\d_][^()$]*?)\s*\)")
_GLUED_LABEL = re.compile(r"[^\W\d_]+")  # (v5) a unit glued to its price: "$9gl"


def price_label(text: str, toks: list[PriceToken], tok: PriceToken) -> str:
    """The label printed with one price: a ``/Medium`` suffix ("$7.50/Medium",
    "$18.00 / LB.", "$32.00 / 12 pcs"), (v5) a parenthesized one ("$6.99 (Sm) /
    $8.99 (Lg)"), else the text between the previous price in the block (or the
    block start), past that price's own parenthesized label, and it ("Half $14.95 |
    Whole $22.95").
    """
    suffix = re.match(r"\s*/\s*([^|•$/\d\s][^|•$/]*|\d+\s*[^\W\d][^|•$/]*)", text[tok.end :])
    # "Half $20.95/ Whole $41.95": a label followed by a price belongs to that price
    if suffix and not re.match(r"\s*\$?\d", text[tok.end + suffix.end() :]):
        return suffix.group(1).strip()
    if glued := _GLUED_LABEL.match(text, tok.end):  # (v5) "$9gl | $32btl"
        return glued.group(0)
    prev_end = max((t.end for t in toks if t.end <= tok.start), default=0)
    if prev_end and (prev_suffix := _GLUED_LABEL.match(text, prev_end)):
        prev_end = min(prev_suffix.end(), tok.start)
    if prev_end and (prev_paren := _PAREN_LABEL.match(text, prev_end)):
        prev_end = min(prev_paren.end(), tok.start)
    before = text[prev_end : tok.start].strip(" |•-–—:,/")
    paren = _PAREN_LABEL.match(text, tok.end)
    if paren and not re.search(r"\w", before):  # "6” – $65 (8-12 servings)": "6”"
        return paren.group(1).strip()
    return text[prev_end : tok.start].strip(" |•-–—:,")


# (v5) price columns: "16oz / 20oz / Pitcher" printed once over rows like
# "LAGER $8 / $9.95 / $24.95", "HELLES — / $8.95 / —" or "9" "/" "11" "/" "-"
_SLOT_SEP = re.compile(r"\s*[/|]\s*")
_SEPARATOR = re.compile(r"\s*[/|•·]\s*")  # a block that only separates two prices
_PLACEHOLDER = re.compile(r"\s*[—–-]\s*")  # "—": nothing in this column
_DASH = re.compile(r"(?<![\w$])[—–-](?![\w$])")
_HEADER_PART = re.compile(r"[^\W_][^/|$]{0,19}")
_DIGIT = re.compile(r"\d")
COLUMN_SCAN = 200  # max blocks scanned up from a row for its column header (to a heading)


def _slot_block(block: Block, toks: list[PriceToken]) -> bool:
    return bool(_PLACEHOLDER.fullmatch(block.text)) or (
        len(toks) == 1 and _is_price_only(block, toks)
    )


def _row_slots(
    blocks: list[Block], prices: list[list[PriceToken]], tok: PriceToken
) -> tuple[int, int, int] | None:
    """(column of ``tok``, columns in its row, the row's first block), or None."""
    j = tok.block_index
    text, toks = blocks[j].text, prices[j]
    dash = _DASH.search(text)
    starts = [t.start for t in toks] + ([dash.start()] if dash else [])
    if len(toks) >= 2 or (toks and dash):  # one block: "LAGER $8 / $9.95 / $24.95"
        area = text[min(starts) :]
        parts = _SLOT_SEP.split(area)
        if len(parts) < 2 or not all(_PLACEHOLDER.fullmatch(p) or _DIGIT.search(p) for p in parts):
            return None  # every column holds a price or a dash
        return len(_SLOT_SEP.findall(text[min(starts) : tok.start])), len(parts), j
    if not _slot_block(blocks[j], toks):  # one value per block: "9" "/" "11" "/" "-"
        return None
    first = j
    while first > 0 and (
        _SEPARATOR.fullmatch(blocks[first - 1].text)
        or _slot_block(blocks[first - 1], prices[first - 1])
    ):
        first -= 1
    last = j
    while last + 1 < len(blocks) and (
        _SEPARATOR.fullmatch(blocks[last + 1].text)
        or _slot_block(blocks[last + 1], prices[last + 1])
    ):
        last += 1
    slots = [k for k in range(first, last + 1) if not _SEPARATOR.fullmatch(blocks[k].text)]
    if len(slots) < 2 or not any(
        _SEPARATOR.fullmatch(blocks[k].text) for k in range(first, last + 1)
    ):
        return None
    return slots.index(j), len(slots), first


def column_label(blocks: list[Block], prices: list[list[PriceToken]], tok: PriceToken) -> str:
    """(v5) The column header over a price printed in a row of price columns, or "".

    The nearest block above the row (up to ``COLUMN_SCAN``, not past a heading) that
    prints only short labels split by "/" or "|", as many as the row has columns.
    """
    row = _row_slots(blocks, prices, tok)
    if row is None:
        return ""
    column, columns, first = row
    for k in range(first - 1, max(-1, first - 1 - COLUMN_SCAN), -1):
        parts = _header_parts(blocks[k], prices[k])
        if parts:
            if len(parts) != columns or not _heads_rows(blocks, prices, k, columns):
                return ""
            return parts[column]
        if blocks[k].heading:
            return ""
    return ""


def _header_parts(block: Block, toks: list[PriceToken]) -> list[str]:
    """The labels of a column-header block ("16oz / 20oz / Pitcher"), else []."""
    if toks:
        return []
    parts = _SLOT_SEP.split(block.text.strip())
    if len(parts) >= 2 and all(
        _HEADER_PART.fullmatch(p) and _LETTER.search(p) and len(p.split()) <= 3 for p in parts
    ):
        return parts
    return []


def _heads_rows(blocks: list[Block], prices: list[list[PriceToken]], k: int, columns: int) -> bool:
    """A header heads at least two rows: two rows' worth of prices below it before the
    next heading or header-like line ("Tempranillo | Rioja, Spain" under one wine is not)."""
    seen = 0
    for j in range(k + 1, min(len(blocks), k + 1 + COLUMN_SCAN)):
        if blocks[j].heading or _header_parts(blocks[j], prices[j]):
            break
        seen += len(prices[j])
    return seen >= 2 * columns


def label_tokens(blocks: list[Block], prices: list[list[PriceToken]], tok: PriceToken) -> set[str]:
    """The words printed as one price's label: beside it, or (v5) as its column header."""
    beside = price_label(blocks[tok.block_index].text, prices[tok.block_index], tok)
    return set(norm_tokens(beside)) | set(norm_tokens(column_label(blocks, prices, tok)))


def _variant_before(
    blocks: list[Block], prices: list[list[PriceToken]], tok: PriceToken, variant: str | None
) -> bool:
    """A variant ("SM", "Large", "sub shrimp") must be the label printed with its price."""
    if not variant:
        return True
    return set(norm_tokens(variant)) <= label_tokens(blocks, prices, tok)


def _claimed_by_other(
    blocks: list[Block],
    prices: list[list[PriceToken]],
    tok: PriceToken,
    variant: str | None,
    others: set[str | None],
) -> bool:
    """This price's label names a different variant of the item, not this row's."""
    label = label_tokens(blocks, prices, tok)
    own = set(norm_tokens(variant or ""))
    if own and own <= label:
        return False  # "X-Large" row on an "X-Large" price, even though "Large" is in it
    return any(o and set(norm_tokens(o)) <= label for o in others)


def _sole_number(block: Block) -> bool:
    """A bare integer is a price only when it stands alone ("16", "11 / 44"), not
    in "Calories: 300"."""
    return bool(_BARE_PAIR.fullmatch(block.text)) or bool(
        re.fullmatch(r"\s*\d{1,3}\s*", block.text)
    )


def _run_tokens(blocks: list[Block], prices: list[list[PriceToken]], j: int) -> list[PriceToken]:
    return [t for t in prices[j] if t.kind == "money" or _sole_number(blocks[j])]


_ADDON_LEAD = re.compile(r"(?:\+|(?<![^\W\d_])add)\s*$", re.IGNORECASE)
_OWN_ADDON = re.compile(r"[\W_]*(?:add|\+)?[\W_]*", re.IGNORECASE)  # "Add Sauerkraut +1"


def is_addon(block: Block, tok: PriceToken) -> bool:
    """A price printed with a leading plus ("+$2", "vegan + $1") or (v5) right after
    "add" ("add $.95 per cake"): a modifier's price."""
    return bool(_ADDON_LEAD.search(block.text[: tok.start]))


def _price_run(
    blocks: list[Block],
    prices: list[list[PriceToken]],
    nb: int,
    item_blocks: set[int],
    *,
    inline: bool,
) -> list[PriceToken]:
    """The nearest run of price blocks after an item's name block.

    With a price already in the name's block ("Fajita Quesadilla ... 11.99"), only
    immediately following price-only blocks join ("SUB SHRIMP 12.99"). Otherwise
    skip non-price blocks (descriptions, allergens, icons; at most ``SCAN`` of them)
    to the first price-bearing block and take the consecutive price blocks from
    there. The scan stops at another extracted item or at a price-less heading.

    (v4) Pages that print every price twice, above the name and again below the
    description ("$4.00" / name / description / "$4.00" / "$5.00" / next name),
    put the next item's upper copy right after this item's lower one: when the
    run's first block repeats the price-only block just above the name, the run
    is that one block.
    """
    run: list[PriceToken] = []
    doubled = False  # the run's first block repeats the price printed just above the name
    for j in range(nb + 1, min(nb + 1 + SCAN, len(blocks))):
        if j in item_blocks:
            break
        toks = _run_tokens(blocks, prices, j)
        if inline or run:
            if doubled:
                break
            if toks and (not inline or _is_price_only(blocks[j], toks)):
                run.extend(toks)
                continue
            if _SEPARATOR.fullmatch(blocks[j].text) or _PLACEHOLDER.fullmatch(blocks[j].text):
                continue  # (v5) "9" "/" "11" "/" "-": one price column per block
            break
        if toks and all(is_addon(blocks[j], t) for t in toks):
            continue  # (v5) a modifier's price line ("add $.95 per cake") starts no run
        if toks:
            run.extend(toks)
            above = blocks[nb - 1].text.strip() if nb > 0 else None
            doubled = above == blocks[j].text.strip() and _is_price_only(
                blocks[nb - 1], prices[nb - 1]
            )
        elif blocks[j].heading:
            break
    return run


def unlabeled_price_runs(blocks: list[Block], prices: list[list[PriceToken]]) -> bool:
    """True when the page prints two different prices in a row with no label between
    them: "$2.85 | $3.65", "11 / 44", or "$3" and "$5" as adjacent price-only blocks.

    These are the size runs where text can't tell which price is which size, so a
    swapped extraction passes grounding (spike findings 3 and 9). Chrome blocks are
    skipped; they aren't extracted.
    """
    prev: PriceToken | None = None  # the last price of the previous price-only block
    for j, block in enumerate(blocks):
        toks = [] if block.in_chrome else _run_tokens(blocks, prices, j)
        for a, b in zip(toks, toks[1:], strict=False):
            if a.amount != b.amount and not _LETTER.search(block.text[a.end : b.start]):
                return True
        if not toks or not _is_price_only(block, toks):
            prev = None
            continue
        first = toks[0]
        if (
            prev is not None
            and prev.amount != first.amount
            and not _LETTER.search(blocks[prev.block_index].text[prev.end :])
            and not _LETTER.search(block.text[: first.start])
        ):
            return True
        prev = toks[-1]
    return False


def validate(blocks: list[Block], rows: list[Row]) -> Validation:
    """Decide every row against the page's segmented blocks (one linear pass)."""
    block_toks = [block_tokens(b.text) for b in blocks]
    prices = price_tokens(blocks)
    index_of = {b.id: i for i, b in enumerate(blocks)}

    # Pass 1: name grounding. Per row, the grounding block is the claimed one if it
    # grounds, else the first grounding block at/after the previous row's.
    name_block: list[int | None] = []
    cursor = 0
    for row in rows:
        toks = norm_tokens(row.item)
        cands = [i for i, bt in enumerate(block_toks) if _grounds(toks, bt)]
        claimed = index_of.get(row.claimed_block or "")
        if claimed is not None and claimed in cands:
            # (v5) the name printed again right below (image alt text, then the card's
            # heading): the item is its last copy
            while claimed + 1 < len(blocks) and block_toks[claimed + 1] == block_toks[claimed]:
                claimed += 1
            chosen: int | None = claimed
        else:
            after = [i for i in cands if i >= cursor]
            chosen = after[0] if after else (cands[0] if cands else None)
            # image-alt text then the heading repeat the name; take the last copy
            while chosen is not None and chosen + 1 in cands:
                chosen += 1
        name_block.append(chosen)
        if chosen is not None:
            cursor = chosen
    item_blocks = {i for i in name_block if i is not None}
    stop_blocks = {  # blocks that end another item's price scan
        i
        for row, i in zip(rows, name_block, strict=True)
        if i is not None and not (row.amount is None and _NOT_ITEM.search(row.item.strip()))
    }
    # Name starts per block, so two items printed in one block ("Taco $3 Burrito $8")
    # each own only the prices between their name and the next item's name.
    starts_in: dict[int, list[int]] = {}
    spans_in: dict[int, list[tuple[int, int]]] = {}
    for row, nb in zip(rows, name_block, strict=True):
        if nb is not None:
            name_span = _name_span(blocks[nb], norm_tokens(row.item))
            starts_in.setdefault(nb, []).append(name_span[0])
            spans_in.setdefault(nb, []).append(name_span)

    def joined_end(nb: int, span: tuple[int, int]) -> tuple[int, int]:
        """(v5) Names joined by "," / "&" / "and" in a block that prints one price,
        right after the last name ("sidral, sangría, topo chico $3.25"), share that
        price: (the group's first start, its last end). Otherwise the row's own span."""
        text = blocks[nb].text
        if len(prices[nb]) != 1:  # one row, one price; not run-together inline text
            return span
        ordered = sorted(set(spans_in[nb]))
        first, end = span
        for start, stop in reversed(ordered):  # back to the group's first name
            if stop <= first and _JOINED.fullmatch(text[stop:first]):
                first = start
        for start, stop in ordered:
            if start >= end and _JOINED.fullmatch(text[end:start]):
                end = stop
        priced_at = min((t.start for t in prices[nb] if t.start >= end), default=None)
        if priced_at is None or _LETTER.search(text[end:priced_at]):
            return span  # "A, B, C (with D) — each 11.99": not one priced name list
        return first, end

    variants_of: dict[str, set[str | None]] = {}
    for row in rows:
        variants_of.setdefault(" ".join(norm_tokens(row.item)), set()).add(row.variant)

    bound: dict[tuple[int, int], int] = {}  # price occurrence -> row index
    groups: dict[int, tuple[int, tuple[int, int]]] = {}  # row -> (name block, joined names)
    seen_keys: set[tuple[str, str, str, str, str]] = set()

    def judge(r_i: int, row: Row, nb: int | None) -> Verdict:
        if nb is None:
            return Verdict(row, "reject", ("name_not_grounded",))
        block = blocks[nb]
        span = _name_span(block, norm_tokens(row.item))
        named = evidence(block, *span)

        def downgrade(reason: str) -> Verdict:
            return Verdict(row, "downgrade", (reason,), named)

        amount = parse_amount(row.amount)
        key = (" ".join(norm_tokens(row.item)), (row.variant or "").lower(), str(amount))
        # the same dish listed in two sections, or printed again in another inline
        # menu (another name block), is two placements, not a duplicate
        dup_key = (*key, (row.section or "").lower(), str(nb))
        if dup_key in seen_keys:
            return Verdict(row, "reject", ("duplicate_row",), named)
        seen_keys.add(dup_key)
        if row.currency.upper() != "USD":
            return Verdict(row, "reject", ("currency",), named)
        if amount is None:
            return downgrade("no_price_extracted")
        if not MIN_AMOUNT <= amount <= MAX_AMOUNT:
            return Verdict(row, "reject", ("implausible_amount",), named)

        # The item's own region: prices after the name in its block, then the nearest
        # run of price-bearing blocks after it, before the next item/heading.
        group = joined_end(nb, span)
        next_start = min(
            (s for s in starts_in[nb] if s > span[0] and not (group != span and s < group[1])),
            default=len(block.text),
        )
        region = [t for t in prices[nb] if span[0] <= t.start < next_start]
        region.extend(_price_run(blocks, prices, nb, stop_blocks, inline=bool(region)))
        if (  # price-first layout: only when nothing is priced after the name
            not region
            and nb > 0
            and nb - 1 not in item_blocks
            and nb - 2 not in item_blocks
            and _is_price_only(blocks[nb - 1], prices[nb - 1])
        ):
            region.extend(prices[nb - 1])
        # (v4) a "+$2" price is an add-on or surcharge, never the item's own price;
        # (v5) unless the row is that add-on, its name printed right before it on its
        # own line ("Add Sauerkraut +1")
        addons = [
            t
            for t in region
            if is_addon(blocks[t.block_index], t)
            and not (
                t.block_index == nb
                and len(prices[nb]) == 1
                and _OWN_ADDON.fullmatch(block.text[span[1] : t.start])
            )
        ]
        region = [t for t in region if t not in addons]
        shared: list[PriceToken] = []
        for j in range(nb - 1, -1, -1):  # nearest preceding heading = section scope
            if blocks[j].heading and not _is_price_only(blocks[j], prices[j]):
                shared = [t for t in prices[j] if t.kind == "money"]
                break

        other_variants = variants_of[key[0]] - {row.variant}
        same = [
            t
            for t in region
            if t.amount == amount
            and not _claimed_by_other(blocks, prices, t, row.variant, other_variants)
        ]
        if not same and any(t.amount == amount for t in region):
            return downgrade("price_belongs_to_other_variant")
        match = next((t for t in same if _variant_before(blocks, prices, t, row.variant)), None)
        if match is None and same and row.variant:
            return downgrade("variant_not_grounded")
        match = match or (same[0] if same else None)
        is_shared = False
        if match is None:
            match = next((t for t in shared if t.amount == amount), None)
            is_shared = match is not None
        if match is None:
            if any(t.amount == amount for t in addons):
                return downgrade("addon_price")
            return downgrade("price_not_grounded")
        occ = (match.block_index, match.start)
        if (  # variants of one item may share one printed price
            occ in bound
            and not is_shared
            and not blocks[match.block_index].heading
            and rows[bound[occ]].item != row.item
            and not (group != span and groups.get(bound[occ]) == (nb, group))  # (v5) joined
        ):
            return downgrade("price_bound_to_other_item")
        bound.setdefault(occ, r_i)
        if group != span:
            groups[r_i] = (nb, group)
        reasons = ("shared_section_price",) if is_shared else ()
        if match.kind == "bare":
            reasons = (*reasons, "bare_integer_price")
        priced = evidence(blocks[match.block_index], match.start, match.end)
        return Verdict(row, "accept", reasons, named, priced)

    verdicts = tuple(
        judge(r_i, row, nb) for r_i, (row, nb) in enumerate(zip(rows, name_block, strict=True))
    )
    return Validation(verdicts, unlabeled_price_runs(blocks, prices))
