"""CLI: the monthly spot check's labelling packet (ADR-0013 §8, Amendment 3 item 4;
ADR-0030 Amendment 1 A4)::

    python -m apps.menu_pipeline.spot_check --run-id 20261210T180002Z
        [--until ISO] [--size 10] [--seed N] [--out-dir DIR] [--base-dir .]

Draws :data:`SIZE` of the run's newly extracted pages at random (all of them when fewer), with a
recorded seed (default: the run id's digits). A page qualifies when it is a published ``llm``
Menu page, accepted between the run's start (the run id) and ``--until`` (default: now), and is
the first ``llm`` page of its Version, so new or changed text. Re-interpretations of known text
after a pipeline bump are not drawn.

The packet (default ``var/pipeline-host/reports/<run id>/spot-check/``) has the layout
``apps.menu_pipeline.evaluate`` reads:

- ``pages/<page_id>.html`` and ``pages/<page_id>.blocks.json``: the Version's Capture bundle as
  production read it (``page_html`` and the bundle's segmented blocks, which the harness
  prefers over re-segmenting), so PDF and rendered pages score exactly; a PDF page also gets
  ``<page_id>.pdf``, which is what its labeller reads;
- ``labels/``: empty, for the gold labels;
- ``extract/run-<run id>/<page_id>.json``: the run's saved page answers, for scoring only;
- ``manifest.json``: the draw (seed, window, candidates) and each page's ids, URL and venue;
- ``README.md``: the labelling brief.

The labeller sees ``pages/`` and the brief only (blind labelling); nothing is labelled here.
"""

from __future__ import annotations

import argparse
import json
import random
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sqlalchemy import text

from apps.menu_pipeline.bundle import BundleStore
from apps.menu_pipeline.extraction import OutputStore, page_html
from apps.menu_pipeline.run_report import run_started
from packages.helios_core.db.session import get_sessionmaker

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sqlalchemy.orm import Session

SIZE = 10
EXTRACTOR_PARTS = 4  # model;prompt;chunker;segmenter: the saved-answer key in method_version

_CANDIDATES = text(
    """
    select p.id as page_id, p.source_record_version_id as version_id, p.subject_id,
           p.method_version, r.external_key as record_key,
           v.source_payload->>'menu_url' as menu_url,
           v.source_payload->>'text_hash' as text_hash,
           c.bundle_path,
           coalesce(
             (select o.canonical_name from identity.organization o
               where o.subject_id = p.subject_id),
             (select o.canonical_name from identity.establishment e
                join identity.organization o on o.subject_id = e.organization_subject_id
               where e.subject_id = p.subject_id)
           ) as venue
      from menu.menu_page p
      join bronze.source_record r on r.id = p.source_record_id
      join bronze.source_record_version v on v.id = p.source_record_version_id
      join bronze.capture c on c.id = v.capture_id
     where p.source_kind = 'llm' and p.state = 'published'
       and p.accepted_at >= :since and p.accepted_at < :until
       and not exists (
         select 1 from menu.menu_page q
          where q.source_record_version_id = p.source_record_version_id
            and q.source_kind = 'llm' and q.id < p.id)
     order by p.id
    """
)


@dataclass(frozen=True, slots=True)
class Candidate:
    page_id: int
    version_id: int
    subject_id: int
    method_version: str
    record_key: str
    menu_url: str | None
    text_hash: str | None
    bundle_path: str | None
    venue: str | None

    @property
    def extractor(self) -> str:
        return ";".join(self.method_version.split(";")[:EXTRACTOR_PARTS])


def default_seed(run_id: str) -> int:
    """The run id's digits: ``20261210T180002Z`` → ``20261210180002``."""
    return int("".join(ch for ch in run_id if ch.isdigit()))


def candidates(session: Session, since: datetime, until: datetime) -> list[Candidate]:
    rows = session.execute(_CANDIDATES, {"since": since, "until": until}).mappings()
    return [Candidate(**row) for row in rows]


def draw(pool: Sequence[Candidate], seed: int, size: int = SIZE) -> list[Candidate]:
    """``size`` pages (all when fewer) by ``random.Random(seed)`` over the pool in page order,
    so a seed names the same pages however the pool was read; returned in page order."""
    ordered = sorted(pool, key=lambda c: c.page_id)
    chosen = random.Random(seed).sample(ordered, min(size, len(ordered)))  # noqa: S311 - a draw, not a secret
    return sorted(chosen, key=lambda c: c.page_id)


