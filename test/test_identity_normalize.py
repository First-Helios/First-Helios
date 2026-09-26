"""Unit tests for the pure identity-matching helpers (no DB, no network)."""

from __future__ import annotations

import pytest

from packages.helios_core.identity.normalize import (
    haversine_m,
    name_fingerprint,
    normalize_address,
    normalize_name,
    within_radius_m,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Torchy's Tacos", "torchys tacos"),
        ("  Franklin   Barbecue ", "franklin barbecue"),
        ("Veracruz All-Natural", "veracruz all natural"),
        ("Café Crème", "cafe creme"),
        ("P. Terry's Burger Stand #12", "p terrys burger stand 12"),
        ("", ""),
        ("!!!", ""),
    ],
)
def test_normalize_name_is_stable_and_conservative(raw: str, expected: str) -> None:
    assert normalize_name(raw) == expected
    # Idempotent: normalizing an already-normalized name changes nothing.
    assert normalize_name(normalize_name(raw)) == expected


def test_name_fingerprint_matches_across_punctuation_and_case() -> None:
    assert name_fingerprint("Torchy's Tacos") == name_fingerprint("TORCHYS TACOS")
    assert name_fingerprint("Home Slice Pizza") == name_fingerprint("home-slice pizza")


def test_name_fingerprint_keeps_distinct_names_distinct() -> None:
    # Conservative: it does not collapse different brands together.
    assert name_fingerprint("Home Slice Pizza") != name_fingerprint("Home Slice Cafe")
    assert name_fingerprint("Torchys Tacos") != name_fingerprint("Torchys Burgers")


# R18: non-English letters are kept; only accents (combining marks) are stripped.
@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("Chinese Restaurant 金龍", "Chinese Restaurant 福州"),
        ("Đông Phương", "Ông Phương"),
        ("Pho Ha Noi Ørsted", "Pho Ha Noi rsted"),
        ("مطعم الأمير", "مطعم الأميرة"),
        ("Ταβέρνα Ζορμπάς", "Ταβέρνα Μύθος"),
        ("Taj किताब", "Taj"),
    ],
)
def test_name_fingerprint_keeps_non_english_letters(a: str, b: str) -> None:
    assert name_fingerprint(a) != name_fingerprint(b)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("金龍", "金龍"),  # all-CJK: normalized, not the raw-string fallback
        ("Chinese Restaurant 金龍", "chinese restaurant 金龍"),
        ("Đông Phương", "dong phuong"),
        ("Smørrebrød", "smorrebrod"),
        ("Łódź Pierogi", "lodz pierogi"),
        ("Æble Œuvre", "aeble oeuvre"),
        ("Straße", "strasse"),
        ("Kırmızı İskender", "kirmizi iskender"),
        ("Þór's Hús", "thors hus"),
        ("ΤΑΒΕΡΝΑΣ", "ταβερνασ"),  # final and medial sigma fold together
        ("ταβέρνας", "ταβερνασ"),
        ("مَطْعَم", "مطعم"),  # Arabic harakat are marks, stripped like accents
        ("ＡＢＣ　Ｃａｆｅ", "abc cafe"),  # fullwidth compatibility forms
        ("Caf­e Bar", "cafe bar"),  # soft hyphen is invisible, not a break
        ("🍕🍕", ""),
    ],
)
def test_normalize_name_unicode_letters(raw: str, expected: str) -> None:
    assert normalize_name(raw) == expected
    assert normalize_name(normalize_name(raw)) == expected


@pytest.mark.parametrize(
    "variant",
    ["Torchy's Tacos", "Torchy’s Tacos", "Torchyʼs Tacos", "Torchy´s Tacos", "Torchy＇s Tacos"],
)
def test_apostrophe_variants_are_elided(variant: str) -> None:
    assert name_fingerprint(variant) == "torchys tacos"


def test_indic_vowel_signs_stay_inside_the_word() -> None:
    # Spacing vowel signs are marks with combining class 0: part of the letter,
    # not accents, so they must not become word breaks.
    assert " " not in normalize_name("किताब")


def test_normalize_name_is_idempotent_across_the_bmp() -> None:
    for code_point in range(0x10000):
        if 0xD800 <= code_point <= 0xDFFF:
            continue
        once = normalize_name(f"a{chr(code_point)}b")
        assert normalize_name(once) == once, hex(code_point)


def test_normalize_address_normalizes_like_a_name() -> None:
    assert normalize_address("1311 S. 1st St, Austin, TX") == "1311 s 1st st austin tx"


def test_haversine_known_short_distance() -> None:
    # ~0.001 deg of latitude is ~111.2 m at any longitude.
    assert haversine_m(30.0, -97.0, 30.001, -97.0) == pytest.approx(111.2, abs=1.0)


def test_haversine_is_symmetric_and_zero_on_identity() -> None:
    assert haversine_m(30.2672, -97.7431, 30.2672, -97.7431) == pytest.approx(0.0, abs=1e-6)
    a = haversine_m(30.27, -97.74, 30.51, -97.68)
    b = haversine_m(30.51, -97.68, 30.27, -97.74)
    assert a == pytest.approx(b, rel=1e-9)


def test_within_radius_respects_the_boundary() -> None:
    # Two points ~33 m apart (0.0003 deg lat).
    assert within_radius_m(30.0, -97.0, 30.0003, -97.0, 50.0)
    assert not within_radius_m(30.0, -97.0, 30.0003, -97.0, 25.0)
