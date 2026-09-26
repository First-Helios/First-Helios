"""Held-out-3 labeling aid: turn a reviewed per-page spec into ``review.txt`` lines.

    MENU_SPIKE_DATA=... uv run python -m spikes.menu_model.labeldraft SPEC_FILE [--show]

The spec (one page per file, written while reading every block of the page) is::

    page <id> menu <format> | note
    region b0010 b0299
    section b0010 b0025 ...        # explicit roles, block ids or lo..hi ranges
    noise b0011 b0026 ...
    item ... / description ... / price ... / modifier ...
    name b0015=Mexican Gelatine    # passed through to review.txt
    prices b0130=12" Small:14.99,14" Medium:15.99
    additem b0027=Name|-:9.99

Every region block without an explicit role gets a default (a price-only line -> price, a
6+ word line -> description, anything else -> item); ``--show`` prints the labeled region
for the read-through. The output is a ``review.txt`` entry whose ``fix`` lines list every
block's final role explicitly (ranges compressed), so the record does not depend on these
defaults.
"""

from __future__ import annotations

import sys
from pathlib import Path

from spikes.menu_model.labeltool import PRICE_ONLY_RE, blocks_of

ROLES = ("section", "noise", "item", "description", "price", "modifier")


def _ids(tokens: list[str], order: list[str]) -> list[str]:
    out: list[str] = []
    for t in tokens:
        lo, _, hi = t.partition("..")
        out += [b for b in order if lo <= b <= (hi or lo)]
    return out


def main() -> None:
    spec = Path(sys.argv[1]).read_text(encoding="utf-8").splitlines()
    lines = [ln.rstrip() for ln in spec if ln.strip()]
    head = lines[0]
    pid = head.split()[1]
    blocks = blocks_of(pid)
    order = [b.id for b in blocks]
    regions = [ln.split()[1:] for ln in lines if ln.startswith("region ")]
    in_region = [
        b
        for b in blocks
        if any(lo <= b.id <= hi for r in regions for lo, hi in zip(r[::2], r[1::2], strict=True))
    ]
    explicit: dict[str, str] = {}
    for ln in lines:
        word, *rest = ln.split()
        if word in ROLES:
            for bid in _ids(rest, order):
                explicit[bid] = word
    labels: dict[str, str] = {}
    for b in in_region:
        if b.id in explicit:
            labels[b.id] = explicit[b.id]
        elif PRICE_ONLY_RE.match(b.text.strip()):
            labels[b.id] = "price"
        elif len(b.text.split()) >= 6:  # noqa: PLR2004
            labels[b.id] = "description"
        else:
            labels[b.id] = "item"
    if "--show" in sys.argv:
        for b in in_region:
            mark = "*" if b.id in explicit else " "
            print(f"{b.id} {labels[b.id][:5]:5}{mark} {b.text[:100]}")
    # compress consecutive in-region blocks with one role into ranges
    fixes: list[str] = []
    runs: list[tuple[str, list[str]]] = []
    for blk in in_region:
        if runs and runs[-1][0] == labels[blk.id]:
            runs[-1][1].append(blk.id)
        else:
            runs.append((labels[blk.id], [blk.id]))
    for role, ids in runs:
        fixes.append(f"{ids[0]}..{ids[-1]}={role}" if len(ids) > 1 else f"{ids[0]}={role}")
    out = [head] + [ln for ln in lines if ln.startswith("region ")]
    for i in range(0, len(fixes), 8):
        out.append("fix " + " ".join(fixes[i : i + 8]))
    out += [ln for ln in lines if ln.split()[0] in {"name", "prices", "additem"}]
    print("\n".join(out))


if __name__ == "__main__":
    main()
