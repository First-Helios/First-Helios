"""Stage [5]: the final gate. Deterministic static grounding checks, per the tracker.

For every extracted row (one item, one price) decide:

- ``accept``    — the item name and the price are both grounded in the page, the
                  price is bound to this item, and the row passes sanity checks;
- ``downgrade`` — the item name is grounded but its price is not: keep the item,
                  price becomes ``unknown`` (a priced row is never invented);
- ``reject``    — the item name is not on the page, or the row is insane
                  (duplicate, implausible amount, foreign currency).

Checks (tracker §[5]):

1. **Name grounding** — the name's word tokens (case/whitespace/punctuation-
   insensitive, a few connector words ignored) are a subset of one block's
   tokens. ``fuzzy=True`` also allows one edit on tokens of ≥5 characters; it is
   off by default and measured separately.
2. **Price grounding** — the normalized amount occurs as a price token in the
   item's *own region*: its block (after the name span) and the nearest run of
   price blocks after it, before the next extracted item or a price-less heading
   (v2; v1 used a fixed 4-block window), or a price-only block immediately before
   it (price-first layouts), or the nearest preceding section heading that has
   words (a shared "all tacos $3" price).
3. **Binding** — the price occurrence chosen is the nearest matching one in
   document order, and one occurrence is bound to one item only, unless it sits
   in a heading/section block (a deliberate shared price). A row with a variant
   ("SM", "Large") must have that label printed just before the price.
4. **Sanity** — USD only; 0.10 ≤ amount ≤ 500; no duplicate (item, variant,
   price, section) rows; each accepted field records its evidence locator
   ``(block_id, start, end)``.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from spikes.menu_model.segment import Block

SCAN = 15  # v2: max blocks scanned after a name for its nearest price run (v1: fixed window 4)
MIN_AMOUNT, MAX_AMOUNT = Decimal("0.10"), Decimal("500")
IGNORED_TOKENS = frozenset({"and", "the", "a", "of", "with", "w", "n"})

# $12 | $12.50 | $ 12,50 | 12.50 | 12,50 ; bare integers handled separately
_MONEY = re.compile(
    r"(?P<cur>\$)\s?(?P<a>\d{1,3}(?:,\d{3})*|\d+)(?:[.,](?P<c>\d{2}))?(?!\d)"
    r"|(?<![\w$.,])(?P<a2>\d{1,3})[.,](?P<c2>\d{2})(?![\d%])"
)
_BARE_INT = re.compile(r"(?<![\w$.,:/-])(\d{1,3})(?![\w.,:%/])")
_WORD = re.compile(r"\w+", re.UNICODE)

Decision = Literal["accept", "downgrade", "reject"]


@dataclass(frozen=True, slots=True)
class PriceToken:
    block_index: int
    start: int
    end: int
    amount: Decimal
    kind: str  # "money" ($ or decimals) | "bare" (a trailing/sole integer)


@dataclass(frozen=True, slots=True)
class Row:
    item: str
    amount: str | None  # as extracted, e.g. "12.50"; None = extractor gave no price
    variant: str | None = None
    section: str | None = None
    currency: str = "USD"
    claimed_block: str | None = None  # the extractor's own evidence claim, a hint only


@dataclass(slots=True)
class Verdict:
    row: Row
    decision: Decision
    reasons: list[str] = field(default_factory=list)
    name_evidence: tuple[str, int, int] | None = None
    price_evidence: tuple[str, int, int] | None = None


def norm_tokens(text: str) -> list[str]:
    text = unicodedata.normalize("NFKC", text).lower().replace("&", " and ")
    return [t for t in _WORD.findall(text) if t not in IGNORED_TOKENS]


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
        return None


def price_tokens(blocks: list[Block]) -> list[list[PriceToken]]:
    """Price occurrences per block. Bare integers count only as a block's last token."""
    out: list[list[PriceToken]] = []
    for i, b in enumerate(blocks):
        toks: list[PriceToken] = []
        for m in _MONEY.finditer(b.text):
            whole = (m.group("a") or m.group("a2") or "0").replace(",", "")
            cents = m.group("c") or m.group("c2") or "00"
            toks.append(PriceToken(i, m.start(), m.end(), Decimal(f"{whole}.{cents}"), "money"))
        if not toks:
            bare = list(_BARE_INT.finditer(b.text))
            if bare and not b.text[bare[-1].end() :].strip(" .-–—|"):
                m = bare[-1]
                toks.append(PriceToken(i, m.start(), m.end(), Decimal(m.group(1)) * 1, "bare"))
        out.append(toks)
    return out


def _edit1(a: str, b: str) -> bool:
    if abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        return sum(x != y for x, y in zip(a, b, strict=True)) <= 1
    short, long_ = (a, b) if len(a) < len(b) else (b, a)
    return any(long_[:k] + long_[k + 1 :] == short for k in range(len(long_)))


