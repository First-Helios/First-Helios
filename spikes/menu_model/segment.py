"""Stage [2]: generic, site-agnostic segmentation of an HTML page into text blocks.

No per-site code and no parser dependency (stdlib ``html.parser``). A block is
the inline text between two block-level boundaries, so "Carne Asada Taco" and a
sibling "$3.50" in separate ``<div>``s become two adjacent blocks, while
"Carne Asada Taco ....... $3.50" in one ``<p>`` stays one block. Every block
keeps its id, document order, tag path and text, so any extracted value can be
located as (block id, character span) — the evidence locator the validator
records.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
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
_WS = re.compile(r"\s+")


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
        self._stack: list[tuple[str, str]] = []  # (tag, class/id tokens) of open elements
        self._buf: list[str] = []
        self._skip = 0

    def _flush(self) -> None:
        text = _WS.sub(" ", "".join(self._buf)).strip()
        self._buf.clear()
        if not text:
            return
        block_anc = [(t, c) for t, c in self._stack if t in BLOCK_TAGS]
        tag, classes = block_anc[-1] if block_anc else ("body", "")
        tags = [t for t, _ in self._stack]
        self.blocks.append(
            Block(
                id=f"b{len(self.blocks) + 1:04d}",
                text=text,
                tag=tag,
                path="/".join(t for t, _ in block_anc[-4:]),
                heading=any(t in {"h1", "h2", "h3", "h4", "h5", "h6"} for t in tags),
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
        if tag == "img":  # alt text of an image can carry an item/section name
            alt = dict(attrs).get("alt") or ""
            if alt.strip():
                self._buf.append(f" {alt} ")
        if tag not in VOID_TAGS:
            a = dict(attrs)
            self._stack.append((tag, f"{a.get('class') or ''} {a.get('id') or ''}".strip()))

    def handle_endtag(self, tag: str) -> None:
        if tag in SKIP_TAGS:
            self._skip = max(0, self._skip - 1)
            return
        if self._skip:
            return
        if tag in BLOCK_TAGS:
            self._flush()
        # pop to the matching open tag (tolerates unclosed children)
        for i in range(len(self._stack) - 1, -1, -1):
            if self._stack[i][0] == tag:
                del self._stack[i:]
                break

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self._buf.append(data)

    def close(self) -> None:
        super().close()
        self._flush()


def segment(html: str) -> list[Block]:
    parser = _Segmenter()
    parser.feed(html)
    parser.close()
    return parser.blocks


def json_ld_objects(html: str) -> list[object]:
    """All parseable ``application/ld+json`` payloads (stage [0] input)."""
    out: list[object] = []
    for match in re.finditer(
        r"<script[^>]*type=[\"']application/ld\+json[\"'][^>]*>(.*?)</script>",
        html,
        re.IGNORECASE | re.DOTALL,
    ):
        try:
            out.append(json.loads(match.group(1).strip()))
        except ValueError:
            continue
    return out


def blocks_as_dicts(blocks: list[Block]) -> list[dict[str, object]]:
    return [asdict(b) for b in blocks]
