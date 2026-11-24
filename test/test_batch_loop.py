"""The pipeline host's batch loop (ADR-0030 D2), with every host action faked."""

from __future__ import annotations

import ast
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from apps.menu_pipeline import batch_loop
from apps.menu_pipeline.batch_loop import (
    CONTAINER_PREFIX,
    COOL_TO,
    EXTRACT,
    FETCH,
    PAUSE_AT,
    RESUME_AT,
    Config,
    GpuWatch,
    Host,
    Loop,
    cli_command,
    fetch_done,
    parse_args,
    same_commit,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence


class FakeHost:
    """Records commands and answers each CLI with a summary line."""

    def __init__(
        self,
        fetched: list[int] | None = None,
        *,
        fail: str | None = None,
        gpu: list[int] | None = None,
        on_sleep: Path | None = None,
    ) -> None:
        self.fetched = list(fetched or [])
        self.fail = fail  # "fetch" or "extract": that CLI exits 1
        self.gpu_readings = list(gpu or [])
        self.on_sleep = on_sleep  # a STOP file the first sleep creates
        self.commands: list[list[str]] = []
        self.envs: list[Mapping[str, str] | None] = []
        self.docker_calls: list[tuple[str, str]] = []
        self.sleeps: list[float] = []

    def run(
        self, command: Sequence[str], out: Path, err: Path, env: Mapping[str, str] | None
    ) -> int:
        self.commands.append(list(command))
        self.envs.append(env)
        err.write_text("")
        if FETCH in command:
            summary = {"fetched": self.fetched.pop(0), "outcomes": {"ok": 1}}
            out.write_text("menu-page run complete: " + json.dumps(summary) + "\n")
            return 1 if self.fail == "fetch" else 0
        summary = {"due": 3, "extracted": 2, "reused_outputs": 1, "failed": {}}
        if "--no-model" in command:
            summary["refused_chunk_calls"] = 4
        out.write_text("extraction run complete: " + json.dumps(summary) + "\n")
        return 1 if self.fail == "extract" else 0

    def gpu(self) -> int | None:
        return self.gpu_readings.pop(0) if self.gpu_readings else 70

    def docker(self, action: str, container: str) -> None:
        self.docker_calls.append((action, container))

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        if self.on_sleep is not None:
            self.on_sleep.touch()

    def host(self) -> Host:
        return Host(
            run=self.run,
            soc=lambda: 60.0,
            gpu=self.gpu,
            docker=self.docker,
            sleep=self.sleep,
            now=lambda: datetime(2026, 11, 24, tzinfo=UTC),
        )


def _config(tmp_path: Path, **overrides: object) -> Config:
    values: dict[str, object] = {
        "host": "pi",
        "phase": "full",
        "batch": 50,
        "stop_every": 10,
        "data_dir": tmp_path,
        "code_dir": tmp_path,
    } | overrides
    return Config(**values)  # type: ignore[arg-type]


def _master(tmp_path: Path, host: str = "pi", commit: str = "87108bb") -> None:
    run_dir = tmp_path / "var" / "pipeline-host"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "MASTER").write_text(f"host={host}\ncommit={commit}\nmoved_at=x\n")
    (tmp_path / "DEPLOYED_COMMIT").write_text("87108bb1234\n")


def _progress(tmp_path: Path) -> str:
    return (tmp_path / "var" / "pipeline-host" / "logs" / "progress.log").read_text()


def test_runs_batches_until_a_fetch_takes_fewer_than_the_batch(tmp_path: Path) -> None:
    _master(tmp_path)
    fake = FakeHost([50, 50, 12])

    status = Loop(_config(tmp_path), fake.host()).run()

    assert status == 0
    modules = [FETCH if FETCH in c else EXTRACT for c in fake.commands]
    assert modules == [FETCH, EXTRACT] * 3
    log = _progress(tmp_path)
    assert "batch 003 full" in log and "fetched 12 < 50: nothing left, done" in log
    assert "model_pages=1" in log


def test_stops_every_n_batches_for_a_swap(tmp_path: Path) -> None:
    _master(tmp_path)
    fake = FakeHost([50] * 5)

    assert Loop(_config(tmp_path, stop_every=2), fake.host()).run() == 0
    assert len(fake.commands) == 4
    assert "2 batches: swap due, stopping" in _progress(tmp_path)


