"""Step E/F: stage [4] LLM extractor (llama.cpp server) and its scoring.

    # llama-server -m MODEL.gguf --host 127.0.0.1 --port 8080 -c 8192 ...
    MENU_SPIKE_DATA=... python -m spikes.menu_model.extract run --tag TAG [--server URL] [PAGE ...]
    MENU_SPIKE_DATA=... python -m spikes.menu_model.extract score --tag TAG [--split=all|dev|ho1|ho2]

``run`` sends each gold menu page's non-chrome blocks, one ``bNNNN | text`` line
each, in chunks of at most :data:`CHUNK_CHARS`, to llama-server's OpenAI-style
chat endpoint with a JSON schema (llama.cpp turns it into a GBNF grammar, so the
output is JSON-only by construction). The schema is deliberately compact, because
output tokens dominate CPU time: sections, each with rows
``[block_id, item name, price, variant]``. The block id is the extractor's
evidence claim (``Row.claimed_block``); the validator treats it as a hint only.

``score`` validates every extracted row against the page (stage [5]) and matches
rows to gold items by normalized name:

- **item recall** — gold items with at least one row (raw), and with a row the
  validator kept (accept or downgrade);
- **exact price accuracy on accepted rows** — accepted, gold-matched rows whose
  amount is one of that gold item's amounts;
- **validator on real output (step F)** — a row is *correct* when it matches a
  gold item and one of its amounts, else *wrong* (wrong price, or an item that is
  not in gold). False-reject rate = correct rows not accepted; catch rate =
  wrong rows not accepted. Rows without a price are counted apart. Rows naming non-gold text that is still on the page
  (e.g. an add-on labeled ``modifier``) count as wrong, so the catch rate is
  conservative.
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.request
from collections import Counter
from pathlib import Path
from typing import Any

from spikes.menu_model.eval_validator import DEV_PAGES, HELDOUT_1, load_gold
from spikes.menu_model.labeltool import blocks_of
from spikes.menu_model.validator import Row, norm_tokens, parse_amount, validate

DATA = Path(os.environ.get("MENU_SPIKE_DATA", "var/spikes/menu-model"))
CHUNK_CHARS = 3000
BLOCK_CHARS = 300
MAX_TOKENS = 3072

SYSTEM = (
    "You extract restaurant menus. Input lines are 'BLOCK_ID | text' in page order. "
    "Return every menu item that is sold, grouped by the menu section it is under. "
    "For each item give: the block id where its name appears, the item name copied "
    "exactly as printed, the price copied exactly as printed (digits only, e.g. 12.50; "
    'empty string "" if no price is printed for it), and the size/variant label printed '
    "next to that price (empty string if none). An item with several prices (sizes) gets "
    "one row per price. Do not invent items or prices, do not convert or compute prices, "
    "skip navigation, hours, addresses, reviews and add-on/extra lines. "
    "If the text contains no menu items, return no sections."
)

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "sections": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "section": {"type": "string"},
                    "rows": {
                        "type": "array",
                        "items": {
                            "type": "array",
                            "prefixItems": [{"type": "string"}] * 4,
                            "items": False,
                            "minItems": 4,
                            "maxItems": 4,
                        },
                    },
                },
                "required": ["section", "rows"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["sections"],
    "additionalProperties": False,
}


def chunks(page_id: str) -> list[str]:
    lines = [f"{b.id} | {b.text[:BLOCK_CHARS]}" for b in blocks_of(page_id) if not b.in_chrome]
    out: list[str] = []
    cur: list[str] = []
    size = 0
    for line in lines:
        if cur and size + len(line) + 1 > CHUNK_CHARS:
            out.append("\n".join(cur))
            cur, size = [], 0
        cur.append(line)
        size += len(line) + 1
    if cur:
        out.append("\n".join(cur))
    return out


def _post(server: str, body: dict[str, Any]) -> dict[str, Any]:
    req = urllib.request.Request(  # noqa: S310 - 127.0.0.1 llama-server only
        f"{server}/v1/chat/completions",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=1800) as resp:  # noqa: S310
        result: dict[str, Any] = json.loads(resp.read())
        return result


def extract_chunk(server: str, text: str) -> dict[str, Any]:
    body = {
        "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": text}],
        "temperature": 0,
        "max_tokens": MAX_TOKENS,
        "response_format": {"type": "json_schema", "json_schema": {"schema": SCHEMA}},
        "chat_template_kwargs": {"enable_thinking": False},
        "cache_prompt": False,
    }
    t0 = time.perf_counter()
    resp = _post(server, body)
    wall = time.perf_counter() - t0
    content = resp["choices"][0]["message"]["content"]
    try:
        parsed = json.loads(content)
    except ValueError:
        parsed = {"sections": [], "parse_error": content[-200:]}
    return {
        "wall_s": round(wall, 2),
        "finish": resp["choices"][0].get("finish_reason"),
        "timings": resp.get("timings", {}),
        "usage": resp.get("usage", {}),
        "out": parsed,
    }


def rows_of(result: dict[str, Any]) -> list[Row]:
    rows: list[Row] = []
    for ch in result["chunks"]:
        for sec in ch["out"].get("sections", []):
            for r in sec.get("rows", []):
                block, name, price, variant = (str(x).strip() for x in r)
                if name:
                    rows.append(
                        Row(
                            item=name,
                            amount=price or None,
                            variant=variant or None,
                            section=str(sec.get("section") or "") or None,
                            claimed_block=block or None,
                        )
                    )
    return rows


def cmd_run(tag: str, server: str, page_ids: list[str]) -> None:
    out_dir = DATA / "extract" / tag
    out_dir.mkdir(parents=True, exist_ok=True)
    gold = load_gold()
    for pid in page_ids or sorted(gold):
        path = out_dir / f"{pid}.json"
        if path.exists():
            continue
        t0 = time.perf_counter()
        results = [extract_chunk(server, c) for c in chunks(pid)]
        rec = {"page_id": pid, "wall_s": round(time.perf_counter() - t0, 2), "chunks": results}
        path.write_text(json.dumps(rec, indent=1), encoding="utf-8")
        gen = sum(int(c["timings"].get("predicted_n", 0)) for c in results)
        print(
            f"{pid} chunks={len(results)} rows={len(rows_of(rec))} gen_tokens={gen} wall={rec['wall_s']}s",
            flush=True,
        )


def _key(name: str) -> frozenset[str]:
    return frozenset(norm_tokens(name))


def _match(row: Row, gold_items: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Gold item with the same name tokens (prefer the claimed block), else a same-block subset match."""
    k = _key(row.item)
    same = [g for g in gold_items if _key(g["name"]) == k]
    if same:
        return next((g for g in same if g["block"] == row.claimed_block), same[0])
    for g in gold_items:
        gk = _key(g["name"])
        if g["block"] == row.claimed_block and k and (k <= gk or gk <= k):
            return g
    return None


