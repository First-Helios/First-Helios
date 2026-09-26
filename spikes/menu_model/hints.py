"""Out-of-fold block-role hints for the extractor (tracker finding 7, open question 10).

    D=var/spikes/menu-model   # MENU_SPIKE_DATA
    $D/.venv-ml/bin/python -m spikes.menu_model.hints [PAGE ...]

Writes ``$D/hints/<page_id>.json`` = {block_id: role} with the stage [3] block classifier's
prediction (bge-small-en-v1.5 embedding + layout features, logistic regression; the step D
config). **Every prediction is out-of-fold by venue:** for a block-labeled page the model is
trained on the labeled pages of all *other* venues; for an unlabeled page (default: every page
in ``stress_pages.json`` without block labels) on all labeled pages of other venues. The pickled
step D model saw every labeled page and is not used.

Also prints the hint accuracy (item/price F1) over the labeled pages, which is the step D CV
number recomputed leave-one-venue-out.
"""

from __future__ import annotations

import json
import sys
from typing import Any

import numpy as np  # type: ignore[import-not-found]  # spike venv only
from sklearn.metrics import classification_report  # type: ignore[import-not-found]

from spikes.menu_model.classify import (
    BLOCK_CLASSES,
    BLOCK_MODEL,
    BLOCK_TEXT_CHARS,
    DATA,
    Embedder,
    _html,
    _labels,
    _lr,
    _pages,
    block_hand,
)
from spikes.menu_model.segment import segment


def _features(embed: Embedder, page_id: str) -> tuple[list[str], Any]:
    blocks = segment(_html(page_id))
    x = np.hstack([embed([b.text[:BLOCK_TEXT_CHARS] for b in blocks]), block_hand(blocks)])
    return [b.id for b in blocks], x


def main() -> None:
    labels, pages = _labels(), _pages()
    labeled = sorted(
        pid for pid, lab in labels.items() if lab["page_label"] == "menu" and lab.get("blocks")
    )
    targets = sys.argv[1:] or sorted(
        set(json.loads((DATA / "stress_pages.json").read_text(encoding="utf-8"))) | set(labeled)
    )
    embed = Embedder(BLOCK_MODEL)
    feats: dict[str, tuple[list[str], Any, Any]] = {}
    for pid in labeled:
        ids, x = _features(embed, pid)
        lab = labels[pid]["blocks"]
        assert isinstance(lab, dict)
        feats[pid] = (ids, x, np.array([BLOCK_CLASSES.index(lab.get(b, "noise")) for b in ids]))
    venue = {pid: str(pages[pid]["gers_id"]) for pid in pages}
    out_dir = DATA / "hints"
    out_dir.mkdir(parents=True, exist_ok=True)
    ys, preds = [], []
    models: dict[str, Any] = {}  # one fit per held-out venue
    for pid in targets:
        v = venue[pid]
        if v not in models:
            train = [p for p in labeled if venue[p] != v]
            models[v] = _lr().fit(
                np.vstack([feats[p][1] for p in train]),
                np.concatenate([feats[p][2] for p in train]),
            )
        ids, x = (feats[pid][0], feats[pid][1]) if pid in feats else _features(embed, pid)
        pred = models[v].predict(x)
        (out_dir / f"{pid}.json").write_text(
            json.dumps({b: BLOCK_CLASSES[int(k)] for b, k in zip(ids, pred, strict=True)}),
            encoding="utf-8",
        )
        if pid in feats:
            ys.append(feats[pid][2])
            preds.append(pred)
    print(f"wrote {len(targets)} hint files to {out_dir} ({len(models)} venue folds)")
    if ys:
        rep = classification_report(
            np.concatenate(ys),
            np.concatenate(preds),
            labels=list(range(len(BLOCK_CLASSES))),
            target_names=BLOCK_CLASSES,
            output_dict=True,
            zero_division=0,
        )
        print(
            "leave-one-venue-out F1: "
            + " ".join(f"{c}={rep[c]['f1-score']:.3f}" for c in BLOCK_CLASSES)
        )


if __name__ == "__main__":
    main()
