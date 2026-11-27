"""Frozen sites with scripted saved model answers. Network and model are offline."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from apps.discovery.url_pipeline import resolve_urls
from apps.gold.refresh import refresh_gold
from apps.menu_pipeline.bundle import BundleStore
from apps.menu_pipeline.extraction import NoModel, OutputStore, extractor_version
from apps.menu_pipeline.page_bronze import run_menu_pages
from apps.menu_pipeline.venue_price_eval import Label, Manifest, State, Trace, first_loss, report
from packages.helios_parsing.segment import segment, text_hash
from packages.helios_parsing.validator import Row
from test.test_menu_extraction import _T1, _Venues
from test.test_menu_page_bronze import _WordVerifier
from test.test_url_pipeline import _NOW
from test.test_web_client import _fetcher

if TYPE_CHECKING:
    import pytest
    from sqlalchemy.orm import Session, sessionmaker


FIXTURES = Path(__file__).parent / "fixtures" / "venue-prices"


def test_frozen_venue_prices(
    committed_menu_sessions: sessionmaker[Session], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    venues = _Venues(committed_menu_sessions, tmp_path, monkeypatch)
    manifest = Manifest.model_validate_json((FIXTURES / "frozen.json").read_text())
    counter, east = manifest.venues
    counter.gers = venues.add(counter.venue, website="https://juniper.example")
    east.gers = venues.add(east.venue, website="https://pier.example")
    routes = {
        "https://juniper.example/": (
            200,
            '<a href="/menu">Lunch &amp; dinner menu</a>',
            "text/html",
        ),
        "https://pier.example/": (200, '<a href="/west/menu">West pier menu</a>', "text/html"),
    }
    answers = json.loads((FIXTURES / "answers.json").read_text())
    outputs = OutputStore(tmp_path)
    model = "frozen-model"
    for source, url in [
        ("counter", counter.pages[0].url),
        ("west", east.pages[0].other_location_urls[0]),
    ]:
        html = (FIXTURES / f"{source}.html").read_text()
        routes[url] = (200, html, "text/html")
        outputs.write(
            extractor_version(model),
            text_hash(segment(html)),
            [{"raw": json.dumps(answers[source])}],
        )

    with _fetcher(tmp_path / "http", routes, page_check=_WordVerifier()) as fetcher:
        with committed_menu_sessions.begin() as session:
            resolve_urls(session, resolver=fetcher, registry={}, decided_at=_NOW, observed_at=_NOW)
        with committed_menu_sessions() as session:
            run_menu_pages(
                session,
                fetcher=fetcher,
                verifier=_WordVerifier(),
                bundles=BundleStore(tmp_path),
                now=_T1,
                on_page=session.commit,
            )
            session.commit()
    no_model = NoModel()
    extraction = venues.extract(None, model=model, no_model=no_model)
    assert not extraction.failed and no_model.refused == 0
    with committed_menu_sessions() as session:
        refresh_gold(session, effective_instant=datetime.now(UTC))
        measured = report(manifest, session, tmp_path)
        # Keep the correct 12-inch row and give the 16-inch label the wrong amount.
        # The API's extra price must appear in the audit even when its item is served.
        altered = Manifest.model_validate(manifest.model_dump())
        altered.venues[0].pages[0].states[1].prices[1].usd_minor = 1400
        audited = report(altered, session, tmp_path)["venues"][0]
        assert audited["wrong_variant_prices"] == [
            {"url": counter.pages[0].url, "item": "garden pie", "variant": "16", "usd_minor": 1800}
        ]
    print(json.dumps(measured, indent=2))
    result, other = measured["venues"]
    assert result["counts"] == {
        "served": 5,
        "state_missing": 1,
    }
    assert (result["gained"], result["lost"], result["wrong_variant_prices"]) == (2, 0, [])
    assert other["counts"] == {"wrong_location": 1}
    assert other["wrong_location_published"] == east.pages[0].other_location_urls


def test_first_loss_separates_rejection_selection_and_publication() -> None:
    label = Label(item="Soup", usd_minor=600, baseline="served")
    state = State(name="lunch", anchor="Lunch served", prices=[label])
    trace = Trace(blocks={"lunch served"}, interpreted=True)
    assert first_loss(trace, state, label)[0] == "item_omitted"
    trace.proposed = [Row("Soup", "6.00")]
    trace.rejected[("soup", "", 600)] = "price_not_grounded"
    assert first_loss(trace, state, label) == ("price_rejected", "price_not_grounded")
    trace.stored.update(label.keys)
    assert first_loss(trace, state, label)[0] == "selection_loss"
    trace.selected.update(label.keys)
    assert first_loss(trace, state, label)[0] == "publication_loss"
    trace.published.update(label.keys)
    assert first_loss(trace, state, label)[0] == "served"
