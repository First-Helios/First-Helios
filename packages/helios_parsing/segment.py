"""Generic, site-agnostic segmentation of an HTML page into text blocks (stage [2]).

No per-site code and no parser dependency (stdlib ``html.parser``). A block is
the inline text between two block-level boundaries, so "Carne Asada Taco" and a
sibling "$3.50" in separate ``<div>``s become two adjacent blocks, while
"Carne Asada Taco ....... $3.50" in one ``<p>`` stays one block. Every block
keeps its id, document order, tag path and text. Ported from the menu-model
spike (``spikes/menu_model/segment.py``); dialogs are skipped since S6f
(ADR-0013 Amendment 2 item 9).

``SEGMENTER_VERSION`` names this output: Evidence locators cite it, so a change
to what ``segment`` returns for the same HTML needs a new version. ``text_hash``
is the page's change signal (ADR-0013 §5).
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from html.parser import HTMLParser

BLOCK_TAGS = frozenset(
    {
        "address", "article", "aside", "blockquote", "body", "br", "caption", "dd", "details",
        "dialog", "div", "dl", "dt", "fieldset", "figcaption", "figure", "footer", "form",
        "h1", "h2", "h3", "h4", "h5", "h6", "header", "hr", "html", "legend", "li", "main",
        "nav", "ol", "option", "p", "pre", "section", "summary", "table", "tbody", "td",
        "tfoot", "th", "thead", "tr", "ul", "button", "select", "label",
    }
)  # fmt: skip
SKIP_TAGS = frozenset({"script", "style", "noscript", "template", "svg", "iframe", "title"})
VOID_TAGS = frozenset(
    {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "wbr"}
)
# Landmarks whose contents are usually chrome, kept as a feature (not dropped).
CHROME_TAGS = frozenset({"nav", "header", "footer", "aside", "form", "button", "select"})
_HEADINGS = frozenset({"h1", "h2", "h3", "h4", "h5", "h6"})
_WS = re.compile(r"\s+")
_DIALOG_ROLES = frozenset({"dialog", "alertdialog"})
# v1: the spike's segmenter; v2: dialogs skipped (S6f).
SEGMENTER_VERSION = "segment-v2"


def _is_dialog(attrs: dict[str, str | None]) -> bool:
    """A dialog (``role=dialog|alertdialog`` or ``aria-modal``): a consent prompt or a
    pop-up over the page, never the page's own content."""
    role = (attrs.get("role") or "").strip().lower()
    return role in _DIALOG_ROLES or (attrs.get("aria-modal") or "").strip().lower() == "true"


@dataclass(frozen=True, slots=True)
class Block:
    id: str  # "b0001", document order
    text: str
    tag: str  # the innermost block-level ancestor
    path: str  # up to the last 4 block-level ancestors, outermost first
    heading: bool  # inside h1-h6
    in_chrome: bool  # inside nav/header/footer/aside/form/button/select
    classes: str  # class/id tokens of the innermost block ancestor (layout hint only)


class _Segmenter(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.blocks: list[Block] = []
        # (tag, class/id tokens, inside a dialog) of open elements
        self._stack: list[tuple[str, str, bool]] = []
        self._buf: list[str] = []
        self._skip = 0

    def _flush(self) -> None:
        text = _WS.sub(" ", "".join(self._buf)).strip()
        self._buf.clear()
        if not text:
            return
        block_ancestors = [(t, c) for t, c, _ in self._stack if t in BLOCK_TAGS]
        tag, classes = block_ancestors[-1] if block_ancestors else ("body", "")
        tags = [t for t, _, _ in self._stack]
        self.blocks.append(
            Block(
                id=f"b{len(self.blocks) + 1:04d}",
                text=text,
                tag=tag,
                path="/".join(t for t, _ in block_ancestors[-4:]),
                heading=any(t in _HEADINGS for t in tags),
                in_chrome=any(t in CHROME_TAGS for t in tags),
                classes=classes[:120],
            )
        )

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "body":
            self._skip = 0  # a missing </svg>/</noscript> in <head> must not hide the page
        if tag in SKIP_TAGS:
            self._skip += 1
            return
        if self._skip:
            return
        if tag in BLOCK_TAGS:
            self._flush()
        named = dict(attrs)
        dialog = self._in_dialog() or _is_dialog(named)
        if tag == "img" and not dialog:  # alt text of an image can carry an item/section name
            alt = named.get("alt") or ""
            if alt.strip():
                self._buf.append(f" {alt} ")
        if tag not in VOID_TAGS:
            classes = f"{named.get('class') or ''} {named.get('id') or ''}".strip()
            self._stack.append((tag, classes, dialog))

    def handle_endtag(self, tag: str) -> None:
        if tag in SKIP_TAGS:
            self._skip = max(0, self._skip - 1)
            return
        if self._skip:
            return
        if tag in BLOCK_TAGS:
            self._flush()
        # pop to the matching open tag (tolerates unclosed children)
        for index in range(len(self._stack) - 1, -1, -1):
            if self._stack[index][0] == tag:
                del self._stack[index:]
                break

    def _in_dialog(self) -> bool:
        return bool(self._stack) and self._stack[-1][2]

    def handle_data(self, data: str) -> None:
        if not self._skip and not self._in_dialog():
            self._buf.append(data)

    def close(self) -> None:
        super().close()
        self._flush()


def segment(html: str) -> list[Block]:
    """The page's text blocks in document order."""
    parser = _Segmenter()
    parser.feed(html)
    parser.close()
    return parser.blocks


def text_hash(blocks: list[Block]) -> str:
    """``sha256:`` digest of the normalized segmented text, the Bronze change signal.

    One line per block, in order: its heading and chrome flags, then its text
    (whitespace already collapsed by ``segment``), NFC-normalized. Those are the
    block fields chunking and the validator read, so markup, class names and
    scripts can change without changing the hash, while anything the later
    stages could see changes it. Chrome text counts: chunking drops it, but the
    validator grounds names over every block and block ids are positional.
    """
    lines = (f"{'h' if b.heading else '-'}{'c' if b.in_chrome else '-'} {b.text}" for b in blocks)
    text = unicodedata.normalize("NFC", "\n".join(lines))
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()
