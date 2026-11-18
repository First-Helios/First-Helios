"""Validated repeatable category filters shared by venue and item routes."""

from __future__ import annotations

from typing import Annotated

from fastapi import Query

from apps.api.errors import ApiError
from packages.helios_core.gold.categories import LABELS


def category_filters(
    cuisine: Annotated[list[str] | None, Query(max_length=20)] = None,
    specialty: Annotated[list[str] | None, Query(max_length=20)] = None,
    place_type: Annotated[list[str] | None, Query(max_length=20)] = None,
) -> dict[str, tuple[str, ...]]:
    """Values are exact mapping keys; every page must resend every group."""
    result = {}
    for group, keys in (("cuisine", cuisine), ("specialty", specialty), ("place_type", place_type)):
        if keys:
            if any((group, key) not in LABELS for key in keys):
                raise ApiError(422, "validation_error", f"unknown {group} category")
            result[group] = tuple(sorted(set(keys)))
    return result
