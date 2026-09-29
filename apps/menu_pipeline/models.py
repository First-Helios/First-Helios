"""Checksum-pinned model files (ADR-0013 §3): manifest, verification and download.

The manifest (``config/models.yaml``) lists each model's source, revision,
licence and every file's sha256 and size. Files live in ``var/models/<name>/``,
never in an image. :func:`verified_model_dir` refuses a directory whose files
differ from the manifest, so a worker never runs a model it can't identify::

    python -m apps.menu_pipeline.models download [--root var/models] [NAME ...]
"""

from __future__ import annotations

import argparse
import hashlib
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

import httpx
import yaml

MANIFEST_PATH = Path(__file__).resolve().parents[2] / "config" / "models.yaml"
DEFAULT_ROOT = Path("var/models")
_CHUNK = 1 << 20


class ModelFileError(RuntimeError):
    """A model file is missing or differs from the manifest."""


@dataclass(frozen=True, slots=True)
class ModelFile:
    name: str
    sha256: str
    size: int


@dataclass(frozen=True, slots=True)
class ModelSpec:
    name: str
    embedding_model: str
    source: str
    revision: str
    licence: str
    files: tuple[ModelFile, ...]

    def url(self, file: ModelFile) -> str:
        return f"{self.source}/resolve/{self.revision}/{file.name}"


def load_manifest(path: Path = MANIFEST_PATH) -> dict[str, ModelSpec]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{path}: expected a mapping of model names")
    specs: dict[str, ModelSpec] = {}
    for name, entry in raw.items():
        files = tuple(
            ModelFile(str(file), str(meta["sha256"]), int(meta["size"]))
            for file, meta in dict(entry["files"]).items()
        )
        specs[str(name)] = ModelSpec(
            name=str(name),
            embedding_model=str(entry["embedding_model"]),
            source=str(entry["source"]).rstrip("/"),
            revision=str(entry["revision"]),
            licence=str(entry["licence"]),
            files=files,
        )
    return specs


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def verified_model_dir(spec: ModelSpec, root: Path = DEFAULT_ROOT) -> Path:
    """``root/<name>`` when every manifest file is present with its size and sha256."""
    directory = root / spec.name
    for file in spec.files:
        path = directory / file.name
        if not path.is_file():
            raise ModelFileError(
                f"{path} is missing; run `python -m apps.menu_pipeline.models download`"
            )
        if path.stat().st_size != file.size or _sha256(path) != file.sha256:
            raise ModelFileError(f"{path} does not match config/models.yaml")
    return directory


def download(spec: ModelSpec, root: Path = DEFAULT_ROOT, *, client: httpx.Client) -> Path:
    """Fetch each missing or wrong file; keep a file only if its checksum matches."""
    directory = root / spec.name
    directory.mkdir(parents=True, exist_ok=True)
    for file in spec.files:
        target = directory / file.name
        if target.is_file() and _sha256(target) == file.sha256:
            continue
        digest = hashlib.sha256()
        fd, tmp_name = tempfile.mkstemp(dir=directory, suffix=".part")
        tmp = Path(tmp_name)
        try:
            with (
                os.fdopen(fd, "wb") as handle,
                client.stream("GET", spec.url(file), follow_redirects=True) as response,
            ):
                response.raise_for_status()
                for chunk in response.iter_bytes(_CHUNK):
                    digest.update(chunk)
                    handle.write(chunk)
            if digest.hexdigest() != file.sha256:
                raise ModelFileError(f"{spec.url(file)} does not match config/models.yaml")
            tmp.chmod(0o644)  # mkstemp's 0600 would hide it from the worker's user
            tmp.replace(target)
        finally:
            tmp.unlink(missing_ok=True)
    return verified_model_dir(spec, root)


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m apps.menu_pipeline.models")
    parser.add_argument("command", choices=["download", "verify"])
    parser.add_argument("names", nargs="*", help="model names (default: all in the manifest)")
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    args = parser.parse_args()
    manifest = load_manifest()
    names = args.names or sorted(manifest)
    with httpx.Client(timeout=60.0) as client:
        for name in names:
            spec = manifest[name]
            path = (
                download(spec, args.root, client=client)
                if args.command == "download"
                else verified_model_dir(spec, args.root)
            )
            print(f"{name}: ok ({path})")  # noqa: T201 - CLI output


if __name__ == "__main__":
    main()
