"""CLI: one pipeline run's report (ADR-0030 Amendment 1 A3)::

    python -m apps.menu_pipeline.run_report --run-id 20261210T180002Z
        [--logs var/pipeline-host/logs] [--out-dir DIR] [--end-reason REASON]
        [--failed-step STEP]

The batch loop runs it at the end of every run (in the worker image on the Pi, pointed at the
master by ``apps.menu_pipeline.with_db``). A run is the loop's lines in ``progress.log`` from
the ``loop start`` stamped with the run id up to the next ``loop start``. The report reads:

- each batch's CLI summary (``batch-NNN-{fetch,extract,extract-only}.out``): pages fetched,
  changed and extracted, outcomes by reason code, model pages and pages/h, and each
  extraction's SoC peak and CPU frequency cap;
- the end-of-batch SoC (laptop: GPU and CPU) readings in the progress lines;
- ``gate.json`` and ``spot-check/manifest.json`` in ``--out-dir``, when the loop wrote them;
- the master database, for venue freshness against the 45-day target (ROADMAP §2).

It writes ``run-report.json`` and ``run-report.md`` to ``--out-dir`` (default
``var/pipeline-host/reports/<run id>``) and prints the Markdown.

**Freshness.** A covered venue has a menu (the API's ``_has_menu``). Its newest observation is
the newest ``succeeded`` Capture at an endpoint of any menu-page record behind its Gold rows
(Establishment or Organization scope). An unchanged re-read writes such a Capture without a
Version (ADR-0013 Amendment 4), so a venue whose menu did not change stays fresh.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sqlalchemy import select, text

from apps.api.routes.venues import _has_menu
from apps.menu_pipeline.batch_loop import EXTRACT_DONE, FETCH_DONE, last_summary
from packages.helios_core.db.session import get_sessionmaker
from packages.helios_core.identity.models import Establishment

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

    from sqlalchemy.orm import Session

TARGET_DAYS = 45  # ROADMAP §2: >= 80% of covered venues observed within 45 days
TARGET_SHARE = 0.80
AGE_BUCKETS = ((20, "le_20d"), (45, "d21_45"))  # then "gt_45d"; "never" without a Capture
RUN_ID_FORMAT = "%Y%m%dT%H%M%SZ"
STAMP_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
_BATCH = re.compile(r"^\S+ batch (\d{3,}) ")
_START = re.compile(r"loop start: host (\S+), phase (\S+), db (\S+), master (.*), batches")
_COMMIT = re.compile(r"'commit': '([0-9a-f]+)'")
_SOC = re.compile(r"\b(?:SoC|CPU)=([0-9.]+)C")
_GPU = re.compile(r"\bGPU=([0-9]+)C")
# extraction summary counts summed over batches
_EXTRACT_SUMS = (
    "due",
    "extracted",
    "reused_outputs",
    "chunks",
    "reused_chunks",
    "items_written",
    "prices_written",
    "empty",
    "flagged",
    "rejected",
    "withdrawn",
    "jsonld_pages",
)
_FETCH_SUMS = ("fetched", "renders", "versions_new", "versions_changed", "unchanged")


def run_started(run_id: str) -> datetime:
    """The loop start a run id names (UTC)."""
    return datetime.strptime(run_id, RUN_ID_FORMAT).replace(tzinfo=UTC)


def run_lines(progress: str, run_id: str) -> list[str]:
    """The run's ``progress.log`` lines: its ``loop start`` up to the next one."""
    stamp = run_started(run_id).strftime(STAMP_FORMAT)
    lines = progress.splitlines()
    start = next(
        (i for i, line in enumerate(lines) if line.startswith(f"{stamp} loop start:")), None
    )
    if start is None:
        raise ValueError(f"no 'loop start' at {stamp} in progress.log")
    out = [lines[start]]
    for line in lines[start + 1 :]:
        if " loop start:" in line:
            break
        out.append(line)
    return out


@dataclass(slots=True)
class Batch:
    """One batch: its CLI summaries and the loop's end-of-batch readings."""

    number: str
    fetch: dict[str, object] = field(default_factory=dict)
    extract: dict[str, object] = field(default_factory=dict)
    soc_end: float | None = None
    gpu_end: int | None = None

    def thermal(self) -> dict[str, object]:
        return {
            "batch": self.number,
            "soc_end_c": self.soc_end,
            "soc_max_c": self.extract.get("soc_max_temp_c"),
            "cpu_freq_cap": self.extract.get("cpu_freq_cap"),
            "gpu_end_c": self.gpu_end,
        }


