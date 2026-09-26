"""Step D: stage [1] page classifier and stage [3] block classifier.

Embedding (ONNX Runtime via ``fastembed``) + logistic regression, cross-validated
by venue: ``GroupKFold`` on the venue's GERS id, so no venue has pages in both
train and test. Runs in the spike's own venv, never the Helios one:

    D=var/spikes/menu-model   # MENU_SPIKE_DATA
    $D/.venv-ml/bin/python -m spikes.menu_model.classify pages  [--model M] [--json OUT]
    $D/.venv-ml/bin/python -m spikes.menu_model.classify blocks [--model M] [--json OUT]

Feature sets are compared, each with the same LR: ``hand`` (layout/price
features only, no model), ``emb`` (embedding only), ``emb+hand``.

Page classifier: positive = ``menu``, negative = ``not_menu``. ``js_only`` and
``empty`` pages are excluded from the metrics and only reported as the count
each fold's model would have called ``menu``. The operating threshold for the
precision >= 0.95 bar is chosen per outer fold from inner-CV (also grouped by
venue) out-of-fold probabilities on that fold's training venues only.

Block classifier: every block of each block-labeled menu page (outside the
labeled menu regions = ``noise``); item/price F1 is the tracker's bar.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import pickle
import re
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import numpy as np  # type: ignore[import-not-found]  # spike venv only
from sklearn.linear_model import LogisticRegression  # type: ignore[import-not-found]
from sklearn.metrics import (  # type: ignore[import-not-found]
    classification_report,
    confusion_matrix,
)
from sklearn.model_selection import GroupKFold  # type: ignore[import-not-found]
from sklearn.pipeline import make_pipeline  # type: ignore[import-not-found]
from sklearn.preprocessing import StandardScaler  # type: ignore[import-not-found]

from apps.discovery.menu_url import page_menu_signal
from spikes.menu_model.labeltool import LABELS
from spikes.menu_model.segment import Block, segment
from spikes.menu_model.validator import price_tokens

DATA = Path(os.environ.get("MENU_SPIKE_DATA", "var/spikes/menu-model"))
DEFAULT_MODEL = "BAAI/bge-small-en-v1.5"
PAGE_TEXT_CHARS = 2000
BLOCK_TEXT_CHARS = 300
FOLDS = 5
TARGET_PRECISION = 0.95
BLOCK_CLASSES = ("section", "item", "description", "price", "modifier", "noise")
_MOD = re.compile(r"^(add|\+|sub|substitute|extra|choice of|choose|make it)\b", re.I)
_TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)


# ---------------------------------------------------------------- embeddings


class Embedder:
    """fastembed wrapper with an on-disk cache keyed by (model, text hash)."""

    def __init__(self, model: str) -> None:
        from fastembed import TextEmbedding  # type: ignore[import-not-found]  # noqa: PLC0415

        self.model_name = model
        self._model = TextEmbedding(model, cache_dir=str(DATA / "models"))
        self._path = DATA / "emb" / f"{model.replace('/', '__')}.pkl"
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._cache: dict[str, np.ndarray] = (
            pickle.loads(self._path.read_bytes()) if self._path.exists() else {}  # noqa: S301 - own cache file
        )

    def __call__(self, texts: list[str]) -> np.ndarray:
        keys = [hashlib.sha1(t.encode()).hexdigest() for t in texts]  # noqa: S324 - cache key
        todo = sorted(
            {k: t for k, t in zip(keys, texts, strict=True) if k not in self._cache}.items()
        )
        if todo:
            vecs = list(self._model.embed([t for _, t in todo], batch_size=64))
            self._cache.update({k: v for (k, _), v in zip(todo, vecs, strict=True)})
            self._path.write_bytes(pickle.dumps(self._cache))
        return np.stack([self._cache[k] for k in keys])


# ---------------------------------------------------------------- data


def _labels() -> dict[str, dict[str, object]]:
    return {
        p.stem: json.loads(p.read_text(encoding="utf-8")) for p in (LABELS / "pages").glob("*.json")
    }


def _pages() -> dict[str, dict[str, object]]:
    rows = (json.loads(line) for line in (DATA / "pages.jsonl").open(encoding="utf-8"))
    return {str(p["page_id"]): p for p in rows}


def _html(page_id: str) -> str:
    return (DATA / "pages" / f"{page_id}.html").read_text(encoding="utf-8")


def page_text(html: str, url: str, blocks: list[Block]) -> str:
    """Title, URL path, headings first, then body text (chrome blocks dropped)."""
    m = _TITLE.search(html)
    title = re.sub(r"\s+", " ", m.group(1)).strip() if m else ""
    heads = " | ".join(b.text for b in blocks if b.heading and not b.in_chrome)[:400]
    body = " | ".join(b.text for b in blocks if not b.in_chrome)
    return f"{title}\n{urlsplit(url).path}\n{heads}\n{body}"[:PAGE_TEXT_CHARS]


def page_hand(html: str, url: str, blocks: list[Block]) -> list[float]:
    prices = price_tokens(blocks)
    body = [i for i, b in enumerate(blocks) if not b.in_chrome]
    priced = [i for i in body if prices[i]]
    money = sum(1 for i in body for t in prices[i] if t.kind == "money")
    n = max(len(body), 1)
    words = sum(len(blocks[i].text.split()) for i in body)
    return [
        math.log1p(len(body)),
        len(priced) / n,
        math.log1p(money),
        math.log1p(len(priced)),
        words / n,
        sum(1 for i in body if len(blocks[i].text) < 40) / n,  # noqa: PLR2004
        float(page_menu_signal(html, url)),  # S4's own predicate, as one feature
    ]


def block_hand(blocks: list[Block]) -> np.ndarray:
    prices = price_tokens(blocks)
    own = []
    for i, b in enumerate(blocks):
        text = b.text
        toks = prices[i]
        covered = sum(t.end - t.start for t in toks)
        letters = [c for c in text if c.isalpha()]
        own.append(
            [
                float(bool(toks)),
                float(bool(toks) and len(text) - covered <= 12),  # noqa: PLR2004 - price-only-ish
                float(len(toks)),
                math.log1p(len(text)),
                math.log1p(len(text.split())),
                sum(c.isupper() for c in letters) / max(len(letters), 1),
                sum(c.isdigit() for c in text) / max(len(text), 1),
                float(b.heading),
                float(b.in_chrome),
                float(b.tag in {"h1", "h2", "h3"}),
                float(b.tag in {"h4", "h5", "h6"}),
                float(b.tag == "p"),
                float(b.tag == "li"),
                float(b.tag in {"td", "th", "tr"}),
                float(bool(_MOD.match(text))),
                float(text.rstrip().endswith((".", "!"))),
                i / max(len(blocks) - 1, 1),
            ]
        )
    arr = np.array(own, dtype=np.float32)
    zero = np.zeros((1, arr.shape[1]), dtype=np.float32)
    prev1 = np.vstack([zero, arr[:-1]])
    next1 = np.vstack([arr[1:], zero])
    next2 = np.vstack([arr[2:], zero, zero])[: len(arr)]
    return np.hstack([arr, prev1, next1, next2])


# ---------------------------------------------------------------- CV helpers


def _lr() -> Any:
    return make_pipeline(StandardScaler(), LogisticRegression(max_iter=3000, C=0.5))


def _threshold_for_precision(y: np.ndarray, p: np.ndarray, target: float) -> float:
    """Lowest threshold whose precision on (y, p) reaches ``target`` (else the max prob)."""
    for thr in sorted(set(p.tolist())):
        pred = p >= thr
        if pred.sum() and (y[pred] == 1).mean() >= target:
            return float(thr)
    return float(p.max()) + 1e-9


def _prf(y: np.ndarray, pred: np.ndarray) -> dict[str, float]:
    tp = int(((pred == 1) & (y == 1)).sum())
    fp = int(((pred == 1) & (y == 0)).sum())
    fn = int(((pred == 0) & (y == 1)).sum())
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "precision": p,
        "recall": r,
        "f1": 2 * p * r / (p + r) if p + r else 0.0,
    }


# ---------------------------------------------------------------- stage [1]


def run_pages(model: str) -> dict[str, Any]:
    labels, pages = _labels(), _pages()
    ids = sorted(pid for pid, lab in labels.items() if lab["page_label"] in ("menu", "not_menu"))
    other = sorted(pid for pid, lab in labels.items() if lab["page_label"] in ("js_only", "empty"))
    feats: dict[str, tuple[str, list[float]]] = {}
    for pid in ids + other:
        html = _html(pid)
        url = str(pages[pid]["final_url"] or pages[pid]["url"])
        blocks = segment(html)
        feats[pid] = (page_text(html, url, blocks), page_hand(html, url, blocks))
    embed = Embedder(model)
    emb = embed([feats[pid][0] for pid in ids + other])
    hand = np.array([feats[pid][1] for pid in ids + other], dtype=np.float32)
    n = len(ids)
    y = np.array([1 if labels[pid]["page_label"] == "menu" else 0 for pid in ids])
    groups = np.array([str(pages[pid]["gers_id"]) for pid in ids])
    sets = {"hand": hand, "emb": emb, "emb+hand": np.hstack([emb, hand])}

    out: dict[str, Any] = {
        "model": model,
        "n_pages": n,
        "n_menu": int(y.sum()),
        "n_excluded": len(other),
    }
    for name, x_all in sets.items():
        x, x_other = x_all[:n], x_all[n:]
        prob = np.zeros(n)
        pred_thr = np.zeros(n, dtype=int)
        other_pos_05, other_pos_thr = 0, 0
        for tr, te in GroupKFold(n_splits=FOLDS).split(x, y, groups):
            clf = _lr().fit(x[tr], y[tr])
            prob[te] = clf.predict_proba(x[te])[:, 1]
            inner = np.zeros(len(tr))
            for itr, ite in GroupKFold(n_splits=FOLDS).split(x[tr], y[tr], groups[tr]):
                inner[ite] = _lr().fit(x[tr][itr], y[tr][itr]).predict_proba(x[tr][ite])[:, 1]
            thr = _threshold_for_precision(y[tr], inner, TARGET_PRECISION)
            pred_thr[te] = (prob[te] >= thr).astype(int)
            po = clf.predict_proba(x_other)[:, 1]
            other_pos_05 += int((po >= 0.5).sum())  # noqa: PLR2004
            other_pos_thr += int((po >= thr).sum())
        pred05 = (prob >= 0.5).astype(int)  # noqa: PLR2004
        out[name] = {
            "at_0.5": _prf(y, pred05),
            "at_nested_p95_threshold": _prf(y, pred_thr),
            "excluded_called_menu_at_0.5_summed_over_folds": other_pos_05,
            "excluded_called_menu_at_thr_summed_over_folds": other_pos_thr,
            "false_positives_at_thr": [ids[i] for i in np.where((pred_thr == 1) & (y == 0))[0]],
            "false_negatives_0.5": [ids[i] for i in np.where((pred05 == 0) & (y == 1))[0]],
            "false_negatives_nested_p95_threshold": [
                ids[i] for i in np.where((pred_thr == 0) & (y == 1))[0]
            ],
        }
    s4 = np.array([int(h[-1]) for _, h in (feats[pid] for pid in ids)])
    out["s4_predicate_same_pages"] = _prf(y, s4)
    # priced menus (>= 5 money tokens outside chrome): the pages price extraction needs
    priced = np.array([feats[pid][1][2] >= math.log1p(5) for pid in ids]) & (y == 1)
    out["n_priced_menu"] = int(priced.sum())
    for name in sets:
        r = out[name]
        assert isinstance(r, dict)
        for k in ("at_0.5", "at_nested_p95_threshold"):
            hit = {ids[i] for i in np.where(priced)[0]} - set(
                r["false_negatives_" + k.split("_", 1)[1]]
            )
            r[k]["priced_menu_recall"] = len(hit) / max(int(priced.sum()), 1)
    out["s4_predicate_same_pages"]["priced_menu_recall"] = float(s4[priced].mean())
    return out


# ---------------------------------------------------------------- stage [3]


def run_blocks(model: str, *, context_emb: bool) -> dict[str, Any]:
    labels, pages = _labels(), _pages()
    ids = sorted(
        pid for pid, lab in labels.items() if lab["page_label"] == "menu" and lab.get("blocks")
    )
    embed = Embedder(model)
    xs_hand, xs_emb, ys, gs, owners = [], [], [], [], []
    for pid in ids:
        blocks = segment(_html(pid))
        lab = labels[pid]["blocks"]
        assert isinstance(lab, dict)
        xs_hand.append(block_hand(blocks))
        e = embed([b.text[:BLOCK_TEXT_CHARS] for b in blocks])
        if context_emb:
            z = np.zeros((1, e.shape[1]), dtype=e.dtype)
            e = np.hstack([e, np.vstack([z, e[:-1]]), np.vstack([e[1:], z])])
        xs_emb.append(e)
        ys += [BLOCK_CLASSES.index(lab.get(b.id, "noise")) for b in blocks]
        gs += [str(pages[pid]["gers_id"])] * len(blocks)
        owners += [pid] * len(blocks)
    hand, emb = np.vstack(xs_hand), np.vstack(xs_emb)
    y, groups = np.array(ys), np.array(gs)
    out: dict[str, Any] = {
        "model": model,
        "context_emb": context_emb,
        "pages": len(ids),
        "venues": len(set(gs)),
        "blocks": len(y),
        "class_counts": {c: int((y == i).sum()) for i, c in enumerate(BLOCK_CLASSES)},
    }
    for name, x in {"hand": hand, "emb": emb, "emb+hand": np.hstack([emb, hand])}.items():
        pred = np.zeros(len(y), dtype=int)
        for tr, te in GroupKFold(n_splits=FOLDS).split(x, y, groups):
            pred[te] = _lr().fit(x[tr], y[tr]).predict(x[te])
        rep = classification_report(
            y,
            pred,
            labels=list(range(len(BLOCK_CLASSES))),
            target_names=BLOCK_CLASSES,
            output_dict=True,
            zero_division=0,
        )
        per_page: Counter[str] = Counter()
        for i, pid in enumerate(owners):
            per_page[pid] += int(pred[i] != y[i])
        out[name] = {
            "report": rep,
            "item_f1": rep["item"]["f1-score"],
            "price_f1": rep["price"]["f1-score"],
            "confusion": confusion_matrix(y, pred).tolist(),
            "worst_pages": per_page.most_common(5),
        }
    return out


# ---------------------------------------------------------------- final models (for the Pi bench)

PAGE_MODEL = "minishlab/potion-base-8M"  # the only stage [1] config that met P >= 0.95 in CV
BLOCK_MODEL = "BAAI/bge-small-en-v1.5"  # best stage [3] item F1 (emb+hand, no context)


def train() -> None:
    """Fit the chosen configs on all labeled data and pickle them for ``bench``."""
    labels, pages = _labels(), _pages()
    ids = sorted(pid for pid, lab in labels.items() if lab["page_label"] in ("menu", "not_menu"))
    xs, ys = [], []
    embed = Embedder(PAGE_MODEL)
    for pid in ids:
        html = _html(pid)
        url = str(pages[pid]["final_url"] or pages[pid]["url"])
        blocks = segment(html)
        xs.append(
            np.hstack([embed([page_text(html, url, blocks)])[0], page_hand(html, url, blocks)])
        )
        ys.append(1 if labels[pid]["page_label"] == "menu" else 0)
    x, y = np.vstack(xs), np.array(ys)
    groups = np.array([str(pages[pid]["gers_id"]) for pid in ids])
    oof = np.zeros(len(y))
    for tr, te in GroupKFold(n_splits=FOLDS).split(x, y, groups):
        oof[te] = _lr().fit(x[tr], y[tr]).predict_proba(x[te])[:, 1]
    page = {
        "model": PAGE_MODEL,
        "clf": _lr().fit(x, y),
        "threshold": _threshold_for_precision(y, oof, TARGET_PRECISION),
    }

    bids = sorted(
        pid for pid, lab in labels.items() if lab["page_label"] == "menu" and lab.get("blocks")
    )
    bembed = Embedder(BLOCK_MODEL)
    bx, by = [], []
    for pid in bids:
        blocks = segment(_html(pid))
        lab = labels[pid]["blocks"]
        assert isinstance(lab, dict)
        bx.append(
            np.hstack([bembed([b.text[:BLOCK_TEXT_CHARS] for b in blocks]), block_hand(blocks)])
        )
        by += [BLOCK_CLASSES.index(lab.get(b.id, "noise")) for b in blocks]
    block = {
        "model": BLOCK_MODEL,
        "clf": _lr().fit(np.vstack(bx), np.array(by)),
        "classes": BLOCK_CLASSES,
    }
    out = DATA / "models" / "classifiers.pkl"
    out.write_bytes(pickle.dumps({"page": page, "block": block}))
    print(f"wrote {out} page_threshold={page['threshold']:.3f}")


# ---------------------------------------------------------------- CLI


def main() -> None:
    args = sys.argv[1:]
    model = args[args.index("--model") + 1] if "--model" in args else DEFAULT_MODEL
    t0 = time.perf_counter()
    if args[0] == "train":
        train()
        return
    if args[0] == "pages":
        res = run_pages(model)
        print(
            f"stage [1] model={model} pages={res['n_pages']} menu={res['n_menu']} excluded={res['n_excluded']}"
        )
        s4 = res["s4_predicate_same_pages"]
        print(
            f"  S4 predicate           P={s4['precision']:.3f} R={s4['recall']:.3f} F1={s4['f1']:.3f} "
            f"priced_R={s4['priced_menu_recall']:.3f} (priced menus={res['n_priced_menu']})"
        )
        for name in ("hand", "emb", "emb+hand"):
            r = res[name]
            for k in ("at_0.5", "at_nested_p95_threshold"):
                m = r[k]
                print(
                    f"  {name:9} {k:24} P={m['precision']:.3f} R={m['recall']:.3f} F1={m['f1']:.3f} "
                    f"tp={m['tp']} fp={m['fp']} fn={m['fn']} priced_R={m['priced_menu_recall']:.3f}"
                )
            print(
                f"  {name:9} js_only/empty called menu (sum over folds): "
                f"@0.5={r['excluded_called_menu_at_0.5_summed_over_folds']} "
                f"@thr={r['excluded_called_menu_at_thr_summed_over_folds']}"
            )
    else:
        res = run_blocks(model, context_emb="--context" in args)
        print(
            f"stage [3] model={model} context_emb={res['context_emb']} pages={res['pages']} "
            f"venues={res['venues']} blocks={res['blocks']} {res['class_counts']}"
        )
        for name in ("hand", "emb", "emb+hand"):
            r = res[name]
            rep = r["report"]
            cls = " ".join(f"{c}={rep[c]['f1-score']:.3f}" for c in BLOCK_CLASSES)
            print(f"  {name:9} item_F1={r['item_f1']:.3f} price_F1={r['price_f1']:.3f} | {cls}")
    print(f"  wall {time.perf_counter() - t0:.1f}s")
    if "--json" in args:
        Path(args[args.index("--json") + 1]).write_text(
            json.dumps(res, indent=1, default=str), encoding="utf-8"
        )


if __name__ == "__main__":
    main()
