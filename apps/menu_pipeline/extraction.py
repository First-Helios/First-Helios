"""Extraction over ``menu-page`` Versions: chunks → llama-server → repairs → validator → Menu.

ADR-0013 implementation slice 5 (session P5-4). For each due Version
(:func:`~apps.menu_pipeline.menu_writes.due_pages`), from its Capture's bundle
(no refetch):

1. **Extract.** The page's chunks go to ``llama-server`` (:mod:`.llama_client`),
   :data:`~apps.menu_pipeline.llama_client.SLOTS` requests in flight over a
   look-ahead of pages, as the spike measured throughput (X3). The raw answers
   are saved content-addressed (:class:`OutputStore`) before anything is
   written, keyed by the extractor's inputs (model file, prompt, chunking,
   segmenter) and the page's text hash: a page whose answers are already saved
   is not sent again. So a repairs, validator or classifier bump re-validates
   saved answers in minutes, and only a model, prompt, chunking or segmenter
   bump runs the model again (X2).
2. **Validate.** The answers are parsed, repaired and stitched
   (``output.rows_of``), and validator v3 decides every row; the page's
   schema.org JSON-LD goes through the same validator (§1).
3. **Write.** Per page, the Evidence its nodes cite is committed first (Menu
   admission accepts only committed input), then in one transaction the ``llm``
   page aggregate and, when
   JSON-LD has (or had) items, the ``jsonld`` one (:mod:`.menu_writes`). A
   page whose scope is not eligible yet is counted ``scope_not_eligible`` and
   stays due (Amendment 3).

A chunk that still fails after its retry fails its page: nothing is written,
the page stays due and is retried next run; after
:data:`MAX_CONSECUTIVE_FAILURES` failed pages in a row the run stops (the
server is likely gone) and says so.

**Pipeline version** (X2): ``method_version`` names every component of the
interpretation (:class:`PipelineVersion`); a page is up to date when its
``llm`` head is on the record's latest Version with exactly this string.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import re
import tempfile
import time
from collections import Counter, deque
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from decimal import ROUND_HALF_EVEN, Decimal
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Protocol

from apps.menu_pipeline.llama_client import SLOTS, ChunkFailed, ChunkResult
from apps.menu_pipeline.menu_writes import (
    due_pages,
    head_has_items,
    record_span_evidence,
    write_page,
)
from packages.helios_core.identity.contracts import SubjectNotEligibleError
from packages.helios_parsing.chunking import CHUNKER_VERSION, chunks
from packages.helios_parsing.jsonld import JSONLD_VERSION, menu_items, validator_rows
from packages.helios_parsing.menu_shape import shape
from packages.helios_parsing.output import REPAIRS_VERSION, parse_output, rows_of
from packages.helios_parsing.prompt import PROMPT_VERSION
from packages.helios_parsing.segment import SEGMENTER_VERSION, text_hash
from packages.helios_parsing.validator import VALIDATOR_VERSION, validate

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from sqlalchemy.orm import Session

    from apps.menu_pipeline.bundle import Bundle, BundleStore
    from apps.menu_pipeline.menu_writes import DuePage
    from apps.menu_pipeline.models import ModelSpec
    from packages.helios_core.domains.menu.contracts import SourceKind
    from packages.helios_parsing.validator import Validation

OUTPUT_FORMAT = "menu-extract-v1"
OUTPUT_PREFIX = PurePosixPath("var/replay/menu-extract")
LOOKAHEAD = 2  # pages whose chunks are queued behind the one being finished
MAX_CONSECUTIVE_FAILURES = 3
_METHOD_VERSION_MAX = 128  # menu_page.method_version


class ChunkExtractor(Protocol):
    """What the run needs from :class:`~apps.menu_pipeline.llama_client.LlamaClient`."""

    def extract_chunk(self, chunk: str) -> ChunkResult: ...


class PageScorer(Protocol):
    """The page classifier: its name (a pipeline-version part) and its probability."""

    @property
    def name(self) -> str: ...

    def probability(self, html: str, url: str) -> float: ...


def model_tag(spec: ModelSpec) -> str:
    """``<manifest name>@<sha256 prefix>`` of the extraction model's single file."""
    (file,) = spec.files
    return f"{spec.name.lower()}@{file.sha256[:12]}"


