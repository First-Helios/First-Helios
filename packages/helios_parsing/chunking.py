"""Extractor input: a page's non-chrome blocks as ``bNNNN | text`` lines, in chunks.

Ported from ``spikes/menu_model/extract.py`` ``chunks`` (process v2.1, the
configuration ADR-0013 §1 measured): chunks of at most ``CHUNK_CHARS``
characters, cut before a heading block once a chunk passes ``CHUNK_SOFT``
characters. Every chunk after the first opens with a context line naming the
current heading and the last three lines before the cut, because a chunk that
started mid-section with no heading came back empty. Chrome blocks (nav, header,
footer, forms) are not sent; the validator still grounds over every block.

(v2.2) A block longer than ``BLOCK_CHARS`` is sent as several lines with its
block id, cut after a space, comma or "|"; v2.1 sent only its first
``BLOCK_CHARS`` characters, so a menu printed as one run-together block was
mostly never read. Pages whose blocks all fit get the same chunks as v2.1.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

    from packages.helios_parsing.segment import Block

CHUNK_CHARS = 1500
CHUNK_SOFT = CHUNK_CHARS * 4 // 5  # past this, cut before the next heading block
BLOCK_CHARS = 300  # a block's text is sent in lines of at most this many characters
CONTEXT_CHARS = 80  # heading and recent-line text carried in a context line
CONTEXT_LINES = 3
# Names what ``chunks`` returns for the same blocks; part of the pipeline version.
CHUNKER_VERSION = "chunk-v2.2"


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


def chunks(blocks: Sequence[Block]) -> list[str]:
    """The extractor's input chunks for one page, in page order."""
    out: list[str] = []
    cur: list[str] = []
    size = 0
    section = ""
    recent: list[str] = []  # texts of the last lines, carried as context (no block ids)
    for block in blocks:
        if block.in_chrome:
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
