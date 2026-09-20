"""Unit tests for opaque cursor encode/decode (no database)."""

from __future__ import annotations

import pytest

from apps.api.errors import InvalidCursorError
from apps.api.pagination import decode_cursor, encode_cursor


@pytest.mark.parametrize("subject_id", [0, 1, 42, 1_000_000, 9_223_372_036_854_775_807])
def test_cursor_round_trips(subject_id: int) -> None:
    assert decode_cursor(encode_cursor(subject_id)) == subject_id


def test_cursor_is_opaque() -> None:
    # Not the bare integer; a client cannot trivially forge or infer it.
    assert encode_cursor(42) != "42"


@pytest.mark.parametrize(
    "bad",
    ["", "not-base64!!", "MTIz.extra", "bm90LWFuLWludA==", "LTU="],
)
def test_invalid_cursor_raises(bad: str) -> None:
    with pytest.raises(InvalidCursorError):
        decode_cursor(bad)
