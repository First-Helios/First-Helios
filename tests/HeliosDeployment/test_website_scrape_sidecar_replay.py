"""Replay-based integration tests for the STRUCT-01 / TARGET-01 sidecar wiring.

Scrapes a cached debug bundle (JSON-LD-rich) end-to-end in replay mode and
asserts the menu sidecar gets populated plus every emitted signal is linked
to a sidecar offer target.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from collectors.meal_deals.website_scraper import (
    _load_site_debug_bundle,
    scrape_restaurant_website,
)

_BUNDLE_DIR = Path("data/cache/website_scrape_debug")
# La Posada South is the canonical fixture — rich JSON-LD menu hierarchy.
_LAPOSADA_BUNDLE = _BUNDLE_DIR / "laposadasouth_com__9e05a1a3db03.json"


def _skip_if_missing(bundle: Path) -> None:
    if not bundle.exists():
        pytest.skip(f"Replay bundle not synced locally: {bundle}")


def test_laposada_replay_populates_menu_sidecar(tmp_path, monkeypatch):
    _skip_if_missing(_LAPOSADA_BUNDLE)

    # Work on an isolated copy so we don't mutate the shared corpus.
    staging = tmp_path / "website_scrape_debug"
    staging.mkdir()
    shutil.copy(_LAPOSADA_BUNDLE, staging / _LAPOSADA_BUNDLE.name)

    monkeypatch.setattr(
        "collectors.meal_deals.website_scraper.WEBSITE_SCRAPE_DEBUG_DIR",
        staging,
    )

    bundle_before = json.loads(_LAPOSADA_BUNDLE.read_text())
    url = bundle_before["site_url"]

    signals = scrape_restaurant_website(
        url,
        bundle_before.get("restaurant_name", "Test"),
        1,
        replay_debug_cache=True,
    )
    assert signals, "expected at least one signal from La Posada replay"

    bundle_after = json.loads((staging / _LAPOSADA_BUNDLE.name).read_text())
    sidecar = bundle_after.get("menu_sidecar")
    assert sidecar is not None, "menu_sidecar must be written to the bundle"

    counts = sidecar["counts"]
    assert counts["sections"] >= 5, counts
    assert counts["items"] >= 20, counts
    assert counts["price_points"] >= 20, counts

    # Sidecar baselines must surface at least one course median.
    baselines = sidecar["baselines"]
    assert baselines["course_price_median"], baselines
    assert baselines["section_price_median"], baselines

    # Every signal coming out of the JSON-LD menu should carry an offer_target.
    linked_signals = [s for s in signals if s.metadata.get("offer_target")]
    assert linked_signals, "expected signals to link to sidecar offer targets"
    for sig in linked_signals:
        target = sig.metadata["offer_target"]
        assert target["scope"] in {"item", "section", "service_period", "venue"}
        if target["scope"] == "item":
            assert target["item_key"]
            assert target["section_key"]
        # ARCH-02: every linked target should carry confidence + disposition.
        assert "confidence" in target
        assert target["disposition"] in {"auto_accept", "review", "discard"}

    # At least one signal should carry a narrow value profile tied to its offer target.
    vp_signals = [s for s in signals if isinstance(s.metadata.get("value_profile"), dict)]
    assert vp_signals, "expected at least one signal to pick up a value_profile"
    assert any(
        "course_baseline" in s.metadata["value_profile"]
        or "section_baseline" in s.metadata["value_profile"]
        for s in vp_signals
    )


def test_laposada_replay_writes_offer_targets_into_sidecar(tmp_path, monkeypatch):
    _skip_if_missing(_LAPOSADA_BUNDLE)

    staging = tmp_path / "website_scrape_debug"
    staging.mkdir()
    shutil.copy(_LAPOSADA_BUNDLE, staging / _LAPOSADA_BUNDLE.name)
    monkeypatch.setattr(
        "collectors.meal_deals.website_scraper.WEBSITE_SCRAPE_DEBUG_DIR",
        staging,
    )

    bundle_before = json.loads(_LAPOSADA_BUNDLE.read_text())
    scrape_restaurant_website(
        bundle_before["site_url"],
        bundle_before.get("restaurant_name", "Test"),
        1,
        replay_debug_cache=True,
    )

    bundle_after = json.loads((staging / _LAPOSADA_BUNDLE.name).read_text())
    sidecar = bundle_after.get("menu_sidecar")
    assert sidecar is not None
    assert sidecar["offer_targets"], "sidecar must capture offer targets for replayable analysis"

    # Offer targets must reference real section or item keys.
    section_keys = {s["key"] for s in sidecar["sections"]}
    item_keys = {i["key"] for i in sidecar["items"]}
    for target in sidecar["offer_targets"]:
        if target["scope"] == "item":
            assert target["item_key"] in item_keys
            assert target["section_key"] in section_keys
        elif target["scope"] == "section":
            assert target["section_key"] in section_keys