def test_numbering_continues_from_logged_batches(tmp_path: Path) -> None:
    _master(tmp_path)
    logs = tmp_path / "var" / "pipeline-host" / "logs"
    logs.mkdir()
    (logs / "batch-001-fetch.out").write_text("")
    (logs / "batch-002-fetch.out").write_text("")

    Loop(_config(tmp_path), FakeHost([3]).host()).run()

    assert (logs / "batch-003-fetch.out").exists()


def test_a_stop_file_stops_before_any_batch(tmp_path: Path) -> None:
    _master(tmp_path)
    (tmp_path / "var" / "pipeline-host" / "STOP").touch()
    fake = FakeHost([50])

    assert Loop(_config(tmp_path), fake.host()).run() == 0
    assert fake.commands == []
    assert "STOP file" in _progress(tmp_path)


@pytest.mark.parametrize(("fail", "commands"), [("fetch", 1), ("extract", 2)])
def test_a_failed_cli_stops_the_loop(tmp_path: Path, fail: str, commands: int) -> None:
    _master(tmp_path)
    fake = FakeHost([50, 50], fail=fail)

    assert Loop(_config(tmp_path), fake.host()).run() == 1
    assert len(fake.commands) == commands, "a failed fetch is not followed by an extract"
    assert "a CLI failed" in _progress(tmp_path)


def test_fetch_phase_never_extracts(tmp_path: Path) -> None:
    _master(tmp_path)
    fake = FakeHost([50, 7])

    assert Loop(_config(tmp_path, phase="fetch"), fake.host()).run() == 0
    assert all(FETCH in c for c in fake.commands) and len(fake.commands) == 2


def test_no_model_phase_runs_one_extraction_without_a_server(tmp_path: Path) -> None:
    _master(tmp_path)
    fake = FakeHost()
    config = _config(tmp_path, phase="extract-no-model", server="http://192.168.1.183:8083")

    assert Loop(config, fake.host()).run() == 0
    (command,) = fake.commands
    assert EXTRACT in command and "--no-model" in command and "--server" not in command
    assert "refused_chunk_calls=4" in _progress(tmp_path)


def test_extract_phase_passes_the_remote_server(tmp_path: Path) -> None:
    _master(tmp_path)
    fake = FakeHost()
    config = _config(tmp_path, phase="extract", server="http://192.168.1.183:8083")

    assert Loop(config, fake.host()).run() == 0
    (command,) = fake.commands
    assert command[-2:] == ["--server", "http://192.168.1.183:8083"]


@pytest.mark.parametrize(
    ("marker", "reason"),
    [
        (None, "this host is not the master"),
        ({"host": "laptop", "commit": "87108bb"}, "names host 'laptop'"),
        ({"host": "pi", "commit": "5b8f62a"}, "is not DEPLOYED_COMMIT"),
    ],
)
def test_refuses_unless_the_marker_names_this_host_and_commit(
    tmp_path: Path, marker: dict[str, str] | None, reason: str
) -> None:
    if marker is not None:
        _master(tmp_path, marker["host"], marker["commit"])
    fake = FakeHost([50])

    assert Loop(_config(tmp_path), fake.host()).run() == 2
    assert fake.commands == []
    assert reason in _progress(tmp_path)


def test_same_commit_accepts_abbreviations_only() -> None:
    assert same_commit("87108bb", "87108bb1234")
    assert not same_commit("87108bb", "87108bc")
    assert not same_commit("", "87108bb")
    assert not same_commit("871", "87108bb")


def test_pi_commands_run_in_the_worker_against_the_master(tmp_path: Path) -> None:
    config = _config(tmp_path)
    fetch, env = cli_command(
        config, FETCH, ["--limit", "50", "--render"], render=True, name="007-fetch"
    )
    extract, _ = cli_command(config, EXTRACT, [], render=False, name="007-extract")

    assert env is None
    assert fetch[:3] == ["docker", "compose", "-f"] and "worker" in fetch
    worker = fetch.index("worker")
    assert fetch[worker - 2 : worker] == ["--name", f"{CONTAINER_PREFIX}007-fetch"]
    assert fetch[worker + 1 : worker + 3] == ["xvfb-run", "-a"]
    assert fetch[worker + 3 :] == [
        *("python", "-m", "apps.menu_pipeline.with_db", "helios_work"),
        *("-m", FETCH, "--limit", "50", "--render"),
    ]
    assert "xvfb-run" not in extract


