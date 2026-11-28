"""infra/ops/ (ADR-0031 D5): the watcher's four checks and the pings, run against stubs."""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
OPS = ROOT / "infra" / "ops"
BASH = shutil.which("bash")
URLS = {
    "HC_SITE_URL": "https://hc.test/site",
    "HC_DISK_URL": "https://hc.test/disk",
    "HC_RUN_PROGRESS_URL": "https://hc.test/progress",
    "HC_AWAITING_READER_URL": "https://hc.test/reader",
}
# curl: `-w` asks for a status code (the site check), anything else is a ping (logged).
CURL = """#!/usr/bin/env bash
for a in "$@"; do [ "$a" = -w ] && { echo "${STUB_CODE:-200}"; exit 0; }; done
echo "${@: -1}" >>"$PING_LOG"
"""
DF = """#!/usr/bin/env bash
printf 'Use%%\\n %s%%\\n' "${STUB_PCENT:-53}"
"""
SYSTEMCTL = """#!/usr/bin/env bash
case "$1" in
  is-active) exit "${STUB_INACTIVE:-0}" ;;
  show) echo "@${STUB_STARTED:-0}" ;;
esac
"""

pytestmark = pytest.mark.skipif(BASH is None, reason="no bash")


def _watch(tmp_path: Path, **stub: str) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    stubs = tmp_path / "bin"
    stubs.mkdir(exist_ok=True)
    for name, body in {"curl": CURL, "df": DF, "systemctl": SYSTEMCTL}.items():
        (stubs / name).write_text(body, encoding="utf-8")
        (stubs / name).chmod(0o755)
    pings = tmp_path / "pings.log"
    pings.write_text("", encoding="utf-8")
    env = {
        "PATH": f"{stubs}:/usr/bin:/bin",
        "DATA": str(tmp_path),
        "PING_LOG": str(pings),
        **URLS,
        **stub,
    }
    result = subprocess.run(
        [BASH or "bash", str(OPS / "watch.sh")],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    return result, pings.read_text(encoding="utf-8").splitlines()


def _age(path: Path, seconds: int) -> None:
    then = time.time() - seconds
    os.utime(path, (then, then))


def test_all_well_pings_each_check(tmp_path: Path) -> None:
    result, pings = _watch(tmp_path, STUB_INACTIVE="3")
    assert result.returncode == 0, result.stderr
    assert pings == list(URLS.values())


def test_each_failure_pings_fail_and_the_rest_still_ping(tmp_path: Path) -> None:
    state = tmp_path / "var" / "pipeline-host"
    (state / "logs").mkdir(parents=True)
    (state / "logs" / "progress.log").write_text("batch 1\n", encoding="utf-8")
    _age(state / "logs" / "progress.log", 9 * 3600)
    (state / "AWAITING_SWAP").write_text("run=2026-12-10\n", encoding="utf-8")
    _age(state / "AWAITING_SWAP", 4 * 86400)
    result, pings = _watch(tmp_path, STUB_CODE="502", STUB_PCENT="85", STUB_STARTED="1")
    assert result.returncode == 0, "one failing check must not stop the others"
    assert pings == [f"{url}/fail" for url in URLS.values()]
    assert "https://firsthelios.com/healthz 502" in result.stdout
    assert "/ is 85% full" in result.stdout
    assert "has not changed for 9 h" in result.stdout
    assert "waited 4 days for its reader: run=2026-12-10" in result.stdout


def test_a_fresh_start_or_a_young_marker_is_not_a_failure(tmp_path: Path) -> None:
    state = tmp_path / "var" / "pipeline-host"
    (state / "logs").mkdir(parents=True)
    (state / "logs" / "progress.log").write_text("last month\n", encoding="utf-8")
    _age(state / "logs" / "progress.log", 30 * 86400)
    (state / "AWAITING_SWAP").write_text("run\n", encoding="utf-8")
    _age(state / "AWAITING_SWAP", 2 * 86400)
    started = str(int(time.time()) - 600)  # the loop started 10 minutes ago
    _, pings = _watch(tmp_path, STUB_STARTED=started, STUB_PCENT="84")
    assert pings == list(URLS.values())


def _ping(kind: str, **env: str) -> list[str]:
    log = Path(env["PING_LOG"])
    log.write_text("", encoding="utf-8")
    subprocess.run(
        [BASH or "bash", str(OPS / "hc-ping.sh"), "HC_MONTHLY_RUN_URL", kind],
        check=True,
        env={"PATH": f"{Path(env['PING_LOG']).parent / 'bin'}:/usr/bin:/bin", **env},
    )
    return log.read_text(encoding="utf-8").splitlines()


@pytest.mark.parametrize(
    ("kind", "exit_status", "suffix"),
    [("start", "", "/start"), ("exit", "0", "/0"), ("exit", "2", "/2"), ("exit", "TERM", "/fail")],
)
def test_the_loop_pings(tmp_path: Path, kind: str, exit_status: str, suffix: str) -> None:
    (tmp_path / "bin").mkdir()
    (tmp_path / "bin" / "curl").write_text(CURL, encoding="utf-8")
    (tmp_path / "bin" / "curl").chmod(0o755)
    env = {"PING_LOG": str(tmp_path / "pings.log"), "HC_MONTHLY_RUN_URL": "https://hc.test/run"}
    assert _ping(kind, **env, EXIT_STATUS=exit_status) == [f"https://hc.test/run{suffix}"]
    assert _ping(kind, PING_LOG=env["PING_LOG"], EXIT_STATUS=exit_status) == [], "unset: no ping"


def test_the_loop_unit_pings_without_risk_to_the_run() -> None:
    unit = (ROOT / "infra" / "pipeline-host" / "helios-pipeline-loop.service").read_text("utf-8")
    lines = [line for line in unit.splitlines() if not line.startswith("#")]
    assert "EnvironmentFile=-/home/orangepi/.config/helios-ops/hc.env" in lines
    assert "ExecStartPre=-/bin/bash infra/ops/hc-ping.sh HC_MONTHLY_RUN_URL start" in lines
    assert "ExecStopPost=-/bin/bash infra/ops/hc-ping.sh HC_MONTHLY_RUN_URL exit" in lines


def test_the_watch_units() -> None:
    timer = (OPS / "helios-watch.timer").read_text(encoding="utf-8").splitlines()
    assert {"OnCalendar=*:0/5", "Unit=helios-watch.service", "WantedBy=timers.target"} <= set(timer)
    service = (OPS / "helios-watch.service").read_text(encoding="utf-8").splitlines()
    assert "EnvironmentFile=/home/orangepi/.config/helios-ops/hc.env" in service
    assert "ExecStart=/bin/bash infra/ops/watch.sh" in service


def test_the_example_env_names_every_ping_and_holds_no_value() -> None:
    lines = [
        line
        for line in (OPS / "hc.env.example").read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#")
    ]
    assert lines == [f"{name}=" for name in [*URLS, "HC_MONTHLY_RUN_URL", "HC_BACKUP_URL"]]


@pytest.mark.parametrize("script", sorted(OPS.glob("*.sh")), ids=lambda p: p.name)
def test_script_parses(script: Path) -> None:
    result = subprocess.run(
        [BASH or "bash", "-n", str(script)], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr
