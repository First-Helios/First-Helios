"""Stage [5c] section assignment from page structure (ADR-0013 Amendment 28; session P8-12).

Generic and stdlib only: no per-site or per-platform rule. It runs after [5b]
(``resolve.judge``) and before ``menu_shape.shape``, on the ``llm`` stream only,
and changes nothing but which section a kept item is filed under:

- **Structure.** The page's HTML is re-parsed with a subclass of the segment-v2
  parser that also records each block's open elements (tag, class/id tokens and a
  node id each) and its ``h1``–``h6`` level. If the blocks it yields differ from
  the Version's blocks, nothing is assigned.
- **Candidate headings.** Non-chrome, unpriced blocks with a letter: the first
  block of an ``h1``–``h6`` element (at most :data:`MAX_HEADING_CHARS`), or a block
  whose own classes read as a heading or category title (:data:`_HEADING_CLASS`,
  none of :data:`_NOT_HEADING_CLASS`, at most :data:`MAX_CLASS_HEADING_CHARS`).
  A class token holding a uuid or a digit run is an instance id
  ("section-3eeb5dad-…"), not a role, and is ignored.
- **Section style.** A heading's layout signature is its last three block-level
  ancestors (tag and first class token, uuids and digit runs masked). A
  signature is a section style when at least half its headings, and at least
  :data:`MIN_SECTIONS`, enclose a kept item of another signature before the next
  heading of the same signature: Toast's group ``h3`` encloses dish ``h3``s, a dish
  ``h3`` encloses nothing of another layout, and a lone page title is no section.
- **Assignment.** A kept item's section is the nearest section-style heading
  before its name block.
- **Page gate.** At least :data:`MIN_ASSIGNED` of the page's kept items (name
  blocks) are assigned, and either at least :data:`MIN_WRAPPED` of them are
  *wrapped* (the lowest common ancestor of item and heading holds no other heading
  of that style) or one heading style serves them all. On an ungated page nothing
  is assigned, so its shape is byte-identical to the one without [5c].

Leaf sections only: no outline parent, no ``service_period``. The section shape
(key, name, Evidence on the heading block) is ``menu_shape``'s. Part of
``resolve.RESOLVER_VERSION`` ("resolve-v5" = [5b] + [5c] + [5d] + duplicate removal,
``page_template``).
"""

from __future__ import annotations

import bisect
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from packages.helios_parsing.prices import price_tokens
from packages.helios_parsing.segment import _HEADINGS, BLOCK_TAGS, _Segmenter

if TYPE_CHECKING:
    from collections.abc import Sequence

    from packages.helios_parsing.segment import Block
    from packages.helios_parsing.validator import Verdict

MAX_HEADING_CHARS = 160  # an h1-h6 heading's text
MAX_CLASS_HEADING_CHARS = 80  # a class-named heading's text
MIN_SECTIONS = 2  # headings of a section style that enclose items
MIN_ASSIGNED = 0.9  # page gate: share of kept items assigned
MIN_WRAPPED = 0.95  # page gate: share of assignments wrapped (else one style)
SIGNATURE_DEPTH = 3  # block-level ancestors in a layout signature

