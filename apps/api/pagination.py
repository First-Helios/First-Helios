"""Opaque cursor pagination (ADR-0008).

Cursors are base64url-encoded tokens over a stable, unique ordering key (the
Establishment ``subject_id``). Opaque so clients cannot construct or depend on
the encoding, and stable so a page boundary is insert-safe -- unlike offset
pagination, which is O(n) at depth and drifts under concurrent writes.
"""

from __future__ import annotations

import base64

from apps.api.errors import InvalidCursorError

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
