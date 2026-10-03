"""LLM extraction and Menu writes (ADR-0013 slice 5, session P5-4).

No live network and no model: ``llama-server`` is an ``httpx.MockTransport``
that answers from the chunk it is sent, pages are synthetic, and the page
classifier is a fixed probability. The end-to-end tests commit like the CLIs
(Menu admission needs committed Bronze input) in a disposable ``*_test``
database, with UUID keys so other committed rows never interfere.
"""

from __future__ import annotations

import gzip
import json
import os
import re
import subprocess
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

import apps.menu_pipeline.evaluate as evaluate
import apps.menu_pipeline.extraction as extraction
import apps.menu_pipeline.menu_writes as menu_writes
import apps.menu_pipeline.page_bronze as page_bronze
from apps.discovery.pipeline import run_discovery
from apps.discovery.url_pipeline import resolve_urls
from apps.menu_pipeline.bundle import BundleStore, excerpt
from apps.menu_pipeline.extraction import (
    OutputStore,
    PipelineVersion,
    SocProbe,
    model_tag,
    run_extraction,
)
from apps.menu_pipeline.llama_client import (
    ChunkFailed,
    LlamaClient,
    ServerNotReady,
    WrongModel,
)
from apps.menu_pipeline.menu_writes import FLAGGED_PRICE_CONFIDENCE, PRICE_CONFIDENCE
from apps.menu_pipeline.models import load_manifest
from apps.menu_pipeline.page_bronze import REFETCH_WINDOW, run_menu_pages
from packages.helios_core.config import get_database_url
from packages.helios_core.domains.menu.enumeration import enumerate_current_requests
from packages.helios_core.domains.menu.models import (
    EvidenceLink,
    MenuItem,
    MenuPage,
    MenuSection,
    MenuVariant,
    PriceObservation,
)
from packages.helios_core.identity.contracts import SubjectNotEligibleError
from packages.helios_core.provenance.models import Capture, Evidence, SourceRecord
from packages.helios_parsing.evaluation import gold_page, metrics, score_page
from packages.helios_parsing.menu_shape import shape
from packages.helios_parsing.prompt import GRAMMAR, SYSTEM_PROMPT, token_cap
from packages.helios_parsing.segment import segment
from packages.helios_parsing.validator import Row, validate
from test.test_menu_page_bronze import _page, _Pages, _Sites, _WordVerifier
from test.test_url_pipeline import _NOW, _FakeResolver, _poi

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy.engine import Engine

_REPO_ROOT = Path(__file__).resolve().parents[1]
_LINE = re.compile(r"^(b\d{4}) \| (.*)$")
_MENU = (
    "<html><body><nav>Drinks</nav><h1>Menu</h1><p>MENU</p><h2>Tacos</h2>"
    "<p>Carne Asada Taco</p><p>$3.50</p><p>Queso</p><p>$6.00</p>"
    "<h2>Drinks</h2><p>Horchata</p><p>$2.50/Small</p><p>$3.50/Large</p></body></html>"
)
_PRICES: dict[str, list[tuple[str, str | None]]] = {
    "Carne Asada Taco": [("3.50", None)],
    "Queso": [("6.00", None)],
    "Horchata": [("2.50", "Small"), ("3.50", "Large")],
    "Elote": [("4.25", None)],
}
_SECTIONS = {"Carne Asada Taco": "Tacos", "Queso": "Tacos", "Horchata": "Drinks"}


# -- a scripted llama-server -------------------------------------------------------


def _answer(chunk: str) -> str:
    """The rows a perfect extractor returns for ``chunk`` (the prompt's JSON form)."""
    sections: dict[str, list[dict[str, str]]] = {}
    for line in chunk.splitlines():
        match = _LINE.match(line)
        if match is None or match.group(2) not in _PRICES:
            continue
        block, name = match.groups()
        for price, variant in _PRICES[name]:
            item = {"b": block, "n": name, "p": price}
            if variant:
                item["v"] = variant
            sections.setdefault(_SECTIONS.get(name, "Specials"), []).append(item)
    return json.dumps(
        {"sections": [{"section": s, "items": items} for s, items in sections.items()]},
        separators=(",", ":"),
    )