def read_batches(lines: Sequence[str], logs: Path) -> list[Batch]:
    """The run's batches, in order, with each CLI's last summary line."""
    batches = []
    for line in lines:
        match = _BATCH.match(line)
        if match is None:
            continue
        number = match.group(1)
        soc = _SOC.search(line)
        gpu = _GPU.search(line)
        extract = last_summary(logs / f"batch-{number}-extract.out", EXTRACT_DONE)
        if not extract:
            extract = last_summary(logs / f"batch-{number}-extract-only.out", EXTRACT_DONE)
        batches.append(
            Batch(
                number=number,
                fetch=last_summary(logs / f"batch-{number}-fetch.out", FETCH_DONE),
                extract=extract,
                soc_end=float(soc.group(1)) if soc else None,
                gpu_end=int(gpu.group(1)) if gpu else None,
            )
        )
    return batches


def _int(value: object) -> int:
    return value if isinstance(value, int) else 0


def _add(total: Counter[str], value: object) -> None:
    if isinstance(value, dict):
        for key, count in value.items():
            if isinstance(count, int):
                total[str(key)] += count


def _numbers(values: Iterable[object]) -> list[float]:
    return [float(v) for v in values if isinstance(v, int | float) and not isinstance(v, bool)]


def aggregate(batches: Sequence[Batch]) -> dict[str, Any]:
    """Pages, outcomes, model and thermal sections over the run's batches."""
    fetch = {key: sum(_int(b.fetch.get(key)) for b in batches) for key in _FETCH_SUMS}
    last_fetch = next((b.fetch for b in reversed(batches) if b.fetch), {})
    extract = {key: sum(_int(b.extract.get(key)) for b in batches) for key in _EXTRACT_SUMS}
    model_pages = extract["extracted"] - extract["reused_outputs"]
    hours = sum(_numbers(b.extract.get("wall_s") for b in batches)) / 3600
    outcomes: Counter[str] = Counter()
    failed: Counter[str] = Counter()
    due: Counter[str] = Counter()
    withdrawn_records: Counter[str] = Counter()
    for b in batches:
        _add(outcomes, b.fetch.get("outcomes"))
        _add(failed, b.extract.get("failed"))
        _add(due, b.extract.get("due_by_reason"))
        withdrawals = b.extract.get("withdrawals")
        if isinstance(withdrawals, dict):
            _add(withdrawn_records, withdrawals.get("records"))
    socs = _numbers(
        [b.soc_end for b in batches] + [b.extract.get("soc_max_temp_c") for b in batches]
    )
    caps = _numbers(b.extract.get("cpu_freq_cap") for b in batches)
    gpus = _numbers(b.gpu_end for b in batches)
    cap_min = min(caps) if caps else None
    return {
        "pages": {
            "urls_fetched": fetch["fetched"],
            "renders": fetch["renders"],
            "versions_new": fetch["versions_new"],
            "versions_changed": fetch["versions_changed"],
            "changed": fetch["versions_new"] + fetch["versions_changed"],
            "unchanged": fetch["unchanged"],
            "urls_not_due_after_last_batch": last_fetch.get("not_due"),
            "due": extract["due"],
            "extracted": extract["extracted"],
            "reused_outputs": extract["reused_outputs"],
            "model_pages": model_pages,
            "chunks": extract["chunks"],
            "reused_chunks": extract["reused_chunks"],
            "empty": extract["empty"],
            "flagged": extract["flagged"],
            "jsonld_pages": extract["jsonld_pages"],
            "items_written": extract["items_written"],
            "prices_written": extract["prices_written"],
        },
        "outcomes": {
            "capture": dict(sorted(outcomes.items())),
            "extraction_failed": dict(sorted(failed.items())),
            "due_by_reason": dict(sorted(due.items())),
            "rejected": extract["rejected"],
            "withdrawn": extract["withdrawn"],
            "withdrawn_records": dict(sorted(withdrawn_records.items())),
        },
        "model": {
            "model_pages": model_pages,
            "extract_hours": round(hours, 2),
            "model_pages_per_hour": round(model_pages / hours, 2) if hours > 0 else None,
            "pages_per_hour": round(extract["extracted"] / hours, 2) if hours > 0 else None,
        },
        "thermal": {
            "soc_peak_c": max(socs) if socs else None,
            "cpu_freq_cap_min": cap_min,
            "throttled": None if cap_min is None else cap_min < 1.0,
            "gpu_peak_c": max(gpus) if gpus else None,
            "batches": [b.thermal() for b in batches],
        },
    }


