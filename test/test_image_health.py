"""The image's health and contents (ADR-0031 D3, R116): one HEALTHCHECK, in the image."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
BASH = shutil.which("bash")


def _runtime_stage() -> str:
    dockerfile = (ROOT / "infra" / "Dockerfile").read_text(encoding="utf-8")
    return dockerfile.split("AS runtime", 1)[1]


def _services() -> dict[str, Any]:
    compose = yaml.safe_load((ROOT / "infra" / "docker-compose.yml").read_text(encoding="utf-8"))
    services: dict[str, Any] = compose["services"]
    return services


def test_the_runtime_stage_probes_liveness() -> None:
    runtime = _runtime_stage()
    assert "HEALTHCHECK --interval=10s --timeout=5s --start-period=10s --retries=5" in runtime
    assert "http://127.0.0.1:8000/healthz" in runtime, "liveness, not /readyz"
    dockerfile = (ROOT / "infra" / "Dockerfile").read_text(encoding="utf-8")
    assert dockerfile.count("HEALTHCHECK ") == 1, "the worker stage inherits nothing"


def test_compose_has_one_definition_and_the_one_shots_opt_out() -> None:
    services = _services()
    assert "healthcheck" not in services["api"], "the image's HEALTHCHECK is the one definition"
    for one_shot in ("migrate", "llama-model-check"):
        assert services[one_shot]["healthcheck"] == {"disable": True}, one_shot


def test_docs_and_tests_stay_out_of_the_image() -> None:
    lines = (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
    assert {"docs/", "test/", ".env", "var/"} <= set(lines)


@pytest.mark.skipif(BASH is None, reason="no bash")
def test_the_smoke_script_parses() -> None:
    script = ROOT / "infra" / "ci" / "docker-smoke.sh"
    result = subprocess.run(
        [BASH or "bash", "-n", str(script)], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr
