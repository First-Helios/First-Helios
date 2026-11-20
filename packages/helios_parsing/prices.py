"""Price occurrences in segmented blocks: the pipeline's price reader (v5-v7, v11-v13) and the frozen v4 one.

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
  a bare integer counts only as a block's last token; (v6) on a page that prints
  its prices bare (``bare_page``), that last integer may also follow a spaced dash
  ("peppers -13") or be glued to a word ("Cod Cakes16"), never on a page that marks
  its prices ("Margaritas & Cocktails16" over "$16" cards is a tab's item count).

A one-decimal amount needs a mark ("$", a currency word, an underscore): an
unmarked "6.2", "0.5 pounds" or "WCAG 2.1" is not a price; (v7) except on a bare
page, where a block's last one-decimal amount reads like its last integer ("6.5",
"salsa roja 7.5"), unless it is a parenthesized or percent figure ("( 6.2 % ABV)")
or a ".0" after words ("HAWAII 5.0").

(v11, ``validator-v11``, ADR-0013 Amendment 35) A bare reading is never taken from a numeric
table's cell. A block that prints only an unmarked number ("330", "4.5", "1,170") is a cell
when it sits in a table row: a run of at least :data:`TABLE_COLUMNS` such blocks right after
one label block, in a sequence of at least :data:`TABLE_ROWS` consecutive rows (a nutrition
table: a dish's name, then its servings, calories, fat, ...). A price column printed apart
from its names ("10", "19", "16" after a section's dishes) is one run per section, not rows
that each follow one label, and a glass/bottle or size table prints fewer columns than a
nutrition row. Blank blocks and mark cells (an allergen table's "X") neither join nor split a
run, and a table split by section headings keeps its column count (:func:`table_cells`). Marked
and decimal money is read as before, and cells don't vote in ``bare_page``.

(v12, ``validator-v12``, ADR-0013 Amendment 36) A bare reading is never taken right after a
calorie marker in its block: "cal 320", "Calories: 180", "kcal 450", "cal 400-800" and
"calories: 610 – 920" print energy, not a price. Such a number doesn't vote in ``bare_page``
either. Marked money is read as before ("Calories 320 $12.50" still reads $12.50). Nor is a
position counter a glass/bottle pair: a "k/n" block is a counter when its page prints "1/n",
"2/n" and "3/n" as blocks of their own (a carousel's "3/7", every k at most n;
:func:`position_counters`), while a pair repeated as "9/36" or "12/48" still reads.

(v13, ``validator-v13``, ADR-0029 D5) Nor from a numeric table's row
printed as one block: a block of at least :data:`TABLE_COLUMNS` number-only tokens that are at
least two thirds of its tokens ("670 380 42 3.5 0 300 1600 48 2 3 24" and "240 230 26 4.5 0 15
740 2 0 less than 1 g 1", a nutrition PDF's rows; mark tokens such as "-" or "X" don't count)
gives no bare reading and doesn't vote in ``bare_page`` (:func:`table_rows`). Its marked and
decimal money is read as before; a priced line with a few counts in it ("Party Pack 12 tacos 2
queso 1 rice 1 beans 1 salsa 45") still reads its last number.

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
# (v6) a block's last integer after a spaced dash ("peppers -13"; "8-12" stays a range)
# or glued to a word of two or more letters ("Cod Cakes16")
_BARE_INT_V6 = re.compile(r"(?:(?<=\s-)|(?<=[^\W\d_]{2}))(\d{1,3})(?![\w.,:%/])")
# (v7) on a bare page, a block's last one-decimal amount ("6.5", "salsa roja 7.5")
_BARE_DEC_V7 = re.compile(r"(?<![\w$.,:/(-])(\d{1,3}\.\d)(?![\w.,:%/])")
_LETTER = re.compile(r"[^\W\d_]")
# (v11) a block that prints only an unmarked number: a numeric table's cell candidate
_NUMBER_ONLY = re.compile(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:[.,]\d+)?")
_DIGIT = re.compile(r"\d")
# (v12) a calorie marker right before a number, optionally a range's first number between them:
# "cal 320", "Calories: 180", "kcal 450", "cal 400-", "calories: 610 – "
_CALORIE_BEFORE = re.compile(
    r"(?<![^\W\d_])(?i:k?cals?|calories|calorie)\.?\s*:?\s*(?:\d{1,4}\s*[-–/]\s*)?$"
)
# (v12) a block that prints one "k/n": a position counter candidate ("3/7")
_COUNTER = re.compile(r"\s*(\d{1,3})\s*/\s*(\d{1,3})\s*")
TABLE_COLUMNS = 6  # (v11) cells in a numeric table's row, at least
TABLE_ROWS = 3  # (v11) consecutive rows that make a numeric table, at least

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


def _last_bare(text: str, forms: tuple[re.Pattern[str], ...]) -> re.Match[str] | None:
    """The block's last bare integer when nothing but punctuation follows it."""
    found = [m for form in forms for m in form.finditer(text)]
    last = max(found, key=lambda m: m.start(), default=None)
    return last if last is not None and not text[last.end() :].strip(" .-–—|") else None


