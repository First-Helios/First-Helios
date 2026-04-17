"""Tests for collectors.meal_deals.hint_registry (ARCH-04)."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from collectors.meal_deals.hint_registry import (
    DEFAULT_REGISTRY_PATH,
    HINT_SCOPE,
    SCHEMA_VERSION,
    annotate_exploration_use,
    find_hints,
    load_hints,
)


def _write_registry(path: Path, hints: list[dict]) -> None:
    path.write_text(
        json.dumps({"schema_version": SCHEMA_VERSION, "hints": hints}, indent=2)
    )


def _sample_hint(**overrides) -> dict:
    base = {
        "id": "hint_demo_001",
        "brand": "demo",
        "hint_type": "corporate_promo_slug",
        "slug": "/promotions",
        "target_domain": "demo.com",
        "source": "manual_replay",
        "first_seen": "2026-04-01",
        "last_verified": "2026-04-10",
        "expires_at": "2026-07-01",
        "verified_against_url": "https://demo.com/promotions",
        "notes": "test",
    }
    base.update(overrides)
    return base


def test_checked_in_registry_is_loadable_and_scope_is_exploration():
    """The registry file that ships with the repo must load cleanly."""
    if not DEFAULT_REGISTRY_PATH.exists():
        pytest.skip("default registry not present in this checkout")
    hints = load_hints(include_expired=True)
    assert hints, "expected at least one seeded hint"
    for h in hints:
        assert h.scope == HINT_SCOPE, "hints must always be exploration-only"
        assert h.source and h.last_verified and h.expires_at and h.verified_against_url


def test_load_hints_filters_expired(tmp_path):
    path = tmp_path / "registry.json"
    _write_registry(path, [
        _sample_hint(id="fresh", expires_at="2099-01-01"),
        _sample_hint(id="stale", expires_at="2020-01-01"),
    ])
    hints = load_hints(path=path, as_of=date(2026, 4, 17))
    assert {h.id for h in hints} == {"fresh"}


def test_load_hints_include_expired(tmp_path):
    path = tmp_path / "registry.json"
    _write_registry(path, [
        _sample_hint(id="stale", expires_at="2020-01-01"),
    ])
    hints = load_hints(path=path, include_expired=True)
    assert {h.id for h in hints} == {"stale"}
    assert hints[0].is_expired(as_of=date(2026, 4, 17))


def test_load_hints_requires_provenance_fields(tmp_path):
    path = tmp_path / "registry.json"
    bad = _sample_hint()
    bad.pop("last_verified")
    _write_registry(path, [bad])
    with pytest.raises(ValueError, match="missing required fields"):
        load_hints(path=path, as_of=date(2026, 4, 17))


def test_load_hints_rejects_unknown_schema_version(tmp_path):
    path = tmp_path / "registry.json"
    path.write_text(json.dumps({
        "schema_version": "hint_registry.v99",
        "hints": [_sample_hint()],
    }))
    with pytest.raises(ValueError, match="schema_version"):
        load_hints(path=path)


def test_find_hints_filters_by_brand_type_and_domain(tmp_path):
    path = tmp_path / "registry.json"
    _write_registry(path, [
        _sample_hint(id="a", brand="brandx", target_domain="brandx.com"),
        _sample_hint(id="b", brand="brandy", target_domain="brandy.com"),
        _sample_hint(id="c", brand="brandx", hint_type="footer_label", target_domain="brandx.com"),
    ])
    hints = load_hints(path=path, as_of=date(2026, 4, 17))
    assert len(find_hints(hints, brand="brandx")) == 2
    assert len(find_hints(hints, brand="brandx", hint_type="corporate_promo_slug")) == 1
    assert len(find_hints(hints, target_domain="brandy.com")) == 1
    assert len(find_hints(hints, brand="notfound")) == 0


def test_annotate_exploration_use_records_provenance(tmp_path):
    path = tmp_path / "registry.json"
    _write_registry(path, [_sample_hint()])
    hint = load_hints(path=path, as_of=date(2026, 4, 17))[0]
    blob = annotate_exploration_use(hint, used_at_url="https://demo.com/promotions")
    assert blob["hint_scope"] == HINT_SCOPE
    assert blob["used_as"] == "exploration_probe"
    assert blob["hint_verified_against_url"] == "https://demo.com/promotions"
    assert blob["used_at_url"] == "https://demo.com/promotions"


def test_missing_registry_returns_empty_list(tmp_path):
    assert load_hints(path=tmp_path / "does_not_exist.json") == []