_UUID = re.compile(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", re.I)
_DIGITS = re.compile(r"\d+")
_HEADING_CLASS = re.compile(r"(?i)(categor|section|group|heading|header|title)")
_NOT_HEADING_CLASS = re.compile(
    r"(?i)(item|product|dish|price|desc|btn|button|nav|link|logo|page|site|hero|banner|footer)"
)
_LETTER = re.compile(r"[^\W\d_]")

Signature = tuple[tuple[str, str], ...]


@dataclass(frozen=True, slots=True)
class Placed:
    """A block with the DOM context segment-v2 drops."""

    block: Block
    level: int | None  # 1-6 inside h1-h6 (the innermost), else None
    heading_node: int | None  # node id of the innermost h1-h6 element
    stack: tuple[tuple[str, str], ...]  # (tag, class/id tokens) of open elements, outermost first
    node_ids: tuple[int, ...]  # one id per open element, parallel to ``stack``


class _PlacingSegmenter(_Segmenter):
    """segment-v2's parser, unchanged, recording each block's open elements."""

    def __init__(self) -> None:
        super().__init__()
        self.placed: list[Placed] = []
        self._ids: list[int] = []
        self._next_id = 0

    def _flush(self) -> None:
        before = len(self.blocks)
        super()._flush()
        if len(self.blocks) == before:
            return
        levels = [(int(t[1]), i) for i, (t, _, _) in enumerate(self._stack) if t in _HEADINGS]
        self.placed.append(
            Placed(
                block=self.blocks[-1],
                level=levels[-1][0] if levels else None,
                heading_node=self._ids[levels[-1][1]] if levels else None,
                stack=tuple((t, c) for t, c, _ in self._stack),
                node_ids=tuple(self._ids),
            )
        )

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        depth = len(self._stack)
        super().handle_starttag(tag, attrs)
        if len(self._stack) > depth:
            self._next_id += 1
            self._ids.append(self._next_id)

    def handle_endtag(self, tag: str) -> None:
        super().handle_endtag(tag)
        del self._ids[len(self._stack) :]


def placed_blocks(html: str) -> list[Placed]:
    """The page's segment-v2 blocks with their DOM context."""
    parser = _PlacingSegmenter()
    parser.feed(html)
    parser.close()
    return parser.placed


def _mask(token: str) -> str:
    return _DIGITS.sub("#", _UUID.sub("#", token))


def signature(placed: Placed) -> Signature:
    """The last block-level ancestors' tag and first class token, ids and digits masked."""
    ancestors = [(t, c) for t, c in placed.stack if t in BLOCK_TAGS][-SIGNATURE_DEPTH:]
    return tuple((t, _mask(c.split()[0]) if c else "") for t, c in ancestors)


def _own_classes(placed: Placed) -> str:
    """Class/id tokens of the innermost block ancestor and the inline elements inside it,
    without instance ids (a token holding a uuid or a digit run)."""
    inner = max((k for k, (t, _) in enumerate(placed.stack) if t in BLOCK_TAGS), default=0)
    return " ".join(
        token for _, c in placed.stack[inner:] for token in c.split() if "#" not in _mask(token)
    )


def _candidate(placed: Sequence[Placed], priced: Sequence[bool], j: int) -> bool:
    here = placed[j]
    text = here.block.text
    if here.block.in_chrome or priced[j] or len(text) > MAX_HEADING_CHARS:
        return False
    if not _LETTER.search(text):
        return False
    if here.level is not None:  # only an h element's first block, not a line inside it
        return j == 0 or placed[j - 1].heading_node != here.heading_node
    if len(text) > MAX_CLASS_HEADING_CHARS:
        return False
    own = _own_classes(here)
    return bool(_HEADING_CLASS.search(own)) and not _NOT_HEADING_CLASS.search(own)


@dataclass(frozen=True, slots=True)
class DomSections:
    """[5c]'s answer for one page: ``assignment`` maps a kept item's name block (index)
    to its heading block (index) on a gated page, and is empty otherwise."""

    assignment: dict[int, int] = field(default_factory=dict)
    matched: bool = False  # the re-parse gave the Version's blocks
    items: int = 0  # kept items' name blocks
    assigned_share: float = 0.0
    wrapped_share: float = 0.0
    styles: int = 0  # section styles serving the assigned items
    gated: bool = False


def _section_styles(
    sigs: Sequence[Signature], candidates: Sequence[int], items: Sequence[int], end: int
) -> set[Signature]:
    by_sig: dict[Signature, list[int]] = {}
    for j in candidates:
        by_sig.setdefault(sigs[j], []).append(j)
    styles = set()
    for sig, heads in by_sig.items():
        enclosing = 0
        for at, nxt in zip(heads, [*heads[1:], end], strict=True):
            lo, hi = bisect.bisect_right(items, at), bisect.bisect_left(items, nxt)
            enclosing += any(sigs[i] != sig for i in items[lo:hi])
        if enclosing * 2 >= len(heads) and enclosing >= MIN_SECTIONS:
            styles.add(sig)
    return styles


def _wrapped(placed: Sequence[Placed], item: int, head: int, same_style: Sequence[int]) -> bool:
    common = None
    for x, y in zip(placed[head].node_ids, placed[item].node_ids, strict=False):
        if x != y:
            break
        common = x
    if common is None:
        return False
    return sum(common in placed[h].node_ids for h in same_style) == 1


def assign(
    html: str,
    blocks: Sequence[Block],
    verdicts: Sequence[Verdict],
    placed: Sequence[Placed] | None = None,
) -> DomSections:
    """Stage [5c] over one page's HTML, its Version's blocks and the kept verdicts;
    ``placed`` is ``placed_blocks(html)`` when the caller already parsed it."""
    if placed is None:
        placed = placed_blocks(html)
    if tuple(p.block for p in placed) != tuple(blocks):
        return DomSections()
    index = {b.id: i for i, b in enumerate(blocks)}
    items = sorted(
        {
            index[v.name_evidence.block_id]
            for v in verdicts
            if v.decision != "reject" and v.name_evidence is not None
        }
    )
    if not items:
        return DomSections(matched=True)
    priced = [bool(tokens) for tokens in price_tokens(list(blocks))]
    sigs = [signature(p) for p in placed]
    candidates = [j for j in range(len(placed)) if _candidate(placed, priced, j)]
    styles = _section_styles(sigs, candidates, items, len(placed))
    heads = [j for j in candidates if sigs[j] in styles]
    found: dict[int, int] = {}
    for i in items:
        k = bisect.bisect_left(heads, i)
        if k:
            found[i] = heads[k - 1]
    by_style: dict[Signature, list[int]] = {}
    for h in heads:
        by_style.setdefault(sigs[h], []).append(h)
    wrapped = sum(_wrapped(placed, i, j, by_style[sigs[j]]) for i, j in found.items())
    used = {sigs[j] for j in found.values()}
    assigned_share = len(found) / len(items)
    wrapped_share = wrapped / len(found) if found else 0.0
    gated = assigned_share >= MIN_ASSIGNED and (wrapped_share >= MIN_WRAPPED or len(used) == 1)
    return DomSections(
        assignment=found if gated else {},
        matched=True,
        items=len(items),
        assigned_share=assigned_share,
        wrapped_share=wrapped_share,
        styles=len(used),
        gated=gated,
    )