def freshness_summary(observed: Mapping[int, datetime | None], now: datetime) -> dict[str, Any]:
    """Covered venues by age of their newest observation, against the 45-day target."""
    buckets = Counter({name: 0 for _, name in AGE_BUCKETS} | {"gt_45d": 0, "never": 0})
    for at in observed.values():
        if at is None:
            buckets["never"] += 1
            continue
        days = (now - at).total_seconds() / 86400
        name = next((n for limit, n in AGE_BUCKETS if days <= limit), "gt_45d")
        buckets[name] += 1
    covered = len(observed)
    fresh = buckets["le_20d"] + buckets["d21_45"]
    share = fresh / covered if covered else None
    return {
        "as_of": now.strftime(STAMP_FORMAT),
        "target_days": TARGET_DAYS,
        "target_share": TARGET_SHARE,
        "covered_venues": covered,
        "observed_within_target": fresh,
        "share": None if share is None else round(share, 4),
        "passed": None if share is None else share >= TARGET_SHARE,
        "by_age": dict(buckets),
    }


_OBSERVED = """
with gold_pages as (
  select distinct g.subject_id, unnest(array[g.price_page_id, g.content_page_id]) as page_id
    from gold.current_menu g
), records as (
  select distinct e.subject_id, p.source_record_id
    from identity.establishment e
    join gold_pages gp on gp.subject_id in (e.subject_id, e.organization_subject_id)
    join menu.menu_page p on p.id = gp.page_id
   where e.subject_id = any(:venues)
), endpoints as (
  select distinct r.subject_id, c.source_id, c.source_endpoint_id
    from records r
    join bronze.source_record_version v on v.source_record_id = r.source_record_id
    join bronze.capture c on c.id = v.capture_id
)
select ep.subject_id, max(c.fetched_at) as observed_at
  from endpoints ep
  join bronze.capture c
    on c.source_endpoint_id = ep.source_endpoint_id
   and c.source_id = ep.source_id
   and c.outcome = 'succeeded'
 group by ep.subject_id
"""


def observed_at(session: Session) -> dict[int, datetime | None]:
    """Each covered venue's newest observation (module docstring); ``None``: never."""
    venues = sorted(session.scalars(select(Establishment.subject_id).where(_has_menu())))
    seen = {
        row.subject_id: row.observed_at
        for row in session.execute(text(_OBSERVED), {"venues": venues})
    }
    return {venue: seen.get(venue) for venue in venues}


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return document if isinstance(document, dict) else None


