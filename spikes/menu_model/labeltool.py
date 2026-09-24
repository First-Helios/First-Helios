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
from spikes.menu_model.validator import price_label, price_tokens

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


def cmd_peek() -> None:
    """One line per not-yet-labeled page: title, first headings, first body text."""
    done = {p.stem for p in (LABELS / "pages").glob("*.json")}
    for p in load_pages():
        pid = str(p["page_id"])
        if pid in done:
            continue
        blocks = [b for b in blocks_of(pid) if not b.in_chrome]
        heads = [b.text[:28] for b in blocks if b.heading][:6]
        body = [b.text[:28] for b in blocks if not b.heading and len(b.text) > 3][:4]  # noqa: PLR2004
        print(
            f"{pid} {str(p['role'])[:6]:6} J={int(bool(p.get('js_only')))} n={len(blocks):3} "
            f"pdf={p.get('pdf_links', 0)} {str(p['url'])[8:55]:47} | {_title(pid)[:35]} "
            f"| H:{heads} | B:{body}"
        )


def cmd_show(page_id: str, lo: str | None, hi: str | None) -> None:
    for b in blocks_of(page_id):
        if lo and hi and not (lo <= b.id <= hi):
            continue
        mark = ("H" if b.heading else "") + ("c" if b.in_chrome else "")
        print(f"{b.id} {b.tag:6} {mark:2} {b.text[:400]}")


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


def _amounts(text: str, *, labels: bool) -> list[dict[str, str | None]]:
    """Prices in a block; for a price-only block also its per-price label as variant."""
    toks = price_tokens([Block("x", text, "div", "", heading=False, in_chrome=False, classes="")])[
        0
    ]
    out: list[dict[str, str | None]] = []
    if labels and not any(t.kind == "money" for t in toks):
        # a price block with bare numbers ("10", "11 / 44", "11hh/12"): every number
        return [
            {"amount": f"{float(m):.2f}", "variant": None}
            for m in re.findall(r"(?<![\w.])(\d{1,3}(?:\.\d{2})?)(?!\d)", text)
        ]
    for t in toks:
        if t.kind != "money":
            continue
        variant = price_label(text, toks, t) if labels else ""
        if len(variant.split()) > 3:  # noqa: PLR2004 - a description, not a size label
            variant = ""
        out.append({"amount": f"{t.amount:.2f}", "variant": variant or None})
    return out


def _derive_items(blocks: list[Block], labels: dict[str, str]) -> list[dict[str, object]]:
    items: list[dict[str, object]] = []
    section: str | None = None
    for b in blocks:
        lab = labels.get(b.id, "noise")
        if lab == "section":
            section = b.text
        elif lab == "item":
            # inline "Name – description – $9" / "Name ~ description 9.99": the name leads
            bare = PRICE_RE.sub("", b.text)
            head, *rest = re.split(r"\s*[–—~]\s|\s-\s", bare, maxsplit=1)
            desc_like = bool(rest) and len(rest[0].split()) >= 3  # noqa: PLR2004
            name = (head if desc_like else bare).strip(" -–—.:|~/,")
            items.append(
                {
                    "section": section,
                    "name": name,
                    "description": None,
                    "prices": _amounts(b.text, labels=False),
                    "block": b.id,
                }
            )
        elif lab == "description" and items and items[-1]["description"] is None:
            items[-1]["description"] = b.text
        elif lab == "price" and items:
            prices = items[-1]["prices"]
            assert isinstance(prices, list)
            prices.extend(_amounts(b.text, labels=True))
    return items


def cmd_draft(page_id: str, bounds: list[str]) -> None:
    labels = _draft(page_id, bounds)
    for b in blocks_of(page_id):
        if b.id in labels:
            print(f"{b.id} {labels[b.id][:4]:4} {b.text[:100]}")


def _draft(page_id: str, bounds: list[str]) -> dict[str, str]:
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
    return labels


def _load_label(page_id: str) -> tuple[Path, dict[str, object]]:
    path = LABELS / "pages" / f"{page_id}.json"
    return path, json.loads(path.read_text(encoding="utf-8"))