@dataclass
class _Server:
    """``/health``, ``/props`` and ``/v1/chat/completions``; ``mode`` scripts failures."""

    mode: str = "ok"  # ok | sparse | truncate | timeout_once | error
    health: list[int] = field(default_factory=lambda: [200])
    model_path: str = "/models/Qwen3-4B-Instruct-2507-Q4_0.gguf"
    slots: int = 2
    bodies: list[dict[str, Any]] = field(default_factory=list)
    timeouts: int = 0

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == "/health":
            status = self.health.pop(0) if len(self.health) > 1 else self.health[0]
            return httpx.Response(status, json={"status": "ok" if status == 200 else "loading"})
        if request.url.path == "/props":
            return httpx.Response(
                200, json={"model_path": self.model_path, "total_slots": self.slots}
            )
        body = json.loads(request.content)
        self.bodies.append(body)
        user = body["messages"][1]["content"]
        if self.mode == "error":
            return httpx.Response(500, text="boom")
        if self.mode == "timeout_once" and self.timeouts == 0:
            self.timeouts += 1
            raise httpx.ReadTimeout("slow", request=request)
        content, finish = _answer(user.split("\n\n(This text prints")[0]), "stop"
        if self.mode == "sparse" and "(This text prints" not in user:
            content = '{"sections":[]}'
        if self.mode == "truncate":
            content, finish = content[: content.rindex("},{") + 1], "length"  # cut mid-list
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": content}, "finish_reason": finish}],
                "timings": {"prompt_n": 100, "predicted_n": 20},
            },
        )


def _client(server: _Server, **kwargs: Any) -> LlamaClient:
    return LlamaClient(
        httpx.Client(transport=httpx.MockTransport(server)), base_url="http://llama", **kwargs
    )


# -- client ------------------------------------------------------------------------


def test_wait_ready_polls_health_until_200_and_times_out() -> None:
    server = _Server(health=[503, 503, 200])
    sleeps: list[float] = []
    _client(server, sleep=sleeps.append, clock=lambda: 0.0).wait_ready(timeout_s=10, poll_s=2)
    assert sleeps == [2, 2]

    now = [0.0]

    def tick(seconds: float) -> None:
        now[0] += seconds

    stuck = _client(_Server(health=[503]), sleep=tick, clock=lambda: now[0])
    with pytest.raises(ServerNotReady, match="HTTP 503"):
        stuck.wait_ready(timeout_s=10, poll_s=5)


def test_check_model_refuses_another_file_or_slot_count() -> None:
    _client(_Server()).check_model("Qwen3-4B-Instruct-2507-Q4_0.gguf")
    with pytest.raises(WrongModel, match="other.gguf"):
        _client(_Server(model_path="/models/other.gguf")).check_model(
            "Qwen3-4B-Instruct-2507-Q4_0.gguf"
        )
    with pytest.raises(WrongModel, match="1 slots"):
        _client(_Server(slots=1)).check_model("Qwen3-4B-Instruct-2507-Q4_0.gguf")


def _chunk() -> str:
    return "b0004 | Carne Asada Taco\nb0005 | $3.50\nb0006 | Queso\nb0007 | $6.00\nb0009 | $9.00"


def test_extract_chunk_sends_the_measured_request() -> None:
    server = _Server()
    result = _client(server).extract_chunk(_chunk())
    (body,) = server.bodies
    assert body["messages"][0] == {"role": "system", "content": SYSTEM_PROMPT}
    assert body["messages"][1]["content"] == _chunk()
    assert (body["temperature"], body["grammar"], body["cache_prompt"]) == (0, GRAMMAR, True)
    assert body["max_tokens"] == token_cap(_chunk())
    assert body["chat_template_kwargs"] == {"enable_thinking": False}
    assert [r.name for s in result.output.sections for r in s.rows] == ["Carne Asada Taco", "Queso"]
    assert (result.first, result.truncated, result.resent) == (None, False, 0)
    assert result.record()["raw"] == result.attempt.raw


def test_truncated_output_keeps_its_complete_rows() -> None:
    result = _client(_Server(mode="truncate")).extract_chunk(_chunk())
    assert result.truncated and result.output.recovered
    assert [r.name for s in result.output.sections for r in s.rows] == ["Carne Asada Taco"]


