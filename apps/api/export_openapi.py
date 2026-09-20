"""Regenerate the committed OpenAPI snapshot (ADR-0008 contract test).

Run after an intentional wire-surface change:

    uv run python -m apps.api.export_openapi
"""

from __future__ import annotations

import json
from pathlib import Path

from apps.api.main import app

_SNAPSHOT = Path(__file__).resolve().parent / "openapi_snapshot.json"


def main() -> None:
    """Write the current schema to the committed snapshot file."""
    _SNAPSHOT.write_text(json.dumps(app.openapi(), indent=2, sort_keys=True) + "\n")
    print(f"wrote {_SNAPSHOT}")  # noqa: T201 - dev CLI output


if __name__ == "__main__":
    main()
