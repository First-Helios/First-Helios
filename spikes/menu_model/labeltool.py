"""Labeling helper for step B (drafted by the spike session, spot-checked by the owner).

    python -m spikes.menu_model.labeltool pages               # one line per fetched 200 page
    python -m spikes.menu_model.labeltool show PAGE [FROM TO]  # compact block dump
    python -m spikes.menu_model.labeltool draft PAGE FROM TO [FROM TO ...]

``draft`` writes ``labels/pages/PAGE.json`` with a heuristic pre-label for every
block inside the given menu region(s) (outside = noise) and gold items derived
from it. The pre-label is only a starting point: every in-region block is then
reviewed by hand and corrected with ``fix`` edits in the JSON before any metric
is computed. The heuristics here are deliberately NOT reused by the classifiers.

Block classes: section | item | description | price | modifier | noise.
(The tracker lists five; ``description`` is split out of ``item`` so gold items
can carry descriptions. Item+price F1 is computed on ``item`` and ``price``.)
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

from spikes.menu_model.segment import Block, segment

DATA = Path(os.environ.get("MENU_SPIKE_DATA", "var/spikes/menu-model"))
LABELS = Path(__file__).parent / "labels"

PRICE = r"\$?\s?\d{1,3}(?:[.,]\d{2})?"
PRICE_RE = re.compile(
    r"(?<![\w.])\$\s?\d{1,3}(?:[.,]\d{2})?(?!\d)|(?<![\w.$])\d{1,3}[.,]\d{2}(?!\d)"
)
PRICE_ONLY_RE = re.compile(rf"^(?:[A-Za-z .]{{0,12}}\s?)?{PRICE}(?:\s*[/|,-]\s*{PRICE})*$")
MODIFIER_RE = re.compile(r"^(add|\+|sub|substitute|extra|choice of|choose|with|make it)\b", re.I)


def load_pages() -> list[dict[str, object]]:
    return [
        p
        for p in (json.loads(line) for line in (DATA / "pages.jsonl").open(encoding="utf-8"))
        if p.get("status") == 200  # noqa: PLR2004
    ]


def blocks_of(page_id: str) -> list[Block]:
    return segment((DATA / "pages" / f"{page_id}.html").read_text(encoding="utf-8"))


def _title(page_id: str) -> str:
    html = (DATA / "pages" / f"{page_id}.html").read_text(encoding="utf-8")
    m = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
    return re.sub(r"\s+", " ", m.group(1)).strip()[:50] if m else ""


def cmd_pages() -> None:
    for p in load_pages():
        pid = str(p["page_id"])
        blocks = blocks_of(pid)
        priced = sum(1 for b in blocks if PRICE_RE.search(b.text))
        flags = (
            "".join(f for f, on in (("J", p.get("js_only")), ("I", p.get("image_only"))) if on)
            or "-"
        )
        pdfs = p.get("pdf_links", 0)
        print(
            f"{pid} {str(p['role'])[:8]:8} {flags:2} blk={len(blocks):4} priced={priced:4} "
            f"pdf={pdfs} {str(p['url'])[:60]} | {_title(pid)}"
        )


def cmd_show(page_id: str, lo: str | None, hi: str | None) -> None:
    for b in blocks_of(page_id):
        if lo and hi and not (lo <= b.id <= hi):
            continue
        mark = ("H" if b.heading else "") + ("c" if b.in_chrome else "")
        print(f"{b.id} {b.tag:6} {mark:2} {b.text[:110]}")


def _draft_label(b: Block) -> str:
    text = b.text
    has_price = bool(PRICE_RE.search(text))
    letters = len(re.findall(r"[A-Za-z]", PRICE_RE.sub("", text)))
    if has_price and PRICE_ONLY_RE.match(text):
        return "price"
    if MODIFIER_RE.match(text):
        return "modifier"
    if has_price and letters >= 2:  # noqa: PLR2004
        return "item"
    if b.heading or (text.isupper() and len(text) <= 40):  # noqa: PLR2004
        return "section"
    if len(text) > 40 and re.search(r"[a-z]", text):  # noqa: PLR2004
        return "description"
    return "item"


def _amounts(text: str) -> list[str]:
    out = []
    for m in PRICE_RE.findall(text):
        num = m.replace("$", "").replace(" ", "").replace(",", ".")
        out.append(f"{float(num):.2f}")
    return out


def _derive_items(blocks: list[Block], labels: dict[str, str]) -> list[dict[str, object]]:
    items: list[dict[str, object]] = []
    section: str | None = None
    for b in blocks:
        lab = labels.get(b.id, "noise")
        if lab == "section":
            section = b.text
        elif lab == "item":
            name = PRICE_RE.sub("", b.text).strip(" -–—.:|")
            items.append(
                {
                    "section": section,
                    "name": name,
                    "description": None,
                    "prices": [{"amount": a, "variant": None} for a in _amounts(b.text)],
                    "block": b.id,
                }
            )
        elif lab == "description" and items and items[-1]["description"] is None:
            items[-1]["description"] = b.text
        elif lab == "price" and items:
            prices = items[-1]["prices"]
            assert isinstance(prices, list)
            prices.extend({"amount": a, "variant": None} for a in _amounts(b.text))
    return items


def cmd_draft(page_id: str, bounds: list[str]) -> None:
    regions = list(zip(bounds[::2], bounds[1::2], strict=True))
    blocks = blocks_of(page_id)
    labels = {b.id: _draft_label(b) for b in blocks if any(lo <= b.id <= hi for lo, hi in regions)}
    page = next(p for p in load_pages() if p["page_id"] == page_id)
    out = {
        "page_id": page_id,
        "url": page["url"],
        "page_label": "menu",
        "format": None,
        "menu_regions": regions,
        "reviewed": False,
        "blocks": labels,
        "items": _derive_items(blocks, labels),
    }
    path = LABELS / "pages" / f"{page_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    for b in blocks:
        if b.id in labels:
            print(f"{b.id} {labels[b.id][:4]:4} {b.text[:100]}")


def _load_label(page_id: str) -> tuple[Path, dict[str, object]]:
    path = LABELS / "pages" / f"{page_id}.json"
    return path, json.loads(path.read_text(encoding="utf-8"))


def _save_label(path: Path, label: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(label, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


def cmd_fix(page_id: str, edits: list[str]) -> None:
    """Apply reviewed corrections: ``b0012=noise`` or a range ``b0012..b0020=noise``.

    Gold items are re-derived from the corrected block labels; item-level edits
    (variants, split names) are applied afterwards with ``items`` patches in the JSON.
    """
    path, label = _load_label(page_id)
    blocks = blocks_of(page_id)
    labels = label["blocks"]
    assert isinstance(labels, dict)
    for edit in edits:
        target, value = edit.split("=", 1)
        lo, _, hi = target.partition("..")
        for b in blocks:
            if lo <= b.id <= (hi or lo):
                if value == "noise":
                    labels.pop(b.id, None)
                else:
                    labels[b.id] = value
    items = _derive_items(blocks, labels)
    label |= {"items": items, "reviewed": True}
    _save_label(path, label)
    print(f"{page_id}: {len(labels)} labeled blocks, {len(items)} gold items")


def cmd_setpage(page_id: str, page_label: str, fmt: str, note: str) -> None:
    """Page-level label only (non-menus, JS-only/image-only menus)."""
    page = next(p for p in load_pages() if p["page_id"] == page_id)
    path = LABELS / "pages" / f"{page_id}.json"
    label: dict[str, object] = (
        json.loads(path.read_text(encoding="utf-8"))
        if path.exists()
        else {"page_id": page_id, "url": page["url"], "menu_regions": [], "blocks": {}, "items": []}
    )
    label |= {"page_label": page_label, "format": fmt, "note": note, "reviewed": True}
    _save_label(path, label)


def main() -> None:
    cmd, *args = sys.argv[1:]
    if cmd == "pages":
        cmd_pages()
    elif cmd == "show":
        cmd_show(args[0], *(args[1:3] if len(args) >= 3 else (None, None)))  # noqa: PLR2004
    elif cmd == "draft":
        cmd_draft(args[0], args[1:])
    elif cmd == "fix":
        cmd_fix(args[0], args[1:])
    elif cmd == "setpage":
        cmd_setpage(args[0], args[1], args[2], " ".join(args[3:]))
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main()