@dataclass(frozen=True, slots=True)
class PipelineVersion:
    """The components of an interpretation; their strings are ``method_version``."""

    model: str  # model_tag()
    classifier: str  # the page classifier's name (page confidence)

    @property
    def extractor(self) -> str:
        """What the model's answers depend on: the key of saved raw outputs."""
        return f"{self.model};{PROMPT_VERSION};{CHUNKER_VERSION};{SEGMENTER_VERSION}"

    @property
    def llm(self) -> str:
        return _checked(f"{self.extractor};{REPAIRS_VERSION};{VALIDATOR_VERSION};{self.classifier}")

    @property
    def jsonld(self) -> str:
        return _checked(
            f"{JSONLD_VERSION};{VALIDATOR_VERSION};{SEGMENTER_VERSION};{self.classifier}"
        )


def _checked(version: str) -> str:
    if len(version) > _METHOD_VERSION_MAX:
        raise ValueError(f"method_version longer than {_METHOD_VERSION_MAX}: {version}")
    return version


class OutputStore:
    """Raw extractor answers per (extractor version, text hash), under ``base_dir``.

    ``var/replay/menu-extract/<sha256(extractor)[:16]>/<text hash>.json.gz``: one
    record per page text, in the harness's format (``{"chunks": [{"raw": …}]}``),
    so ``apps.menu_pipeline.evaluate`` can score what production extracted.
    Written only when every chunk answered; never rewritten.
    """

    def __init__(self, base_dir: Path) -> None:
        self._base_dir = base_dir

    def _path(self, extractor: str, page_text_hash: str) -> Path:
        folder = hashlib.sha256(extractor.encode("utf-8")).hexdigest()[:16]
        digest = page_text_hash.removeprefix("sha256:")
        return self._base_dir / OUTPUT_PREFIX / folder / f"{digest}.json.gz"

    def read(self, extractor: str, page_text_hash: str) -> list[str] | None:
        """The saved raw answers, one per chunk, or ``None``."""
        path = self._path(extractor, page_text_hash)
        if not path.is_file():
            return None
        record = json.loads(gzip.decompress(path.read_bytes()))
        if record.get("format") != OUTPUT_FORMAT or record.get("extractor") != extractor:
            raise ValueError(f"{path} is not a {OUTPUT_FORMAT} record for {extractor}")
        return [str(chunk["raw"]) for chunk in record["chunks"]]

    def write(self, extractor: str, page_text_hash: str, results: Sequence[ChunkResult]) -> None:
        path = self._path(extractor, page_text_hash)
        if path.exists():
            return
        record = {
            "format": OUTPUT_FORMAT,
            "extractor": extractor,
            "text_hash": page_text_hash,
            "chunks": [result.record() for result in results],
        }
        data = json.dumps(record, sort_keys=True, ensure_ascii=False).encode("utf-8")
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(gzip.compress(data, mtime=0))
            Path(tmp_name).replace(path)
        except BaseException:
            Path(tmp_name).unlink(missing_ok=True)
            raise


@dataclass(slots=True)
class SocProbe:
    """SoC temperature and frequency cap, read when the host exposes them (ADR-0013 §3).

    ``max_temp_c`` is the hottest thermal zone seen; ``freq_cap`` the lowest
    ``scaling_max_freq / cpuinfo_max_freq`` over CPUs (below 1.0 = throttled or
    capped). Both stay ``None`` where ``/sys`` doesn't have them.
    """

    root: Path = Path("/sys")
    max_temp_c: float | None = None
    freq_cap: float | None = None

    def sample(self) -> None:
        for zone in self.root.glob("class/thermal/thermal_zone*/temp"):
            try:
                celsius = int(zone.read_text().strip()) / 1000
            except (OSError, ValueError):
                continue
            self.max_temp_c = max(celsius, self.max_temp_c or celsius)
        for cpu in self.root.glob("devices/system/cpu/cpu[0-9]*/cpufreq"):
            try:
                ratio = int((cpu / "scaling_max_freq").read_text()) / int(
                    (cpu / "cpuinfo_max_freq").read_text()
                )
            except (OSError, ValueError, ZeroDivisionError):
                continue
            self.freq_cap = min(ratio, self.freq_cap or ratio)