def test_sparse_chunk_is_asked_once_more_and_the_first_answer_kept() -> None:
    server = _Server(mode="sparse")
    result = _client(server).extract_chunk(_chunk())
    assert len(server.bodies) == 2
    assert server.bodies[1]["messages"][1]["content"].startswith(
        _chunk() + "\n\n(This text prints 3"
    )
    assert server.bodies[1]["max_tokens"] == token_cap(_chunk())
    assert result.first is not None and result.first.raw == '{"sections":[]}'
    assert result.output.priced_rows == 2
    assert result.record()["retry"]["first"]["raw"] == '{"sections":[]}'


def test_timeout_is_resent_once_then_the_chunk_fails() -> None:
    result = _client(_Server(mode="timeout_once")).extract_chunk(_chunk())
    assert result.resent == 1 and result.output.priced_rows == 2
    with pytest.raises(ChunkFailed, match="2 attempts"):
        _client(_Server(mode="error")).extract_chunk(_chunk())

    def not_found(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text="no route")

    calls = LlamaClient(httpx.Client(transport=httpx.MockTransport(not_found)))
    with pytest.raises(ChunkFailed, match="HTTP 404"):
        calls.extract_chunk(_chunk())


def test_evaluate_extract_saves_harness_records_that_score(tmp_path: Path) -> None:
    (tmp_path / "pages").mkdir()
    (tmp_path / "pages" / "p1.html").write_text(_MENU, encoding="utf-8")
    blocks = segment(_MENU)
    ids = {b.text: b.id for b in blocks}
    label = {
        "page_id": "p1",
        "page_label": "menu",
        "reviewed": True,
        "items": [
            {"name": "Queso", "block": ids["Queso"], "prices": [{"amount": "6.00"}]},
            {"name": "Elote", "block": None, "prices": [{"amount": "4.25"}]},
        ],
    }
    gold = {"p1": gold_page(label)}
    server = _Server()

    evaluate.cmd_extract(tmp_path, gold, "t1", _client(server))
    evaluate.cmd_extract(tmp_path, gold, "t1", _client(server))  # saved pages are skipped

    assert len(server.bodies) == 1
    rows = evaluate.extracted_rows(tmp_path, "t1", "p1", blocks)
    counts = score_page(gold["p1"], blocks, rows)
    assert metrics(counts)["item_recall"] == 0.5 and counts["accepted_price_exact"] == 1


# -- pure parts ----------------------------------------------------------------------


def test_shape_grounds_sections_groups_variants_and_keeps_downgrades() -> None:
    blocks = segment(_MENU + "<p>Cake</p>")
    ids = {b.text: b.id for b in blocks}
    rows = [
        Row("Carne Asada Taco", "3.50", section="Tacos", claimed_block=ids["Carne Asada Taco"]),
        Row("Carne Asada Taco", "3.50", section="Tacos", claimed_block=ids["Carne Asada Taco"]),
        Row("Horchata", "2.50", variant="Small", section="Drinks", claimed_block=ids["Horchata"]),
        Row("Horchata", "3.50", variant="Large", section="Drinks", claimed_block=ids["Horchata"]),
        Row("Cake", None, section="Desserts", claimed_block=ids["Cake"]),
        Row("Pizza", "9.00", section="Tacos"),
    ]
    decisions = validate(blocks, rows).verdicts
    assert [v.decision for v in decisions] == [
        "accept",
        "reject",  # duplicate row
        "accept",
        "accept",
        "downgrade",
        "reject",  # not on the page
    ]
    unsectioned, tacos, drinks = shape(blocks, decisions)
    assert (unsectioned.key, [i.name for i in unsectioned.items]) == (None, ["Cake"])
    assert unsectioned.items[0].prices == () and unsectioned.items[0].variants == ()
    assert tacos.name == "Tacos" and tacos.key == f"{ids['Tacos']}:tacos"
    assert [(p.amount_minor, p.evidence[0].locator) for p in tacos.items[0].prices] == [
        (350, f"blocks:segment-v2:{ids['$3.50']}[0:5]")
    ]
    # the heading, not the nav link that prints the same word earlier
    assert drinks.key == f"{ids['Drinks']}:drinks" and ids["Drinks"] != blocks[0].id
    horchata = drinks.items[0]
    assert [(v.label, [p.amount_minor for p in v.prices]) for v in horchata.variants] == [
        ("Small", [250]),
        ("Large", [350]),
    ]