def test_laptop_commands_use_uv_and_the_data_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
    data = tmp_path / "data"
    config = _config(tmp_path, host="laptop", data_dir=data)

    fetch, env = cli_command(
        config, FETCH, ["--limit", "50", "--render"], render=True, name="001-fetch"
    )

    assert "--name" not in fetch
    assert fetch[:6] == ["xvfb-run", "-a", "uv", "run", "--extra", "menu"]
    assert f"{data}/.env" in fetch
    assert fetch[-6:] == [
        *("--base-dir", str(data), "--model-root", f"{data}/var/models"),
        *("--cache-dir", f"{data}/var/site-cache"),
    ]
    assert env is not None and "WAYLAND_DISPLAY" not in env and env["PYTHONPATH"] == "."


def test_laptop_waits_for_the_gpu_to_cool_between_batches(tmp_path: Path) -> None:
    _master(tmp_path, "laptop")
    fake = FakeHost([3], gpu=[PAUSE_AT + 2, PAUSE_AT, COOL_TO + 1, COOL_TO - 1])
    config = _config(tmp_path, host="laptop", phase="fetch")

    assert Loop(config, fake.host()).run() == 0
    assert len(fake.sleeps) == 2
    assert f"waiting for < {COOL_TO}" in _progress(tmp_path)


def test_pi_never_pauses_for_heat(tmp_path: Path) -> None:
    _master(tmp_path)
    fake = FakeHost([3], gpu=[120] * 5)

    Loop(_config(tmp_path), fake.host()).run()

    assert fake.sleeps == [] and fake.docker_calls == []
    assert "SoC=60.0C" in _progress(tmp_path)


def test_gpu_watch_band() -> None:
    watch = GpuWatch()
    readings = [PAUSE_AT, PAUSE_AT + 1, PAUSE_AT + 3, RESUME_AT, RESUME_AT - 1, None, PAUSE_AT + 1]
    assert [watch.step(t) for t in readings] == [
        None,
        "pause",
        None,
        None,
        "unpause",
        None,
        "pause",
    ]


def test_gpu_watch_phase_pauses_and_unpauses_on_stop(tmp_path: Path) -> None:
    stop = tmp_path / "var" / "pipeline-host" / "STOP"
    fake = FakeHost(gpu=[PAUSE_AT + 1], on_sleep=stop)
    config = _config(tmp_path, host="laptop", phase="gpu-watch", llama_container="llama")

    assert Loop(config, fake.host()).run() == 0
    assert fake.docker_calls == [("pause", "llama"), ("unpause", "llama")]
    assert fake.commands == []


def test_gpu_watch_is_refused_on_the_pi(tmp_path: Path) -> None:
    assert Loop(_config(tmp_path, phase="gpu-watch"), FakeHost().host()).run() == 2


def test_fetch_done_needs_a_count() -> None:
    assert fetch_done({"fetched": 49}, 50)
    assert not fetch_done({"fetched": 50}, 50)
    assert not fetch_done({}, 50), "no summary (a crash) is not done"


def test_arguments_protect_the_public_database() -> None:
    with pytest.raises(SystemExit):
        parse_args(["--host", "pi", "--db", "helios"])
    with pytest.raises(SystemExit):
        parse_args(["--host", "pi", "--data-dir", "/elsewhere"])
    assert parse_args(["--host", "laptop", "--data-dir", "/srv"]).data_dir == Path("/srv")


def test_the_loop_parses_as_python_3_10() -> None:
    """The Pi runs it with its system python3 (3.10); the repo targets 3.12."""
    source = Path(batch_loop.__file__).read_text(encoding="utf-8")
    ast.parse(source, feature_version=(3, 10))
    assert "datetime.UTC" not in source and "from datetime import UTC" not in source