@dataclass(slots=True)
class ExtractionReport:
    """Counts from one extraction run (pages unless named otherwise)."""

    method_version: str = ""
    due: int = 0
    due_by_reason: Counter[str] = field(default_factory=Counter)  # new / changed / reinterpret
    up_to_date: int = 0
    needs_review: int = 0  # records not resolved to a scope
    no_bundle: int = 0
    attempted: int = 0  # pages taken this run (``--limit`` counts these)
    extracted: int = 0  # pages written (an llm page, maybe a jsonld one)
    reused_outputs: int = 0  # pages validated from saved answers, no model call
    empty: int = 0  # llm pages with no item
    flagged: int = 0  # pages with unlabeled_price_runs
    jsonld_pages: int = 0
    scope_not_eligible: int = 0
    failed: Counter[str] = field(default_factory=Counter)  # chunk_failed, bundle_*
    aborted: bool = False
    chunks: int = 0  # chunks sent to the model
    sparse_retries: int = 0
    truncated_chunks: int = 0
    resent_requests: int = 0
    rows: Counter[str] = field(default_factory=Counter)  # "<kind>:<decision>[:<reason>]"
    items_written: int = 0
    prices_written: int = 0
    unsectioned_items: int = 0  # stored, not projected to Gold (no native key)
    wall_s: float = 0.0
    soc_max_temp_c: float | None = None
    cpu_freq_cap: float | None = None

    def summary(self) -> dict[str, object]:
        out: dict[str, object] = {}
        for name in self.__dataclass_fields__:
            value = getattr(self, name)
            out[name] = dict(sorted(value.items())) if isinstance(value, Counter) else value
        out["wall_s"] = round(self.wall_s, 1)
        hours = self.wall_s / 3600
        out["pages_per_hour"] = round(self.extracted / hours, 2) if hours > 0 else None
        return out


@dataclass(slots=True)
class _Pending:
    due: DuePage
    bundle: Bundle | None = None
    failure: str | None = None
    saved: list[str] | None = None
    futures: list[Future[ChunkResult]] = field(default_factory=list)


def _charset(content_type: str) -> str:
    match = re.search(r"charset=([\w.-]+)", content_type, re.IGNORECASE)
    return match.group(1) if match else "utf-8"


def page_html(bundle: Bundle) -> str:
    """The page text the classifier and the JSON-LD reader read: the render, else the body."""
    if bundle.rendered_dom is not None:
        return bundle.rendered_dom
    body = bundle.body or b""
    try:
        return body.decode(_charset(bundle.content_type), errors="replace")
    except LookupError:  # an unknown charset in the Content-Type header
        return body.decode("utf-8", errors="replace")


def _confidence(probability: float) -> Decimal:
    value = Decimal(repr(min(max(probability, 0.0), 1.0)))
    return value.quantize(Decimal("0.0001"), rounding=ROUND_HALF_EVEN)


def _count_rows(report: ExtractionReport, kind: str, validation: Validation) -> None:
    for verdict in validation.verdicts:
        reason = (
            f":{verdict.reasons[0]}" if verdict.decision != "accept" and verdict.reasons else ""
        )
        report.rows[f"{kind}:{verdict.decision}{reason}"] += 1


