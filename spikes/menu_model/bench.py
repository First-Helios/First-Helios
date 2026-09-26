"""Pi timing for stages [1]-[3]: segment, page classifier, block classifier.

    MENU_SPIKE_DATA=... python -m spikes.menu_model.bench [PAGE_ID ...]

Loads ``models/classifiers.pkl`` (written by ``classify train``) and, per page,
times: segmentation, page features + page embedding + LR, block embeddings +
block features + LR. Reports median / p90 / max per stage and the process's
peak RSS (``ru_maxrss``). The first page is a warm-up (model load, ONNX session
creation) and is reported separately.
"""

from __future__ import annotations

import json
import pickle
import resource
import statistics
import sys
import time

import numpy as np  # type: ignore[import-not-found]  # spike venv only

from spikes.menu_model.classify import (
    BLOCK_TEXT_CHARS,
    DATA,
    Embedder,
    _html,
    _labels,
    _pages,
    block_hand,
    page_hand,
    page_text,
)
from spikes.menu_model.segment import segment


def main() -> None:
    t_load = time.perf_counter()
    models = pickle.loads((DATA / "models" / "classifiers.pkl").read_bytes())  # noqa: S301 - own file
    page_embed, block_embed = Embedder(models["page"]["model"]), Embedder(models["block"]["model"])
    page_embed._cache.clear()  # noqa: SLF001 - time real inference, never the local cache
    block_embed._cache.clear()  # noqa: SLF001
    page_embed._path = block_embed._path = DATA / "emb" / "bench-discard.pkl"  # noqa: SLF001
    load_s = time.perf_counter() - t_load
    labels, pages = _labels(), _pages()
    ids = sys.argv[1:] or sorted(
        pid for pid, lab in labels.items() if lab["page_label"] == "menu" and lab.get("blocks")
    )
    times: dict[str, list[float]] = {"segment": [], "page_clf": [], "block_clf": [], "total": []}
    nblocks = []
    for n, pid in enumerate(ids):
        html = _html(pid)
        url = str(pages[pid]["final_url"] or pages[pid]["url"])
        t0 = time.perf_counter()
        blocks = segment(html)
        t1 = time.perf_counter()
        x = np.hstack([page_embed([page_text(html, url, blocks)])[0], page_hand(html, url, blocks)])
        models["page"]["clf"].predict_proba(x[None, :])
        t2 = time.perf_counter()
        bx = np.hstack(
            [block_embed([b.text[:BLOCK_TEXT_CHARS] for b in blocks]), block_hand(blocks)]
        )
        models["block"]["clf"].predict(bx)
        t3 = time.perf_counter()
        if n == 0:
            warm = t3 - t0
            continue
        nblocks.append(len(blocks))
        for k, v in (
            ("segment", t1 - t0),
            ("page_clf", t2 - t1),
            ("block_clf", t3 - t2),
            ("total", t3 - t0),
        ):
            times[k].append(v)
    rss_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
    out: dict[str, object] = {
        "pages": len(ids) - 1,
        "model_load_s": round(load_s, 2),
        "first_page_s": round(warm, 2),
        "blocks_median": statistics.median(nblocks),
        "blocks_max": max(nblocks),
        "peak_rss_mb": round(rss_mb, 1),
    }
    for k, ts in times.items():
        ts.sort()
        out[k] = {
            "median": round(statistics.median(ts), 3),
            "p90": round(ts[int(0.9 * (len(ts) - 1))], 3),
            "max": round(ts[-1], 3),
        }
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
