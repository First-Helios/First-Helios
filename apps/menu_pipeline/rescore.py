"""CLI: R4 re-score of the stored menu pages, without the extraction model::

    python -m apps.menu_pipeline.rescore

ADR-0013 Amendment 24 item 5 and Amendment 27. What an extraction run does
before it calls the model, on its own, so a verifier change can be applied
(and its withdrawals counted) before any extraction pass:

1. withdraw the published Menu streams of every record whose menu URL was
   withdrawn (ADR-0015) or whose latest fetch was a classifier rejection;
2. score the bundle of every due page (after a pipeline-version bump, every
   stored page not already out of the queue) with the live verifier, and
   withdraw the pages it rejects the same way.

A rejected page with no published stream (never extracted, or already
withdrawn) has nothing to withdraw: it is counted ``rejected_unwritten`` and
stays due, and extraction skips it again. Accepted pages are left for
extraction. Reads bundles under ``--base-dir``; commits after every record.
Needs the ``menu`` extra and model files matching ``config/models.yaml``.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from apps.menu_pipeline.bundle import BundleStore
from apps.menu_pipeline.classifier import load_verifier
from apps.menu_pipeline.extract import EXTRACTION_MODEL
from apps.menu_pipeline.extraction import RESCORED, PipelineVersion, model_tag, rejects
from apps.menu_pipeline.menu_writes import Withdrawals, due_pages, retract_rejected, withdraw
from apps.menu_pipeline.models import DEFAULT_ROOT, load_manifest
from packages.helios_core.db.session import get_sessionmaker
from packages.helios_parsing.segment import text_hash

if TYPE_CHECKING:
    from collections.abc import Callable

    from sqlalchemy.orm import Session

    from apps.menu_pipeline.extraction import PageScorer


@dataclass(slots=True)
class RescoreReport:
    """Counts from one re-score (pages unless named otherwise)."""

    method_version: str = ""
    due: int = 0  # due pages after step 1
    scored: int = 0
    accepted: int = 0
    rejected: int = 0
    rejected_unwritten: int = 0  # rejected, nothing published to withdraw (stay due)
    failed: Counter[str] = field(default_factory=Counter)  # bundle_unreadable / bundle_mismatch
    not_due: dict[str, int] = field(default_factory=dict)  # due_pages' counts before step 2
    withdrawals: Withdrawals = field(default_factory=Withdrawals)
    rejected_keys: list[str] = field(default_factory=list)

    def summary(self) -> dict[str, object]:
        out: dict[str, object] = {
            name: getattr(self, name)
            for name in self.__dataclass_fields__
            if name not in {"failed", "withdrawals", "rejected_keys"}
        }
        out["failed"] = dict(sorted(self.failed.items()))
        out["withdrawals"] = self.withdrawals.summary()
        out["rejected_keys"] = sorted(self.rejected_keys)
        return out


def rescore_pages(
    session: Session,
    *,
    scorer: PageScorer,
    bundles: BundleStore,
    model: str,
    commit: Callable[[], None] | None = None,
) -> RescoreReport:
    """Withdraw rejected records, then score every due page's bundle (``commit`` per record)."""
    version = PipelineVersion(model=model, classifier=scorer.name)
    report = RescoreReport(method_version=version.llm)
    retract_rejected(
        session, method_versions=version.streams, withdrawals=report.withdrawals, commit=commit
    )
    due, skipped = due_pages(session, version.llm)
    report.not_due = dict(skipped)
    report.due = len(due)
    for page in due:
        try:
            bundle = bundles.read(page.bundle_path)
        except (OSError, ValueError):
            report.failed["bundle_unreadable"] += 1
            continue
        if text_hash(list(bundle.blocks)) != page.text_hash:
            report.failed["bundle_mismatch"] += 1
            continue
        report.scored += 1
        if not rejects(scorer, bundle):
            report.accepted += 1
            continue
        report.rejected += 1
        report.rejected_keys.append(page.key)
        report.rejected_unwritten += not withdraw(
            session,
            page,
            RESCORED,
            method_versions=version.streams,
            withdrawals=report.withdrawals,
            commit=commit,
        )
    return report


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m apps.menu_pipeline.rescore")
    parser.add_argument(
        "--base-dir",
        type=Path,
        default=Path(),
        help="deploy directory that bundle paths (var/replay/...) are relative to",
    )
    parser.add_argument(
        "--model-root", type=Path, default=DEFAULT_ROOT, help="verified model files (ADR-0013)"
    )
    args = parser.parse_args()
    try:
        scorer = load_verifier(model_root=args.model_root)
    except ModuleNotFoundError as error:
        raise SystemExit(
            f"the page classifier needs the `menu` extra (worker image): {error}"
        ) from error
    with get_sessionmaker()() as session:
        report = rescore_pages(
            session,
            scorer=scorer,
            bundles=BundleStore(args.base_dir),
            model=model_tag(load_manifest()[EXTRACTION_MODEL]),
            commit=session.commit,
        )
        session.commit()
    print("rescore complete: " + json.dumps(report.summary()))  # noqa: T201 - CLI output


if __name__ == "__main__":
    main()
