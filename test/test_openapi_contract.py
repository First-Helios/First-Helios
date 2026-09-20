"""The published OpenAPI schema is a committed contract (ADR-0008).

A breaking change to the wire surface must fail CI, not surprise the frontend.
When the schema legitimately changes, regenerate the snapshot:

    uv run python -m apps.api.export_openapi
"""

from __future__ import annotations

import json
from pathlib import Path

from apps.api.main import app

_SNAPSHOT = Path(__file__).resolve().parents[1] / "apps" / "api" / "openapi_snapshot.json"


def test_openapi_matches_committed_snapshot() -> None:
    committed = json.loads(_SNAPSHOT.read_text())
    current = json.loads(json.dumps(app.openapi(), sort_keys=True))
    assert current == committed, (
        "OpenAPI schema drifted from the committed snapshot. If intended, "
        "regenerate with `uv run python -m apps.api.export_openapi`."
    )


def test_expected_paths_present() -> None:
    paths = set(app.openapi()["paths"])
    assert {"/healthz", "/readyz", "/v1/venues", "/v1/venues/{venue_id}"} <= paths