def _grounds(name_toks: list[str], block_toks: set[str], *, fuzzy: bool) -> bool:
    if not name_toks:
        return False
    for t in name_toks:
        if t in block_toks:
            continue
        if fuzzy and len(t) >= 5 and any(_edit1(t, u) for u in block_toks if len(u) >= 4):  # noqa: PLR2004
            continue
        return False
    return True


def _name_span(block: Block, name_toks: list[str]) -> tuple[int, int]:
    low = unicodedata.normalize("NFKC", block.text).lower()
    starts = [low.find(t) for t in name_toks if low.find(t) >= 0]
    ends = [low.find(t) + len(t) for t in name_toks if low.find(t) >= 0]
    return (min(starts), max(ends)) if starts else (0, len(block.text))


def _is_price_only(block: Block, toks: list[PriceToken]) -> bool:
    rest = block.text
    for t in sorted(toks, key=lambda t: -t.start):
        rest = rest[: t.start] + rest[t.end :]
    return bool(toks) and len(re.findall(r"[^\W\d_]", rest)) <= 12  # noqa: PLR2004 - "Small", "Lg"


def price_label(text: str, toks: list[PriceToken], tok: PriceToken) -> str:
    """The label printed with one price: a ``/Medium`` suffix ("$7.50/Medium"), else
    the text between the previous price in the block (or the block start) and it
    ("Half $14.95 | Whole $22.95").
    """
    suffix = re.match(r"/\s*([^|•$/\d\s][^|•$/]*|\d+\s*[^\W\d][^|•$/]*)", text[tok.end :])
    # v2: "Half $20.95/ Whole $41.95" - a label followed by a price belongs to that price
    if suffix and not re.match(r"\s*\$?\d", text[tok.end + suffix.end() :]):
        return suffix.group(1).strip()
    prev_end = max((t.end for t in toks if t.end <= tok.start), default=0)
    return text[prev_end : tok.start].strip(" |•-–—:,")


def _label_tokens(blocks: list[Block], prices: list[list[PriceToken]], tok: PriceToken) -> set[str]:
    return set(norm_tokens(price_label(blocks[tok.block_index].text, prices[tok.block_index], tok)))


def _variant_before(
    blocks: list[Block], prices: list[list[PriceToken]], tok: PriceToken, variant: str | None
) -> bool:
    """A variant ("SM", "Large", "sub shrimp") must be the label printed with its price."""
    if not variant:
        return True
    return set(norm_tokens(variant)) <= _label_tokens(blocks, prices, tok)


def _claimed_by_other(
    blocks: list[Block],
    prices: list[list[PriceToken]],
    tok: PriceToken,
    variant: str | None,
    others: set[str | None],
) -> bool:
    """This price's label names a different variant of the item, not this row's."""
    label = _label_tokens(blocks, prices, tok)
    own = set(norm_tokens(variant or ""))
    if own and own <= label:
        return False  # "X-Large" row on an "X-Large" price, even though "Large" ⊆ it
    return any(o and set(norm_tokens(o)) <= label for o in others)


def _sole_number(block: Block) -> bool:
    """A bare integer is a price only when it stands alone ("16"), not "Calories: 300"."""
    return re.fullmatch(r"\s*\d{1,3}\s*", block.text) is not None


def _price_run(
    blocks: list[Block],
    prices: list[list[PriceToken]],
    nb: int,
    item_blocks: set[int],
    *,
    inline: bool,
) -> list[PriceToken]:
    """The nearest run of price blocks after an item's name block (v2).

    With a price already in the name's block ("Fajita Quesadilla ... 11.99"), only
    immediately following price-only blocks join ("SUB SHRIMP 12.99"). Otherwise
    skip non-price blocks (descriptions, allergens, icons; at most ``SCAN`` of them)
    to the first price-bearing block and take the consecutive price blocks from
    there. The scan stops at another extracted item or at a price-less heading.
    """
    run: list[PriceToken] = []
    for j in range(nb + 1, min(nb + 1 + SCAN, len(blocks))):
        if j in item_blocks:
            break
        toks = [t for t in prices[j] if t.kind == "money" or _sole_number(blocks[j])]
        if inline or run:
            if toks and (not inline or _is_price_only(blocks[j], toks)):
                run.extend(toks)
                continue
            break
        if toks:
            run.extend(toks)
        elif blocks[j].heading:
            break
    return run


