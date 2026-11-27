"""Opaque cursor pagination (ADR-0008).

Cursors are base64url-encoded tokens over a stable, unique ordering key (the
Establishment ``subject_id``; for the price-index cell list, a row's business
key, ADR-0007 Amendment 3; for a drawn area's items, the price and the Gold
row's business grain, ADR-0020 §4, or in the ``typical`` order the pivot,
course group, distance, price, venue round and venue before that grain, ADR-0020
Amendment 1).
Opaque means clients are told not to construct or
depend on the encoding; it is not a security boundary. The token is unsigned, so
anyone can forge one. That is harmless: the data is public and a cursor is only
a keyset lower bound, so a forged cursor just starts a page elsewhere. Stable
means a page boundary is insert-safe -- unlike offset pagination, which is O(n)
at depth and drifts under concurrent writes.
"""

from __future__ import annotations

import base64
import binascii
import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING, cast

from apps.api.errors import InvalidCursorError

if TYPE_CHECKING:
    from collections.abc import Callable

    from packages.helios_core.gold.price_index_read import AreaItemKey, TypicalAreaItemKey

DEFAULT_LIMIT = 50
MAX_LIMIT = 200

# subject_id is a Postgres BIGINT (identity/models.py); a decoded value
# outside this range can never match a row, and passing it straight to a
# ``::BIGINT`` comparison raises `numeric field overflow` -- a 500, not a
# 400 (R41). Also the upper bound path/query params are validated against.
BIGINT_MAX = 2**63 - 1


def encode_cursor(subject_id: int) -> str:
    """Encode the last row's ordering key as an opaque token."""
    return base64.urlsafe_b64encode(str(subject_id).encode("ascii")).decode("ascii")


