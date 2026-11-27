"""Measure PR 186 against a swap-5 restore and a disposable replay directory."""

import argparse
import json
import random
from collections import Counter
from pathlib import Path

from sqlalchemy import text

from apps.menu_pipeline.bundle import Bundle, BundleStore
from apps.menu_pipeline.classifier import VERIFIER_NAME
from apps.menu_pipeline.extract import EXTRACTION_MODEL
from apps.menu_pipeline.extraction import OutputStore, PipelineVersion, model_tag, page_html
from apps.menu_pipeline.menu_writes import due_pages
from apps.menu_pipeline.models import load_manifest
from packages.helios_core.db.session import get_sessionmaker
from packages.helios_parsing.chunking import chunks
from packages.helios_parsing.jsonld import json_ld_objects, menu_items
from packages.helios_parsing.menu_shape import shape
from packages.helios_parsing.output import parse_output
from packages.helios_parsing.page_template import llm_stream
from packages.helios_parsing.segment import text_hash

# Restrict to one stable menu record per endpoint, with no target URL switches
# or redirects. An unchanged capture has no version/record link of its own.
HISTORY = text("""
    with versions as (
        select c.source_endpoint_id ep, v.source_record_id rec, v.capture_id,
               v.source_payload p, e.canonical_uri url
        from bronze.source_record_version v join bronze.capture c on c.id=v.capture_id
        join bronze.source_endpoint e on e.id=c.source_endpoint_id
        join bronze.source s on s.id=c.source_id where s.namespace='menu-page'
    ), stable as (
        select ep from versions group by ep
        having count(distinct rec)=1 and bool_and(p->>'menu_url'=url)
        and every(rec not in (select rec from versions group by rec
                              having count(distinct ep)>1 or count(distinct p->>'menu_url')>1))
    )
    select c.source_endpoint_id, c.id, c.outcome, c.content_hash, c.bundle_path, v.p
    from bronze.capture c join stable on stable.ep=c.source_endpoint_id
    left join versions v on v.capture_id=c.id
    order by c.source_endpoint_id,c.fetched_at,c.id
""")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("cache", type=Path, help="scratch deploy directory with var/replay")
    parser.add_argument("pairs", type=Path, help="output JSONL for inspecting additional versions")
    args = parser.parse_args()
    bundles, outputs = BundleStore(args.cache), OutputStore(args.cache)
    version = PipelineVersion(model_tag(load_manifest()[EXTRACTION_MODEL]), VERIFIER_NAME)

    def cache_cost(counts: Counter[str], bundle: Bundle) -> None:
        texts = chunks(list(bundle.blocks))
        saved = outputs.read(
            version.extractor, text_hash(list(bundle.blocks)), expected_chunks=len(texts)
        )
        misses = (
            0
            if saved is not None
            else sum(outputs.read_chunk(version.extractor, chunk) is None for chunk in texts)
        )
        counts["pages"] += 1
        counts["page_hits"] += saved is not None
        counts["fully_cached"] += misses == 0
        counts["missing_chunks"] += misses

    with get_sessionmaker()() as session:
        due, _ = due_pages(session, version.llm)
        upgrade: Counter[str] = Counter()
        for page in due:
            cache_cost(upgrade, bundles.read(page.bundle_path))
        print("upgrade", dict(upgrade), flush=True)

        previous = None
        last_endpoint = None
        comparisons: Counter[str] = Counter()
        extra: Counter[str] = Counter()
        all_changed: Counter[str] = Counter()
        prior_only: Counter[str] = Counter()
        urls = set()
        with args.pairs.open("w") as pairs:
            for endpoint, cid, outcome, digest, path, payload in session.execute(HISTORY):
                if endpoint != last_endpoint or outcome != "succeeded":
                    previous = None
                if endpoint != last_endpoint:
                    old = None
                last_endpoint = endpoint
                if outcome != "succeeded":
                    continue
                if payload is not None:
                    old = payload
                if old is None:
                    continue
                bundle = bundles.read(path)
                if text_hash(list(bundle.blocks)) != old["text_hash"]:
                    raise ValueError(f"Capture {cid} differs from its historical text hash")
                document = (
                    bundle.url.partition("://")[2],
                    bundle.content_type,
                    bundle.rendered_dom if bundle.rendered_dom is not None else digest,
                )
                if previous is not None:
                    old_before, doc_before, prev_id, prev_path = previous
                    urls.add(endpoint)
                    comparisons["pairs"] += 1
                    old_changed = old != old_before
                    new_changed = old_changed or document != doc_before
                    comparisons["old_versions"] += old_changed
                    comparisons["new_versions"] += new_changed
                    if new_changed:
                        cache_cost(all_changed, bundle)
                        # Prospective scenario with only the preceding page and its chunk answers.
                        before = bundles.read(prev_path)
                        known = set(chunks(list(before.blocks)))
                        missing = sum(chunk not in known for chunk in chunks(list(bundle.blocks)))
                        prior_only["fully_cached"] += missing == 0
                        prior_only["missing_chunks"] += missing
                    if new_changed and not old_changed:
                        cache_cost(extra, bundle)
                        print(
                            json.dumps([prev_id, cid, prev_path, path, old["menu_url"]]), file=pairs
                        )
                previous = old, document, cid, path
        print("comparisons", len(urls), dict(comparisons))
        print("recrawl (archive-end cache)", dict(all_changed))
        print("incremental", dict(extra))
        print("recrawl with only preceding answers", dict(prior_only))

    sample = random.Random(186).sample(args.pairs.read_text().splitlines(), 16)  # noqa: S311
    for line in sample:
        first, second, left, right, url = json.loads(line)
        before, after = bundles.read(left), bundles.read(right)
        answers = outputs.read(version.extractor, text_hash(list(before.blocks)))
        if answers is None:
            raise ValueError(f"No page answers for sampled capture {first}")
        parsed = [parse_output(raw) for raw in answers]
        shapes = []
        for bundle in (before, after):
            blocks = list(bundle.blocks)
            stream = llm_stream(blocks, parsed, page_html(bundle))
            shapes.append(shape(blocks, stream.validation.verdicts, stream.sections.assignment))
        a, b = page_html(before), page_html(after)
        print(
            first,
            second,
            url,
            "changed: llm, MenuItem, any JSON-LD",
            shapes[0] != shapes[1],
            menu_items(a) != menu_items(b),
            json_ld_objects(a) != json_ld_objects(b),
        )


if __name__ == "__main__":
    main()
