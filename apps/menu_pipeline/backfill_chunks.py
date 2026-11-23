"""CLI: save per-chunk answers from the existing page records (ADR-0013 Amendment 37)::

    python -m apps.menu_pipeline.backfill_chunks [--base-dir .]

One-time, before the first run with chunk-answer reuse: a run writes a chunk
record for every chunk the model answers, but the page records saved before it
have none. For every stored bundle (``var/replay/menu-page/``) whose page text has
a saved page record under the current extractor version, the page is chunked
again (``chunk-v2.3``, as the run does) and each chunk the model answered gets its
record (:meth:`~apps.menu_pipeline.extraction.OutputStore.write_chunk`). A record
whose chunk count differs from its page's chunks is skipped and counted (no such
record is expected: the chunker is part of the extractor version).

Reads bundles and page records, writes only new files under
``var/replay/menu-extract/<extractor>/chunks/``; existing files are never
rewritten, so a second run writes nothing. No database, no model.
"""

from __future__ import annotations

import argparse
import gzip
import json
from collections import Counter
from pathlib import Path

from apps.menu_pipeline.bundle import BUNDLE_PREFIX, Bundle
from apps.menu_pipeline.extract import EXTRACTION_MODEL
from apps.menu_pipeline.extraction import OutputStore, extractor_version, model_tag
from apps.menu_pipeline.models import load_manifest
from packages.helios_parsing.chunking import chunks
from packages.helios_parsing.segment import text_hash


def backfill(base_dir: Path, extractor: str) -> Counter[str]:
    """Write the missing chunk records of ``extractor``'s page records; the counts."""
    outputs = OutputStore(base_dir)
    answered = {
        path.name.removesuffix(".json.gz") for path in outputs.folder(extractor).glob("*.json.gz")
    }
    counts: Counter[str] = Counter(page_records=len(answered))
    done: set[str] = set()
    for path in sorted((base_dir / BUNDLE_PREFIX).rglob("*.json.gz")):
        counts["bundles"] += 1
        try:
            blocks = list(Bundle.from_json(gzip.decompress(path.read_bytes())).blocks)
        except (OSError, ValueError):
            counts["bundles_unreadable"] += 1
            continue
        page_hash = text_hash(blocks)
        digest = page_hash.removeprefix("sha256:")
        if digest not in answered or digest in done:
            continue
        done.add(digest)
        record = outputs.read_record(extractor, page_hash)
        texts = chunks(blocks)
        if record is None or len(texts) != len(record["chunks"]):
            counts["chunk_count_mismatch"] += 1
            continue
        counts["pages"] += 1
        for text, answer in zip(texts, record["chunks"], strict=True):
            if "reused" in answer:  # answered from a chunk record already
                counts["chunks_reused"] += 1
            elif outputs.write_chunk(extractor, text, answer, page_text_hash=page_hash):
                counts["chunk_records_written"] += 1
            else:
                counts["chunks_already_saved"] += 1
    counts["page_records_without_bundle"] = len(answered - done)
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="python -m apps.menu_pipeline.backfill_chunks", description=__doc__
    )
    parser.add_argument(
        "--base-dir",
        type=Path,
        default=Path(),
        help="deploy directory that var/replay/... is relative to",
    )
    args = parser.parse_args()
    extractor = extractor_version(model_tag(load_manifest()[EXTRACTION_MODEL]))
    counts = backfill(args.base_dir, extractor)
    print(json.dumps({"extractor": extractor, **dict(sorted(counts.items()))}))  # noqa: T201 - CLI output


if __name__ == "__main__":
    main()
