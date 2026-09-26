"""Step 3: adaptive second pass, composed from two extraction runs.

    # 1) first pass over all pages (tag A); 2) coverage per page, list the pages below THR:
    MENU_SPIKE_DATA=... MENU_SPIKE_STITCH=2 uv run python -m spikes.menu_model.stress.adaptive list A THR PAGE...
    # 3) second pass (stronger setup) over those pages only (tag B), then compose:
    MENU_SPIKE_DATA=... MENU_SPIKE_STITCH=2 uv run python -m spikes.menu_model.stress.adaptive compose A B THR OUT

``compose`` writes extraction tag OUT: for each page of A whose coverage (label-free, see
``coverage.py``) is below THR and that B also extracted, the result with MORE validator-accepted
priced rows (ties keep A); every other page is A's. OUT is then scored like any tag. The
extra Pi time is B's wall time on the re-extracted pages, recorded in ``OUT/adaptive.json``.
"""

from __future__ import annotations

import json
import sys

from spikes.menu_model.extract import DATA
from spikes.menu_model.stress.coverage import page_coverage


def _load(tag: str, pid: str) -> dict[str, object] | None:
    path = DATA / "extract" / tag / f"{pid}.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def below(tag: str, thr: float, pids: list[str]) -> list[tuple[str, float]]:
    out = []
    for pid in pids:
        res = _load(tag, pid)
        if res is not None:
            cov = page_coverage(res, pid)[0]
            if cov < thr:
                out.append((pid, cov))
    return out


def compose(first: str, second: str, thr: float, out_tag: str) -> None:
    out_dir = DATA / "extract" / out_tag
    out_dir.mkdir(parents=True, exist_ok=True)
    pids = sorted(p.stem for p in (DATA / "extract" / first).glob("*.json") if len(p.stem) == 12)
    log: dict[str, object] = {"first": first, "second": second, "threshold": thr, "pages": {}}
    extra = 0.0
    for pid in pids:
        a = _load(first, pid)
        assert a is not None
        choice, rec = "first", a
        cov_a, acc_a, printed, _ = page_coverage(a, pid)
        b = _load(second, pid) if cov_a < thr else None
        if b is not None:
            extra += float(b["wall_s"])  # type: ignore[arg-type]
            cov_b, acc_b, _, _ = page_coverage(b, pid)
            if acc_b > acc_a:
                choice, rec = "second", b
            log["pages"][pid] = {  # type: ignore[index]
                "coverage_first": round(cov_a, 3),
                "coverage_second": round(cov_b, 3),
                "printed": printed,
                "second_wall_s": b["wall_s"],
                "choice": choice,
            }
        (out_dir / f"{pid}.json").write_text(json.dumps(rec), encoding="utf-8")
    log["extra_wall_s"] = round(extra, 1)
    (out_dir / "adaptive.json").write_text(json.dumps(log, indent=1), encoding="utf-8")
    print(json.dumps(log, indent=1))


def main() -> None:
    cmd, args = sys.argv[1], sys.argv[2:]
    if cmd == "list":
        for pid, cov in below(args[0], float(args[1]), args[2:]):
            print(pid, f"{cov:.2f}")
    else:
        compose(args[0], args[1], float(args[2]), args[3])


if __name__ == "__main__":
    main()
