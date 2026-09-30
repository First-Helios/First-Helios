"""Durable replay bundles for ``menu-page`` Captures (ADR-0013 §5).

A bundle holds what one fetch or render read: the raw response body (the bytes
the Capture's ``content_hash`` hashes; none for a render), the rendered DOM if a
browser produced the page, and the segmented blocks the pipeline reads. It is
gzipped canonical JSON at ``var/replay/menu-page/<yyyy>/<mm>/<sha256>.json.gz``,
named by the sha256 of its uncompressed bytes, so an identical re-read shares
one file and a file is never rewritten. That path is the Capture's
``bundle_path``, relative to the deploy directory (``var/`` is a host bind
mount on the Pi). Unlike the 7-day fetch cache, bundles are evidence: nothing
prunes them before Phase 8 backup (owner decision S6).

A Capture-targeted Evidence locator (``blocks:<segmenter>:<block>[<s>:<e>]``)
can be checked from the bundle alone: :func:`excerpt` returns the span and
:func:`~packages.helios_core.provenance.validation.capture_excerpt_hash` its hash.
"""

from __future__ import annotations

import base64
import gzip
import hashlib
import json
import os
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any

from packages.helios_core.provenance.validation import parse_capture_locator
from packages.helios_parsing.segment import Block

if TYPE_CHECKING:
    from datetime import datetime

BUNDLE_FORMAT = "menu-page-bundle-v1"
BUNDLE_PREFIX = PurePosixPath("var/replay/menu-page")


@dataclass(frozen=True, slots=True)
class Bundle:
    """One Capture's replay content."""

    url: str  # the final URL the bytes came from
    content_type: str
    body: bytes | None  # raw response body; None for a render
    rendered_dom: str | None  # the serialized DOM a browser produced
    segmenter: str
    blocks: tuple[Block, ...]

    def to_json(self) -> bytes:
        document: dict[str, Any] = {
            "format": BUNDLE_FORMAT,
            "url": self.url,
            "content_type": self.content_type,
            "body_b64": None if self.body is None else base64.b64encode(self.body).decode("ascii"),
            "rendered_dom": self.rendered_dom,
            "segmenter": self.segmenter,
            "blocks": [asdict(block) for block in self.blocks],
        }
        return json.dumps(
            document, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")

    @classmethod
    def from_json(cls, data: bytes) -> Bundle:
        document = json.loads(data)
        if document.get("format") != BUNDLE_FORMAT:
            raise ValueError(f"not a {BUNDLE_FORMAT} bundle")
        body = document["body_b64"]
        return cls(
            url=str(document["url"]),
            content_type=str(document["content_type"]),
            body=None if body is None else base64.b64decode(body, validate=True),
            rendered_dom=document["rendered_dom"],
            segmenter=str(document["segmenter"]),
            blocks=tuple(Block(**block) for block in document["blocks"]),
        )


class BundleStore:
    """Writes and reads bundles under ``base_dir`` (the deploy directory)."""

    def __init__(self, base_dir: Path) -> None:
        self._base_dir = base_dir

    def write(self, bundle: Bundle, *, fetched_at: datetime) -> str:
        """Store ``bundle`` (once) and return its ``bundle_path``."""
        data = bundle.to_json()
        digest = hashlib.sha256(data).hexdigest()
        relative = BUNDLE_PREFIX / f"{fetched_at:%Y}" / f"{fetched_at:%m}" / f"{digest}.json.gz"
        target = self._base_dir / relative
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp_name = tempfile.mkstemp(dir=target.parent, suffix=".tmp")
            try:
                with os.fdopen(fd, "wb") as handle:
                    handle.write(gzip.compress(data, mtime=0))
                Path(tmp_name).replace(target)
            except BaseException:
                Path(tmp_name).unlink(missing_ok=True)
                raise
        return str(relative)

    def read(self, bundle_path: str) -> Bundle:
        relative = PurePosixPath(bundle_path)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("bundle path must be relative to the deploy directory")
        return Bundle.from_json(gzip.decompress((self._base_dir / relative).read_bytes()))


def excerpt(bundle: Bundle, locator: str) -> str:
    """The text a Capture-targeted locator names in ``bundle``."""
    segmenter, block_id, start, end = parse_capture_locator(locator)
    if segmenter != bundle.segmenter:
        raise ValueError(f"locator cites {segmenter}, the bundle holds {bundle.segmenter}")
    block = next((block for block in bundle.blocks if block.id == block_id), None)
    if block is None or end > len(block.text):
        raise ValueError(f"locator {locator} is not in the bundle")
    return block.text[start:end]
