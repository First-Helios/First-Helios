"""CLI: extract due ``menu-page`` Versions into Menu pages (ADR-0013 slice 5)::

    python -m apps.menu_pipeline.extract --limit N

Run it after ``python -m apps.menu_pipeline.run`` has fetched pages, with
``llama-server`` up (session P5-4, X1)::

    docker compose -f infra/docker-compose.yml --profile menu up -d --wait llama-server
    docker compose -f infra/docker-compose.yml --profile menu run --rm worker \\
        python -m apps.menu_pipeline.extract --limit 20

It waits for ``/health`` (``--ready-timeout``), refuses a server whose ``/props``
names another model file than ``config/models.yaml`` or another slot count,
then extracts every due page from its bundle (no refetch) and writes its Menu
page aggregates, committing each page (:mod:`.extraction`). Resumable: a
page is due until its ``llm`` page exists at the current pipeline version, so an
interrupted run picks up where it stopped. ``--limit`` counts pages taken.
Raw model answers are kept under ``var/replay/menu-extract/``. Needs the ``menu``
extra (the page classifier gives page confidence), so it runs in the worker
image. Exits 1 when the run stopped after repeated page failures.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from apps.menu_pipeline.bundle import BundleStore
from apps.menu_pipeline.classifier import load_page_classifier
from apps.menu_pipeline.extraction import OutputStore, model_tag, run_extraction
from apps.menu_pipeline.llama_client import (
    DEFAULT_SERVER,
    READY_TIMEOUT_S,
    LlamaClient,
    http_client,
)
from apps.menu_pipeline.models import DEFAULT_ROOT, load_manifest
from packages.helios_core.db.session import get_sessionmaker

EXTRACTION_MODEL = "Qwen3-4B-Instruct-2507-Q4_0"  # config/models.yaml entry llama-server serves


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m apps.menu_pipeline.extract", description=__doc__
    )
    parser.add_argument("--limit", type=int, default=None, help="max pages taken")
    parser.add_argument("--server", default=DEFAULT_SERVER, help="llama-server base URL")
    parser.add_argument(
        "--ready-timeout", type=float, default=READY_TIMEOUT_S, help="seconds to wait for /health"
    )
    parser.add_argument(
        "--base-dir",
        type=Path,
        default=Path(),
        help="deploy directory that bundle and output paths (var/replay/...) are relative to",
    )
    parser.add_argument(
        "--model-root", type=Path, default=DEFAULT_ROOT, help="verified model files (ADR-0013)"
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    spec = load_manifest()[EXTRACTION_MODEL]
    try:
        scorer = load_page_classifier(model_root=args.model_root)
    except ModuleNotFoundError as error:
        raise SystemExit(
            f"the page classifier needs the `menu` extra (worker image): {error}"
        ) from error
    with http_client() as http, get_sessionmaker()() as session:
        client = LlamaClient(http, base_url=args.server)
        client.wait_ready(timeout_s=args.ready_timeout)
        (model_file,) = spec.files
        client.check_model(model_file.name)
        print(f"extraction started {datetime.now(UTC).isoformat()}", flush=True)  # noqa: T201 - CLI output
        report = run_extraction(
            session,
            extractor=client,
            scorer=scorer,
            bundles=BundleStore(args.base_dir),
            outputs=OutputStore(args.base_dir),
            model=model_tag(spec),
            limit=args.limit,
            commit=session.commit,  # Evidence, then the page's Menu writes
        )
        session.commit()
    print("extraction run complete: " + json.dumps(report.summary()))  # noqa: T201 - CLI output
    if report.aborted:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