BRIEF = """# Spot-check labelling packet: run {run_id}

ADR-0013 §8 Amendment 3 item 4, ADR-0030 Amendment 1 A4. {drawn} of {candidates} newly
extracted pages, drawn with seed {seed} (`manifest.json`).

**Labeller (blind):** read only `pages/` and this file. Do not open `extract/` or look at the
pipeline's Menu rows for these pages until your labels are frozen. Write one gold label per page
as `labels/<page_id>.json` in the gold-label format (`packages/helios_parsing/evaluation.py`),
marking promo rows as that format asks. Read `<page_id>.pdf` where there is one (a PDF menu),
otherwise `<page_id>.html` in a browser; `<page_id>.blocks.json` is the harness's input, not
for labelling. The manifest's `page_file` names the file to read.

**Scoring, after the labels are frozen:**

```bash
uv run python -m apps.menu_pipeline.evaluate report run-{run_id} --data <this folder> \\
    --labels <this folder>/labels
```

The owner reviews only the rows where the label and the pipeline disagree; confirmed labels
are final. Pass = the §8 extraction bars on the pooled sample. A failure is a finding in
`docs/reviews/`, these pages become the next held-out set, and the run is not blocked.
"""


def write_packet(  # noqa: PLR0913 - one packet's inputs
    out_dir: Path,
    *,
    run_id: str,
    seed: int,
    since: datetime,
    until: datetime,
    pool: Sequence[Candidate],
    chosen: Sequence[Candidate],
    base_dir: Path,
) -> dict[str, Any]:
    """Write the packet (module docstring); returns the manifest."""
    pages_dir, labels_dir = out_dir / "pages", out_dir / "labels"
    answers_dir = out_dir / "extract" / f"run-{run_id}"
    for folder in (pages_dir, labels_dir, answers_dir):
        folder.mkdir(parents=True, exist_ok=True)
    bundles, outputs = BundleStore(base_dir), OutputStore(base_dir)
    entries = []
    for page in chosen:
        entry: dict[str, Any] = asdict(page)
        entry["page_file"] = None
        entry["answers"] = False
        if page.bundle_path is not None:
            bundle = bundles.read(page.bundle_path)
            stem = pages_dir / str(page.page_id)
            # the harness's inputs, exactly as production read them: blocks and page text
            stem.with_suffix(".html").write_text(page_html(bundle), encoding="utf-8")
            blocks = [asdict(block) for block in bundle.blocks]
            stem.with_suffix(".blocks.json").write_text(json.dumps(blocks) + "\n", "utf-8")
            path = stem.with_suffix(".html")
            if "pdf" in bundle.content_type.lower() and bundle.body is not None:
                path = stem.with_suffix(".pdf")  # the labeller reads the PDF itself
                path.write_bytes(bundle.body)
            entry["page_file"] = str(path.relative_to(out_dir))
        if page.text_hash is not None:
            record = outputs.read_record(page.extractor, page.text_hash)
            if record is not None:
                (answers_dir / f"{page.page_id}.json").write_text(
                    json.dumps(record, ensure_ascii=False) + "\n", encoding="utf-8"
                )
                entry["answers"] = True
        entries.append(entry)
    manifest = {
        "run_id": run_id,
        "seed": seed,
        "since": since.isoformat(),
        "until": until.isoformat(),
        "candidates": len(pool),
        "size": len(chosen),
        "pages": entries,
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=1) + "\n", "utf-8")
    (out_dir / "README.md").write_text(
        BRIEF.format(run_id=run_id, drawn=len(chosen), candidates=len(pool), seed=seed), "utf-8"
    )
    return manifest


def _instant(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="python -m apps.menu_pipeline.spot_check",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--run-id", required=True, help="the loop start, UTC: 20261210T180002Z")
    parser.add_argument("--until", type=_instant, help="window end (default: now)")
    parser.add_argument("--size", type=int, default=SIZE)
    parser.add_argument("--seed", type=int, help="default: the run id's digits")
    parser.add_argument("--out-dir", type=Path, help="default var/pipeline-host/reports/<run>/…")
    parser.add_argument("--base-dir", type=Path, default=Path(), help="deploy dir (var/replay)")
    args = parser.parse_args(argv)
    since = run_started(args.run_id)
    until = args.until or datetime.now(UTC)
    seed = default_seed(args.run_id) if args.seed is None else args.seed
    out_dir = args.out_dir or Path("var/pipeline-host/reports") / args.run_id / "spot-check"
    with get_sessionmaker()() as session:
        pool = candidates(session, since, until)
    chosen = draw(pool, seed, args.size)
    manifest = write_packet(
        out_dir,
        run_id=args.run_id,
        seed=seed,
        since=since,
        until=until,
        pool=pool,
        chosen=chosen,
        base_dir=args.base_dir,
    )
    summary = {k: manifest[k] for k in ("run_id", "seed", "candidates", "size")}
    print("spot check complete: " + json.dumps(summary | {"packet": str(out_dir)}))  # noqa: T201 - CLI output


if __name__ == "__main__":
    main()