def validate(  # noqa: C901, PLR0912 - one linear pass mirroring the tracker's check list
    blocks: list[Block], rows: list[Row], *, fuzzy: bool = False
) -> list[Verdict]:
    block_toks = [set(norm_tokens(b.text)) for b in blocks]
    prices = price_tokens(blocks)
    index_of = {b.id: i for i, b in enumerate(blocks)}

    # Pass 1: name grounding. Choose, per row, the grounding block: the claimed one
    # if it grounds, else the first grounding block at/after the previous row's.
    name_block: list[int | None] = []
    cursor = 0
    for row in rows:
        toks = norm_tokens(row.item)
        cands = [i for i, bt in enumerate(block_toks) if _grounds(toks, bt, fuzzy=fuzzy)]
        claimed = index_of.get(row.claimed_block or "")
        if claimed is not None and claimed in cands:
            chosen: int | None = claimed
        else:
            after = [i for i in cands if i >= cursor]
            chosen = after[0] if after else (cands[0] if cands else None)
            # v2: image-alt text then the heading repeat the name; take the last copy
            while chosen is not None and chosen + 1 in cands:
                chosen += 1
        name_block.append(chosen)
        if chosen is not None:
            cursor = chosen
    item_blocks = {i for i in name_block if i is not None}
    # Name starts per block, so two items printed in one block ("Taco $3 Burrito $8")
    # each own only the prices between their name and the next item's name.
    starts_in: dict[int, list[int]] = {}
    for row, nb in zip(rows, name_block, strict=True):
        if nb is not None:
            starts_in.setdefault(nb, []).append(_name_span(blocks[nb], norm_tokens(row.item))[0])

    variants_of: dict[str, set[str | None]] = {}
    for row in rows:
        variants_of.setdefault(" ".join(norm_tokens(row.item)), set()).add(row.variant)

    verdicts: list[Verdict] = []
    bound: dict[tuple[int, int], int] = {}  # price occurrence -> row index
    seen_keys: set[tuple[str, str, str, str]] = set()
    for r_i, (row, nb) in enumerate(zip(rows, name_block, strict=True)):
        v = Verdict(row=row, decision="accept")
        verdicts.append(v)
        amount = parse_amount(row.amount)

        if nb is None:
            v.decision = "reject"
            v.reasons.append("name_not_grounded")
            continue
        block = blocks[nb]
        span = _name_span(block, norm_tokens(row.item))
        v.name_evidence = (block.id, *span)

        key = (" ".join(norm_tokens(row.item)), (row.variant or "").lower(), str(amount))
        # v2: the same dish listed in two sections is two placements, not a duplicate
        dup_key = (*key, (row.section or "").lower())
        if dup_key in seen_keys:
            v.decision = "reject"
            v.reasons.append("duplicate_row")
            continue
        seen_keys.add(dup_key)
        if row.currency.upper() != "USD":
            v.decision = "reject"
            v.reasons.append("currency")
            continue
        if amount is None:
            v.decision = "downgrade"
            v.reasons.append("no_price_extracted")
            continue
        if not MIN_AMOUNT <= amount <= MAX_AMOUNT:
            v.decision = "reject"
            v.reasons.append("implausible_amount")
            continue

        # The item's own region (v2): prices after the name in its block, then the
        # nearest run of price-bearing blocks after it, before the next item/heading.
        next_start = min((s for s in starts_in[nb] if s > span[0]), default=len(block.text))
        region = [t for t in prices[nb] if span[0] <= t.start < next_start]
        region.extend(_price_run(blocks, prices, nb, item_blocks, inline=bool(region)))
        if (  # price-first layout: only when nothing is priced after the name
            not region
            and nb > 0
            and nb - 1 not in item_blocks
            and nb - 2 not in item_blocks
            and _is_price_only(blocks[nb - 1], prices[nb - 1])
        ):
            region.extend(prices[nb - 1])
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
            v.decision = "downgrade"
            v.reasons.append("price_belongs_to_other_variant")
            continue
        match = next((t for t in same if _variant_before(blocks, prices, t, row.variant)), None)
        if match is None and same and row.variant:
            v.decision = "downgrade"
            v.reasons.append("variant_not_grounded")
            continue
        match = match or (same[0] if same else None)
        is_shared = False
        if match is None:
            match = next((t for t in shared if t.amount == amount), None)
            is_shared = match is not None
        if match is None:
            v.decision = "downgrade"
            v.reasons.append("price_not_grounded")
            continue
        occ = (match.block_index, match.start)
        if occ in bound and not is_shared and not blocks[match.block_index].heading:
            other = rows[bound[occ]]
            if other.item != row.item:  # variants of one item may share one printed price
                v.decision = "downgrade"
                v.reasons.append("price_bound_to_other_item")
                continue
        bound.setdefault(occ, r_i)
        v.price_evidence = (blocks[match.block_index].id, match.start, match.end)
        if is_shared:
            v.reasons.append("shared_section_price")
        if match.kind == "bare":
            v.reasons.append("bare_integer_price")
    return verdicts
