"""The run report and the spot-check draw (ADR-0030 Amendment 1 A3-A4), without a database.

The batch loop itself writes the logs these tests read, so a change to its line format breaks
them here rather than on the Pi.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest

from apps.menu_pipeline.batch_loop import FETCH, REPORT, Config, Host, Loop
from apps.menu_pipeline.evaluate import blocks_of
from apps.menu_pipeline.run_report import (
    TARGET_SHARE,
    aggregate,
    build_report,
    freshness_summary,
    markdown,
    read_batches,
    run_lines,
    write_report,
)
from apps.menu_pipeline.spot_check import Candidate, default_seed, draw
from packages.helios_parsing.segment import segment

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from pathlib import Path

_START = datetime(2026, 12, 10, 18, 0, 2, tzinfo=UTC)
RUN = "20261210T180002Z"


class _Pipeline:
    """Answers each batch's fetch and extract with a realistic summary line."""

    def __init__(self, fetched: list[int]) -> None:
        self.fetched = fetched
        self.batch = 0

    def run(
        self, command: Sequence[str], out: Path, err: Path, env: Mapping[str, str] | None
    ) -> int:
        del env
        err.write_text("")
        if (
            REPORT in command
            or "apps.menu_pipeline.extract" not in command
            and FETCH not in command
        ):
            out.write_text("")  # end-of-run steps: tested in test_batch_loop
            return 0
        if FETCH in command:
            self.batch += 1
            fetch = {
                "fetched": self.fetched[self.batch - 1],
                "not_due": 1700 - 50 * self.batch,
                "renders": 2,
                "versions_new": 1,
                "versions_changed": 9,
                "unchanged": 40,
                "outcomes": {"succeeded": 48, "http_404": 2},
            }
            out.write_text("menu-page run complete: " + json.dumps(fetch) + "\n")
            return 0
        extract = {
            "due": 10,
            "extracted": 10,
            "reused_outputs": 4,
            "chunks": 30,
            "reused_chunks": 5,
            "failed": {"chunk_failed": 1} if self.batch == 2 else {},
            "due_by_reason": {"changed": 9, "new": 1},
            "withdrawals": {"records": {"not_menu": 1}, "pages": {}, "not_eligible": 0},
            "withdrawn": 1,
            "prices_written": 300,
            "items_written": 250,
            "wall_s": 3600.0,
            "soc_max_temp_c": 84.5 + self.batch,
            "cpu_freq_cap": 1.0 if self.batch == 1 else 0.75,
        }
        out.write_text("noise\nextraction run complete: " + json.dumps(extract) + "\n")
        return 0


def _logs(tmp_path: Path, fetched: list[int]) -> Path:
    run_dir = tmp_path / "var" / "pipeline-host"
    run_dir.mkdir(parents=True)
    (run_dir / "MASTER").write_text("host=pi\ncommit=d2cadea\n")
    (tmp_path / "DEPLOYED_COMMIT").write_text("d2cadea\n")
    clock = iter(_START + timedelta(minutes=i) for i in range(1000))
    host = Host(run=_Pipeline(fetched).run, soc=lambda: 71.5, now=lambda: next(clock))
    config = Config(host="pi", phase="full", data_dir=tmp_path, code_dir=tmp_path)
    assert Loop(config, host).run() == 0
    return run_dir / "logs"


def test_the_report_reads_the_loops_own_logs(tmp_path: Path) -> None:
    logs = _logs(tmp_path, [50, 20])
    lines = run_lines((logs / "progress.log").read_text(), RUN)
    batches = read_batches(lines, logs)

    assert [b.number for b in batches] == ["001", "002"]
    report = aggregate(batches)
    pages = report["pages"]
    assert (pages["urls_fetched"], pages["changed"], pages["unchanged"]) == (70, 20, 80)
    assert (pages["extracted"], pages["reused_outputs"], pages["model_pages"]) == (20, 8, 12)
    assert pages["urls_not_due_after_last_batch"] == 1600
    assert report["outcomes"]["capture"] == {"http_404": 4, "succeeded": 96}
    assert report["outcomes"]["extraction_failed"] == {"chunk_failed": 1}
    assert report["outcomes"]["withdrawn_records"] == {"not_menu": 2}
    assert report["model"] == {
        "model_pages": 12,
        "extract_hours": 2.0,
        "model_pages_per_hour": 6.0,
        "pages_per_hour": 10.0,
    }
    thermal = report["thermal"]
    assert (thermal["soc_peak_c"], thermal["cpu_freq_cap_min"], thermal["throttled"]) == (
        86.5,
        0.75,
        True,
    )
    assert thermal["batches"][0]["soc_end_c"] == 71.5


def test_a_run_is_its_own_lines_only(tmp_path: Path) -> None:
    progress = "\n".join(
        [
            "2026-11-10T18:00:00Z loop start: host pi, phase full, db helios_work, master {}, "
            "batches already logged 0, run 20261110T180000Z",
            "2026-11-10T19:00:00Z batch 001 full fetch_exit=0",
            f"2026-12-10T18:00:02Z loop start: host pi, phase full, db helios_work, master "
            f"{{'host': 'pi', 'commit': 'd2cadea'}}, batches already logged 1, run {RUN}",
            "2026-12-10T19:00:00Z batch 002 full fetch_exit=0 SoC=80.1C",
            "2026-12-10T20:00:00Z loop end",
            "2026-12-11T18:00:00Z loop start: host pi, phase full, db helios_work, master {}, "
            "batches already logged 2, run 20261211T180000Z",
            "2026-12-11T19:00:00Z batch 003 full fetch_exit=0",
        ]
    )
    lines = run_lines(progress, RUN)
    assert [b.number for b in read_batches(lines, tmp_path)] == ["002"]
    with pytest.raises(ValueError, match="no 'loop start'"):
        run_lines(progress, "20261209T000000Z")


