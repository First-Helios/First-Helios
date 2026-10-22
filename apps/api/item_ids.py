"""Opaque menu item ids (ADR-0018 §B4).

An ``item_id`` names one Gold target -- ``(scope subject kind, scope subject id,
source record, root key, target path)``, the ``uq_gold_current_menu`` grain
without context and currency -- as unpadded base64url over compact JSON. It
survives Gold refreshes and needs no lookup table. Like the cursor it is opaque
but not secret: a forged token can only name a target that does or doesn't
exist. Only the canonical encoding decodes, so each target has exactly one id.
"""

from __future__ import annotations

import base64
import binascii
import json
from dataclasses import dataclass
from typing import Literal, cast

from fastapi import status

from apps.api.errors import ApiError
from apps.api.pagination import BIGINT_MAX

_SCOPE_KINDS = ("establishment", "organization")
_NODE_KINDS = ("section", "item", "variant", "modifier")
_BASE_KIND = "base"  # a pinned-base prefix, only ever first (ADR-0005 §10)


class InvalidItemIdError(ApiError):
    """An ``item_id`` that does not decode to a target."""

    def __init__(self) -> None:
        super().__init__(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "validation_error", "item_id is malformed"
        )


@dataclass(frozen=True, slots=True)
class ItemId:
    """The Gold target an ``item_id`` names."""

    subject_kind: Literal["establishment", "organization"]
    subject_id: int
    source_record_id: int
    root_key: str
    target_path: tuple[tuple[str, str], ...]  # (node kind, native key), root first

    @property
    def target_kind(self) -> str:
        return self.target_path[-1][0]


def encode_item_id(item: ItemId) -> str:
    payload = [
        item.subject_kind,
        item.subject_id,
        item.source_record_id,
        item.root_key,
        [[kind, key] for kind, key in item.target_path],
    ]
    raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _text(value: object) -> str:
    # PostgreSQL text cannot hold NUL; such a key could never name a target.
    if not isinstance(value, str) or "\x00" in value:
        raise InvalidItemIdError
    return value


def _bigint(value: object) -> int:
    if type(value) is not int or not 0 <= value <= BIGINT_MAX:
        raise InvalidItemIdError
    return value


def _path(value: object) -> tuple[tuple[str, str], ...]:
    if not isinstance(value, list) or not value:
        raise InvalidItemIdError
    path: list[tuple[str, str]] = []
    for position, node in enumerate(cast("list[object]", value)):
        if not isinstance(node, list) or len(node) != 2:
            raise InvalidItemIdError
        kind, key = _text(node[0]), _text(node[1])
        if kind not in _NODE_KINDS and not (kind == _BASE_KIND and position == 0):
            raise InvalidItemIdError
        path.append((kind, key))
    if path[-1][0] == _BASE_KIND:
        raise InvalidItemIdError
    return tuple(path)


def decode_item_id(token: str) -> ItemId:
    """Decode a canonical ``item_id``, or raise :class:`InvalidItemIdError` (422)."""
    try:
        raw = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4))
        payload = json.loads(raw.decode("utf-8"))
    except (ValueError, binascii.Error, UnicodeError) as exc:
        raise InvalidItemIdError from exc
    if not isinstance(payload, list) or len(payload) != 5:
        raise InvalidItemIdError
    subject_kind, subject_id, source_record_id, root_key, path = cast("list[object]", payload)
    if subject_kind not in _SCOPE_KINDS:
        raise InvalidItemIdError
    item = ItemId(
        subject_kind=cast("Literal['establishment', 'organization']", subject_kind),
        subject_id=_bigint(subject_id),
        source_record_id=_bigint(source_record_id),
        root_key=_text(root_key),
        target_path=_path(path),
    )
    if encode_item_id(item) != token:
        raise InvalidItemIdError  # a non-canonical alias of some target
    return item
