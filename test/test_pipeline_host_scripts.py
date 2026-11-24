"""infra/pipeline-host/ (ADR-0030): the scripts parse, and their guards hold without a host."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

HOST_DIR = Path(__file__).resolve().parent.parent / "infra" / "pipeline-host"
SCRIPTS = sorted(HOST_DIR.glob("*.sh"))
BASH = shutil.which("bash")


def _bash(*args: str) -> subprocess.CompletedProcess[str]:
    assert BASH is not None
    return subprocess.run([BASH, *args], capture_output=True, text=True, check=False)


def test_every_script_is_listed() -> None:
    assert {s.name for s in SCRIPTS} == {
        "dump.sh",
        "laptop-llama.sh",
        "lib.sh",
        "mark-master.sh",
        "mirror-laptop.sh",
        "move-master.sh",
        "replay-sync.sh",
        "restore.sh",
        "swap.sh",
    }


@pytest.mark.skipif(BASH is None, reason="no bash")
@pytest.mark.parametrize("script", SCRIPTS, ids=lambda p: p.name)
def test_script_parses(script: Path) -> None:
    result = _bash("-n", str(script))
    assert result.returncode == 0, result.stderr


@pytest.mark.skipif(BASH is None, reason="no bash")
def test_restore_refuses_the_public_database(tmp_path: Path) -> None:
    dump = tmp_path / "x.dump"
    dump.write_bytes(b"")
    result = _bash(str(HOST_DIR / "restore.sh"), "pi", "helios", str(dump))
    assert result.returncode == 1 and "replaced only by swap.sh" in result.stderr


@pytest.mark.skipif(BASH is None, reason="no bash")
@pytest.mark.parametrize(
    ("args", "message"),
    [
        (("restore.sh", "nas", "helios_work", "{dump}"), "host must be pi or laptop"),
        (("restore.sh", "pi", "helios_work; drop", "{dump}"), "not a database name"),
        (("swap.sh",), "usage"),
        (("move-master.sh", "sideways"), "BACKUPS"),
        (("mark-master.sh", "pi", "zz", "0" * 64), "not a commit"),
        (("mark-master.sh", "pi", "87108bb", "abc"), "not a sha256"),
    ],
)
def test_guards(tmp_path: Path, args: tuple[str, ...], message: str) -> None:
    dump = tmp_path / "x.dump"
    dump.write_bytes(b"")
    script, *rest = args
    result = _bash(str(HOST_DIR / script), *(a.format(dump=dump) for a in rest))
    assert result.returncode != 0 and message in result.stderr


@pytest.mark.skipif(BASH is None, reason="no bash")
def test_mark_master_writes_the_marker_the_loop_reads(tmp_path: Path) -> None:
    sha = "a9af1391" + "0" * 56
    result = subprocess.run(
        [BASH or "bash", str(HOST_DIR / "mark-master.sh"), "pi", "87108bb", sha],
        capture_output=True,
        text=True,
        check=False,
        env={"PATH": "/usr/bin:/bin", "DATA": str(tmp_path)},
    )
    assert result.returncode == 0, result.stderr
    from apps.menu_pipeline.batch_loop import read_marker  # noqa: PLC0415 - the reader under test

    marker = read_marker(tmp_path / "var" / "pipeline-host" / "MASTER")
    assert marker is not None
    assert (marker["host"], marker["commit"], marker["dump_sha256"]) == ("pi", "87108bb", sha)


def test_the_unit_cannot_start_at_boot() -> None:
    text = (HOST_DIR / "helios-pipeline-loop.service").read_text(encoding="utf-8")
    lines = [line for line in text.splitlines() if not line.startswith("#")]
    assert "[Install]" not in lines, "manual starts only (ADR-0030 Q2)"
    assert "ExecStart=/usr/bin/python3 -m apps.menu_pipeline.batch_loop $LOOP_ARGS" in lines