def decode_cursor(cursor: str) -> int:
    """Decode a cursor to its ordering key, or raise :class:`InvalidCursorError`."""
    try:
        raw = base64.urlsafe_b64decode(cursor.encode("ascii"))
        value = int(raw.decode("ascii"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise InvalidCursorError from exc
    if value < 0 or value > BIGINT_MAX:
        raise InvalidCursorError
    return value


# The varchar lengths of gold.price_index's (area_key, category_kind,
# category_key, currency_code): a longer string can never be a stored key.
CELL_KEY_LENGTHS = (64, 32, 128, 3)


def encode_cell_cursor(key: tuple[str, str, str, str]) -> str:
    """Encode a price-index row key as unpadded base64url over compact JSON."""
    raw = json.dumps(list(key), separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_cell_cursor(cursor: str) -> tuple[str, str, str, str]:
    """Decode a canonical cell cursor, or raise :class:`InvalidCursorError` (400).

    As with ``item_id`` (ADR-0018 §B4), only the canonical encoding decodes, so
    each key has exactly one cursor.
    """
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
        payload = json.loads(raw.decode("utf-8"))
    except (ValueError, binascii.Error, UnicodeError) as exc:
        raise InvalidCursorError from exc
    if not isinstance(payload, list) or len(payload) != len(CELL_KEY_LENGTHS):
        raise InvalidCursorError
    values = cast("list[object]", payload)
    for value, length in zip(values, CELL_KEY_LENGTHS, strict=True):
        # PostgreSQL text cannot hold NUL; such a key could never be stored.
        if not isinstance(value, str) or len(value) > length or "\x00" in value:
            raise InvalidCursorError
    key = cast("tuple[str, str, str, str]", tuple(values))
    try:
        canonical = encode_cell_cursor(key)
    except UnicodeError as exc:  # a lone surrogate from a \ud800 escape
        raise InvalidCursorError from exc
    if canonical != cursor:
        raise InvalidCursorError
    return key


BIGINT_MIN = -(2**63)
# The varchar lengths of gold.current_menu's (subject_kind, root_key, channel,
# service_period, currency_code); target_path is unbounded text.
_SUBJECT_KIND_LENGTH, _ROOT_KEY_LENGTH, _CHANNEL_LENGTH, _SERVICE_PERIOD_LENGTH = 32, 512, 16, 128
_CURRENCY_LENGTH = 3
_LAST_COURSE_GROUP = 3  # price_index_read.COURSE_GROUPS: food 0 … extras 3


def _wire_time(value: datetime | None) -> str | None:
    return value.astimezone(UTC).isoformat() if value is not None else None


def encode_area_item_cursor(key: AreaItemKey) -> str:
    """Encode an area item's key (ADR-0020 §4) as unpadded base64url over compact JSON.

    Times are ISO-8601 in UTC; ``None`` is ``null``.
    """
    return _encode_payload([key[0], *_wire_grain(key[1:])])


def encode_typical_area_item_cursor(key: TypicalAreaItemKey) -> str:
    """Encode an area item's ``typical`` key (ADR-0020 Amendment 1 item 3) like the price key.

    ``[pivot, group, distance, amount, round, venue_id, …grain]``: 16 values, so
    a cursor of one ``sort`` never decodes as the other's, nor one issued before
    the course group joined the order (15 values).
    """
    return _encode_payload([*key[:6], *_wire_grain(key[6:])])


def _wire_grain(grain: tuple[object, ...]) -> list[object]:
    subject, kind, record, root, path, channel, period, valid_from, valid_to, currency = grain
    return [
        subject,
        kind,
        record,
        root,
        path,
        channel,
        period,
        _wire_time(cast("datetime | None", valid_from)),
        _wire_time(cast("datetime | None", valid_to)),
        currency,
    ]


def _encode_payload(payload: list[object]) -> str:
    raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _cursor_int(value: object, low: int) -> int:
    if type(value) is not int or not low <= value <= BIGINT_MAX:
        raise InvalidCursorError
    return value


def _cursor_text(value: object, length: int | None, *, nullable: bool = False) -> str | None:
    if value is None and nullable:
        return None
    # PostgreSQL text cannot hold NUL; such a key could never be stored.
    if not isinstance(value, str) or "\x00" in value:
        raise InvalidCursorError
    if length is not None and len(value) > length:
        raise InvalidCursorError
    return value


def _cursor_time(value: object) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise InvalidCursorError
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise InvalidCursorError from exc
    if parsed.tzinfo is None:
        raise InvalidCursorError
    return parsed


def decode_area_item_cursor(cursor: str) -> AreaItemKey:
    """Decode a canonical area item cursor, or raise :class:`InvalidCursorError` (400).

    As with the cell cursor, only the canonical encoding decodes, so each key
    has exactly one cursor. A ``typical`` cursor (16 values) is refused.
    """
    values = _decode_payload(cursor, 11)
    key: AreaItemKey = (_cursor_int(values[0], BIGINT_MIN), *_cursor_grain(values[1:]))
    _require_canonical(cursor, encode_area_item_cursor, key)
    return key


def decode_typical_area_item_cursor(cursor: str) -> TypicalAreaItemKey:
    """Decode a canonical ``typical`` area item cursor, or raise :class:`InvalidCursorError`.

    Canonical as the price cursor is; its course group is one of the four, and
    its distance must be exactly ``|amount - pivot|``. A price cursor (11
    values) and a pre-course-group cursor (15) are refused.
    """
    values = _decode_payload(cursor, 16)
    pivot = _cursor_int(values[0], BIGINT_MIN)
    group = _cursor_int(values[1], 0)
    distance = values[2]
    amount = _cursor_int(values[3], BIGINT_MIN)
    if group > _LAST_COURSE_GROUP or type(distance) is not int or distance != abs(amount - pivot):
        raise InvalidCursorError
    key: TypicalAreaItemKey = (
        pivot,
        group,
        distance,
        amount,
        _cursor_int(values[4], 1),  # rounds count from 1
        _cursor_int(values[5], 0),
        *_cursor_grain(values[6:]),
    )
    _require_canonical(cursor, encode_typical_area_item_cursor, key)
    return key


def _decode_payload(cursor: str, length: int) -> list[object]:
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
        payload = json.loads(raw.decode("utf-8"))
    except (ValueError, binascii.Error, UnicodeError) as exc:
        raise InvalidCursorError from exc
    if not isinstance(payload, list) or len(payload) != length:
        raise InvalidCursorError
    return cast("list[object]", payload)


def _cursor_grain(
    values: list[object],
) -> tuple[int, str, int, str, str, str, str | None, datetime | None, datetime | None, str]:
    return (
        _cursor_int(values[0], 0),
        cast("str", _cursor_text(values[1], _SUBJECT_KIND_LENGTH)),
        _cursor_int(values[2], 0),
        cast("str", _cursor_text(values[3], _ROOT_KEY_LENGTH)),
        cast("str", _cursor_text(values[4], None)),
        cast("str", _cursor_text(values[5], _CHANNEL_LENGTH)),
        _cursor_text(values[6], _SERVICE_PERIOD_LENGTH, nullable=True),
        _cursor_time(values[7]),
        _cursor_time(values[8]),
        cast("str", _cursor_text(values[9], _CURRENCY_LENGTH)),
    )


def _require_canonical[K](cursor: str, encode: Callable[[K], str], key: K) -> None:
    try:
        canonical = encode(key)
    except UnicodeError as exc:  # a lone surrogate from a \ud800 escape
        raise InvalidCursorError from exc
    if canonical != cursor:
        raise InvalidCursorError