def gate_summary(gate: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if gate is None:
        return None
    return {
        key: gate.get(key)
        for key in (
            "passed",
            "stop_reasons",
            "rows_change",
            "venues_change",
            "median_shift",
            "gained",
            "lost_by_kind",
        )
    } | {
        "current_menu_rows": (gate.get("master") or {}).get("current_menu_rows"),
        "venues_with_menu": (gate.get("master") or {}).get("venues_with_menu"),
    }


def spot_summary(manifest: Mapping[str, Any] | None, out_dir: Path) -> dict[str, Any] | None:
    if manifest is None:
        return None
    return {
        "seed": manifest.get("seed"),
        "candidates": manifest.get("candidates"),
        "drawn": len(manifest.get("pages") or []),
        "packet": str(out_dir / "spot-check"),
    }


def run_section(
    lines: Sequence[str], batches: Sequence[Batch], run_id: str, now: datetime
) -> dict[str, Any]:
    start = _START.search(lines[0])
    commit = _COMMIT.search(lines[0])
    return {
        "id": run_id,
        "host": start.group(1) if start else None,
        "phase": start.group(2) if start else None,
        "db": start.group(3) if start else None,
        "commit": commit.group(1) if commit else None,
        "started_at": run_started(run_id).strftime(STAMP_FORMAT),
        "ended_at": now.strftime(STAMP_FORMAT),
        "batches": [b.number for b in batches],
    }


def build_report(  # noqa: PLR0913 - one report's inputs
    *,
    run_id: str,
    lines: Sequence[str],
    batches: Sequence[Batch],
    freshness: dict[str, Any] | None,
    out_dir: Path,
    now: datetime,
    end_reason: str | None,
    failed_step: str | None,
) -> dict[str, Any]:
    run = run_section(lines, batches, run_id, now) | {
        "end_reason": end_reason,
        "failed_step": failed_step,
    }
    return (
        {"run": run}
        | aggregate(batches)
        | {
            "freshness": freshness,
            "gate": gate_summary(_read_json(out_dir / "gate.json")),
            "spot_check": spot_summary(
                _read_json(out_dir / "spot-check" / "manifest.json"), out_dir
            ),
        }
    )


def _pct(value: object) -> str:
    return f"{value:.1%}" if isinstance(value, float) else "n/a"


def markdown(report: Mapping[str, Any]) -> str:
    """The short human summary of :func:`build_report`'s document."""
    run, pages, model = report["run"], report["pages"], report["model"]
    thermal, outcomes = report["thermal"], report["outcomes"]
    lines = [
        f"# Pipeline run {run['id']}",
        "",
        f"- **Run:** host {run['host']}, phase {run['phase']}, db {run['db']}, "
        f"commit {run['commit']}; {run['started_at']} to {run['ended_at']}; "
        f"{len(run['batches'])} batches; ended: {run['end_reason']}"
        + (f" (failed step: {run['failed_step']})" if run["failed_step"] else ""),
        f"- **Pages:** {pages['urls_fetched']} URLs fetched ({pages['renders']} rendered), "
        f"{pages['changed']} records changed ({pages['versions_new']} new, "
        f"{pages['versions_changed']} changed), {pages['unchanged']} unchanged; "
        f"{pages['extracted']} pages extracted ({pages['reused_outputs']} from saved answers, "
        f"{pages['model_pages']} by the model), {pages['prices_written']} prices written",
        f"- **Model:** {model['model_pages']} model pages in {model['extract_hours']} h of "
        f"extraction: {model['model_pages_per_hour']} model pages/h, "
        f"{model['pages_per_hour']} pages/h overall",
        f"- **Thermal:** SoC peak {thermal['soc_peak_c']} °C, lowest CPU frequency cap "
        f"{thermal['cpu_freq_cap_min']} (throttled: {thermal['throttled']})"
        + (f", GPU peak {thermal['gpu_peak_c']} °C" if thermal["gpu_peak_c"] is not None else ""),
        f"- **Capture outcomes:** {json.dumps(outcomes['capture'])}; extraction failures "
        f"{json.dumps(outcomes['extraction_failed'])}; withdrawn {outcomes['withdrawn']}",
    ]
    fresh = report["freshness"]
    if fresh is not None:
        verdict = "meets" if fresh["passed"] else "misses"
        lines.append(
            f"- **Freshness ({fresh['as_of']}):** {fresh['observed_within_target']} of "
            f"{fresh['covered_venues']} covered venues observed within {fresh['target_days']} "
            f"days ({_pct(fresh['share'])}), {verdict} the {fresh['target_share']:.0%} target; "
            f"by age {json.dumps(fresh['by_age'])}"
        )
    gate = report["gate"]
    if gate is not None:
        state = "passed" if gate["passed"] else "STOPPED: " + "; ".join(gate["stop_reasons"])
        lines.append(
            f"- **Gate:** {state}. Rows {_pct(gate['rows_change'])}, venues with a menu "
            f"{_pct(gate['venues_change'])} ({gate['venues_with_menu']}), median "
            f"{_pct(gate['median_shift'])}, gained {gate['gained']}, lost by kind "
            f"{json.dumps(gate['lost_by_kind'])}. No swap was made: a reader decides."
        )
    spot = report["spot_check"]
    if spot is not None:
        lines.append(
            f"- **Spot check:** {spot['drawn']} of {spot['candidates']} newly extracted pages "
            f"drawn (seed {spot['seed']}): `{spot['packet']}`"
        )
    return "\n".join(lines) + "\n"


def write_report(report: Mapping[str, Any], out_dir: Path) -> str:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "run-report.json").write_text(
        json.dumps(report, indent=1, default=str) + "\n", encoding="utf-8"
    )
    text = markdown(report)
    (out_dir / "run-report.md").write_text(text, encoding="utf-8")
    return text


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="python -m apps.menu_pipeline.run_report",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--run-id", required=True, help="the loop start, UTC: 20261210T180002Z")
    parser.add_argument("--logs", type=Path, default=Path("var/pipeline-host/logs"))
    parser.add_argument("--out-dir", type=Path, help="default var/pipeline-host/reports/<run id>")
    parser.add_argument("--end-reason", help="why the loop ended (the loop passes it)")
    parser.add_argument("--failed-step", help="the end-of-run step that failed, if one did")
    args = parser.parse_args(argv)
    out_dir = args.out_dir or Path("var/pipeline-host/reports") / args.run_id
    lines = run_lines((args.logs / "progress.log").read_text(encoding="utf-8"), args.run_id)
    batches = read_batches(lines, args.logs)
    now = datetime.now(UTC)
    with get_sessionmaker()() as session:
        freshness = freshness_summary(observed_at(session), now)
    report = build_report(
        run_id=args.run_id,
        lines=lines,
        batches=batches,
        freshness=freshness,
        out_dir=out_dir,
        now=now,
        end_reason=args.end_reason,
        failed_step=args.failed_step,
    )
    print(write_report(report, out_dir), end="")  # noqa: T201 - CLI output


if __name__ == "__main__":
    main()