class _Run:
    def __init__(  # noqa: PLR0913 - the run's collaborators, injected for tests
        self,
        session: Session,
        *,
        extractor: ChunkExtractor,
        scorer: PageScorer,
        bundles: BundleStore,
        outputs: OutputStore,
        version: PipelineVersion,
        report: ExtractionReport,
        on_commit: Callable[[], None] | None,
        soc: SocProbe,
    ) -> None:
        self._session = session
        self._extractor = extractor
        self._scorer = scorer
        self._bundles = bundles
        self._outputs = outputs
        self._version = version
        self._report = report
        self._on_commit = on_commit
        self._soc = soc
        self._consecutive_failures = 0

    def start(self, due: DuePage, pool: ThreadPoolExecutor) -> _Pending:
        pending = _Pending(due)
        try:
            pending.bundle = self._bundles.read(due.bundle_path)
        except (OSError, ValueError):
            pending.failure = "bundle_unreadable"
            return pending
        blocks = list(pending.bundle.blocks)
        if text_hash(blocks) != due.text_hash:
            pending.failure = "bundle_mismatch"  # the bundle isn't the Version's text
            return pending
        pending.saved = self._outputs.read(self._version.extractor, due.text_hash)
        if pending.saved is None:
            pending.futures = [
                pool.submit(self._extractor.extract_chunk, c) for c in chunks(blocks)
            ]
        return pending

    def finish(self, pending: _Pending) -> None:
        report = self._report
        if pending.failure is not None or pending.bundle is None:
            report.failed[pending.failure or "bundle_unreadable"] += 1
            return
        due, bundle = pending.due, pending.bundle
        if pending.saved is not None:
            raws = pending.saved
            report.reused_outputs += 1
        else:
            try:
                results = [future.result() for future in pending.futures]
            except ChunkFailed:
                for future in pending.futures:
                    future.cancel()
                report.failed["chunk_failed"] += 1
                self._consecutive_failures += 1
                return
            for result in results:
                report.chunks += 1
                report.sparse_retries += result.first is not None
                report.truncated_chunks += result.truncated
                report.resent_requests += result.resent
            self._outputs.write(self._version.extractor, due.text_hash, results)
            raws = [result.attempt.raw for result in results]
        self._consecutive_failures = 0
        self._write(due, bundle, raws)
        self._soc.sample()

    def _write(self, due: DuePage, bundle: Bundle, raws: list[str]) -> None:
        report = self._report
        blocks = list(bundle.blocks)
        html = page_html(bundle)
        llm = validate(blocks, rows_of([parse_output(raw) for raw in raws], blocks))
        streams: list[tuple[SourceKind, Validation]] = [("llm", llm)]
        jsonld_rows = validator_rows(menu_items(html))
        if jsonld_rows or head_has_items(self._session, due.source_record_id, "jsonld"):
            streams.append(("jsonld", validate(blocks, jsonld_rows)))
        shapes = [shape(blocks, validation.verdicts) for _, validation in streams]
        confidence = _confidence(self._scorer.probability(html, bundle.url))
        evidence_ids = record_span_evidence(self._session, due, blocks, shapes)
        self._commit()  # Menu admission accepts only committed Evidence
        try:
            with self._session.begin_nested():
                written = [
                    (
                        kind,
                        validation,
                        write_page(
                            self._session,
                            due,
                            kind=kind,
                            sections=sections,
                            evidence_ids=evidence_ids,
                            flagged=validation.unlabeled_price_runs,
                            page_confidence=confidence,
                            method_version=(
                                self._version.llm if kind == "llm" else self._version.jsonld
                            ),
                        ),
                    )
                    for (kind, validation), sections in zip(streams, shapes, strict=True)
                ]
        except SubjectNotEligibleError:
            report.scope_not_eligible += 1
            return
        self._commit()
        report.extracted += 1
        report.flagged += llm.unlabeled_price_runs
        for kind, validation, page in written:
            _count_rows(report, kind, validation)
            report.items_written += page.items
            report.prices_written += page.prices
            report.unsectioned_items += page.unsectioned_items
            if kind == "llm" and page.items == 0:
                report.empty += 1
            report.jsonld_pages += kind == "jsonld"

    def _commit(self) -> None:
        if self._on_commit is not None:
            self._on_commit()

    @property
    def should_abort(self) -> bool:
        return self._consecutive_failures >= MAX_CONSECUTIVE_FAILURES


def run_extraction(  # noqa: PLR0913 - the run's collaborators, injected for tests
    session: Session,
    *,
    extractor: ChunkExtractor,
    scorer: PageScorer,
    bundles: BundleStore,
    outputs: OutputStore,
    model: str,
    limit: int | None = None,
    commit: Callable[[], None] | None = None,
    soc: SocProbe | None = None,
) -> ExtractionReport:
    """Extract and write every due page (at most ``limit``); the caller's ``commit`` ends each step.

    ``commit`` runs after a page's Evidence and again after its Menu pages (the
    CLI passes ``session.commit``): Menu admission accepts only committed input.
    """
    started = time.monotonic()
    version = PipelineVersion(model=model, classifier=scorer.name)
    report = ExtractionReport(method_version=version.llm)
    due, skipped = due_pages(session, version.llm)
    report.due = len(due)
    report.due_by_reason.update(page.reason for page in due)
    report.up_to_date = skipped["up_to_date"]
    report.needs_review = skipped["needs_review"]
    report.no_bundle = skipped["no_bundle"]
    todo = due if limit is None else due[:limit]
    probe = soc or SocProbe()
    run = _Run(
        session,
        extractor=extractor,
        scorer=scorer,
        bundles=bundles,
        outputs=outputs,
        version=version,
        report=report,
        on_commit=commit,
        soc=probe,
    )
    pool = ThreadPoolExecutor(max_workers=SLOTS, thread_name_prefix="llama")
    window: deque[_Pending] = deque()
    try:
        for page in todo:
            report.attempted += 1
            window.append(run.start(page, pool))
            while len(window) > LOOKAHEAD and not run.should_abort:
                run.finish(window.popleft())
            if run.should_abort:
                break
        while window and not run.should_abort:
            run.finish(window.popleft())
    finally:
        pool.shutdown(wait=True, cancel_futures=True)
    if run.should_abort:
        report.aborted = True
        report.attempted -= len(window)  # queued pages that were never finished
    report.wall_s = time.monotonic() - started
    report.soc_max_temp_c, report.cpu_freq_cap = probe.max_temp_c, probe.freq_cap
    return report
