"""Offline repeated-card experiment on captured HTML. Emits evidence and residual model inputs."""

from __future__ import annotations

import argparse
import json
import re
import time
from collections import Counter, defaultdict
from dataclasses import asdict
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Any

from apps.menu_pipeline.llama_client import LlamaClient, http_client
from packages.helios_parsing.chunking import chunks
from packages.helios_parsing.dom_sections import placed_blocks
from packages.helios_parsing.evaluation import gold_page
from packages.helios_parsing.output import ExtractorOutput, OutputRow, OutputSection
from packages.helios_parsing.page_template import llm_stream
from packages.helios_parsing.segment import segment
from packages.helios_parsing.validator import Row, validate

if TYPE_CHECKING:
    from collections.abc import Iterable

    from packages.helios_parsing.evaluation import GoldPage


_CARD = re.compile(r"(?:menu[-_]?item|dish[-_]?card|item[-_]?card)", re.I)
_PRICE = re.compile(r"\$\s*(\d{1,4}(?:\.\d{2})?)")


def price_matches(label: GoldPage, prices: Iterable[tuple[str, str | None, str]]) -> dict[str, int]:
    """Exact accepted triples with multiplicity, using the evaluation corpus's scope."""

    def key(name: str, variant: str | None, amount: str) -> tuple[str, str, Decimal]:
        return name.strip().casefold(), (variant or "").strip().casefold(), Decimal(amount)

    expected = Counter(
        key(item.name, p.variant, p.amount) for item in label.items for p in item.prices
    )
    actual = Counter(key(*price) for price in prices)
    matched = (actual & expected).total()
    return {
        "expected": expected.total(),
        "proposed": actual.total(),
        "matched": matched,
        "omitted": expected.total() - matched,
        "unmatched": actual.total() - matched,
    }


def inspect_cards(html: str) -> dict[str, Any]:
    placed = placed_blocks(html)
    blocks = [p.block for p in placed]
    groups: dict[tuple[int, str, str], list[int]] = defaultdict(list)
    sections: dict[int, str] = {}
    heading = ""
    for i, p in enumerate(placed):
        for node, (tag, classes) in reversed(list(zip(p.node_ids, p.stack, strict=True))):
            if tag in {"article", "li"} or _CARD.fullmatch(classes):
                groups[node, tag, classes].append(i)
                sections[node] = heading
                break
        else:
            if p.block.heading:
                heading = p.block.text
    repeats = Counter((tag, classes) for _, tag, classes in groups)
    rows = []
    covered: set[int] = set()
    for (node, tag, classes), indices in groups.items():
        if repeats[tag, classes] < 2 or len(indices) != 2:
            continue
        name, price = (blocks[i] for i in indices)
        match = _PRICE.fullmatch(price.text)
        if (
            not match
            or name.in_chrome
            or price.in_chrome
            or not any(c.isalpha() for c in name.text)
        ):
            continue
        row = Row(name.text, match[1], section=sections[node] or None, claimed_block=name.id)
        (v,) = validate(blocks, [row]).verdicts
        if (
            v.decision == "accept"
            and v.price_evidence
            and v.price_evidence.block_id == price.id
            and v.name_evidence
            and v.name_evidence.block_id == name.id
        ):
            covered.update(indices)
            rows.append(asdict(v))
    residual = [b for i, b in enumerate(blocks) if i not in covered]
    return {
        "rows": rows,
        "full_chunks": len(chunks(blocks)),
        "residual_chunks": chunks(residual),
    }


def compare_model(html: str, client: LlamaClient) -> dict[str, Any]:
    """Run both routes on the same document and retain exact accepted rows and elapsed cost."""
    blocks = segment(html)
    shadow = inspect_cards(html)
    sections: dict[str, list[OutputRow]] = defaultdict(list)
    for verdict in shadow["rows"]:
        row = verdict["row"]
        sections[row["section"] or ""].append(
            OutputRow(row["claimed_block"], row["item"], row["amount"], "")
        )
    cards = ExtractorOutput(tuple(OutputSection(k, tuple(v)) for k, v in sections.items()))
    report = {}
    for route, inputs, prefix in (
        ("baseline", chunks(blocks), []),
        ("hybrid", shadow["residual_chunks"], [cards]),
    ):
        started = time.monotonic()
        answers = [client.extract_chunk(chunk).output for chunk in inputs]
        elapsed = time.monotonic() - started
        stream = llm_stream(blocks, [*prefix, *answers], html)
        report[route] = {
            "model_seconds": elapsed,
            "chunks": len(inputs),
            "duplicates_removed": stream.duplicates,
            "prices": [
                (v.row.item, v.row.variant, v.row.amount)
                for v in stream.validation.verdicts
                if v.decision == "accept" and v.row.amount is not None
            ],
        }
    return report


def benchmark(folder: Path) -> dict[str, Any]:
    """Score exact card proposals and count residual requests across a frozen corpus."""
    pages = []
    totals: Counter[str] = Counter()
    for path in sorted((folder / "pages").glob("*.html")):
        label = gold_page(json.loads((folder / "labels" / f"{path.stem}.json").read_text()))
        result = inspect_cards(path.read_text())
        matches = price_matches(
            label,
            ((v["row"]["item"], v["row"]["variant"], v["row"]["amount"]) for v in result["rows"]),
        )
        counts = Counter(
            expected=matches["expected"],
            proposed=matches["proposed"],
            matched=matches["matched"],
            full_chunks=result["full_chunks"],
            residual_chunks=len(result["residual_chunks"]),
        )
        totals.update(counts)
        pages.append({"page": path.stem, **counts})
    if not pages:
        raise ValueError(f"No captured pages in {folder}/pages")
    return {"totals": dict(totals), "pages": pages}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="HTML file or corpus with pages/ and labels/")
    parser.add_argument(
        "--server", help="run paired baseline and residual inference on one HTML file"
    )
    parser.add_argument("--label", type=Path, help="score each model route against this page label")
    args = parser.parse_args()
    if args.label and not args.server:
        parser.error("--label requires --server")
    if args.server:
        if not args.source.is_file():
            parser.error("--server requires a single HTML file")
        label = gold_page(json.loads(args.label.read_text())) if args.label else None
        if label is not None and (label.page_id != args.source.stem or not label.reviewed):
            parser.error("a reviewed label for this page ID is required")
        with http_client() as http:
            result = compare_model(args.source.read_text(), LlamaClient(http, base_url=args.server))
        if label is not None:
            for route in result.values():
                route["score"] = price_matches(label, route["prices"])
        print(json.dumps(result, indent=2))
        return
    result = (
        benchmark(args.source) if args.source.is_dir() else inspect_cards(args.source.read_text())
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
