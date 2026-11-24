"""CLI: the pipeline host's batch loop (ADR-0030 D2). It runs on the host, not in a container::

    python3 -m apps.menu_pipeline.batch_loop --host pi [--phase full] [--db helios_work]
        [--batch 50] [--stop-every 10] [--server URL] [--data-dir DIR]

Standard library only, for Python 3.10 (the Orange Pi's system ``python3``): it starts the
pipeline CLIs, each pointed at the master by ``apps.menu_pipeline.with_db``. ``--host pi``
runs them in the Compose ``worker`` (``infra/docker-compose.pi.yml``); ``--host laptop`` runs
them with ``uv run --extra menu`` from the current directory (a checkout or ``git archive`` of
the run's commit) against the data in ``--data-dir``.

**Phases.** Per batch, ``full`` fetches ``--batch`` due URLs (``run --render`` under
``xvfb-run``) and then extracts every due page; ``fetch`` only fetches. Both end when a fetch
takes fewer URLs than ``--batch`` (P8-23's loop waited for zero and never got there: four
redirecting URLs stayed due). ``extract`` and ``extract-no-model`` run one extraction of every
due page (``extract --no-model``: saved answers only; pages that need the model stay due).
``--server`` points extraction at another ``llama-server``, such as the laptop GPU's over
the LAN. ``gpu-watch`` (laptop only) runs no CLI: it pauses the ``llama-server`` container
while the GPU is hot, for a master on the Pi that uses this laptop's GPU.

**Stops.** Between batches: the ``STOP`` file; every ``--stop-every`` batches ("swap due", 0:
never); a CLI that exits non-zero. Exit 0 for those stops, 1 after a failed CLI, 2 when the
loop refuses to start.

**The master.** The loop refuses to start unless ``var/pipeline-host/MASTER`` names this host
and a ``commit`` that matches ``DEPLOYED_COMMIT`` in the current directory: one database is
written, by one version of the code (``infra/pipeline-host/mark-master.sh`` writes the marker).

**Thermal modes** (owner rules, 2026-11-19 and 2026-11-23). ``pi``: no pause; the SoC is only
logged. ``laptop``: measured on the GPU. Between batches it waits while the GPU is above
:data:`PAUSE_AT` until it is below :data:`COOL_TO`; during a batch it ``docker pause``s the
``llama-server`` container above :data:`PAUSE_AT` and unpauses it below :data:`RESUME_AT`.

Files under ``<data-dir>/var/pipeline-host/``: ``STOP``, ``MASTER``, ``logs/progress.log``
(one line per batch) and each CLI's ``logs/batch-NNN-{fetch,extract}.{out,err}``.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

HOSTS = ("pi", "laptop")
PHASES = ("full", "fetch", "extract", "extract-no-model", "gpu-watch")
PAUSE_AT = 91  # °C on the laptop GPU (owner 2026-11-23)
RESUME_AT = 84
COOL_TO = 81
WATCH_EVERY_S = 10
COOL_EVERY_S = 30
FETCH = "apps.menu_pipeline.run"
EXTRACT = "apps.menu_pipeline.extract"
FETCH_DONE = "menu-page run complete: "
EXTRACT_DONE = "extraction run complete: "
COMPOSE_WORKER = (
    *("docker", "compose", "-f", "infra/docker-compose.yml"),
    *("-f", "infra/docker-compose.pi.yml", "--env-file", ".env"),
    *("--profile", "menu", "run", "--rm", "--no-deps", "-T", "worker"),
)
LAPTOP_ENV_DROP = ("WAYLAND_DISPLAY", "XDG_SESSION_TYPE")  # headed Chromium under xvfb-run
MIN_SHA = 7


@dataclass(frozen=True, slots=True)
class Config:
    host: str
    phase: str
    db: str = "helios_work"
    batch: int = 50
    stop_every: int = 10
    server: str | None = None
    data_dir: Path = Path()
    code_dir: Path = Path()
    llama_container: str = "helios-llama-gpu"

    @property
    def run_dir(self) -> Path:
        return self.data_dir / "var" / "pipeline-host"

    @property
    def logs(self) -> Path:
        return self.run_dir / "logs"


def _run(command: Sequence[str], out: Path, err: Path, env: Mapping[str, str] | None) -> int:
    with out.open("w", encoding="utf-8") as stdout, err.open("w", encoding="utf-8") as stderr:
        return subprocess.run(  # noqa: S603 - the loop's own fixed commands
            list(command), stdout=stdout, stderr=stderr, env=env, check=False
        ).returncode


def soc_temp(root: Path = Path("/sys/class/thermal")) -> float | None:
    """The hottest thermal zone, °C (the Pi's SoC); ``None`` when there is none."""
    temps = []
    for zone in root.glob("thermal_zone*/temp"):
        try:
            temps.append(int(zone.read_text().strip()) / 1000)
        except (OSError, ValueError):
            continue
    return max(temps) if temps else None


def gpu_temp() -> int | None:
    """The laptop GPU's temperature, °C, from ``nvidia-smi``; ``None`` when unreadable."""
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=temperature.gpu", "--format=csv,noheader"],  # noqa: S607 - host tool on PATH
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        ).stdout
        return int(out.split()[0])
    except (OSError, ValueError, IndexError, subprocess.TimeoutExpired):
        return None


