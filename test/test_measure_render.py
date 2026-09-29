"""The render measurement's memory accounting (ADR-0013 §4), on a fake ``/proc``."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from apps.menu_pipeline.evaluate_page_classifier import rendered_pages, scores
from apps.menu_pipeline.measure_render import PeakSampler, tree_pss_kb

if TYPE_CHECKING:
    from pathlib import Path


def _proc(root: Path, pid: int, ppid: int, pss_kb: int | None) -> None:
    entry = root / str(pid)
    entry.mkdir()
    (entry / "status").write_text(f"Name:\tx\nPPid:\t{ppid}\n", encoding="utf-8")
    if pss_kb is not None:  # no smaps_rollup: a kernel thread, or no permission
        rollup = f"00400000-7fff [rollup]\nRss:\t{pss_kb * 2} kB\nPss:\t{pss_kb} kB\n"
        (entry / "smaps_rollup").write_text(rollup, encoding="utf-8")


def test_tree_pss_sums_a_process_and_its_descendants(tmp_path: Path) -> None:
    _proc(tmp_path, 10, 1, 100)  # python
    _proc(tmp_path, 11, 10, 50)  # playwright driver
    _proc(tmp_path, 12, 11, 400)  # chromium
    _proc(tmp_path, 13, 12, 300)  # renderer process
    _proc(tmp_path, 14, 12, None)  # a kernel-thread-like entry without smaps_rollup
    _proc(tmp_path, 20, 1, 9_999)  # unrelated
    (tmp_path / "self").mkdir()  # non-numeric entries are ignored
    assert tree_pss_kb(10, tmp_path) == 850
    assert tree_pss_kb(12, tmp_path) == 700


def test_peak_sampler_keeps_the_maximum_since_reset() -> None:
    samples = iter([5, 7, 3, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2])

    def sample() -> int:
        return next(samples, 2)

    sampler = PeakSampler(sample, interval_s=0.001)
    sampler.reset()
    assert sampler.peak_kb == 5
    with sampler:
        pass
    assert sampler.peak_kb >= 5


def test_evaluation_scores_count_precision_and_recall() -> None:
    outcomes = [(True, True), (True, False), (False, True), (False, False), (True, True)]
    assert scores(outcomes) == {
        "pages": 5,
        "menus": 3,
        "tp": 2,
        "fp": 1,
        "fn": 1,
        "precision": 0.667,
        "recall": 0.667,
    }
    assert scores([])["precision"] is None


def test_rendered_pages_keep_only_labelled_renders(tmp_path: Path) -> None:
    (tmp_path / "rendered").mkdir()
    (tmp_path / "rendered" / "a.html").write_text("<h1>Menu</h1>", encoding="utf-8")
    (tmp_path / "rendered" / "b.html").write_text("<p>x</p>", encoding="utf-8")
    rows = [
        {"url": "u1", "outcome": "rendered", "html": "a.html", "set": "heldout"},
        {"url": "u2", "outcome": "rendered", "html": "b.html", "set": "probe"},
        {"url": "u3", "outcome": "skipped", "reason": "robots_disallowed"},
    ]
    (tmp_path / "measure.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8"
    )
    (tmp_path / "labels.json").write_text(
        json.dumps({"a.html": "menu", "b.html": "empty"}), encoding="utf-8"
    )
    (row,) = rendered_pages(tmp_path)
    assert (row["url"], row["label"], row["body"]) == ("u1", "menu", "<h1>Menu</h1>")
