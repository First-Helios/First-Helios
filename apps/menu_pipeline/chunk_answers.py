"""Chunk-answer reuse keys (ADR-0013 Amendment 37 stage 1, session P8-25).

A saved answer is reused per chunk, not only per page: a chunk is looked up by
the extractor version and the sha256 of its text exactly as sent (chunk-v2.3,
page-wide block ids included). A hit gives the model's input word for word, so
the saved answer is used as it is, as page-level reuse does for a whole page.

Only exact text (owner decision on #173, 2026-11-21). Renumbering block ids
chunk-locally would reuse more (P8-24: 0.410 of the Pi's model time vs 0.231),
but the P8-25 laptop-GPU gate showed the model's answers depend on the ids:
the same chunk with other ids differed from a fresh answer about 3x more than
two fresh answers did.
"""

from __future__ import annotations

import hashlib

CHUNK_FORMAT = "menu-chunk-v1"


def chunk_key(chunk: str) -> str:
    """The reuse key's text part: sha256 hex of the chunk as sent to the model."""
    return hashlib.sha256(chunk.encode("utf-8")).hexdigest()