def _save_label(path: Path, label: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(label, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


def cmd_fix(page_id: str, edits: list[str]) -> None:
    """Apply reviewed corrections: ``b0012=noise``, ``b0012..b0020=noise``, ``b0012..b0020%2=item``.

    Gold items are re-derived from the corrected block labels; item-level edits
    (variants, split names) are applied afterwards with ``items`` patches in the JSON.
    """
    path, label = _load_label(page_id)
    blocks = blocks_of(page_id)
    labels = label["blocks"]
    assert isinstance(labels, dict)
    for edit in edits:
        target, value = edit.split("=", 1)
        target, _, step = target.partition("%")  # b0054..b0098%2 = every 2nd block
        lo, _, hi = target.partition("..")
        in_range = [b for b in blocks if lo <= b.id <= (hi or lo)]
        for b in in_range[:: int(step or 1)]:
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


def _parse_prices(spec: str) -> list[dict[str, str | None]]:
    return [
        {"amount": f"{float(a):.2f}", "variant": None if v == "-" else v}
        for v, a in (p.rsplit(":", 1) for p in spec.strip().split(",") if p)
    ]


def _override_items(
    page_id: str,
    names: dict[str, str],
    prices: dict[str, str],
    extra: list[list[str]] | None = None,
) -> None:
    """Item-level review edits keyed by the item's name block.

    ``name b0015=Mexican Gelatine`` fixes a name that shares its block with a
    description; ``prices b0050=SM:6.25,LG:9.75`` replaces the price list
    (``variant:amount``, ``-`` for no variant; empty = no price on the page).
    """
    path, label = _load_label(page_id)
    items = label["items"]
    assert isinstance(items, list)
    for it in items:
        if it["block"] in names:
            it["name"] = names[it["block"]].strip()
        if it["block"] in prices:
            it["prices"] = _parse_prices(prices[it["block"]])
    for block_id, spec in extra or []:  # a second item printed in the same block
        name, _, price_spec = spec.partition("|")
        section = next((it["section"] for it in items if it["block"] == block_id), None)
        items.append(
            {
                "section": section,
                "name": name.strip(),
                "description": None,
                "prices": _parse_prices(price_spec),
                "block": block_id,
            }
        )
    items.sort(key=lambda it: str(it["block"]))
    _save_label(path, label)


def _apply_recipe(page_id: str, recipe: dict[str, str]) -> None:
    """Relabel a regular platform layout inside the regions: ``h2=section h3=item``
    by tag, then ``price=`` for blocks carrying a $ price, ``long=`` for 6+ word
    blocks, and ``other=`` for the rest.
    Exceptions follow as ``fix`` lines; the result is still read block by block.
    """
    path, label = _load_label(page_id)
    labels = label["blocks"]
    assert isinstance(labels, dict)
    for b in blocks_of(page_id):
        if b.id not in labels:
            continue
        has_price = any(t.kind == "money" for t in price_tokens([b])[0])
        if b.tag in recipe:
            labels[b.id] = recipe[b.tag]
        elif has_price and "price" in recipe:
            labels[b.id] = recipe["price"]
        elif "long" in recipe and len(b.text.split()) >= 6:  # noqa: PLR2004
            labels[b.id] = recipe["long"]
        elif "other" in recipe:
            labels[b.id] = recipe["other"]
        if labels[b.id] == "noise":
            del labels[b.id]  # absent = noise, same as ``fix b..=noise``
    _save_label(path, label)


def cmd_apply(review: Path) -> None:
    """Rebuild every label from the review file (idempotent; the auditable record).

    ::

        page <page_id> <menu|not_menu> <format> | free-text note
        region b0054 b0099 [b0120 b0150 ...]
        recipe h2=section h3=item price=price other=description
        fix b0054..b0098%2=item b0100=section ...
        name b0015=Mexican Gelatine
        prices b0050=SM:6.25,LG:9.75
        additem b0027=1/2 Sheets|-:95
    """
    current: list[str] = []

    def flush() -> None:
        if not current:
            return
        head, *rest = current
        meta, _, note = head.partition("|")
        _, pid, page_label, fmt = meta.split()
        regions = [ln.split()[1:] for ln in rest if ln.startswith("region ")]
        recipe = [e for ln in rest if ln.startswith("recipe ") for e in ln.split()[1:]]
        fixes = [e for ln in rest if ln.startswith("fix ") for e in ln.split()[1:]]
        names = dict(ln[5:].split("=", 1) for ln in rest if ln.startswith("name "))
        prices = dict(ln[7:].split("=", 1) for ln in rest if ln.startswith("prices "))
        extra = [ln[8:].split("=", 1) for ln in rest if ln.startswith("additem ")]
        path = LABELS / "pages" / f"{pid}.json"
        path.unlink(missing_ok=True)
        if regions:
            _draft(pid, [b for r in regions for b in r])
        if recipe:
            _apply_recipe(pid, dict(e.split("=", 1) for e in recipe))
        if fixes:
            cmd_fix(pid, fixes)
        if names or prices or extra:
            _override_items(pid, names, prices, extra)
        cmd_setpage(pid, page_label, fmt, note.strip())
        current.clear()

    for raw in review.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("page "):
            flush()
        current.append(line)
    flush()


def main() -> None:
    cmd, *args = sys.argv[1:]
    if cmd == "pages":
        cmd_pages()
    elif cmd == "peek":
        cmd_peek()
    elif cmd == "show":
        cmd_show(args[0], *(args[1:3] if len(args) >= 3 else (None, None)))  # noqa: PLR2004
    elif cmd == "draft":
        cmd_draft(args[0], args[1:])
    elif cmd == "apply":
        cmd_apply(LABELS / "review.txt")
    elif cmd == "fix":
        cmd_fix(args[0], args[1:])
    elif cmd == "setpage":
        cmd_setpage(args[0], args[1], args[2], " ".join(args[3:]))
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main()
