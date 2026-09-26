"""Stress-test report: the PLAN.md decision rule applied to the finished runs.

    MENU_SPIKE_DATA=... uv run python -m spikes.menu_model.stress.report TAG [TAG ...]

Expects ``extract/TAG/`` result files plus ``stress.log``, ``stress-monitor.csv`` and
``stress_gate.json`` in MENU_SPIKE_DATA (copied back from the Pi).
"""

from __future__ import annotations

import contextlib
import csv
import io
import json
import re
import sys
from typing import Any

from spikes.menu_model.extract import DATA, cmd_score

PASSIVE_TRIP_C = 75
PASSIVE_TRIP2_C = 85
BIG_MAX_MHZ = 2256


def _quiet_score(tag: str, split: str) -> dict[str, Any]:
    with contextlib.redirect_stdout(io.StringIO()):
        return cmd_score(tag, split, repair=True)


def _windows() -> dict[str, tuple[int, int, float]]:
    """tag -> (start ts, end ts, peak RSS GB) from stress.log."""
    log = DATA / "stress.log"
    if not log.exists():
        return {}
    text = log.read_text(encoding="utf-8")
    out = {}
    for tag, start in re.findall(r"^(\S+) start (\d+)", text, re.M):
        m = re.search(rf"^{re.escape(tag)} end (\d+) VmHWM:\s+(\d+) kB", text, re.M)
        if m:
            out[tag] = (int(start), int(m.group(1)), int(m.group(2)) / 1024 / 1024)
    return out


def _thermals(start: int, end: int) -> dict[str, float]:
    mon = DATA / "stress-monitor.csv"
    if not mon.exists():
        return {}
    rows = [r for r in csv.DictReader(mon.open()) if start <= int(r["ts"]) <= end]
    if not rows:
        return {}
    soc = [int(r["soc-thermal_c"]) for r in rows]
    big = [max(int(r["bigcore0-thermal_c"]), int(r["bigcore1-thermal_c"])) for r in rows]
    mhz = [min(int(r["big0_mhz"]), int(r["big1_mhz"])) for r in rows]
    n = len(rows)
    return {
        "samples": n,
        "soc_max_c": max(soc),
        "bigcore_max_c": max(big),
        "share_soc_over_75c": sum(t >= PASSIVE_TRIP_C for t in soc) / n,
        "share_soc_over_85c": sum(t >= PASSIVE_TRIP2_C for t in soc) / n,
        "share_big_clock_below_max": sum(f < BIG_MAX_MHZ for f in mhz) / n,
        "big_clock_min_mhz": min(mhz),
        "mem_avail_min_mb": min(int(r["mem_avail_mb"]) for r in rows),
    }


def report(tag: str, windows: dict[str, tuple[int, int, float]], gate: set[str]) -> dict[str, Any]:
    full = _quiet_score(tag, "all")
    ho2 = _quiet_score(tag, "ho2")
    per_page = full["per_page"]  # (pid, n_gold, found_raw, found_kept, wall)
    gold_items = sum(p[1] for p in per_page)
    e2e = sum(p[2] for p in per_page if p[0] in gate) / gold_items if gold_items else float("nan")
    run = json.loads((DATA / "extract" / tag / "run.json").read_text(encoding="utf-8"))
    start, end, rss = windows.get(tag, (0, 0, float("nan")))
    fmt = full["by_format"]
    min_fmt = min(
        (v["item_recall_raw"] for v in fmt.values() if v["pages"] >= 2), default=float("nan")
    )
    c = full["counts"]
    n_chunks = sum(
        len(
            json.loads((DATA / "extract" / tag / f"{p[0]}.json").read_text(encoding="utf-8"))[
                "chunks"
            ]
        )
        for p in per_page
    )
    q_pass = (
        full["price_accuracy_accepted"] >= 0.98  # noqa: PLR2004 - PLAN.md Gate Q
        and full["item_recall_raw"] >= 0.85  # noqa: PLR2004
        and min_fmt >= 0.70  # noqa: PLR2004
        and c.get("error_chunks", 0) == 0
        and c.get("truncated_chunks", 0) <= 0.02 * n_chunks  # noqa: PLR2004
    )
    return {
        "tag": tag,
        "gate_q_pass": q_pass,
        "gate_o_pass": rss <= 8.0,  # noqa: PLR2004 - PLAN.md Gate O
        "item_recall": full["item_recall_raw"],
        "price_recall_accepted": full["price_recall_accepted"],
        "price_accuracy_accepted": full["price_accuracy_accepted"],
        "validator_false_reject": full["validator_false_reject"],
        "validator_catch": full["validator_catch"],
        "ho2_item_recall": ho2["item_recall_raw"],
        "ho2_price_recall_accepted": ho2["price_recall_accepted"],
        "ho2_price_accuracy_accepted": ho2["price_accuracy_accepted"],
        "min_format_item_recall": min_fmt,
        "by_format": fmt,
        "end_to_end_item_recall": e2e,
        "pages": run["pages"],
        "total_wall_h": run["total_wall_s"] / 3600,
        "pages_per_hour": run["pages"] / (run["total_wall_s"] / 3600),
        "median_page_s": full["median_page_s"],
        "max_page_s": full["max_page_s"],
        "peak_rss_gb": rss,
        "retried_chunks": c.get("retried_chunks", 0),
        "error_chunks": c.get("error_chunks", 0),
        "truncated_chunks": c.get("truncated_chunks", 0),
        "thermals": _thermals(start, end),
    }


def main() -> None:
    gate = set(json.loads((DATA / "stress_gate.json").read_text(encoding="utf-8")))
    windows = _windows()
    results = [report(tag, windows, gate) for tag in sys.argv[1:]]
    for r in results:
        print(json.dumps(r, indent=1, default=str))
    passing = [r for r in results if r["gate_q_pass"] and r["gate_o_pass"]]
    if not passing:
        print("WINNER: none passes both gates")
        return
    best = max(r["price_recall_accepted"] for r in passing)
    tied = [r for r in passing if best - r["price_recall_accepted"] <= 0.02]  # noqa: PLR2004
    winner = max(tied, key=lambda r: (r["pages_per_hour"], -r["peak_rss_gb"]))
    print(
        f"WINNER: {winner['tag']} (price recall on accepted rows {winner['price_recall_accepted']:.3f})"
    )
    (DATA / "stress_report.json").write_text(
        json.dumps(results, indent=1, default=str), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
