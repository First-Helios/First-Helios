"""Unit tests for the config/sources.yaml registry loader and validation."""

from __future__ import annotations

from pathlib import Path

import pytest

from apps.discovery.registry import RegistryEntry, load_registry, parse_registry


def test_parse_valid_registry_normalizes_host_and_canonicalizes_urls() -> None:
    document = {
        "venues": [
            {
                "host": "WWW.Veracruz.com",
                "website": "https://veracruz.com",
                "menu_url": "https://veracruz.com/menu",
                "location_unique": True,
            }
        ]
    }
    registry = parse_registry(document)
    assert registry == {
        "veracruz.com": RegistryEntry(
            host="veracruz.com",
            website="https://veracruz.com/",
            menu_url="https://veracruz.com/menu",
            location_unique=True,
        )
    }


def test_none_and_empty_documents_are_empty_registries() -> None:
    assert parse_registry(None) == {}
    assert parse_registry({"venues": []}) == {}
    assert parse_registry({}) == {}


def test_location_unique_defaults_false() -> None:
    registry = parse_registry({"venues": [{"host": "x.com"}]})
    assert registry["x.com"].location_unique is False


@pytest.mark.parametrize(
    "document",
    [
        {"venues": [{"website": "https://x.com"}]},  # missing host
        {"venues": [{"host": "   "}]},  # blank host
        {"venues": [{"host": "x.com", "website": "ftp://x.com"}]},  # non-http url
        {"venues": [{"host": "x.com", "menu_url": "not a url"}]},  # bad menu url
        {"venues": [{"host": "x.com", "location_unique": "yes"}]},  # non-bool
        {"venues": [{"host": "x.com", "bogus": 1}]},  # unknown key
        {"venues": [{"host": "x.com"}, {"host": "x.com"}]},  # duplicate host
        {"venues": "notalist"},  # venues not a list
        "notamapping",  # top-level not a mapping
    ],
)
def test_malformed_registry_raises(document: object) -> None:
    with pytest.raises(ValueError):
        parse_registry(document)


def test_load_missing_file_is_empty_registry(tmp_path: Path) -> None:
    assert load_registry(tmp_path / "nope.yaml") == {}


def test_load_reads_and_validates_yaml(tmp_path: Path) -> None:
    path = tmp_path / "sources.yaml"
    path.write_text(
        "venues:\n  - host: torchystacos.com\n    menu_url: https://torchystacos.com/menu\n",
        encoding="utf-8",
    )
    registry = load_registry(path)
    assert registry["torchystacos.com"].menu_url == "https://torchystacos.com/menu"
    assert registry["torchystacos.com"].website is None


def test_committed_registry_file_is_valid() -> None:
    """The checked-in config/sources.yaml must always parse (CI guard)."""
    repo_root = Path(__file__).resolve().parents[1]
    assert load_registry(repo_root / "config" / "sources.yaml") == {}
