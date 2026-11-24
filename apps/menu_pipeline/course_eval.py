"""Draw a course label set and score labellers against it (ADR-0016 §4, Amendment 1).

The pure harness is ``packages.helios_parsing.course_eval``; this is its file
side. Label sets live in gitignored ``var/course-labels/<set>/`` (``manifest.json``
and ``sections.jsonl``), arm predictions and reports in ``var/course-eval/<set>/``;
only counts and rates go into ``docs/reviews/`` (template:
``docs/reviews/templates/course-labeller-evaluation.md``). The procedure is
``docs/course-labelling-guide.md``::

    uv run python -m apps.menu_pipeline.course_eval sample \\
        --candidates CANDIDATES.jsonl --exclude HELD_OUT_VENUES.txt [--exclude …] \\
        --set set-1 --seed SEED --venues 120 --method-version METHOD_VERSION \\
        [--unsectioned UNSECTIONED.json] [--root var/course-labels]
    uv run python -m apps.menu_pipeline.course_eval disagreements \\
        --labels var/course-labels/set-1 --exclude … PREDICTIONS.jsonl [PREDICTIONS.jsonl …]
    uv run python -m apps.menu_pipeline.course_eval score \\
        --labels var/course-labels/set-1 --exclude … PREDICTIONS.jsonl [--out REPORT.json]
    uv run python -m apps.menu_pipeline.course_eval confirm \\
        --labels var/course-labels/set-1 --exclude … --review REVIEW.tsv \\
        PREDICTIONS.jsonl [PREDICTIONS.jsonl …]
    uv run python -m apps.menu_pipeline.course_eval compare BASELINE.json MODEL.json

``sample`` reads candidate sections (label-set rows without split or labels, one
per Gold-reaching named section) and, optionally, a JSON object of unsectioned
priced items per venue; it never overwrites a drawn set. ``disagreements`` lists
the test sections the owner must review, and ``--review-out`` writes them as a
TSV with an empty ``confirmed`` column; ``confirm`` applies the owner's filled-in
TSV (a course, or ``=`` to keep the agent's label) to the pending disagreements
only, setting ``label`` and ``owner_confirmed`` and never ``agent_label``;
``score`` refuses until there are none
and writes the report (default ``var/course-eval/<set>/<labeller>.json``);
``compare`` applies the winner rule. Every command that reads a label set needs
the exclusion lists it was drawn with.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, Any

from packages.helios_parsing.course_eval import (
    ABSTAIN,
    COURSES,
    LabelSetError,
    Manifest,
    Section,
    check_label_set,
    disagreements,
    draw_label_set,
    exclusion_ids,
    predictions_of,
    score,
    section,
    winner,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

DEFAULT_LABELS = Path("var/course-labels")
DEFAULT_REPORTS = Path("var/course-eval")
SHOWN_ITEMS = 6  # item names per disagreement line


def read_jsonl(path: Path) -> Iterator[dict[str, Any]]:
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                yield json.loads(line)


def read_exclusions(paths: list[Path]) -> frozenset[str]:
    return frozenset().union(
        *(exclusion_ids(p.read_text(encoding="utf-8").splitlines()) for p in paths)
    )


def load_label_set(directory: Path, excluded: frozenset[str]) -> tuple[Manifest, list[Section]]:
    """A drawn label set, refused unless it is the one drawn with these exclusions."""
    manifest = Manifest.from_json(
        json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    )
    rows = [
        section(raw, f"{directory.name}:{n}")
        for n, raw in enumerate(read_jsonl(directory / "sections.jsonl"), 1)
    ]
    check_label_set(manifest, rows, excluded)
    return manifest, rows


def cmd_sample(args: argparse.Namespace) -> None:
    out = args.root / args.set
    if (out / "sections.jsonl").exists() or (out / "manifest.json").exists():
        raise LabelSetError(f"{out} already holds a label set; a drawn split never moves")
    candidates = [
        section(raw, f"candidate {n}") for n, raw in enumerate(read_jsonl(args.candidates), 1)
    ]
    unsectioned = (
        json.loads(args.unsectioned.read_text(encoding="utf-8")) if args.unsectioned else None
    )
    manifest, rows = draw_label_set(
        candidates,
        read_exclusions(args.exclude),
        set_name=args.set,
        seed=args.seed,
        venues=args.venues,
        method_version=args.method_version,
        unsectioned=unsectioned,
    )
    out.mkdir(parents=True, exist_ok=True)
    (out / "manifest.json").write_text(
        json.dumps(manifest.to_json(), indent=1) + "\n", encoding="utf-8"
    )
    with (out / "sections.jsonl").open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row.to_json(), ensure_ascii=False) + "\n")
    test = [row for row in rows if row.split == "test"]
    print(
        f"{manifest.set}: venues={manifest.sampled_venues} sections={len(rows)} "
        f"test venues={len({row.venue for row in test})} test sections={len(test)} "
        f"excluded={manifest.excluded_venues}"
    )


REVIEW_COLUMNS = ("section_key", "name", "agent", "arms", "priced_items", "items", "confirmed")


def _tsv(value: object) -> str:
    return str(value).replace("\t", " ").replace("\n", " ")


def cmd_disagreements(args: argparse.Namespace) -> None:
    _manifest, rows = load_label_set(args.labels, read_exclusions(args.exclude))
    arms = [predictions_of(read_jsonl(path)) for path in args.predictions]
    pending = disagreements(rows, [arm for _, arm in arms], args.split)
    if args.review_out:
        with args.review_out.open("w", encoding="utf-8") as handle:
            handle.write("\t".join(REVIEW_COLUMNS) + "\n")
            for row, predicted in pending:
                fields = (
                    row.section_key,
                    " > ".join(row.name_path),
                    row.agent_label,
                    " ".join(c or ABSTAIN for c in predicted),
                    row.priced_items,
                    " | ".join(row.items),
                    "",
                )
                handle.write("\t".join(_tsv(f) for f in fields) + "\n")
    print(f"{len(pending)} {args.split} sections to review; arms: {[name for name, _ in arms]}")
    for row, predicted in pending:
        shown = ", ".join(row.items[:SHOWN_ITEMS]) + (" …" if len(row.items) > SHOWN_ITEMS else "")
        arms_text = " ".join(c or ABSTAIN for c in predicted)
        print(
            f"{row.section_key}\t{' > '.join(row.name_path)}\tagent={row.agent_label}\t"
            f"arms={arms_text}\titems={row.priced_items}\t[{shown}]"
        )


def confirm_rows(
    rows: list[Section], pending_keys: set[str], review: dict[str, str]
) -> tuple[list[Section], int]:
    """Rows with the owner's confirmations applied (``=`` keeps the agent's label)."""
    if unknown := sorted(set(review) - pending_keys):
        raise LabelSetError(
            f"{len(unknown)} reviewed sections are not pending disagreements: {unknown[0]}"
        )
    out, n = [], 0
    for row in rows:
        decision = review.get(row.section_key)
        if decision is None:
            out.append(row)
            continue
        final = row.agent_label if decision == "=" else decision
        if final not in COURSES:
            raise LabelSetError(f"{row.section_key}: {decision!r} is not a course or '='")
        out.append(replace(row, label=final, owner_confirmed=True))
        n += 1
    return out, n


def cmd_confirm(args: argparse.Namespace) -> None:
    excluded = read_exclusions(args.exclude)
    manifest, rows = load_label_set(args.labels, excluded)
    arms = [arm for _, arm in (predictions_of(read_jsonl(p)) for p in args.predictions)]
    pending = {row.section_key for row, _ in disagreements(rows, arms)}
    review: dict[str, str] = {}
    with args.review.open(encoding="utf-8") as handle:
        header = handle.readline().rstrip("\n").split("\t")
        for line in handle:
            fields = dict(zip(header, line.rstrip("\n").split("\t"), strict=False))
            if decision := fields.get("confirmed", "").strip():
                review[fields["section_key"]] = decision
    updated, n = confirm_rows(rows, pending, review)
    check_label_set(manifest, updated, excluded)
    path = args.labels / "sections.jsonl"
    tmp = path.with_suffix(".jsonl.tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        for row in updated:
            handle.write(json.dumps(row.to_json(), ensure_ascii=False) + "\n")
    tmp.replace(path)
    changed = sum(1 for row in updated if row.owner_confirmed and row.label != row.agent_label)
    left = len(disagreements(updated, arms))
    print(
        f"confirmed {n} sections ({changed} changed in total); {left} disagreements still pending"
    )


def _fmt(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.3f}"


def markdown(report: dict[str, Any]) -> str:
    """The report's tables, ready for the ``docs/reviews/`` write-up."""
    lines = [
        f"**{report['labeller']}** on `{report['set']}` (seed {report['seed']}, "
        f"{report['test_venues']} test venues, {report['test_sections']} sections, "
        f"{report['test_items']} priced items)",
        "",
        "| Course | Predicted items | Correct | Precision | Sections | Venues | Readable | Passes |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for course, c in report["courses"].items():
        lines.append(
            f"| `{course}` | {c['predicted_items']} | {c['correct_items']} | "
            f"{_fmt(c['precision'])} | {c['predicted_sections']} | {c['predicted_venues']} | "
            f"{'yes' if c['readable'] else 'no'} | {'**yes**' if c['passes'] else 'no'} |"
        )
    abstain, other = report["abstain_rate"], report["other_rate"]
    lines += [
        "",
        f"- Passing: {', '.join(report['passing']) or 'none'}",
        f"- Coverage over passing courses: {_fmt(report['coverage'])} "
        f"({report['covered_items']} of {report['test_items']} items)",
        f"- Section accuracy: {_fmt(report['section_accuracy'])}",
        f"- Abstain: {_fmt(abstain['items'])} of items, {_fmt(abstain['sections'])} of sections",
        f"- `other`: {_fmt(other['items'])} of items, {_fmt(other['sections'])} of sections",
        f"- Unsectioned share: {_fmt(report['unsectioned_share'])}",
        f"- Owner review: {report['owner_review']['confirmed']} confirmed, "
        f"{report['owner_review']['changed']} changed",
        "",
        "Confusion (priced items; rows = final label, columns = prediction):",
        "",
    ]
    columns = [*COURSES, ABSTAIN]
    lines.append("| | " + " | ".join(columns) + " |")
    lines.append("|---" * (len(columns) + 1) + "|")
    for gold in COURSES:
        row = report["confusion_items"].get(gold, {})
        lines.append(f"| `{gold}` | " + " | ".join(str(row.get(c, 0)) for c in columns) + " |")
    return "\n".join(lines)


def cmd_score(args: argparse.Namespace) -> None:
    manifest, rows = load_label_set(args.labels, read_exclusions(args.exclude))
    labeller, arm = predictions_of(read_jsonl(args.predictions))
    report = score(manifest, rows, labeller, arm)
    out = args.out or DEFAULT_REPORTS / manifest.set / (
        re.sub(r"[^\w.@-]+", "_", labeller) + ".json"
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=1) + "\n", encoding="utf-8")
    print(markdown(report))
    print(f"\nreport: {out}")


