"""The render measurement's memory accounting (ADR-0013 §4), on a fake ``/proc``."""

from __future__ import annotations

from typing import TYPE_CHECKING

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
