"""Reviewed coordinate corrections for Overture records (ADR-0014).

``config/location_overrides.yaml`` pins a replacement point (and optionally an
address) for one Overture record, keyed by GERS id, when the upstream point is
wrong. Each discovery run persists every entry as a Bronze Version in the
``location-override`` namespace (repo endpoint + file hash, like the URL
registry) and appends a withdrawal Version for an entry that left the file.

:func:`effective_location` is the one place a coordinate consumer (minting,
dedupe, lifecycle projection) learns where a record is: the override's point
while its ``corrects`` point still equals the Overture point, otherwise the
Overture point, reported stale so a human re-confirms or withdraws it.

The file fails closed like the registry: a malformed entry raises and the run
does not start, and CI validates the committed file.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, replace
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml
from sqlalchemy import select

from apps.discovery.overture import MetroBbox
from packages.helios_core.provenance.contracts import (
    BronzeObservation,
    canonicalize_http_url,
    persist_source_record_observation,
)
from packages.helios_core.provenance.models import Source, SourceRecord, SourceRecordVersion

if TYPE_CHECKING:
    from datetime import datetime

    from sqlalchemy.orm import Session

    from apps.discovery.overture import OverturePoi

OVERRIDE_NAMESPACE = "location-override"
OVERRIDE_KIND = "location_override"
DEFAULT_PATH = Path(__file__).resolve().parents[2] / "config" / "location_overrides.yaml"
# How the replacement point was obtained. A single interpolating geocoder is not
# enough: the precision review measured Census 575 m off an official pin.
BASES = frozenset({"official_pin", "parcel", "two_geocoders"})
_KEYS = frozenset(
    {"gers_id", "latitude", "longitude", "address", "corrects", "evidence_url", "basis", "reason"}
)
_REQUIRED = _KEYS - {"address"}
_QUANTUM = Decimal("0.000001")  # Place stores Numeric(9, 6)
_ENTRY_LOCATOR = "$['latitude','longitude','address','corrects']"
_WITHDRAWN_LOCATOR = "$['withdrawn']"


def quantize(value: float) -> Decimal:
    return Decimal(str(value)).quantize(_QUANTUM)


@dataclass(frozen=True, slots=True)
class LocationOverride:
    """One reviewed replacement location for a single Overture record."""

    gers_id: str
    latitude: Decimal
    longitude: Decimal
    corrects_latitude: Decimal
    corrects_longitude: Decimal
    address: str | None
    evidence_url: str
    basis: str
    reason: str

    def payload(self) -> dict[str, object]:
        return {
            "gers_id": self.gers_id,
            "latitude": str(self.latitude),
            "longitude": str(self.longitude),
            "address": self.address,
            "corrects": {
                "latitude": str(self.corrects_latitude),
                "longitude": str(self.corrects_longitude),
            },
            "evidence_url": self.evidence_url,
            "basis": self.basis,
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class OverrideFile:
    """The validated file plus the provenance its Bronze Versions cite."""

    entries: dict[str, LocationOverride]
    content_hash: str = ""
    source_url: str | None = "repo:config/location_overrides.yaml"


@dataclass(frozen=True, slots=True)
class OverrideState:
    """A record's latest override Version; ``entry is None`` means withdrawn."""

    gers_id: str
    entry: LocationOverride | None
    record_id: int
    version_id: int


@dataclass(frozen=True, slots=True)
class EffectiveLocation:
    latitude: float | None
    longitude: float | None
    address: str | None
    applied: bool
    stale: bool


def _text(raw: dict[str, Any], key: str, index: int) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ValueError(f"override entry {index}: {key!r} must be a nonblank trimmed string")
    return value


def _point(raw: Any, index: int, label: str, bbox: MetroBbox) -> tuple[Decimal, Decimal]:  # noqa: ANN401 - raw YAML
    if not isinstance(raw, dict) or set(raw) != {"latitude", "longitude"}:
        raise ValueError(f"override entry {index}: {label} needs exactly latitude and longitude")
    lat, lon = raw["latitude"], raw["longitude"]
    for value in (lat, lon):
        if (
            isinstance(value, bool)
            or not isinstance(value, int | float)
            or not math.isfinite(value)
        ):
            raise ValueError(f"override entry {index}: {label} must be finite numbers")
    if not (bbox.lat_min <= lat <= bbox.lat_max and bbox.lon_min <= lon <= bbox.lon_max):
        raise ValueError(f"override entry {index}: {label} is outside the metro bbox")
    return quantize(lat), quantize(lon)


def _parse_entry(raw: Any, index: int, bbox: MetroBbox) -> LocationOverride:  # noqa: ANN401 - raw YAML
    if not isinstance(raw, dict):
        raise ValueError(f"override entry {index} must be a mapping")
    if unknown := set(raw) - _KEYS:
        raise ValueError(f"override entry {index}: unknown keys {sorted(unknown)}")
    if missing := _REQUIRED - set(raw):
        raise ValueError(f"override entry {index}: missing keys {sorted(missing)}")
    point = {"latitude": raw["latitude"], "longitude": raw["longitude"]}
    latitude, longitude = _point(point, index, "the override point", bbox)
    corrects = _point(raw["corrects"], index, "'corrects'", bbox)
    if (latitude, longitude) == corrects:
        raise ValueError(f"override entry {index}: the override point equals 'corrects'")
    basis = _text(raw, "basis", index)
    if basis not in BASES:
        raise ValueError(f"override entry {index}: 'basis' must be one of {sorted(BASES)}")
    try:
        evidence_url = canonicalize_http_url(_text(raw, "evidence_url", index))
    except ValueError as exc:
        raise ValueError(f"override entry {index}: 'evidence_url' is not HTTP(S)") from exc
    return LocationOverride(
        gers_id=_text(raw, "gers_id", index),
        latitude=latitude,
        longitude=longitude,
        corrects_latitude=corrects[0],
        corrects_longitude=corrects[1],
        address=None if raw.get("address") is None else _text(raw, "address", index),
        evidence_url=evidence_url,
        basis=basis,
        reason=_text(raw, "reason", index),
    )