def cmd_compare(args: argparse.Namespace) -> None:
    baseline, model = (
        json.loads(p.read_text(encoding="utf-8")) for p in (args.baseline, args.model)
    )
    for report in (baseline, model):
        print(
            f"{report['labeller']}: passing={','.join(report['passing']) or '-'} "
            f"covered={report['covered_items']}/{report['test_items']} "
            f"coverage={_fmt(report['coverage'])}"
        )
    chosen = winner(baseline, model)
    print(f"winner: {chosen}" if chosen else "winner: none (no arm passes any course)")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m apps.menu_pipeline.course_eval")
    commands = parser.add_subparsers(dest="command", required=True)

    sample = commands.add_parser("sample", help="draw a new label set")
    sample.add_argument("--candidates", type=Path, required=True)
    sample.add_argument("--exclude", type=Path, action="append", required=True)
    sample.add_argument("--set", required=True)
    sample.add_argument("--seed", type=int, required=True)
    sample.add_argument("--venues", type=int, default=120)
    sample.add_argument("--method-version", required=True)
    sample.add_argument("--unsectioned", type=Path)
    sample.add_argument("--root", type=Path, default=DEFAULT_LABELS)

    review = commands.add_parser("disagreements", help="sections for the owner to review")
    review.add_argument("--labels", type=Path, required=True)
    review.add_argument("--exclude", type=Path, action="append", required=True)
    review.add_argument("--split", choices=["train", "test"], default="test")
    review.add_argument("--review-out", type=Path, help="write the pending rows as a review TSV")
    review.add_argument("predictions", type=Path, nargs="+")

    confirming = commands.add_parser("confirm", help="apply the owner's review TSV")
    confirming.add_argument("--labels", type=Path, required=True)
    confirming.add_argument("--exclude", type=Path, action="append", required=True)
    confirming.add_argument("--review", type=Path, required=True)
    confirming.add_argument("predictions", type=Path, nargs="+")

    scoring = commands.add_parser("score", help="score one arm on the test split")
    scoring.add_argument("--labels", type=Path, required=True)
    scoring.add_argument("--exclude", type=Path, action="append", required=True)
    scoring.add_argument("--out", type=Path)
    scoring.add_argument("predictions", type=Path)

    compare = commands.add_parser("compare", help="apply the winner rule to two reports")
    compare.add_argument("baseline", type=Path)
    compare.add_argument("model", type=Path)

    args = parser.parse_args(argv)
    handler = {
        "sample": cmd_sample,
        "disagreements": cmd_disagreements,
        "confirm": cmd_confirm,
        "score": cmd_score,
        "compare": cmd_compare,
    }[args.command]
    try:
        handler(args)
    except LabelSetError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