def utc_now() -> datetime:
    return datetime.now(timezone.utc)  # noqa: UP017 - Python 3.10 on the Pi


def docker(action: str, container: str) -> None:
    """``docker pause`` / ``unpause`` a container, ignoring a failure (logged by the caller)."""
    subprocess.run(  # noqa: S603 - fixed docker verbs
        ["docker", action, container],  # noqa: S607 - host tool on PATH
        capture_output=True,
        check=False,
    )


@dataclass(slots=True)
class Host:
    """What the loop reaches outside itself; tests replace every part.

    ``run(command, stdout file, stderr file, environment or None to inherit)`` returns the
    exit status.
    """

    run: Callable[[Sequence[str], Path, Path, Mapping[str, str] | None], int] = _run
    soc: Callable[[], float | None] = soc_temp
    gpu: Callable[[], int | None] = gpu_temp
    docker: Callable[[str, str], None] = docker
    sleep: Callable[[float], None] = time.sleep
    now: Callable[[], datetime] = utc_now


class GpuWatch:
    """Pause above :data:`PAUSE_AT`, unpause below :data:`RESUME_AT` (a hysteresis band)."""

    def __init__(self) -> None:
        self.paused = False

    def step(self, temp: int | None) -> str | None:
        """The docker action this reading calls for: ``pause``, ``unpause`` or ``None``."""
        if temp is None:
            return None
        if not self.paused and temp > PAUSE_AT:
            self.paused = True
            return "pause"
        if self.paused and temp < RESUME_AT:
            self.paused = False
            return "unpause"
        return None


def last_summary(path: Path, prefix: str) -> dict[str, object]:
    """The last ``<prefix><json>`` line a CLI printed; ``{}`` when none."""
    found: dict[str, object] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return found
    for line in lines:
        if line.startswith(prefix):
            try:
                found = json.loads(line[len(prefix) :])
            except json.JSONDecodeError:
                continue
    return found


def fetch_done(summary: Mapping[str, object], batch: int) -> bool:
    """A fetch that took fewer URLs than the batch leaves nothing due worth another batch."""
    fetched = summary.get("fetched")
    return isinstance(fetched, int) and fetched < batch


def _compact(value: object) -> str:
    return json.dumps(value, separators=(",", ":"))


def progress(fetch: Mapping[str, object], extract: Mapping[str, object]) -> str:
    """One progress line's counts (P8-23's ``summarize.py``)."""
    parts = []
    if fetch:
        parts.append(
            " ".join(
                f"{name}={fetch.get(key)}"
                for name, key in (
                    ("fetched", "fetched"),
                    ("not_due", "not_due"),
                    ("renders", "renders"),
                    ("new", "versions_new"),
                    ("changed", "versions_changed"),
                    ("unchanged", "unchanged"),
                )
            )
            + f" outcomes={_compact(fetch.get('outcomes', {}))}"
        )
    if extract:
        extracted = extract.get("extracted")
        reused = extract.get("reused_outputs")
        model_pages = (
            extracted - reused if isinstance(extracted, int) and isinstance(reused, int) else None
        )
        line = (
            f"due={extract.get('due')} extracted={extracted} reused={reused} "
            f"model_pages={model_pages} chunks={extract.get('chunks')} "
            f"reused_chunks={extract.get('reused_chunks')} "
            f"failed={_compact(extract.get('failed', {}))} prices={extract.get('prices_written')} "
            f"pages_per_hour={extract.get('pages_per_hour')}"
        )
        if "refused_chunk_calls" in extract:
            line += f" refused_chunk_calls={extract['refused_chunk_calls']}"
        parts.append(line)
    return " | ".join(parts)


