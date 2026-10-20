"""Score extractor output against gold labels (ADR-0013 §8); the harness's file side.

The pure scoring is ``packages.helios_parsing.evaluation``; this reads the
gitignored inputs: pages ``<data>/pages/<page_id>.html``, extractor outputs
``<data>/extract/<tag>/<page_id>.json`` (one ``{"raw": <generated text>}`` per
chunk under ``"chunks"``, in chunk order: the spike's record) and gold labels
``<labels>/<page_id>.json`` (the gold-label format in ``evaluation``)::

    uv run python -m apps.menu_pipeline.evaluate compare \\
        --data var/spikes/menu-model --labels var/spikes/menu_model/labels/pages \\
        [--splits var/menu-eval/splits.json --split ho3] TAG [TAG ...]
    uv run python -m apps.menu_pipeline.evaluate loss --data … --labels … TAG [--pages]
    uv run python -m apps.menu_pipeline.evaluate corrupt --data … --labels … [--seed 7]
    uv run python -m apps.menu_pipeline.evaluate report TAG --data … --labels … [--seed 7]
    uv run python -m apps.menu_pipeline.evaluate invariance --data … --labels … \\
        [--out FLIPS.json] [--baseline FLIPS.json]
    uv run python -m apps.menu_pipeline.evaluate extract --data … --labels … \\
        [--server http://localhost:8080] TAG

``extract`` runs the pipeline's own extractor (``llama_client``: prompt, grammar,
chunking, sparse retry; 2 requests in flight) over the gold pages and saves each
page's answers as ``<data>/extract/<TAG>/<page_id>.json``, skipping pages already
saved; ``compare`` / ``loss`` then score them. Scoring alone needs no server.

``report`` prints one tag's §8 record as Amendment 19 item 1 asks: the §8 numbers;
gold-row FR and usable prices with page-clustered 95 % intervals (and the share of
resamples within the FR bar); accepted rows that match no label; real-output
wrong-price rows accepted; [5b]'s accepts; and per-format and per-page gold-row FR.

``invariance`` runs the invariance suite (ADR-0017 item 1,
``packages.helios_parsing.invariance``) over the gold pages: no extractor output is
read. It prints each style's flips, writes per-page counts with ``--out``, and with
``--baseline`` (an earlier ``--out``) lists every page and style that flips more than
before and exits non-zero if there is one.

``--splits`` names a JSON file mapping split names to page ids (e.g. the tuning
pages and each held-out set); without it every scorable gold page is scored.
``compare`` and ``report`` refuse to score when a tag has no saved output for a gold
page (an incomplete ``extract`` job must not pass as a smaller score).
Pages are segmented with the current segmenter; the rows are repaired and
stitched exactly as the pipeline does. Gold labels, pages and outputs stay in
``var/``; only counts and rates go into ``docs/reviews/``.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import TYPE_CHECKING

from apps.menu_pipeline.llama_client import SLOTS, LlamaClient, http_client
from packages.helios_parsing.chunking import chunks
from packages.helios_parsing.evaluation import (
    GoldPage,
    corruption_eval,
    corruption_metrics,
    gold_page,
    gold_reject_page,
    loss_page,
    metrics,
    page_clustered,
    score_page,
)
from packages.helios_parsing.invariance import VARIANTS, added_flips, invariance_page
from packages.helios_parsing.output import parse_output, rows_of
from packages.helios_parsing.segment import segment

if TYPE_CHECKING:
    from packages.helios_parsing.segment import Block
    from packages.helios_parsing.validator import Row


def load_gold(labels: Path, splits: Path | None, split: str | None) -> dict[str, GoldPage]:
    """Scorable gold pages by page id (sorted), limited to one split if given."""
    pages = {}
    for path in sorted(labels.glob("*.json")):
        page = gold_page(json.loads(path.read_text(encoding="utf-8")))
        if page.scorable:
            pages[page.page_id] = page
    if splits is not None and split is not None:
        members = set(json.loads(splits.read_text(encoding="utf-8"))[split])
        pages = {pid: page for pid, page in pages.items() if pid in members}
    return pages


def blocks_of(data: Path, page_id: str) -> list[Block]:
    return segment((data / "pages" / f"{page_id}.html").read_text(encoding="utf-8"))


def extracted_rows(data: Path, tag: str, page_id: str, blocks: list[Block]) -> list[Row]:
    result = json.loads((data / "extract" / tag / f"{page_id}.json").read_text(encoding="utf-8"))
    return rows_of([parse_output(chunk.get("raw") or "") for chunk in result["chunks"]], blocks)


def _fmt(value: float | None) -> str:
    return "  n/a" if value is None else f"{value:.3f}"


def complete(data: Path, gold: dict[str, GoldPage], tags: list[str]) -> list[str]:
    """The gold pages, once every tag has saved output for each; an incomplete job (a failed
    or interrupted ``extract``) stops the scoring instead of scoring a subset."""
    for tag in tags:
        missing = [pid for pid in gold if not (data / "extract" / tag / f"{pid}.json").exists()]
        if missing:
            raise SystemExit(
                f"{tag}: no saved output for {len(missing)} of {len(gold)} gold pages "
                f"(first: {missing[0]}); finish the extract run or narrow --split"
            )
    return list(gold)


def cmd_compare(data: Path, gold: dict[str, GoldPage], tags: list[str]) -> None:
    common = complete(data, gold, tags)
    promos = sum(len(gold[pid].promos) for pid in common)
    print(f"pages={len(common)} (of {len(gold)} gold) promo_entries={promos}")
    print(f"{'tag':18} items  usable  acc    FR     catch  rows  promo_stored")
    for tag in tags:
        total: Counter[str] = Counter()
        by_format: dict[str, Counter[str]] = {}
        for pid in common:
            blocks = blocks_of(data, pid)
            counts = score_page(gold[pid], blocks, extracted_rows(data, tag, pid, blocks))
            total += counts
            by_format.setdefault(str(gold[pid].format), Counter()).update(counts)
        m = metrics(total)
        print(
            f"{tag:18} {_fmt(m['item_recall'])}  {_fmt(m['usable_prices'])}  "
            f"{_fmt(m['price_accuracy'])}  {_fmt(m['validator_false_reject'])}  "
            f"{_fmt(m['validator_catch'])}  {total['rows']:5} {total['promo_rows_stored']:5}"
        )
        for fmt, counts in sorted(by_format.items()):
            fm = metrics(counts)
            print(
                f"  [{fmt}] pages={counts['pages']} items={_fmt(fm['item_recall'])} "
                f"usable={_fmt(fm['usable_prices'])}"
            )


def cmd_loss(data: Path, gold: dict[str, GoldPage], tag: str, *, per_page: bool) -> None:
    buckets: Counter[str] = Counter()
    pages: dict[str, Counter[str]] = {}
    for pid, page in gold.items():
        if not (data / "extract" / tag / f"{pid}.json").exists():
            continue
        blocks = blocks_of(data, pid)
        pages[pid] = loss_page(page, blocks, extracted_rows(data, tag, pid, blocks))
        buckets += pages[pid]
    total = sum(buckets.values())
    print(f"{tag} pages={len(pages)} gold prices={total}")
    for bucket, n in buckets.most_common():
        print(f"  {bucket:36} {n:5}  {n / total:.3f}")
    if per_page:
        for pid, c in sorted(pages.items(), key=lambda kv: kv[1]["accepted"] - kv[1].total()):
            n = c.total()
            print(f"  {pid} n={n:4} lost={n - c['accepted']:4}")


def cmd_corrupt(data: Path, gold: dict[str, GoldPage], seed: int) -> None:
    c = corruption_eval([(page, blocks_of(data, pid)) for pid, page in gold.items()], seed)
    m = corruption_metrics(c)
    print(f"pages={len(gold)} seed={seed} correct rows={c['correct_rows']}")
    print(f"false_reject={c['false_reject']} rate={_fmt(m['false_reject'])}")
    for kind in sorted(k.split(":", 1)[1] for k in c if k.startswith("n:")):
        print(
            f"  {kind:20} n={c['n:' + kind]:4} caught={c['caught:' + kind]:4} "
            f"indistinguishable={c['indistinguishable:' + kind]}"
        )
    print(f"catch rate={_fmt(m['catch'])}")


FR_BAR = 0.12  # §8 gold-row false-reject bar


def _ratio(num: int, den: int) -> str:
    return f"{num / den:.3f} ({num}/{den})" if den else "  n/a"


def _interval(low: float | None, high: float | None) -> str:
    return "n/a" if low is None or high is None else f"[{low:.3f}, {high:.3f}]"


def cmd_report(data: Path, gold: dict[str, GoldPage], tag: str, seed: int) -> None:
    pids = complete(data, gold, [tag])
    total: Counter[str] = Counter()
    usable: list[tuple[int, int]] = []
    rejects: dict[str, Counter[str]] = {}
    pages: list[tuple[GoldPage, list[Block]]] = []
    for pid in pids:
        blocks = blocks_of(data, pid)
        pages.append((gold[pid], blocks))
        counts = score_page(gold[pid], blocks, extracted_rows(data, tag, pid, blocks))
        total += counts
        usable.append((counts["found_price"], counts["gold_prices"]))
        rejects[pid] = gold_reject_page(gold[pid], blocks)
    corrupt = corruption_eval(pages, seed)
    caught = sum(n for k, n in corrupt.items() if k.startswith("caught:"))
    trials = sum(n for k, n in corrupt.items() if k.startswith("n:"))
    fr = page_clustered([(c["false_reject"], c["correct_rows"]) for c in rejects.values()], FR_BAR)
    use = page_clustered(usable)
    print(f"{tag} pages={len(pids)} (of {len(gold)} gold) seed={seed}")
    print(f"  item recall       {_ratio(total['found_raw'], total['gold_items'])}")
    print(
        f"  price accuracy    {_ratio(total['accepted_price_exact'], total['accepted_matched_priced'])}"
    )
    print(f"  gold-row FR       {_ratio(corrupt['false_reject'], corrupt['correct_rows'])}")
    print(
        f"    page-clustered  {_interval(fr.low, fr.high)}; resamples <= {FR_BAR}: {_fmt(fr.at_most)}"
    )
    print(f"  catch             {_ratio(caught, trials)}")
    print(f"  usable prices     {_ratio(total['found_price'], total['gold_prices'])}")
    print(f"    page-clustered  {_interval(use.low, use.high)}")
    print(f"  accepted rows matching no label   {total['accepted_unmatched']}")
    print(f"  real-output wrong-price accepted  {total['wrong_accepted_price']}")
    print(
        f"  [5b] accepted {total['resolved_accepted']}: exact "
        f"{_ratio(total['resolved_price_exact'], total['resolved_matched_priced'])}, "
        f"matching no label {total['resolved_unmatched']}"
    )
    by_format: dict[str, Counter[str]] = {}
    for pid, c in rejects.items():
        fmt = by_format.setdefault(str(gold[pid].format), Counter())
        fmt.update(c)
        fmt["pages"] += 1
    print("  gold-row FR per format:")
    for fmt_name, c in sorted(by_format.items()):
        print(
            f"    {fmt_name:14} pages={c['pages']:3} {_ratio(c['false_reject'], c['correct_rows'])}"
        )
    print("  gold-row FR per page (pages with a reject, worst first):")
    for pid, c in sorted(rejects.items(), key=lambda kv: -kv[1]["false_reject"]):
        if c["false_reject"]:
            print(f"    {pid} [{gold[pid].format}] {_ratio(c['false_reject'], c['correct_rows'])}")


def cmd_invariance(
    data: Path, gold: dict[str, GoldPage], out: Path | None, baseline: Path | None
) -> None:
    pages = {pid: dict(invariance_page(page, blocks_of(data, pid))) for pid, page in gold.items()}
    total: Counter[str] = sum((Counter(c) for c in pages.values()), Counter())
    print(f"pages={len(pages)} gold prices={total['gold_prices']} accepted={total['base:accept']}")
    for style in VARIANTS:
        print(
            f"  {style:22} flips={total['flip:' + style]:5} "
            f"lost_accept={total['lost_accept:' + style]:5} "
            f"gained_accept={total['gained_accept:' + style]:4}"
        )
    if out is not None:
        out.write_text(json.dumps(pages, indent=1, sort_keys=True), encoding="utf-8")
    if baseline is not None:
        added = added_flips(json.loads(baseline.read_text(encoding="utf-8")), pages)
        for pid, style, before, after in added:
            print(f"  added flips: {pid} {style} {before} -> {after}")
        if added:
            raise SystemExit(f"{len(added)} page/style pairs flip more than the baseline")
        print("  no added flips")


def cmd_extract(data: Path, gold: dict[str, GoldPage], tag: str, client: LlamaClient) -> None:
    out = data / "extract" / tag
    out.mkdir(parents=True, exist_ok=True)
    client.wait_ready()
    with ThreadPoolExecutor(max_workers=SLOTS) as pool:
        for pid in gold:
            target = out / f"{pid}.json"
            if target.exists():
                continue
            texts = chunks(blocks_of(data, pid))
            results = list(pool.map(client.extract_chunk, texts))
            record = {"page_id": pid, "chunks": [result.record() for result in results]}
            target.write_text(json.dumps(record, indent=1), encoding="utf-8")
            print(f"{pid} chunks={len(results)}", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "command", choices=["compare", "loss", "corrupt", "report", "extract", "invariance"]
    )
    parser.add_argument("tags", nargs="*")
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--labels", type=Path, required=True)
    parser.add_argument("--splits", type=Path)
    parser.add_argument("--split")
    parser.add_argument("--pages", action="store_true", help="loss: one line per page")
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--server", default="http://localhost:8080", help="extract: llama-server")
    parser.add_argument("--out", type=Path, help="invariance: write per-page flip counts")
    parser.add_argument("--baseline", type=Path, help="invariance: fail on flips added to it")
    args = parser.parse_args()
    gold = load_gold(args.labels, args.splits, args.split)
    if args.command == "compare":
        cmd_compare(args.data, gold, args.tags)
    elif args.command == "loss":
        for tag in args.tags:
            cmd_loss(args.data, gold, tag, per_page=args.pages)
    elif args.command == "report":
        for tag in args.tags:
            cmd_report(args.data, gold, tag, args.seed)
    elif args.command == "invariance":
        cmd_invariance(args.data, gold, args.out, args.baseline)
    elif args.command == "extract":
        (tag,) = args.tags
        with http_client() as http:
            cmd_extract(args.data, gold, tag, LlamaClient(http, base_url=args.server))
    else:
        cmd_corrupt(args.data, gold, args.seed)


if __name__ == "__main__":
    main()