def cmd_score(tag: str, split: str) -> dict[str, Any]:  # noqa: C901, PLR0912, PLR0915 - flat scoring pass
    gold = load_gold()
    pages = {
        "all": set(gold),
        "dev": set(gold) & DEV_PAGES,
        "ho1": set(gold) & HELDOUT_1,
        "ho2": set(gold) - DEV_PAGES - HELDOUT_1,
    }[split]
    c: Counter[str] = Counter()
    reasons: Counter[str] = Counter()
    walls, gens, per_page = [], [], []
    for pid in sorted(pages):
        path = DATA / "extract" / tag / f"{pid}.json"
        if not path.exists():
            continue
        result = json.loads(path.read_text(encoding="utf-8"))
        walls.append(result["wall_s"])
        gens.append(sum(int(ch["timings"].get("predicted_n", 0)) for ch in result["chunks"]))
        c["truncated_chunks"] += sum(1 for ch in result["chunks"] if ch["finish"] == "length")
        c["unparsed_chunks"] += sum(1 for ch in result["chunks"] if "parse_error" in ch["out"])
        items: list[dict[str, Any]] = gold[pid]["items"]  # type: ignore[assignment]
        rows = rows_of(result)
        verdicts = validate(blocks_of(pid), rows)
        found_raw: set[int] = set()
        found_kept: set[int] = set()
        found_price: set[tuple[int, str]] = set()
        for v in verdicts:
            g = _match(v.row, items)
            amt = parse_amount(v.row.amount)
            gold_amts = {parse_amount(p["amount"]) for p in g["prices"]} if g else set()
            correct = g is not None and (amt in gold_amts if gold_amts else amt is None)
            c["rows"] += 1
            c[f"decision:{v.decision}"] += 1
            if g is not None:
                found_raw.add(id(g))
                if v.decision != "reject":
                    found_kept.add(id(g))
            if v.decision == "accept":
                if g is not None and amt is not None:
                    c["accepted_matched_priced"] += 1
                    c["accepted_price_exact"] += int(amt in gold_amts)
                    if amt in gold_amts:
                        found_price.add((id(g), str(amt)))
                elif g is None:
                    c["accepted_unmatched"] += 1
            if amt is None:  # a missing price is a recall miss, not a corruption to catch
                c["unpriced_rows"] += 1
                continue
            c["correct" if correct else "wrong"] += 1
            if correct and v.decision != "accept":
                c["false_reject"] += 1
                reasons.update(r.split(" ")[0] for r in v.reasons)
            if not correct and v.decision != "accept":
                c["caught"] += 1
            if not correct and v.decision == "accept":
                c["wrong_accepted"] += 1
                if g is not None:
                    c["wrong_accepted_price"] += 1
        n_gold = len(items)
        n_gold_prices = sum(len(it["prices"]) for it in items)
        c["gold_items"] += n_gold
        c["gold_prices"] += n_gold_prices
        c["found_raw"] += len(found_raw)
        c["found_kept"] += len(found_kept)
        c["found_price"] += len(found_price)
        per_page.append((pid, n_gold, len(found_raw), len(found_kept), result["wall_s"]))

    def rate(a: str, b: str) -> float:
        return c[a] / c[b] if c[b] else float("nan")

    walls.sort()
    summary: dict[str, Any] = {
        "tag": tag,
        "split": split,
        "pages": len(walls),
        "item_recall_raw": rate("found_raw", "gold_items"),
        "item_recall_kept": rate("found_kept", "gold_items"),
        "price_recall_accepted": rate("found_price", "gold_prices"),
        "price_accuracy_accepted": rate("accepted_price_exact", "accepted_matched_priced"),
        "validator_false_reject": rate("false_reject", "correct"),
        "validator_catch": rate("caught", "wrong"),
        "median_page_s": walls[len(walls) // 2] if walls else None,
        "max_page_s": walls[-1] if walls else None,
        "gen_tokens_total": sum(gens),
        "counts": dict(c),
        "false_reject_reasons": dict(reasons),
        "per_page": per_page,
    }
    for k, val in summary.items():
        if k != "per_page":
            print(f"{k:26} {val:.3f}" if isinstance(val, float) else f"{k:26} {val}")
    if "--pages" in sys.argv:
        for row in per_page:
            print("   ", row)
    return summary


def main() -> None:
    args = sys.argv[1:]
    tag = args[args.index("--tag") + 1]
    if args[0] == "run":
        server = args[args.index("--server") + 1] if "--server" in args else "http://127.0.0.1:8080"
        skip = {tag, server}
        cmd_run(tag, server, [a for a in args[1:] if not a.startswith("--") and a not in skip])
    else:
        split = next((a.split("=", 1)[1] for a in args if a.startswith("--split=")), "all")
        summary = cmd_score(tag, split)
        (DATA / "extract" / tag / f"score-{split}.json").write_text(
            json.dumps(summary, indent=1, default=str), encoding="utf-8"
        )


if __name__ == "__main__":
    main()
