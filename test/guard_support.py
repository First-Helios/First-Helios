"""Assert that a database guard trigger, not an incidental error, rejected a write."""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING

import pytest
from sqlalchemy.exc import DBAPIError

if TYPE_CHECKING:
    from collections.abc import Iterator

# Bronze and Identity guard triggers raise object_not_in_prerequisite_state.
GUARD_SQLSTATE = "55000"


@contextmanager
def raises_guard(message: str) -> Iterator[None]:
    """Expect a guard trigger's rejection: SQLSTATE 55000 and its message.

    A bare ``pytest.raises(DBAPIError)`` is also satisfied by an FK RESTRICT
    error (23503) on any row with children, so it keeps passing after the
    guard trigger is dropped.
    """
    with pytest.raises(DBAPIError, match=message) as error:
        yield
    assert getattr(error.value.orig, "sqlstate", None) == GUARD_SQLSTATE, error.value