def test_report_files_carry_the_gate_and_the_spot_check(tmp_path: Path) -> None:
    logs = _logs(tmp_path, [12])
    out_dir = tmp_path / "out"
    (out_dir / "spot-check").mkdir(parents=True)
    gate = {
        "passed": False,
        "stop_reasons": ["1 lost venues unclassified: [42]"],
        "rows_change": -0.0123,
        "venues_change": -0.004,
        "median_shift": 0.01,
        "gained": 3,
        "lost_by_kind": {"unclassified": 1},
        "master": {"current_menu_rows": 98200, "venues_with_menu": 1228},
    }
    (out_dir / "gate.json").write_text(json.dumps(gate))
    manifest = {"seed": default_seed(RUN), "candidates": 37, "pages": [{}] * 10}
    (out_dir / "spot-check" / "manifest.json").write_text(json.dumps(manifest))
    lines = run_lines((logs / "progress.log").read_text(), RUN)
    now = _START + timedelta(hours=5)
    fresh = freshness_summary({1: now - timedelta(days=3), 2: None}, now)

    report = build_report(
        run_id=RUN,
        lines=lines,
        batches=read_batches(lines, logs),
        freshness=fresh,
        out_dir=out_dir,
        now=now,
        end_reason="done",
        failed_step=None,
    )
    text = write_report(report, out_dir)

    run = report["run"]
    assert (run["host"], run["phase"], run["db"], run["commit"]) == (
        "pi",
        "full",
        "helios_work",
        "d2cadea",
    )
    assert (run["started_at"], run["end_reason"], run["batches"]) == (
        "2026-12-10T18:00:02Z",
        "done",
        ["001"],
    )
    assert report["gate"]["passed"] is False and report["gate"]["venues_with_menu"] == 1228
    assert report["spot_check"]["seed"] == 20261210180002
    assert report["spot_check"]["drawn"] == 10
    assert json.loads((out_dir / "run-report.json").read_text())["run"]["id"] == RUN
    assert (out_dir / "run-report.md").read_text() == text == markdown(report)
    assert "STOPPED: 1 lost venues unclassified" in text and "No swap was made" in text
    assert "1 of 2 covered venues observed within 45 days (50.0%), misses" in text
    assert "10 of 37 newly extracted pages drawn (seed 20261210180002)" in text


def test_freshness_buckets_and_the_target() -> None:
    now = datetime(2026, 12, 20, tzinfo=UTC)
    observed = {
        1: now - timedelta(days=1),
        2: now - timedelta(days=20),
        3: now - timedelta(days=21),
        4: now - timedelta(days=45),
        5: now - timedelta(days=46),
    }

    fresh = freshness_summary(observed, now)

    assert fresh["by_age"] == {"le_20d": 2, "d21_45": 2, "gt_45d": 1, "never": 0}
    assert (fresh["covered_venues"], fresh["observed_within_target"], fresh["share"]) == (
        5,
        4,
        0.8,
    )
    assert fresh["passed"] is True and TARGET_SHARE == 0.8
    assert freshness_summary({}, now)["passed"] is None


def test_the_harness_scores_a_packets_stored_blocks(tmp_path: Path) -> None:
    pages = tmp_path / "pages"
    pages.mkdir()
    (pages / "1.html").write_text("<p>Queso</p><p>$6.00</p>")
    assert [b.text for b in blocks_of(tmp_path, "1")] == ["Queso", "$6.00"]

    stored = [asdict(b) for b in segment("<p>Taco</p><p>$3.50</p><p>Agua</p>")]
    (pages / "1.blocks.json").write_text(json.dumps(stored))
    assert [b.text for b in blocks_of(tmp_path, "1")] == ["Taco", "$3.50", "Agua"]


def _candidate(page_id: int) -> Candidate:
    return Candidate(
        page_id=page_id,
        version_id=page_id + 1000,
        subject_id=7,
        method_version="qwen@abc;prompt-v2.4;chunk-v2.3;seg-v1;repairs-v9;validator-v13;r;c",
        record_key=f"k{page_id}",
        menu_url=None,
        text_hash=None,
        bundle_path=None,
        venue=None,
    )


def test_the_draw_is_seeded_sorted_and_capped() -> None:
    pool = [_candidate(i) for i in range(1, 38)]

    first = draw(pool, default_seed(RUN))
    again = draw(list(reversed(pool)), default_seed(RUN))

    assert len(first) == 10 and [c.page_id for c in first] == sorted(c.page_id for c in first)
    assert first == again == draw(pool, 20261210180002), "a seed names the same pages"
    assert draw(pool, 7) != first
    assert draw(pool[:4], 1) == pool[:4], "all of them when fewer"
    assert first[0].extractor == "qwen@abc;prompt-v2.4;chunk-v2.3;seg-v1"
