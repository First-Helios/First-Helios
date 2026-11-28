"""infra/backup/ (ADR-0031 D1, D2): the scripts parse, the pins and units say what the ADR says."""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

BACKUP_DIR = Path(__file__).resolve().parent.parent / "infra" / "backup"
SCRIPTS = sorted(BACKUP_DIR.glob("*.sh"))
BASH = shutil.which("bash")


def _bash(*args: str) -> subprocess.CompletedProcess[str]:
    assert BASH is not None
    return subprocess.run([BASH, *args], capture_output=True, text=True, check=False)


def _lines(name: str) -> list[str]:
    text = (BACKUP_DIR / name).read_text(encoding="utf-8")
    return [line for line in text.splitlines() if line and not line.startswith("#")]


def test_every_script_is_listed() -> None:
    assert {s.name for s in SCRIPTS} == {
        "backup.sh",
        "bootstrap.sh",
        "fetch-night.sh",
        "install-restic.sh",
        "laptop-copy.sh",
        "restic.sh",
    }


@pytest.mark.skipif(BASH is None, reason="no bash")
@pytest.mark.parametrize("script", SCRIPTS, ids=lambda p: p.name)
def test_script_parses(script: Path) -> None:
    result = _bash("-n", str(script))
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("script", SCRIPTS, ids=lambda p: p.name)
def test_no_script_traces_its_secrets(script: Path) -> None:
    assert "set -x" not in script.read_text(encoding="utf-8").replace("`set -x`", "")


def test_restic_is_pinned_by_version_and_sha256() -> None:
    text = (BACKUP_DIR / "install-restic.sh").read_text(encoding="utf-8")
    (version,) = re.findall(r"^VERSION=(\d+)\.(\d+)\.(\d+)$", text, flags=re.MULTILINE)
    assert tuple(map(int, version)) >= (0, 17, 0), "compression and --stdin-from-command"
    pins = dict(re.findall(r"ARCH=(\w+) SHA256=([0-9a-f]{64})", text))
    assert set(pins) == {"arm64", "amd64"}
    assert "sha256sum -c" in text


def test_the_timer_runs_nightly_in_utc() -> None:
    lines = _lines("helios-backup.timer")
    assert "OnCalendar=*-*-* 09:00:00 UTC" in lines, "the Pi's clock is Asia/Shanghai"
    assert {"Persistent=true", "Unit=helios-backup.service", "WantedBy=timers.target"} <= set(lines)


def test_the_unit_reads_secrets_from_outside_the_deploy_directory() -> None:
    lines = _lines("helios-backup.service")
    ops = "/home/orangepi/.config/helios-ops"
    assert f"EnvironmentFile={ops}/r2.env" in lines
    assert f"EnvironmentFile=-{ops}/hc.env" in lines, "the backup runs without alerting set up"
    assert f"Environment=RESTIC_PASSWORD_FILE={ops}/restic-password" in lines
    assert "WorkingDirectory=/home/orangepi/First-Helios" in lines
    assert "[Install]" not in lines, "the timer starts it"


def test_the_backup_locks_dumps_safely_and_writes_the_manifest_last() -> None:
    text = (BACKUP_DIR / "backup.sh").read_text(encoding="utf-8")
    dump = '--stdin-from-command -- "${DC[@]}" exec -T postgres pg_dump'
    assert text.index("\ndb_lock") < text.index(dump), "the lock comes before any dump"
    assert "-Fc -Z0" in text, "uncompressed, so restic deduplicates"
    assert "--keep-daily 7 --keep-weekly 5 --keep-monthly 12" in text
    files = text.index("var/replay var/pipeline-host DEPLOYED_COMMIT")
    assert files < text.index("--stdin-filename manifest.json"), "a night with a manifest is whole"


def test_the_example_env_holds_no_values() -> None:
    for line in _lines("r2.env.example"):
        key, value = line.split("=", 1)
        if key.startswith("AWS_") and key != "AWS_DEFAULT_REGION":
            assert value == "", key


@pytest.mark.skipif(BASH is None, reason="no bash")
@pytest.mark.parametrize(
    ("args", "message"),
    [
        (("fetch-night.sh",), "usage"),
        (("fetch-night.sh", "{tmp}/out", "night-yesterday"), "not a night tag"),
        (("bootstrap.sh",), "usage"),
        (("bootstrap.sh", "zz"), "not a commit"),
    ],
)
def test_guards(tmp_path: Path, args: tuple[str, ...], message: str) -> None:
    script, *rest = args
    result = _bash(str(BACKUP_DIR / script), *(a.format(tmp=tmp_path) for a in rest))
    assert result.returncode != 0 and message in result.stderr