def _calorie(text: str, match: re.Match[str]) -> bool:
    """(v12) A calorie marker comes right before this number in its block ("cal 320")."""
    return bool(_CALORIE_BEFORE.search(text[: match.start()]))


def bare_page(blocks: list[Block], cells: frozenset[int] | None = None) -> bool:
    """(v6) The page prints its prices bare: more blocks end in a bare integer (any form)
    than print a marked or decimal price, chrome included; (v11, v13) a numeric table's cells
    and rows (``cells``, :func:`numeric_cells` when not given) don't vote."""
    cells = numeric_cells(blocks) if cells is None else cells
    marked = bare = 0
    for index, block in enumerate(blocks):
        if read_money(block.text):
            marked += 1
        elif (
            index not in cells
            and (last := _last_bare(block.text, (_BARE_INT, _BARE_INT_V6)))
            and not _calorie(block.text, last)
        ):
            bare += 1
    return bare > marked


def _blank(block: Block) -> bool:
    return not block.text.strip(" ​ ")


def table_cells(blocks: list[Block]) -> frozenset[int]:
    """(v11) The indexes of the blocks that are a numeric table's cells (module docstring).

    Runs are maximal sequences of number-only blocks; blank blocks and mark cells (at most two
    characters and no digit: an allergen table's "X", a "✓", a "-") are skipped. A row is a
    run of at least ``TABLE_COLUMNS`` with a label block before it; the next row follows when
    exactly one other block (its label) separates the two runs. At least ``TABLE_ROWS`` rows
    in a sequence are a table.
    """
    runs: list[tuple[int, list[int]]] = []  # (non-number blocks before the run, its cells)
    gap, cells = 0, []
    for index, block in enumerate(blocks):
        text = block.text.replace("\u200b", "").strip()
        if len(text) <= 2 and not _DIGIT.search(text):  # blank or a mark cell
            continue
        if _NUMBER_ONLY.fullmatch(text):
            cells.append(index)
            continue
        if cells:
            runs.append((gap, cells))
            gap, cells = 0, []
        gap += 1
    if cells:
        runs.append((gap, cells))
    widths: set[int] = set()  # the column counts of the tables found
    table: list[list[int]] = []
    for before, run in [*runs, (0, [])]:  # the sentinel ends the last table
        row = before >= 1 and len(run) >= TABLE_COLUMNS
        if row and table and before == 1:
            table.append(run)
            continue
        if len(table) >= TABLE_ROWS:
            widths.update(len(row_cells) for row_cells in table)
        table = [run] if row else []
    # a table split by section headings keeps its column count: every labelled run of a
    # table's width is one of its rows, also in a section of one or two rows
    return frozenset(
        i
        for before, run in runs
        if before >= 1 and len(run) >= TABLE_COLUMNS and len(run) in widths
        for i in run
    )


def _number_row(text: str) -> bool:
    """(v13) ``text`` prints at least ``TABLE_COLUMNS`` number-only tokens, and they are at
    least two thirds of its tokens; mark tokens (at most two characters, no digit) don't count."""
    numbers = others = 0
    for part in text.replace("\u200b", " ").split():
        if _NUMBER_ONLY.fullmatch(part):
            numbers += 1
        elif len(part) > 2 or _DIGIT.search(part):
            others += 1
    return numbers >= TABLE_COLUMNS and numbers >= 2 * others


