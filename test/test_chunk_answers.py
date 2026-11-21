"""Chunk-answer reuse (ADR-0013 Amendment 37 stage 1, session P8-25): keys, id maps,
the per-chunk records and their backfill. No database, no model."""

from __future__ import annotations

import gzip
import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from apps.menu_pipeline.backfill_chunks import backfill
from apps.menu_pipeline.bundle import Bundle, BundleStore
from apps.menu_pipeline.chunk_answers import block_ids, chunk_key, remap, renumbered
from apps.menu_pipeline.extraction import OutputStore
from packages.helios_parsing.chunking import chunks
from packages.helios_parsing.segment import SEGMENTER_VERSION, segment, text_hash

if TYPE_CHECKING:
    from pathlib import Path

_OLD = "b0004 | Tacos\nb0005 | Carne Asada Taco | $3.50\nb0005 | (cont.)\nb0007 | Queso | $6"
_NEW = "b0009 | Tacos\nb0010 | Carne Asada Taco | $3.50\nb0010 | (cont.)\nb0012 | Queso | $6"
_RAW = (
    '{"sections":[{"section":"Tacos","items":[{"b":"b0005","n":"Carne Asada Taco","p":"3.50"},'
    '{"b":"b0007","n":"Queso","p":"6"}]}]}'
)


def test_block_ids_are_distinct_in_order_and_the_pieces_of_a_block_share_one() -> None:
    assert block_ids(_OLD) == ["b0004", "b0005", "b0007"]
    assert (
        renumbered(_OLD)
        == "k0 | Tacos\nk1 | Carne Asada Taco | $3.50\nk1 | (cont.)\nk2 | Queso | $6"
    )


def test_chunks_equal_up_to_block_ids_share_a_key_and_text_changes_do_not() -> None:
    assert chunk_key(_OLD) == chunk_key(_NEW)
    assert chunk_key(_OLD) != chunk_key(_OLD.replace("$6", "$7"))
    # a context line carries no ids; a mid-line "b0001 | " is text, not an id
    context = "(continued from earlier on this page; heading: 'Tacos'; it ended with: 'x')\n"
    assert block_ids(context + _OLD) == block_ids(_OLD)
    assert block_ids("b0001 | see b0002 | here") == ["b0001"]


def test_remap_moves_every_cited_id_through_the_two_id_lists() -> None:
    mapped = remap(_RAW, block_ids(_OLD), block_ids(_NEW))
    assert mapped == _RAW.replace("b0005", "b0010").replace("b0007", "b0012")
    # a truncated answer's last item still has its id mapped
    assert remap(_RAW[:60], block_ids(_OLD), block_ids(_NEW)) == mapped[:60]


def test_an_answer_citing_an_id_outside_its_chunk_is_not_reused() -> None:
    assert remap(_RAW.replace("b0007", "b0006"), block_ids(_OLD), block_ids(_NEW)) is None
    assert remap(_RAW, block_ids(_OLD), block_ids(_NEW)[:2]) is None


def test_chunk_records_round_trip_with_mapped_ids(tmp_path: Path) -> None:
    store = OutputStore(tmp_path)
    assert store.read_chunk("x", _NEW) is None
    answer = {"raw": _RAW, "finish": "stop", "wall_s": 9.5}
    assert store.write_chunk("x", _OLD, answer, page_text_hash="sha256:ab")
    assert not store.write_chunk("x", _NEW, {"raw": "{}"}, page_text_hash="sha256:cd")  # kept
    assert store.read_chunk("x", _NEW) == remap(_RAW, block_ids(_OLD), block_ids(_NEW))
    assert store.read_chunk("x", _OLD) == _RAW
    assert store.read_chunk("y", _NEW) is None  # another extractor version: not reused
    (path,) = tmp_path.glob("var/replay/menu-extract/*/chunks/*.json.gz")
    record = json.loads(gzip.decompress(path.read_bytes()))
    assert (record["ids"], record["text_hash"], record["chunk"]) == (
        ["b0004", "b0005", "b0007"],
        "sha256:ab",
        answer,
    )
    path.write_bytes(gzip.compress(b'{"format": "other"}'))
    with pytest.raises(ValueError, match="menu-chunk-v1"):
        store.read_chunk("x", _NEW)


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