def test_pipeline_version_names_every_component_within_the_column() -> None:
    spec = load_manifest()["Qwen3-4B-Instruct-2507-Q4_0"]
    version = PipelineVersion(model=model_tag(spec), classifier="classifier-v2")
    assert version.llm == (
        "qwen3-4b-instruct-2507-q4_0@e0ba675d86ab;prompt-v2.3;chunk-v2.1;segment-v2;"
        "repairs-v4;validator-v4;classifier-v2"
    )
    assert len(version.llm) <= 128
    assert version.jsonld == "jsonld-v1;validator-v4;segment-v2;classifier-v2"
    assert version.extractor in version.llm


def test_output_store_round_trip(tmp_path: Path) -> None:
    store = OutputStore(tmp_path)
    result = _client(_Server()).extract_chunk(_chunk())
    assert store.read("x", "sha256:ab") is None
    store.write("x", "sha256:ab", [result])
    assert store.read("x", "sha256:ab") == [result.attempt.raw]
    assert store.read("y", "sha256:ab") is None  # another extractor version: not reused
    (path,) = tmp_path.glob("var/replay/menu-extract/*/ab.json.gz")
    path.write_bytes(gzip.compress(b'{"format": "other"}'))
    with pytest.raises(ValueError, match="menu-extract-v1"):
        store.read("x", "sha256:ab")


def test_soc_probe_reads_temperature_and_frequency_cap(tmp_path: Path) -> None:
    (tmp_path / "class/thermal/thermal_zone0").mkdir(parents=True)
    (tmp_path / "class/thermal/thermal_zone0/temp").write_text("61500\n")
    cpu = tmp_path / "devices/system/cpu/cpu4/cpufreq"
    cpu.mkdir(parents=True)
    (cpu / "scaling_max_freq").write_text("1800000")
    (cpu / "cpuinfo_max_freq").write_text("2400000")
    probe = SocProbe(root=tmp_path)
    probe.sample()
    assert (probe.max_temp_c, probe.freq_cap) == (61.5, 0.75)
    empty = SocProbe(root=tmp_path / "none")
    empty.sample()
    assert (empty.max_temp_c, empty.freq_cap) == (None, None)


# -- database: end to end ----------------------------------------------------------------


@pytest.fixture
def committed(disposable_database_engine: Engine) -> Iterator[sessionmaker[Session]]:
    subprocess.run(
        ["alembic", "-c", str(_REPO_ROOT / "alembic.ini"), "upgrade", "head"],
        check=True,
        cwd=_REPO_ROOT,
        env={**os.environ, "DATABASE_URL": get_database_url()},
    )
    yield sessionmaker(bind=disposable_database_engine, expire_on_commit=False)


@dataclass
class _Scorer:
    name: str = "word-v1"
    value: float = 0.9123456

    def probability(self, html: str, url: str) -> float:
        del html, url
        return self.value