def table_rows(blocks: list[Block]) -> frozenset[int]:
    """(v13) The indexes of the blocks that print a numeric table's row on their own."""
    return frozenset(index for index, block in enumerate(blocks) if _number_row(block.text))


def numeric_cells(blocks: list[Block]) -> frozenset[int]:
    """(v11, v13) The blocks that give no bare reading: table cells and one-block table rows."""
    return table_cells(blocks) | table_rows(blocks)


def position_counters(blocks: list[Block]) -> frozenset[int]:
    """(v12) The indexes of a page's position-counter blocks: "k/n" blocks (k at most n) whose
    n the page also prints as "1/n", "2/n" and "3/n" blocks (a carousel's slide numbers)."""
    seen: dict[int, set[int]] = {}
    found: list[tuple[int, int]] = []
    for index, block in enumerate(blocks):
        if (m := _COUNTER.fullmatch(block.text)) and int(m.group(1)) <= int(m.group(2)):
            seen.setdefault(int(m.group(2)), set()).add(int(m.group(1)))
            found.append((index, int(m.group(2))))
    counted = {n for n, ks in seen.items() if {1, 2, 3} <= ks}
    return frozenset(index for index, n in found if n in counted)


def _neighbour(blocks: list[Block], index: int, step: int) -> str:
    """The nearest non-blank block's text before (step -1) or after (step 1) ``index``."""
    index += step
    while 0 <= index < len(blocks) and _blank(blocks[index]):
        index += step
    return blocks[index].text.strip() if 0 <= index < len(blocks) else ""


def _bare_decimal(blocks: list[Block], index: int) -> re.Match[str] | None:
    """(v7) The block's last one-decimal amount on a bare page, unless it is a parenthesized
    or percent figure ("( 6.2 % ABV)" printed over three blocks is a strength), or a ".0"
    after words ("HAWAII 5.0", a name; a sole "12.0" line still reads)."""
    text = blocks[index].text
    last = _last_bare(text, (_BARE_DEC_V7,))
    if last is None or text[last.end() :].lstrip().startswith("%") or _calorie(text, last):
        return None
    if _neighbour(blocks, index, 1).startswith("%") or _neighbour(blocks, index, -1).endswith("("):
        return None
    if last.group(1).endswith(".0") and _LETTER.search(text[: last.start()]):
        return None
    return last


def _tokens(blocks: list[Block], money: Reader, *, v6: bool = False) -> list[list[PriceToken]]:
    out: list[list[PriceToken]] = []
    cells = numeric_cells(blocks) if v6 else frozenset()  # (v11, v13) the pipeline's reader only
    counters = position_counters(blocks) if v6 else frozenset()  # (v12) likewise
    bare = v6 and bare_page(blocks, cells)
    forms = (_BARE_INT, _BARE_INT_V6) if bare else (_BARE_INT,)
    for index, block in enumerate(blocks):
        tokens = [
            PriceToken(index, start, end, amount, "money")
            for start, end, amount in money(block.text)
        ]
        if index in cells:  # (v11, v13) a numeric table's cell or row: its money only
            out.append(tokens)
            continue
        if not tokens and index not in counters and _BARE_PAIR.fullmatch(block.text):
            tokens.extend(
                PriceToken(index, m.start(), m.end(), Decimal(m.group(0)), "bare")
                for m in re.finditer(r"\d{1,3}", block.text)
            )
        if (
            not tokens
            and (last := _last_bare(block.text, forms))
            and not (v6 and _calorie(block.text, last))  # (v12) the pipeline's reader only
        ):
            tokens.append(
                PriceToken(index, last.start(), last.end(), Decimal(last.group(1)), "bare")
            )
        if not tokens and bare and (dec := _bare_decimal(blocks, index)):
            tokens.append(PriceToken(index, dec.start(), dec.end(), Decimal(dec.group(1)), "bare"))
        out.append(tokens)
    return out


def price_tokens(blocks: list[Block]) -> list[list[PriceToken]]:
    """Price occurrences per block, in block order (the pipeline's reader, v13)."""
    return _tokens(blocks, read_money, v6=True)


def price_tokens_v4(blocks: list[Block]) -> list[list[PriceToken]]:
    """The v4 reader, frozen for the page classifier's features (classifier-v2)."""
    return _tokens(blocks, _money)
