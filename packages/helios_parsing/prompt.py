"""Extractor prompt v2.3, its compact GBNF grammar, the token cap and the sparse-chunk retry.

Ported from ``spikes/menu_model/extract.py`` with process v2 and prompt v2.3
hard-wired (ADR-0013 §1): the configuration measured on the Pi as ``st-v23``.
The llama-server client that sends them is ADR-0013 slice 5; everything here is
text in, text or numbers out.

- ``SYSTEM_PROMPT``: keyed items ``{"b","n","p","v"}`` grouped by section, and
  (v2.3) the rule that a name line and the price/description lines after it are
  one item, with a worked example in that layout.
- ``GRAMMAR``: GBNF passed to llama-server as ``grammar`` (not a JSON schema,
  whose ``pattern`` the server ignored). Compact JSON with no whitespace, a block
  id ``bNNNN``, a digits-only price with an optional ``$`` (forbidding it pushed
  ``$70.00`` into the variant), and a free variant string (forcing a letter into
  it derailed the model; ``output.rows_of`` cleans variants instead).
- ``token_cap``: the runaway guard, ~40 output tokens per input line.
- ``sparse_retry``: one deterministic re-ask for a chunk that prints prices but
  came back (nearly) empty; the grammar lets a model close the list at once.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from packages.helios_parsing.output import ExtractorOutput

SYSTEM_PROMPT = (
    "You extract restaurant menus. Input lines are 'BLOCK_ID | text' in page order. "
    "Return every menu item that is sold, grouped by the menu section it is under. "
    'Each item is {"b": block id where its name appears, "n": item name copied exactly as '
    'printed, "p": price copied exactly as printed, digits only (e.g. 12.50), "" if no price '
    'is printed for it, "v": size/variant word printed next to that price (e.g. "Large", '
    '"Glass"), only if there is one}. An item with several prices gets one entry per price. '
    "Many menus print one item over several lines: a short name line, then its price line "
    "and/or a description line, in either order. Those lines are ONE item: its name is the "
    "short name line (never the description sentence), its price comes from the price line "
    "after the name, and a price line or description line is never an item of its own. "
    "Do not invent items or prices, do not convert or compute prices, skip section headings, "
    "descriptions, navigation, hours, addresses, reviews and add-on/extra lines. "
    "If the text contains no menu items, return no sections. "
    "Output compact JSON on a single line with no spaces or newlines. Example input:\n"
    "b0011 | Tacos\nb0012 | Carne Asada Taco | $3.50\nb0014 | Horchata\nb0015 | $2.50/Small\n"
    "b0016 | $3.50/Large\nb0017 | Sides\nb0018 | CHIPS AND SALSA\nb0019 | $4\n"
    "b0020 | House-made chips, roasted tomato salsa.\nb0021 | Elote\n"
    "b0022 | Grilled corn, cotija, chile and lime.\nb0023 | 5.25\nExample output:\n"
    '{"sections":[{"section":"Tacos","items":[{"b":"b0012","n":"Carne Asada Taco","p":"3.50"},'
    '{"b":"b0014","n":"Horchata","p":"2.50","v":"Small"},{"b":"b0014","n":"Horchata","p":"3.50",'
    '"v":"Large"}]},{"section":"Sides","items":[{"b":"b0018","n":"CHIPS AND SALSA","p":"4"},'
    '{"b":"b0021","n":"Elote","p":"5.25"}]}]}'
)

GRAMMAR = r"""
root    ::= "{\"sections\":[" ( section ( "," section )* )? "]}"
section ::= "{\"section\":" str ",\"items\":[" ( item ( "," item )* )? "]}"
item    ::= "{\"b\":\"b" [0-9] [0-9] [0-9] [0-9] "\",\"n\":" str ",\"p\":\"" price "\"" ( ",\"v\":" vstr )? "}"
price   ::= ( "$"? [0-9] [0-9]? [0-9]? [0-9]? ( [.,] [0-9] [0-9]? )? )?
str     ::= "\"" chr{0,160} "\""
vstr    ::= "\"" vchr{0,40} "\""
chr     ::= [^"\\\x00-\x1f] | "\\" ["\\/nt]
vchr    ::= [^"\\\x00-\x1f]
"""

# The prompt, grammar, token cap and sparse retry together; part of the pipeline version.
PROMPT_VERSION = "prompt-v2.3"

MAX_TOKENS = 3072
TOKENS_PER_LINE = 40  # keyed rows need headroom over the ~30 of the first process
TOKENS_BASE = 64

SPARSE_MIN_PRICES = 3  # retry trigger: a chunk printing at least this many prices ...
SPARSE_RATIO = 1 / 3  # ... whose output holds fewer priced rows than this share of them

# A printed price in a block line: "$12", "$ 12.50", "12,50" (not a bare integer).
_PRICE_IN_LINE = re.compile(
    r"(?<![\w.])\$\s?\d{1,3}(?:[.,]\d{2})?(?!\d)|(?<![\w.$])\d{1,3}[.,]\d{2}(?!\d)"
)


def token_cap(chunk: str) -> int:
    """``max_tokens`` for one chunk: a runaway generation stops here."""
    return min(MAX_TOKENS, TOKENS_PER_LINE * (chunk.count("\n") + 1) + TOKENS_BASE)


def printed_prices(chunk: str) -> int:
    """Prices printed in the chunk's block lines (its context line is not counted)."""
    return sum(
        len(_PRICE_IN_LINE.findall(line)) for line in chunk.splitlines() if line.startswith("b")
    )


def sparse_retry(chunk: str, first: ExtractorOutput) -> str | None:
    """The user message for the one retry of a sparse chunk, or ``None`` for no retry.

    A chunk printing at least ``SPARSE_MIN_PRICES`` prices whose first output has
    fewer priced rows than ``SPARSE_RATIO`` of them is asked again once, with a
    nudge appended; the caller keeps the second output (and records the first).
    """
    n_prices = printed_prices(chunk)
    if n_prices >= SPARSE_MIN_PRICES and first.priced_rows < SPARSE_RATIO * n_prices:
        return (
            f"{chunk}\n\n(This text prints {n_prices} prices. List every sold item in it "
            "with its price; the price is often on the line after the name.)"
        )
    return None
