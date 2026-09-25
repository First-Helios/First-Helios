"""Step E/F: stage [4] LLM extractor (llama.cpp server) and its scoring.

    # llama-server -m MODEL.gguf --host 127.0.0.1 --port 8080 -c 8192 ...
    MENU_SPIKE_DATA=... python -m spikes.menu_model.extract run --tag TAG [--server URL] [PAGE ...]
    MENU_SPIKE_DATA=... python -m spikes.menu_model.extract score --tag TAG [--split=all|dev|ho1|ho2] [--repair] [--ref TAG]

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
import re
import sys
import time
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
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
                            "type": "array",  # [block_id, name, price, variant]
                            "items": {"type": "string"},
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


# Process v2 (after the mini tests, see the tracker log E-3): keyed rows so small models
# cannot swap price and variant, a digits-only price and a letter-bearing variant enforced
# by the grammar, smaller chunks (decode slows as context grows), a cached system-prompt
# prefix, and chunks sent concurrently to a multi-slot llama-server.
PROCESS = os.environ.get("MENU_SPIKE_PROCESS", "v1")
CHUNK_CHARS_V2 = 1500

SYSTEM_V2 = (
    "You extract restaurant menus. Input lines are 'BLOCK_ID | text' in page order. "
    "Return every menu item that is sold, grouped by the menu section it is under. "
    'Each item is {"b": block id where its name appears, "n": item name copied exactly as '
    'printed, "p": price copied exactly as printed, digits only (e.g. 12.50), "" if no price '
    'is printed for it, "v": size/variant word printed next to that price (e.g. "Large", '
    '"Glass"), only if there is one}. An item with several prices gets one entry per price. '
    "Do not invent items or prices, do not convert or compute prices, skip section headings, "
    "descriptions, navigation, hours, addresses, reviews and add-on/extra lines. "
    "If the text contains no menu items, return no sections."
)

SCHEMA_V2: dict[str, Any] = {
    "type": "object",
    "properties": {
        "sections": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "section": {"type": "string"},
                    "items": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "b": {"type": "string", "pattern": "^b[0-9]{4}$"},
                                "n": {"type": "string"},
                                "p": {
                                    "type": "string",
                                    "pattern": "^([0-9]{1,4}([.,][0-9]{1,2})?)?$",
                                },
                                "v": {"type": "string", "pattern": '^[^0-9]*[A-Za-z][^"]*$'},
                            },
                            "required": ["b", "n", "p"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["section", "items"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["sections"],
    "additionalProperties": False,
}


def chunks(page_id: str) -> list[str]:
    chunk_chars = CHUNK_CHARS_V2 if PROCESS == "v2" else CHUNK_CHARS
    lines = [f"{b.id} | {b.text[:BLOCK_CHARS]}" for b in blocks_of(page_id) if not b.in_chrome]
    out: list[str] = []
    cur: list[str] = []
    size = 0
    for line in lines:
        if cur and size + len(line) + 1 > chunk_chars:
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


def token_cap(text: str) -> int:
    """Runaway guard (added after the 1.5B run): ~30 output tokens per input line."""
    if os.environ.get("MENU_SPIKE_NO_CAP"):
        return MAX_TOKENS
    per_line = 40 if PROCESS == "v2" else 30  # keyed rows cost ~10 more tokens
    return min(MAX_TOKENS, per_line * (text.count("\n") + 1) + 64)


def extract_chunk(server: str, text: str) -> dict[str, Any]:
    v2 = PROCESS == "v2"
    body = {
        "messages": [
            {"role": "system", "content": SYSTEM_V2 if v2 else SYSTEM},
            {"role": "user", "content": text},
        ],
        "temperature": 0,
        "max_tokens": token_cap(text),
        "response_format": {
            "type": "json_schema",
            "json_schema": {"schema": SCHEMA_V2 if v2 else SCHEMA},
        },
        "chat_template_kwargs": {"enable_thinking": False},
        "cache_prompt": v2,  # v2 reuses the system-prompt KV prefix across chunks
    }
    t0 = time.perf_counter()
    resp = _post(server, body)
    wall = time.perf_counter() - t0
    content = resp["choices"][0]["message"]["content"]
    return {
        "wall_s": round(wall, 2),
        "finish": resp["choices"][0].get("finish_reason"),
        "timings": resp.get("timings", {}),
        "usage": resp.get("usage", {}),
        "raw": content,
        "out": parse_output(content),
    }


_SECTION = re.compile(r'"section"\s*:\s*("(?:[^"\\]|\\.)*")')
_ITEM = re.compile(r'\{\s*"b"\s*:[^{}]*\}')
_ROW = re.compile(
    r'\[\s*("(?:[^"\\]|\\.)*")\s*,\s*("(?:[^"\\]|\\.)*")\s*,\s*("(?:[^"\\]|\\.)*")\s*,\s*("(?:[^"\\]|\\.)*")\s*\]'
)


def parse_output(content: str) -> dict[str, Any]:
    """The JSON object, or (truncated / malformed output) every complete row recovered in order.

    A runaway generation that hits the token cap leaves unterminated JSON; the
    rows it completed before that are still real extractions, so they are kept
    and the chunk is flagged ``recovered``.
    """
    try:
        parsed: dict[str, Any] = json.loads(content)
        return _rows_form(parsed)
    except ValueError:
        pass
    sections: list[dict[str, Any]] = []
    events = sorted(
        [(m.start(), "s", m) for m in _SECTION.finditer(content)]
        + [(m.start(), "r", m) for m in _ROW.finditer(content)]
        + [(m.start(), "i", m) for m in _ITEM.finditer(content)],
        key=lambda e: e[0],
    )
    for _, kind, m in events:
        if kind == "s":
            sections.append({"section": json.loads(m.group(1)), "rows": []})
            continue
        if not sections:
            sections.append({"section": "", "rows": []})
        if kind == "r":
            sections[-1]["rows"].append([json.loads(g) for g in m.groups()])
        else:
            try:
                it = json.loads(m.group(0))
            except ValueError:
                continue
            sections[-1]["rows"].append(_row_of_item(it))
    return {"sections": sections, "recovered": True}


def _row_of_item(it: dict[str, Any]) -> list[str]:
    return [str(it.get("b", "")), str(it.get("n", "")), str(it.get("p", "")), str(it.get("v", ""))]


def _rows_form(parsed: dict[str, Any]) -> dict[str, Any]:
    """Process v2 keyed ``items`` -> the v1 ``rows`` form, so scoring has one shape."""
    for sec in parsed.get("sections", []):
        if isinstance(sec, dict) and "items" in sec and "rows" not in sec:
            sec["rows"] = [_row_of_item(it) for it in sec.pop("items") if isinstance(it, dict)]
    return parsed


_AMOUNT_ONLY = re.compile(r"^\$?\s?\d{1,4}(?:[.,]\d{1,2})?$")


def rows_of(result: dict[str, Any], *, repair: bool = False) -> list[Row]:
    """Extracted rows; ``repair`` applies two deterministic, counted fixes (see ``score``).

    1. price printed in the variant slot and the price slot empty -> swap (small models
       lose the positional order of ``[block, name, price, variant]``);
    2. exact duplicate rows (same item, variant, price, section) collapse to one.
    """
    rows: list[Row] = []
    for ch in result["chunks"]:
        out = parse_output(ch["raw"]) if "raw" in ch else ch["out"]
        for sec in out.get("sections", []):
            for r in sec.get("rows", []):
                block, name, price, variant = (str(x).strip() for x in r)
                if repair and not price and _AMOUNT_ONLY.match(variant):
                    price, variant = variant, ""
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
    if repair:
        seen: set[tuple[str, str | None, str | None, str | None]] = set()
        unique = []
        for row in rows:
            key = (" ".join(norm_tokens(row.item)), row.variant, row.amount, row.section)
            if key not in seen:
                seen.add(key)
                unique.append(row)
        rows = unique
    return rows


def cmd_run(tag: str, server: str, page_ids: list[str], workers: int = 1) -> None:
    """Extract pages; with ``workers`` > 1 all (page, chunk) jobs share a pool of that size.

    A page's ``wall_s`` is then first-chunk-start to last-chunk-end (pages overlap), and
    ``run.json`` records the run's total wall time, the honest throughput number.
    """
    out_dir = DATA / "extract" / tag
    out_dir.mkdir(parents=True, exist_ok=True)
    gold = load_gold()
    todo = [pid for pid in (page_ids or sorted(gold)) if not (out_dir / f"{pid}.json").exists()]
    jobs = [(pid, i, c) for pid in todo for i, c in enumerate(chunks(pid))]
    n_chunks = Counter(pid for pid, _, _ in jobs)
    done: dict[str, dict[int, dict[str, Any]]] = {pid: {} for pid in todo}
    t_run = time.perf_counter()

    def job(pid: str, i: int, text: str) -> tuple[str, int, dict[str, Any], float, float]:
        t0 = time.perf_counter()
        res = extract_chunk(server, text)
        return pid, i, res, t0, time.perf_counter()

    span: dict[str, list[float]] = {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for fut in as_completed([pool.submit(job, *j) for j in jobs]):
            pid, i, res, t0, t1 = fut.result()
            done[pid][i] = res
            lo_hi = span.setdefault(pid, [t0, t1])
            lo_hi[0], lo_hi[1] = min(lo_hi[0], t0), max(lo_hi[1], t1)
            if len(done[pid]) == n_chunks[pid]:
                results = [done[pid][k] for k in sorted(done[pid])]
                rec = {"page_id": pid, "wall_s": round(lo_hi[1] - lo_hi[0], 2), "chunks": results}
                (out_dir / f"{pid}.json").write_text(json.dumps(rec, indent=1), encoding="utf-8")
                gen = sum(int(c["timings"].get("predicted_n", 0)) for c in results)
                print(
                    f"{pid} chunks={len(results)} rows={len(rows_of(rec))} gen_tokens={gen} "
                    f"wall={rec['wall_s']}s",
                    flush=True,
                )
    total = round(time.perf_counter() - t_run, 2)
    run = {
        "process": PROCESS,
        "workers": workers,
        "pages": len(todo),
        "chunks": len(jobs),
        "total_wall_s": total,
    }
    (out_dir / "run.json").write_text(json.dumps(run), encoding="utf-8")
    print(f"RUN {run}", flush=True)


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


def cmd_score(
    tag: str, split: str, *, repair: bool = False, ref: str | None = None
) -> dict[str, Any]:  # noqa: C901, PLR0912, PLR0915 - flat scoring pass
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
    by_format: dict[str, Counter[str]] = {}
    for pid in sorted(pages):
        path = DATA / "extract" / tag / f"{pid}.json"
        if not path.exists() or "chunks" not in json.loads(path.read_text(encoding="utf-8")):
            continue
        result = json.loads(path.read_text(encoding="utf-8"))
        walls.append(result["wall_s"])
        gens.append(sum(int(ch["timings"].get("predicted_n", 0)) for ch in result["chunks"]))
        c["truncated_chunks"] += sum(1 for ch in result["chunks"] if ch["finish"] == "length")
        c["recovered_chunks"] += sum(
            1 for ch in result["chunks"] if "raw" in ch and parse_output(ch["raw"]).get("recovered")
        )
        items: list[dict[str, Any]] = gold[pid]["items"]  # type: ignore[assignment]
        raw_rows = rows_of(result)
        rows = rows_of(result, repair=repair)
        c["rows_raw"] += len(raw_rows)
        c["repair_price_from_variant"] += sum(
            1 for r in raw_rows if not r.amount and r.variant and _AMOUNT_ONLY.match(r.variant)
        )
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
        fmt = str(gold[pid].get("format"))
        f = by_format.setdefault(fmt, Counter())
        f["pages"] += 1
        f["gold_items"] += n_gold
        f["found_raw"] += len(found_raw)
        f["gold_prices"] += n_gold_prices
        f["found_price"] += len(found_price)
        if ref is not None:
            ref_path = DATA / "extract" / ref / f"{pid}.json"
            if ref_path.exists():
                mine = [ch.get("raw") for ch in result["chunks"]]
                theirs = [
                    ch.get("raw")
                    for ch in json.loads(ref_path.read_text(encoding="utf-8"))["chunks"]
                ]
                c["ref_chunks"] += len(mine)
                c["ref_identical_chunks"] += sum(
                    1 for a, b in zip(mine, theirs, strict=False) if a == b
                )
        per_page.append((pid, n_gold, len(found_raw), len(found_kept), result["wall_s"]))

    def rate(a: str, b: str) -> float:
        return c[a] / c[b] if c[b] else float("nan")

    walls.sort()
    summary: dict[str, Any] = {
        "tag": tag,
        "split": split,
        "repair": repair,
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
        "by_format": {
            k: {
                "pages": v["pages"],
                "item_recall_raw": v["found_raw"] / v["gold_items"] if v["gold_items"] else None,
                "price_recall_accepted": v["found_price"] / v["gold_prices"]
                if v["gold_prices"]
                else None,
            }
            for k, v in sorted(by_format.items())
        },
        "output_identical_to_ref": rate("ref_identical_chunks", "ref_chunks") if ref else None,
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
        workers = int(args[args.index("--workers") + 1]) if "--workers" in args else 1
        skip = {tag, server, str(workers)}
        cmd_run(
            tag, server, [a for a in args[1:] if not a.startswith("--") and a not in skip], workers
        )
    else:
        split = next((a.split("=", 1)[1] for a in args if a.startswith("--split=")), "all")
        repair = "--repair" in args
        ref = args[args.index("--ref") + 1] if "--ref" in args else None
        summary = cmd_score(tag, split, repair=repair, ref=ref)
        (DATA / "extract" / tag / f"score-{split}{'-repair' if repair else ''}.json").write_text(
            json.dumps(summary, indent=1, default=str), encoding="utf-8"
        )


if __name__ == "__main__":
    main()
