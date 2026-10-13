"""Extractor input: a page's non-chrome blocks as ``bNNNN | text`` lines, in chunks.

Ported from ``spikes/menu_model/extract.py`` ``chunks`` (process v2.1, the
configuration ADR-0013 §1 measured): chunks of at most ``CHUNK_CHARS``
characters, cut before a heading block once a chunk passes ``CHUNK_SOFT``
characters. Every chunk after the first opens with a context line naming the
current heading and the last three lines before the cut, because a chunk that
started mid-section with no heading came back empty. Chrome blocks (nav, header,
footer, forms) are not sent, except (v2.3) a short priced run inside the body; the
validator still grounds over every block.

(v2.2) A block longer than ``BLOCK_CHARS`` is sent as several lines with its
block id, cut after a space, comma or "|"; v2.1 sent only its first
``BLOCK_CHARS`` characters, so a menu printed as one run-together block was
mostly never read. Pages whose blocks all fit get the same chunks as v2.1.

(v2.3) A short run of chrome blocks between body blocks is sent when it prints a
marked price: card layouts that wrap each card's name, price and an
"Ingredients" toggle in a button (the model saw only the descriptions and named
every item by its description). Price marks are read with the frozen v4 reader
(``price_tokens_v4``), so a later change to the pipeline's price reader can't
change the chunks. Pages without such a run get the same chunks as v2.2.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

    from packages.helios_parsing.segment import Block

from packages.helios_parsing.prices import price_tokens_v4

CHUNK_CHARS = 1500
CHUNK_SOFT = CHUNK_CHARS * 4 // 5  # past this, cut before the next heading block
BLOCK_CHARS = 300  # a block's text is sent in lines of at most this many characters
CONTEXT_CHARS = 80  # heading and recent-line text carried in a context line
CONTEXT_LINES = 3
CHROME_RUN = 4  # (v2.3) longest run of chrome blocks inside the body that is sent
# Names what ``chunks`` returns for the same blocks; part of the pipeline version.
CHUNKER_VERSION = "chunk-v2.3"


def pieces(text: str) -> list[str]:
    """(v2.2) A block's text in pieces of at most ``BLOCK_CHARS`` characters, each cut
    after the last space, comma or "|" that fits (never between "$" and its amount)."""
    out: list[str] = []
    while len(text) > BLOCK_CHARS:
        cut = max(text.rfind(sep, 1, BLOCK_CHARS) for sep in (" ", ",", "|"))
        while cut > 0 and text[cut] == " " and text[cut - 1] == "$":
            cut = max(text.rfind(sep, 1, cut) for sep in (" ", ",", "|"))
        end = cut + 1 if cut > 0 else BLOCK_CHARS
        out.append(text[:end].rstrip())
        text = text[end:].lstrip()
    out.append(text)
    return out


def sent_chrome(blocks: Sequence[Block]) -> set[int]:
    """(v2.3) Chrome blocks that are sent: each run of at most ``CHROME_RUN`` chrome
    blocks with a body block before and after it, when one of them prints a marked
    price ("$16")."""
    prices = price_tokens_v4(list(blocks))
    out: set[int] = set()
    i = 0
    while i < len(blocks):
        if not blocks[i].in_chrome:
            i += 1
            continue
        end = i
        while end < len(blocks) and blocks[end].in_chrome:
            end += 1
        run = range(i, end)
        if (
            i > 0
            and end < len(blocks)
            and len(run) <= CHROME_RUN
            and any(t.kind == "money" for k in run for t in prices[k])
        ):
            out.update(run)
        i = end
    return out


def chunks(blocks: Sequence[Block]) -> list[str]:
    """The extractor's input chunks for one page, in page order."""
    sent = sent_chrome(blocks)
    out: list[str] = []
    cur: list[str] = []
    size = 0
    section = ""
    recent: list[str] = []  # texts of the last lines, carried as context (no block ids)
    for index, block in enumerate(blocks):
        if block.in_chrome and index not in sent:
            continue
        for n, piece in enumerate(pieces(block.text)):
            line = f"{block.id} | {piece}"
            hard = size + len(line) + 1 > CHUNK_CHARS
            soft = n == 0 and block.heading and size > CHUNK_SOFT
            if cur and (hard or soft):
                out.append("\n".join(cur))
                before = " / ".join(f"'{text}'" for text in recent[-CONTEXT_LINES:])
                context = (
                    f"(continued from earlier on this page; heading: '{section}'; "
                    f"it ended with: {before})"
                )
                cur, size = [context], len(context)
            if n == 0:
                if block.heading:
                    section = block.text[:CONTEXT_CHARS]
                recent.append(block.text[:CONTEXT_CHARS])
            cur.append(line)
            size += len(line) + 1
    if cur:
        out.append("\n".join(cur))
    return out