def parse_overrides(
    document: Any,  # noqa: ANN401 - raw YAML
    *,
    bbox: MetroBbox | None = None,
) -> dict[str, LocationOverride]:
    """Validate a parsed YAML document into a GERS-keyed override map."""
    if document is None:
        return {}
    if not isinstance(document, dict) or set(document) - {"overrides"}:
        raise ValueError("override file must be a mapping with an 'overrides' list")
    raw_entries = document.get("overrides") or []
    if not isinstance(raw_entries, list):
        raise ValueError("'overrides' must be a list")
    entries: dict[str, LocationOverride] = {}
    for index, raw in enumerate(raw_entries):
        entry = _parse_entry(raw, index, bbox or MetroBbox.austin())
        if entry.gers_id in entries:
            raise ValueError(f"override entry {index}: duplicate gers_id {entry.gers_id!r}")
        entries[entry.gers_id] = entry
    return entries


def load_overrides(path: Path = DEFAULT_PATH) -> OverrideFile:
    """Read and validate the override file. A missing file raises.

    Never ``missing_ok``: an absent file would withdraw every active override.
    """
    raw = path.read_bytes()
    entries = parse_overrides(yaml.safe_load(raw))
    try:
        relative = path.resolve().relative_to(DEFAULT_PATH.parents[1])
        source_url: str | None = f"repo:{relative.as_posix()}"
    except ValueError:
        source_url = None
    return OverrideFile(
        entries=entries,
        content_hash="sha256:" + hashlib.sha256(raw).hexdigest(),
        source_url=source_url,
    )


def _latest(session: Session) -> dict[str, tuple[int, int, dict[str, Any]]]:
    """GERS id -> (record id, latest version id, payload) for every override record."""
    rows = session.execute(
        select(
            SourceRecord.external_key,
            SourceRecord.id,
            SourceRecordVersion.id,
            SourceRecordVersion.source_payload,
        )
        .join(Source, Source.id == SourceRecord.source_id)
        .join(SourceRecordVersion, SourceRecordVersion.source_record_id == SourceRecord.id)
        .where(Source.namespace == OVERRIDE_NAMESPACE)
        .order_by(SourceRecordVersion.observed_at, SourceRecordVersion.id)
    ).all()
    return {key: (record_id, version_id, payload) for key, record_id, version_id, payload in rows}


def persist_overrides(
    session: Session, overrides: OverrideFile, *, observed_at: datetime
) -> dict[str, OverrideState]:
    """Append a Version per changed entry and a withdrawal per removed one. Flushes.

    Returns the latest state of every override record, withdrawn ones included,
    so the lifecycle can revert a withdrawn correction.
    """
    from apps.discovery.lifecycle import lock_lifecycle

    lock_lifecycle(session)
    latest = _latest(session)
    wanted: dict[str, tuple[dict[str, object], str]] = {
        gers: (entry.payload(), _ENTRY_LOCATOR) for gers, entry in overrides.entries.items()
    }
    for gers, (_, _, payload) in latest.items():
        if gers not in wanted and not payload.get("withdrawn"):
            wanted[gers] = ({"gers_id": gers, "withdrawn": True}, _WITHDRAWN_LOCATOR)
    for gers, (payload, locator) in sorted(wanted.items()):
        if gers in latest and latest[gers][2] == payload:
            continue
        if not (overrides.content_hash and overrides.source_url):
            raise ValueError("override provenance requires file bytes and a repo-relative path")
        content_hash = (
            "sha256:"
            + hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()
        )
        persisted = persist_source_record_observation(
            session,
            BronzeObservation(
                source_namespace=OVERRIDE_NAMESPACE,
                source_kind=OVERRIDE_KIND,
                external_key=gers,
                observed_at=observed_at,
                content_hash=content_hash,
                source_payload=payload,
                evidence_locator=locator,
                source_url=overrides.source_url,
                capture_content_hash=overrides.content_hash,
            ),
        )
        latest[gers] = (persisted.source_record_id, persisted.source_record_version_id, payload)
    return {
        gers: OverrideState(
            gers_id=gers,
            entry=None if payload.get("withdrawn") else overrides.entries[gers],
            record_id=record_id,
            version_id=version_id,
        )
        for gers, (record_id, version_id, payload) in latest.items()
    }


def effective_location(poi: OverturePoi, state: OverrideState | None) -> EffectiveLocation:
    """Where the record is: the active override if it still corrects this point."""
    entry = state.entry if state is not None else None
    if entry is None:
        return EffectiveLocation(poi.latitude, poi.longitude, poi.address, False, False)
    if (
        poi.latitude is None
        or poi.longitude is None
        or (quantize(poi.latitude), quantize(poi.longitude))
        != (entry.corrects_latitude, entry.corrects_longitude)
    ):
        return EffectiveLocation(poi.latitude, poi.longitude, poi.address, False, True)
    return EffectiveLocation(
        float(entry.latitude),
        float(entry.longitude),
        entry.address if entry.address is not None else poi.address,
        True,
        False,
    )


def located(poi: OverturePoi, location: EffectiveLocation) -> OverturePoi:
    """The POI as coordinate consumers see it; ``raw`` (the Bronze payload) is unchanged."""
    return replace(
        poi, latitude=location.latitude, longitude=location.longitude, address=location.address
    )
