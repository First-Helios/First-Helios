"""Chunk-answer reuse keys (ADR-0013 Amendment 37 stage 1, session P8-25).

A saved answer is reused per chunk, not only per page: a chunk is looked up by
the extractor version and the sha256 of its text with every page-wide block id
(``b0123 | …``) replaced by a chunk-local one (``k0``, ``k1``, … in order of
first appearance; the pieces of one long block share one). One block inserted
near the top of a page renumbers every later line, so equal chunks no longer
matched word for word (P8-24: 0.231 of the Pi's model time reused exactly,
0.410 renumbered).

On a hit the saved answer's ``"b"`` ids are mapped back through the two chunks'
id lists: the n-th distinct id of the saved chunk becomes the n-th of the new
one. The renumbered texts are equal, so the map is one-to-one. An answer citing
an id outside its own chunk can't be mapped and is not reused (the chunk goes to
the model). The chunker, the prompt and every miss's input are unchanged, so the
extractor version stays the same; the validator grounds every reused row in the
new page's blocks, as for any answer.
"""

from __future__ import annotations

import hashlib
import re

CHUNK_FORMAT = "menu-chunk-v1"
_ID = re.compile(r"^b\d{4,}(?= \| )", re.MULTILINE)  # a chunk line's block id
_CITED = re.compile(r'("b"\s*:\s*")([^"\\]*)(")')  # an answer item's block id


def block_ids(chunk: str) -> list[str]:
    """The chunk's distinct block ids, in order of first appearance."""
    return list(dict.fromkeys(_ID.findall(chunk)))


def renumbered(chunk: str) -> str:
    """The chunk with its block ids replaced by chunk-local ones (``k0``, ``k1``, …)."""
    local: dict[str, str] = {}
    return _ID.sub(lambda m: local.setdefault(m.group(0), f"k{len(local)}"), chunk)


def chunk_key(chunk: str) -> str:
    """The reuse key's text part: sha256 hex of the renumbered chunk."""
    return hashlib.sha256(renumbered(chunk).encode("utf-8")).hexdigest()


def remap(raw: str, saved_ids: list[str], ids: list[str]) -> str | None:
    """``raw`` (an answer to a chunk with ``saved_ids``) with its ``"b"`` ids moved to
    ``ids``; ``None`` when it cites an id outside its chunk or the lists differ in length."""
    if len(saved_ids) != len(ids):
        return None
    to_new = dict(zip(saved_ids, ids, strict=True))
    if any(m.group(2) not in to_new for m in _CITED.finditer(raw)):
        return None
    return _CITED.sub(lambda m: m.group(1) + to_new[m.group(2)] + m.group(3), raw)
