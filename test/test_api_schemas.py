"""Unit tests for the read API's wire models (no database).

R50: timestamps must serialize as ISO-8601 UTC regardless of the datetime's
own tzinfo -- a DB session with a non-UTC ``TimeZone`` setting must not leak
a non-UTC offset onto the wire.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

from apps.api.schemas import VenueResponse


def _venue(valid_from: datetime, valid_to: datetime | None) -> VenueResponse:
    return VenueResponse(
        id=1,
        name="Test Venue",
        organization_kind="brand",
        address=None,
        latitude=None,
        longitude=None,
        operating_status="open",
        valid_from=valid_from,
        valid_to=valid_to,
    )


def test_naive_datetime_serializes_as_utc_z() -> None:
    venue = _venue(datetime(2024, 1, 1, 12, 0, 0), None)  # noqa: DTZ001 - naive on purpose
    body = venue.model_dump(mode="json")
    assert body["valid_from"] == "2024-01-01T12:00:00Z"


def test_non_utc_aware_datetime_is_converted_to_utc_z() -> None:
    # What a DB session with a non-UTC TimeZone would hand back; the wire
    # format must be UTC regardless of server/session configuration (R50).
    minus_six = timezone(timedelta(hours=-6))
    venue = _venue(datetime(2024, 1, 1, 6, 0, 0, tzinfo=minus_six), None)
    body = venue.model_dump(mode="json")
    assert body["valid_from"] == "2024-01-01T12:00:00Z"


def test_utc_datetime_round_trips_with_z_suffix() -> None:
    venue = _venue(datetime(2024, 1, 1, tzinfo=UTC), None)
    body = venue.model_dump(mode="json")
    assert body["valid_from"] == "2024-01-01T00:00:00Z"


def test_null_valid_to_stays_null() -> None:
    venue = _venue(datetime(2024, 1, 1, tzinfo=UTC), None)
    body = venue.model_dump(mode="json")
    assert body["valid_to"] is None


def test_non_null_valid_to_is_also_normalized() -> None:
    minus_six = timezone(timedelta(hours=-6))
    venue = _venue(
        datetime(2024, 1, 1, tzinfo=UTC),
        datetime(2024, 6, 1, 6, 0, 0, tzinfo=minus_six),
    )
    body = venue.model_dump(mode="json")
    assert body["valid_to"] == "2024-06-01T12:00:00Z"
