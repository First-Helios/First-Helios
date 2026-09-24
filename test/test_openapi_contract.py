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


def test_error_responses_document_the_real_envelope_not_fastapis_default() -> None:
    # R37: the published schema must describe {detail, code, trace_id} with
    # the real code enum, not FastAPI's default HTTPValidationError/
    # ValidationError shape (which the API never actually returns).
    schema = app.openapi()
    schemas = schema["components"]["schemas"]
    assert "HTTPValidationError" not in schemas
    assert "ValidationError" not in schemas

    error_response = schemas["ErrorResponse"]
    assert set(error_response["required"]) == {"detail", "code", "trace_id"}
    assert set(error_response["properties"]["code"]["enum"]) == {
        "not_found",
        "validation_error",
        "invalid_cursor",
        "method_not_allowed",
        "service_unavailable",
        "internal_error",
    }

    venues_get = schema["paths"]["/v1/venues"]["get"]["responses"]
    assert venues_get["422"]["content"]["application/json"]["schema"]["$ref"].endswith(
        "ErrorResponse"
    )
    readyz_responses = schema["paths"]["/readyz"]["get"]["responses"]
    assert readyz_responses["503"]["content"]["application/json"]["schema"]["$ref"].endswith(
        "ErrorResponse"
    )
