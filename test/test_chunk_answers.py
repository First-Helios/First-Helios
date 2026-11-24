"""Chunk-answer reuse (ADR-0013 Amendment 37 stage 1, session P8-25): keys, the
per-chunk records and their backfill. No database, no model."""

from __future__ import annotations

import gzip
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Barrier
from typing import TYPE_CHECKING

from apps.menu_pipeline.backfill_chunks import backfill
from apps.menu_pipeline.bundle import Bundle, BundleStore
from apps.menu_pipeline.chunk_answers import chunk_key
from apps.menu_pipeline.extraction import OutputStore
from packages.helios_parsing.chunking import chunks
from packages.helios_parsing.segment import SEGMENTER_VERSION, segment, text_hash

if TYPE_CHECKING:
    from pathlib import Path

_CHUNK = "b0004 | Tacos\nb0005 | Carne Asada Taco | $3.50\nb0007 | Queso | $6"
_RAW = (
    '{"sections":[{"section":"Tacos","items":[{"b":"b0005","n":"Carne Asada Taco","p":"3.50"}]}]}'
)


def test_only_the_exact_chunk_text_shares_a_key() -> None:
    assert chunk_key(_CHUNK) == chunk_key(str(_CHUNK))
    assert chunk_key(_CHUNK) != chunk_key(_CHUNK.replace("$6", "$7"))
    # other block ids are another input: the model's answers depend on them (P8-25 gate)
    assert chunk_key(_CHUNK) != chunk_key(_CHUNK.replace("b0007", "b0008"))


def test_chunk_records_round_trip(tmp_path: Path) -> None:
    store = OutputStore(tmp_path)
    assert store.read_chunk("x", _CHUNK) is None
    answer = {"raw": _RAW, "finish": "stop", "wall_s": 9.5}
    assert store.write_chunk("x", _CHUNK, answer, page_text_hash="sha256:ab")
    assert not store.write_chunk("x", _CHUNK, {"raw": "{}"}, page_text_hash="sha256:cd")  # kept
    assert store.read_chunk("x", _CHUNK) == _RAW
    assert store.read_chunk("x", _CHUNK.replace("b0007", "b0008")) is None
    assert store.read_chunk("y", _CHUNK) is None  # another extractor version: not reused
    (path,) = tmp_path.glob("var/replay/menu-extract/*/chunks/*.json.gz")
    assert path.stat().st_mode & 0o777 == 0o644  # readable for rsync (ADR-0030 Q6)
    record = json.loads(gzip.decompress(path.read_bytes()))
    assert (record["key"], record["text_hash"], record["chunk"]) == (
        chunk_key(_CHUNK),
        "sha256:ab",
        answer,
    )
    path.write_bytes(gzip.compress(b'{"format": "other"}'))
    assert store.read_chunk("x", _CHUNK) is None
    assert list(path.parent.glob("*.corrupt"))


def test_backfill_writes_the_model_answered_chunks_of_saved_page_records(tmp_path: Path) -> None:
    filler = "".join(f"<p>{'Slow-cooked brisket and sides ' * 6}{n}</p>" for n in range(12))
    blocks = segment(f"<html><body><h1>MENU</h1><p>Queso</p><p>$6.00</p>{filler}</body></html>")
    texts = chunks(blocks)
    assert len(texts) >= 2
    BundleStore(tmp_path).write(
        Bundle("https://x.example/menu", "text/html", b"", None, SEGMENTER_VERSION, tuple(blocks)),
        fetched_at=datetime(2026, 11, 20, tzinfo=UTC),
    )
    store = OutputStore(tmp_path)
    page_hash = text_hash(blocks)
    answers: list[dict[str, object]] = [{"raw": f'{{"n":{i}}}'} for i in range(len(texts))]
    answers[-1] = {"raw": "{}", "reused": chunk_key(texts[-1])}  # no model answer to save
    store.write("x", page_hash, answers)
    store.write("x", "sha256:" + "0" * 64, [{"raw": "{}"}])  # its bundle is gone

    counts = backfill(tmp_path, "x")

    assert counts == {
        "page_records": 2,
        "bundles": 1,
        "pages": 1,
        "chunk_records_written": len(texts) - 1,
        "chunks_reused": 1,
        "page_records_without_bundle": 1,
    }
    assert [store.read_chunk("x", t) for t in texts[:-1]] == [a["raw"] for a in answers[:-1]]
    again = backfill(tmp_path, "x")
    assert again["chunks_already_saved"] == len(texts) - 1
    assert "chunk_records_written" not in again


def test_concurrent_recovery_publishes_one_complete_answer(tmp_path: Path) -> None:
    store = OutputStore(tmp_path)
    workers = 6
    start = Barrier(workers)

    def write(answer: str) -> bool:
        start.wait(timeout=10)
        return store.write_chunk("x", _CHUNK, {"raw": answer}, page_text_hash="sha256:ab")

    answers = [str(i) for i in range(workers)]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        written = list(pool.map(write, answers))
    assert sum(written) == 1
    assert store.read_chunk("x", _CHUNK) == answers[written.index(True)]


def test_page_record_requires_all_expected_chunks(tmp_path: Path) -> None:
    store = OutputStore(tmp_path)
    store.write("x", "sha256:ab", [{"raw": "first"}])
    assert store.read("x", "sha256:ab", expected_chunks=2) is None
    assert len(list(store.folder("x").glob("*.corrupt"))) == 1