def read_marker(path: Path) -> dict[str, str] | None:
    """``key=value`` lines of the ``MASTER`` marker; ``None`` when it is missing."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    marker = {}
    for line in lines:
        key, sep, value = line.partition("=")
        if sep:
            marker[key.strip()] = value.strip()
    return marker


def same_commit(a: str, b: str) -> bool:
    """Equal SHAs, either possibly abbreviated (at least :data:`MIN_SHA` characters)."""
    if min(len(a), len(b)) < MIN_SHA:
        return False
    return a.startswith(b) or b.startswith(a)


def master_refusal(config: Config) -> str | None:
    """Why this host may not write the master, or ``None`` when it may."""
    marker_path = config.run_dir / "MASTER"
    marker = read_marker(marker_path)
    if marker is None:
        return f"no {marker_path}: this host is not the master (infra/pipeline-host/mark-master.sh)"
    if marker.get("host") != config.host:
        return f"{marker_path} names host {marker.get('host')!r}, not {config.host!r}"
    try:
        deployed = (config.code_dir / "DEPLOYED_COMMIT").read_text(encoding="utf-8").strip()
    except OSError:
        return f"no {config.code_dir / 'DEPLOYED_COMMIT'}: the code's commit is unknown"
    if not same_commit(marker.get("commit", ""), deployed):
        return f"MASTER commit {marker.get('commit')!r} is not DEPLOYED_COMMIT {deployed!r}"
    return None


def cli_command(
    config: Config, module: str, args: Sequence[str], *, render: bool
) -> tuple[list[str], dict[str, str] | None]:
    """The command (and environment, ``None`` to inherit) that runs one pipeline CLI."""
    inner = ["python", "-m", "apps.menu_pipeline.with_db", config.db, "-m", module, *args]
    xvfb = ["xvfb-run", "-a"] if render else []
    if config.host == "pi":
        return [*COMPOSE_WORKER, *xvfb, *inner], None
    data = str(config.data_dir)
    paths = ["--base-dir", data, "--model-root", f"{data}/var/models"]
    if module == FETCH:
        paths += ["--cache-dir", f"{data}/var/site-cache"]
    env = {k: v for k, v in os.environ.items() if k not in LAPTOP_ENV_DROP}
    env["PYTHONPATH"] = "."
    uv = ["uv", "run", "--extra", "menu", "--env-file", f"{data}/.env"]
    return [*xvfb, *uv, *inner, *paths], env


class Loop:
    def __init__(self, config: Config, host: Host | None = None) -> None:
        self.config = config
        self.host = host or Host()
        self.watch = GpuWatch()

    # -- output -------------------------------------------------------------------------
    def log(self, message: str) -> None:
        stamp = self.host.now().strftime("%Y-%m-%dT%H:%M:%SZ")
        line = f"{stamp} {message}"
        with (self.config.logs / "progress.log").open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
        print(line, flush=True)  # noqa: T201 - CLI output

    def temps(self) -> str:
        if self.config.host == "pi":
            return f"SoC={self.host.soc()}C"
        return f"GPU={self.host.gpu()}C CPU={self.host.soc()}C"

    # -- thermal (laptop only) ----------------------------------------------------------
    def cool(self) -> None:
        if self.config.host != "laptop":
            return
        temp = self.host.gpu()
        if temp is None or temp <= PAUSE_AT:
            return
        self.log(f"GPU {temp} C > {PAUSE_AT}: waiting for < {COOL_TO}")
        while (temp := self.host.gpu()) is not None and temp >= COOL_TO:
            self.host.sleep(COOL_EVERY_S)
        self.log(f"GPU {temp} C: resuming")

    def watch_step(self) -> None:
        temp = self.host.gpu()
        action = self.watch.step(temp)
        if action is not None:
            self.host.docker(action, self.config.llama_container)
            self.log(f"watchdog: GPU {temp} C, llama-server {action}d")

    def _watchdog(self, stop: threading.Event) -> None:
        while not stop.wait(WATCH_EVERY_S):
            self.watch_step()

    # -- one CLI ------------------------------------------------------------------------
    def cli(self, batch: str, step: str, module: str, args: Sequence[str]) -> tuple[int, float]:
        command, env = cli_command(self.config, module, args, render=module == FETCH)
        out = self.config.logs / f"batch-{batch}-{step}.out"
        err = self.config.logs / f"batch-{batch}-{step}.err"
        started = time.monotonic()
        status = self.host.run(command, out, err, env)
        return status, time.monotonic() - started

    def extract_args(self) -> list[str]:
        args = ["--no-model"] if self.config.phase == "extract-no-model" else []
        if self.config.server is not None and self.config.phase != "extract-no-model":
            args += ["--server", self.config.server]
        return args

    # -- the loop -----------------------------------------------------------------------
    def stop_requested(self) -> bool:
        if (self.config.run_dir / "STOP").exists():
            self.log("STOP file: stopping between batches")
            return True
        return False

    def run(self) -> int:
        config = self.config
        config.logs.mkdir(parents=True, exist_ok=True)
        if config.phase == "gpu-watch":
            return self.gpu_watch()
        refusal = master_refusal(config)
        if refusal is not None:
            self.log(f"refused: {refusal}")
            return 2
        batches = len(list(config.logs.glob("batch-*-fetch.out"))) + len(
            list(config.logs.glob("batch-*-extract-only.out"))
        )
        self.log(
            f"loop start: host {config.host}, phase {config.phase}, db {config.db}, "
            f"master {read_marker(config.run_dir / 'MASTER')}, batches already logged {batches}"
        )
        stop = threading.Event()
        watchdog = None
        if config.host == "laptop" and config.phase != "fetch":
            watchdog = threading.Thread(target=self._watchdog, args=(stop,), daemon=True)
            watchdog.start()
        try:
            if config.phase in {"extract", "extract-no-model"}:
                status = self.extract_only(batches + 1)
            else:
                status = self.batches(batches)
        finally:
            stop.set()
            if self.watch.paused:
                self.host.docker("unpause", config.llama_container)
        self.log("loop end")
        return status

    def extract_only(self, number: int) -> int:
        if self.stop_requested():
            return 0
        batch = f"{number:03d}"
        self.cool()
        status, seconds = self.cli(batch, "extract-only", EXTRACT, self.extract_args())
        summary = last_summary(self.config.logs / f"batch-{batch}-extract-only.out", EXTRACT_DONE)
        self.log(
            f"batch {batch} {self.config.phase} exit={status} s={seconds:.0f} "
            f"{progress({}, summary)} {self.temps()}"
        )
        return 0 if status == 0 else 1

    def batches(self, logged: int) -> int:
        config = self.config
        done_here = 0
        number = logged
        while not self.stop_requested():
            number += 1
            batch = f"{number:03d}"
            self.cool()
            fetch_status, fetch_s = self.cli(
                batch, "fetch", FETCH, ["--limit", str(config.batch), "--render"]
            )
            fetch = last_summary(config.logs / f"batch-{batch}-fetch.out", FETCH_DONE)
            extract: dict[str, object] = {}
            extract_status, extract_s = 0, 0.0
            if config.phase == "full" and fetch_status == 0:
                self.cool()
                extract_status, extract_s = self.cli(batch, "extract", EXTRACT, self.extract_args())
                extract = last_summary(config.logs / f"batch-{batch}-extract.out", EXTRACT_DONE)
            self.log(
                f"batch {batch} {config.phase} fetch_exit={fetch_status} "
                f"extract_exit={extract_status} fetch_s={fetch_s:.0f} extract_s={extract_s:.0f} "
                f"{progress(fetch, extract)} {self.temps()}"
            )
            if fetch_status != 0 or extract_status != 0:
                self.log(f"batch {batch}: a CLI failed, stopping (see logs/batch-{batch}-*.err)")
                return 1
            if fetch_done(fetch, config.batch):
                self.log(f"fetched {fetch.get('fetched')} < {config.batch}: nothing left, done")
                return 0
            done_here += 1
            if config.stop_every and done_here % config.stop_every == 0:
                self.log(f"{done_here} batches: swap due, stopping")
                return 0
        return 0

    def gpu_watch(self) -> int:
        if self.config.host != "laptop":
            self.log("refused: gpu-watch is for --host laptop")
            return 2
        self.log(f"gpu-watch start: container {self.config.llama_container}")
        try:
            while not self.stop_requested():
                self.watch_step()
                self.host.sleep(WATCH_EVERY_S)
        finally:
            if self.watch.paused:
                self.host.docker("unpause", self.config.llama_container)
        self.log("gpu-watch end")
        return 0


def parse_args(argv: Sequence[str] | None = None) -> Config:
    parser = argparse.ArgumentParser(
        prog="python3 -m apps.menu_pipeline.batch_loop",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--host", choices=HOSTS, required=True)
    parser.add_argument("--phase", choices=PHASES, default="full")
    parser.add_argument("--db", default="helios_work", help="the master database")
    parser.add_argument("--batch", type=int, default=50, help="URLs fetched per batch")
    parser.add_argument("--stop-every", type=int, default=10, help="batches per swap; 0: never")
    parser.add_argument("--server", help="llama-server base URL for extraction")
    parser.add_argument("--data-dir", type=Path, default=Path(), help="deploy dir (.env, var/)")
    parser.add_argument("--llama-container", default="helios-llama-gpu", help="laptop only")
    args = parser.parse_args(argv)
    if args.db == "helios":
        parser.error("the public database is written only by a swap (ADR-0030 D1)")
    if args.host == "pi" and args.data_dir.resolve() != Path().resolve():
        parser.error("--host pi runs in the deploy directory (the worker mounts its var/)")
    if args.batch < 1 or args.stop_every < 0:
        parser.error("--batch must be positive and --stop-every not negative")
    return Config(
        host=args.host,
        phase=args.phase,
        db=args.db,
        batch=args.batch,
        stop_every=args.stop_every,
        server=args.server,
        data_dir=args.data_dir,
        llama_container=args.llama_container,
    )


def main(argv: Sequence[str] | None = None) -> None:
    sys.exit(Loop(parse_args(argv)).run())


if __name__ == "__main__":
    main()