class _Venues:
    """Committed venues with own-site menu URLs; runs see only these records."""

    def __init__(
        self, factory: sessionmaker[Session], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self.factory = factory
        self.tmp_path = tmp_path
        self.token = uuid4().hex[:12]
        self.sites: dict[str, _FakeResolver] = {}
        self.menus: dict[str, str] = {}  # gers -> menu URL
        original_saved = page_bronze._saved_menu_urls  # noqa: SLF001 - test isolation
        original_due = menu_writes.due_pages

        def saved(session: Session) -> list[tuple[str, int, str, Any]]:
            return [row for row in original_saved(session) if self.token in row[0]]

        def due(session: Session, method_version: str) -> tuple[list[Any], dict[str, int]]:
            pages, skipped = original_due(session, method_version)
            return [p for p in pages if self.token in p.key], skipped

        monkeypatch.setattr(page_bronze, "_saved_menu_urls", saved)
        monkeypatch.setattr("apps.menu_pipeline.extraction.due_pages", due)

    def add(self, name: str) -> str:
        gers = f"{self.token}-{len(self.menus)}"
        site = f"https://{gers}.example.com"
        self.menus[gers] = f"{site}/menu"
        resolver = _FakeResolver(self.menus[gers])
        self.sites[site] = self.sites[site + "/"] = resolver  # the website as saved
        with self.factory.begin() as session:
            run_discovery(
                session,
                [_poi(f"{name} {gers}", 30.3, -97.7, gers_id=gers, websites=(site,))],
                decided_at=_NOW,
                observed_at=_NOW,
                release="s3://overturemaps-us-west-2/release/2026-01-01.0/theme=places/type=place/*",
            )
        return gers

    def resolve(self) -> None:
        with self.factory.begin() as session:
            report = resolve_urls(
                session, resolver=_Sites(self.sites), registry={}, decided_at=_NOW, observed_at=_NOW
            )
        assert report.menu_urls_found >= 1, report

    def fetch(self, html: dict[str, str], *, at: Any) -> None:
        pages = _Pages({self.menus[g]: _page(self.menus[g], h, at=at) for g, h in html.items()})
        with self.factory() as session:
            report = run_menu_pages(
                session,
                fetcher=pages,
                verifier=_WordVerifier(),
                bundles=BundleStore(self.tmp_path),
                now=at,
                on_page=session.commit,
            )
            session.commit()
        assert report.versions_new + report.versions_changed == len(html), report.summary()

    def extract(
        self, server: _Server, *, scorer: _Scorer | None = None, limit: int | None = None
    ) -> extraction.ExtractionReport:
        with self.factory() as session:
            report = run_extraction(
                session,
                extractor=_client(server),
                scorer=scorer or _Scorer(),
                bundles=BundleStore(self.tmp_path),
                outputs=OutputStore(self.tmp_path),
                model="test-model@0123456789ab",
                limit=limit,
                commit=session.commit,
                soc=SocProbe(root=self.tmp_path / "no-sys"),
            )
            session.commit()
        return report

    def pages(self, gers: str) -> list[MenuPage]:
        with self.factory() as session:
            return list(
                session.scalars(
                    select(MenuPage)
                    .join(
                        SourceRecord,
                        SourceRecord.id == MenuPage.source_record_id,
                    )
                    .where(SourceRecord.external_key == gers)
                    .order_by(MenuPage.source_kind, MenuPage.stream_revision)
                )
            )


@pytest.fixture
def venues(
    committed: sessionmaker[Session], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> _Venues:
    return _Venues(committed, tmp_path, monkeypatch)


_T1 = _NOW + timedelta(minutes=1)


def _rows(session: Session, page_id: int) -> list[tuple[str, str | None, int, Decimal]]:
    """(item, variant label, amount, confidence) of a page's prices."""
    out = []
    for price in session.scalars(
        select(PriceObservation).where(PriceObservation.page_id == page_id)
    ):
        variant = session.get(MenuVariant, price.variant_id) if price.variant_id else None
        item_id = variant.item_id if variant else price.item_id
        item = session.get(MenuItem, item_id)
        assert item is not None and price.amount_minor is not None
        out.append(
            (
                str(item.name),
                variant.label if variant else None,
                price.amount_minor,
                price.confidence,
            )
        )
    return sorted(out)


def test_extraction_writes_an_llm_page_with_checkable_evidence_and_reruns_idempotently(
    venues: _Venues,
) -> None:
    gers = venues.add("Kerbey Lane")
    venues.resolve()
    venues.fetch({gers: _MENU}, at=_T1)
    server = _Server()

    report = venues.extract(server)

    assert (report.due, report.extracted, report.failed, report.aborted) == (1, 1, {}, False)
    assert report.due_by_reason == {"new": 1}
    assert report.rows == {"llm:accept": 4}
    assert (report.items_written, report.prices_written, report.empty) == (3, 4, 0)
    assert (report.chunks, report.jsonld_pages, report.reused_outputs) == (1, 0, 0)
    (page,) = venues.pages(gers)
    assert (page.source_kind, page.operation, page.stream_revision) == ("llm", "initial", 1)
    assert page.method == "menu-pipeline" and page.method_version == report.method_version
    assert page.confidence == Decimal("0.9123") and page.subject_kind == "organization"
    with venues.factory() as session:
        assert _rows(session, page.id) == [
            ("Carne Asada Taco", None, 350, PRICE_CONFIDENCE),
            ("Horchata", "Large", 350, PRICE_CONFIDENCE),
            ("Horchata", "Small", 250, PRICE_CONFIDENCE),
            ("Queso", None, 600, PRICE_CONFIDENCE),
        ]
        sections = sorted(
            (s.name, s.source_native_key)
            for s in session.scalars(select(MenuSection).where(MenuSection.page_id == page.id))
        )
        assert [name for name, _ in sections] == ["Drinks", "Tacos"]
        assert all(
            key and key.startswith(f"v{page.source_record_version_id}:") for _, key in sections
        )
        # every Capture-targeted locator is checkable from the Version's bundle alone
        capture = session.scalar(
            select(Capture)
            .join(Evidence, Evidence.capture_id == Capture.id)
            .join(EvidenceLink, EvidenceLink.evidence_id == Evidence.id)
            .where(EvidenceLink.page_id == page.id)
            .limit(1)
        )
        assert capture is not None and capture.bundle_path is not None
        bundle = BundleStore(venues.tmp_path).read(capture.bundle_path)
        spans = session.scalars(
            select(Evidence)
            .join(EvidenceLink, EvidenceLink.evidence_id == Evidence.id)
            .where(EvidenceLink.page_id == page.id, Evidence.capture_id.is_not(None))
        ).all()
        assert {excerpt(bundle, e.locator) for e in spans} >= {"Tacos", "Queso", "$6.00", "$2.50"}
        # version-local native keys (N1): the prices enumerate for Gold, one target each
        requests = [
            r
            for r in enumerate_current_requests(session, effective_instant=datetime.now(UTC))
            if r.source_record_id == page.source_record_id
        ]
        assert len(requests) == 4
        assert all(r.target.native_path[0][0] == "section" for r in requests)

    again = venues.extract(server)
    assert (again.due, again.extracted) == (0, 0) and again.up_to_date >= 1
    assert len(server.bodies) == 1  # no model call on the re-run
    assert len(venues.pages(gers)) == 1
    assert list(venues.tmp_path.glob("var/replay/menu-extract/*/*.json.gz"))


@pytest.mark.parametrize("mode", ["truncate", "sparse", "timeout_once"])
def test_truncated_sparse_and_timed_out_chunks_end_to_end(venues: _Venues, mode: str) -> None:
    gers = venues.add("Veracruz")
    venues.resolve()
    venues.fetch({gers: _MENU}, at=_T1)

    report = venues.extract(_Server(mode=mode))

    assert report.extracted == 1
    expected = {"truncate": (1, 0, 0), "sparse": (0, 1, 0), "timeout_once": (0, 0, 1)}[mode]
    assert (report.truncated_chunks, report.sparse_retries, report.resent_requests) == expected
    # the cut-off last row (Horchata Large) comes back through labelled variant completion
    assert report.rows == {"llm:accept": 4}


def test_version_bump_reinterprets_from_saved_output_and_new_text_is_an_observation(
    venues: _Venues,
) -> None:
    gers = venues.add("Juan in a Million")
    venues.resolve()
    venues.fetch({gers: _MENU}, at=_T1)
    server = _Server()
    venues.extract(server)

    bumped = venues.extract(server, scorer=_Scorer(name="word-v2"))

    assert bumped.due_by_reason == {"reinterpret": 1} and bumped.reused_outputs == 1
    assert len(server.bodies) == 1  # re-validated from the saved answer, no model call
    first, second = venues.pages(gers)
    assert (second.operation, second.stream_revision, second.interpretation_revision) == (
        "correction",
        2,
        2,
    )
    assert second.supersedes_page_id == first.id
    assert second.source_record_version_id == first.source_record_version_id

    later = _T1 + REFETCH_WINDOW + timedelta(minutes=1)
    venues.fetch({gers: _MENU.replace("</body>", "<p>Elote</p><p>$4.25</p></body>")}, at=later)
    changed = venues.extract(server, scorer=_Scorer(name="word-v2"))

    assert changed.due_by_reason == {"changed": 1} and changed.chunks == 1
    third = venues.pages(gers)[-1]
    assert (third.operation, third.stream_revision, third.interpretation_revision) == (
        "observation",
        3,
        1,
    )
    assert changed.unsectioned_items == 1  # "Specials" is not printed on the page
    with venues.factory() as session:
        assert ("Elote", None, 425, PRICE_CONFIDENCE) in _rows(session, third.id)
        elote = session.scalar(
            select(MenuItem).where(MenuItem.page_id == third.id, MenuItem.name == "Elote")
        )
        assert elote is not None and elote.source_native_key is None  # Unsectioned: not in Gold


_JSONLD = (
    '<script type="application/ld+json">{"@type":"Menu","hasMenuSection":{"@type":"MenuSection",'
    '"name":"Tacos","hasMenuItem":[{"@type":"MenuItem","name":"Queso","offers":{"@type":"Offer",'
    '"price":"6.00","priceCurrency":"USD"}},{"@type":"MenuItem","name":"Queso Fundido","offers":'
    '{"price":"9.00"}}]}}</script>'
)


def test_jsonld_stream_beside_llm_and_its_empty_successor(venues: _Venues) -> None:
    gers = venues.add("Taco Deli")
    venues.resolve()
    venues.fetch({gers: _MENU.replace("<body>", "<body>" + _JSONLD)}, at=_T1)

    report = venues.extract(_Server())

    assert report.jsonld_pages == 1
    # "Queso Fundido" isn't printed on the page: the validator rejects it
    assert report.rows["jsonld:accept"] == 1 and report.rows["jsonld:reject:name_not_grounded"] == 1
    jsonld = next(p for p in venues.pages(gers) if p.source_kind == "jsonld")
    assert jsonld.method_version == "jsonld-v1;validator-v4;segment-v2;word-v1"
    with venues.factory() as session:
        assert _rows(session, jsonld.id) == [("Queso", None, 600, PRICE_CONFIDENCE)]

    # JSON-LD gone (with a text change): an empty successor, so its prices stop being current
    later = _T1 + REFETCH_WINDOW + timedelta(minutes=1)
    venues.fetch({gers: _MENU.replace("</body>", "<p>Elote</p><p>$4.25</p></body>")}, at=later)
    venues.extract(_Server())
    heads = [p for p in venues.pages(gers) if p.source_kind == "jsonld"]
    assert [p.operation for p in heads] == ["initial", "observation"]
    with venues.factory() as session:
        assert session.scalar(select(func.count()).where(MenuItem.page_id == heads[-1].id)) == 0


def test_a_page_with_nothing_extracted_writes_an_empty_llm_page(venues: _Venues) -> None:
    gers = venues.add("Empty Plate")
    venues.resolve()
    venues.fetch({gers: "<html><body><h1>MENU</h1><p>Opening soon.</p></body></html>"}, at=_T1)

    report = venues.extract(_Server())

    assert (report.extracted, report.empty, report.items_written) == (1, 1, 0)
    (page,) = venues.pages(gers)
    assert page.source_kind == "llm"
    assert venues.extract(_Server()).due == 0  # done at this pipeline version


def test_flagged_page_gets_the_lower_price_confidence(venues: _Venues) -> None:
    gers = venues.add("Home Slice")
    venues.resolve()
    flagged = _MENU.replace("<p>$2.50/Small</p><p>$3.50/Large</p>", "<p>$2.50 | $3.50</p>")
    venues.fetch({gers: flagged}, at=_T1)

    report = venues.extract(_Server())

    assert report.flagged == 1
    (page,) = venues.pages(gers)
    with venues.factory() as session:
        confidences = {c for *_, c in _rows(session, page.id)}
    assert confidences == {FLAGGED_PRICE_CONFIDENCE}


def test_failed_pages_stay_due_and_repeated_failures_stop_the_run(venues: _Venues) -> None:
    menus = {venues.add(f"Cafe {i}"): _MENU for i in range(4)}
    venues.resolve()
    venues.fetch(menus, at=_T1)

    report = venues.extract(_Server(mode="error"))

    assert report.aborted and report.failed == {"chunk_failed": 3}
    assert report.extracted == 0 and report.attempted == 3
    assert all(venues.pages(g) == [] for g in menus)

    retry = venues.extract(_Server(), limit=2)
    assert (retry.due, retry.attempted, retry.extracted, retry.aborted) == (4, 2, 2, False)


def test_scope_not_eligible_is_counted_and_retried(
    venues: _Venues, monkeypatch: pytest.MonkeyPatch
) -> None:
    gers = venues.add("Bouldin Creek")
    venues.resolve()
    venues.fetch({gers: _MENU}, at=_T1)
    original = menu_writes.write_page

    def not_eligible(*args: Any, **kwargs: Any) -> Any:
        raise SubjectNotEligibleError("not yet")

    monkeypatch.setattr("apps.menu_pipeline.extraction.write_page", not_eligible)
    report = venues.extract(_Server())
    assert (report.scope_not_eligible, report.extracted) == (1, 0)
    assert venues.pages(gers) == []

    monkeypatch.setattr("apps.menu_pipeline.extraction.write_page", original)
    again = venues.extract(_Server())
    assert (again.due, again.extracted, again.reused_outputs) == (1, 1, 1)
