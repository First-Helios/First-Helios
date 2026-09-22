"""Load and validate the manual website / menu-URL registry.

``config/sources.yaml`` lets a human pin a known-good website and/or menu URL
for a host the automated resolution misses or gets wrong (ADR-0010 §4). The
schema is four fields, so it is validated structurally here — required keys,
types, and HTTP(S) URL well-formedness — with a CI test asserting a malformed
registry raises, rather than pulling in a JSON-Schema dependency.

Registry values take precedence over Overture-derived websites in the pipeline;
``location_unique`` is recorded for a possible future URL-promotion unit and is
not acted on now.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import yaml

from packages.helios_core.provenance.contracts import canonicalize_http_url

if TYPE_CHECKING:
    from pathlib import Path

_ALLOWED_KEYS = frozenset({"host", "website", "menu_url", "location_unique"})


@dataclass(frozen=True, slots=True)
class RegistryEntry:
    """One human-curated override for a single host."""

    host: str
    website: str | None
    menu_url: str | None
    location_unique: bool


def _normalize_host(value: str) -> str:
    host = value.strip().lower()
    return host[4:] if host.startswith("www.") else host


def _require_url(value: Any, *, field: str, index: int) -> str:  # noqa: ANN401 - raw YAML
    if not isinstance(value, str):
        raise ValueError(f"registry entry {index}: {field!r} must be a string")
    try:
        return canonicalize_http_url(value)
    except ValueError as exc:
        raise ValueError(f"registry entry {index}: {field!r} is not a valid HTTP(S) URL") from exc


def _parse_entry(raw: Any, index: int) -> RegistryEntry:  # noqa: ANN401 - raw YAML
    if not isinstance(raw, dict):
        raise ValueError(f"registry entry {index} must be a mapping")
    unknown = set(raw) - _ALLOWED_KEYS
    if unknown:
        raise ValueError(f"registry entry {index}: unknown keys {sorted(unknown)}")

    host = raw.get("host")
    if not isinstance(host, str) or not host.strip():
        raise ValueError(
            f"registry entry {index}: 'host' is required and must be a nonblank string"
        )

    website = (
        None
        if raw.get("website") is None
        else _require_url(raw["website"], field="website", index=index)
    )
    menu_url = (
        None
        if raw.get("menu_url") is None
        else _require_url(raw["menu_url"], field="menu_url", index=index)
    )

    location_unique = raw.get("location_unique", False)
    if not isinstance(location_unique, bool):
        raise ValueError(f"registry entry {index}: 'location_unique' must be a boolean")

    return RegistryEntry(
        host=_normalize_host(host),
        website=website,
        menu_url=menu_url,
        location_unique=location_unique,
    )


def parse_registry(document: Any) -> dict[str, RegistryEntry]:  # noqa: ANN401 - raw YAML
    """Validate a parsed YAML document into a host-keyed registry."""
    if document is None:
        return {}
    if not isinstance(document, dict):
        raise ValueError("registry must be a mapping with a 'venues' list")
    venues = document.get("venues", [])
    if not isinstance(venues, list):
        raise ValueError("'venues' must be a list")

    entries: dict[str, RegistryEntry] = {}
    for index, raw in enumerate(venues):
        entry = _parse_entry(raw, index)
        if entry.host in entries:
            raise ValueError(f"registry entry {index}: duplicate host {entry.host!r}")
        entries[entry.host] = entry
    return entries


def load_registry(path: Path) -> dict[str, RegistryEntry]:
    """Read and validate ``config/sources.yaml``; a missing file is an empty registry."""
    if not path.exists():
        return {}
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    return parse_registry(document)
