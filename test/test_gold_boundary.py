"""Drawn-area boundaries (ADR-0020 §1): the parser's rules and exact even-odd ray casting."""

from __future__ import annotations

from decimal import Decimal

import pytest

from packages.helios_core.gold.price_index import (
    GRID_STEPS,
    Boundary,
    BoundaryError,
    grid_cell,
    parse_boundary,
)

D = Decimal
SQUARE = "30.25,-97.75;30.30,-97.75;30.30,-97.70;30.25,-97.70"


# --------------------------------------------------------------------------- #
# Parser.
# --------------------------------------------------------------------------- #


def test_parse_keeps_the_corners_in_order() -> None:
    boundary = parse_boundary(SQUARE)
    assert boundary.corners == (
        (D("30.25"), D("-97.75")),
        (D("30.30"), D("-97.75")),
        (D("30.30"), D("-97.70")),
        (D("30.25"), D("-97.70")),
    )
    assert (boundary.south, boundary.north, boundary.west, boundary.east) == (
        D("30.25"),
        D("30.30"),
        D("-97.75"),
        D("-97.70"),
    )


def test_a_closing_corner_is_dropped() -> None:
    assert parse_boundary(SQUARE + ";30.25,-97.75") == parse_boundary(SQUARE)
    # Only a final repeat of the first corner; a triangle closed into four corners is three.
    assert len(parse_boundary("0,0;1,0;1,1;0,0").corners) == 3
    with pytest.raises(BoundaryError, match="3-50 corners"):
        parse_boundary("0,0;1,1;0,0")  # two corners once closed


@pytest.mark.parametrize(
    "text",
    [
        "0,0;0,1;1,0",  # three corners, integers
        "-90,-180;-89,-180;-89,-179",  # the range's ends
        "90,180;89,180;89,179",
        "-0,0;0,1;1,0",  # -0 is 0
        "30.123456,-97.123456;30.2,-97.1;30.1,-97.2",  # six decimals
        ";".join(f"{i / 1000:.3f},{(i * 7 % 50) / 1000:.3f}" for i in range(50)),  # 50 corners
        "0,0;0,2;2,2;2,0",  # a 2° x 2° bbox, the most allowed
        "0,0;1,1;0,1;1,0",  # crosses itself (a bowtie)
        "0,0;1,1;0.5,0.5",  # zero area
        "0,0;0,0;1,1",  # a repeated corner
    ],
)
def test_accepted(text: str) -> None:
    parse_boundary(text)


def test_minus_zero_is_zero() -> None:
    (lat, lon), *_ = parse_boundary("-0,-0.0;0,1;1,0").corners
    assert (str(lat), str(lon)) == ("0", "0.0")


@pytest.mark.parametrize(
    ("text", "rule"),
    [
        ("", "lat,lon"),
        ("0,0;0,1", "3-50 corners"),
        ("0,0;0,1;1,0;", "lat,lon"),  # a trailing separator is an empty corner
        (";".join(f"{i / 1000:.3f},0" for i in range(51)), "3-50 corners"),
        ("0,0,0;0,1;1,0", "lat,lon"),
        ("0;0,1;1,0", "lat,lon"),
        ("0 ,0;0,1;1,0", "plain decimal"),
        (" 0,0;0,1;1,0", "plain decimal"),
        ("+1,0;0,1;1,0", "plain decimal"),
        ("1e1,0;0,1;1,0", "plain decimal"),
        ("1.,0;0,1;1,0", "plain decimal"),
        (".5,0;0,1;1,0", "plain decimal"),
        ("0.1234567,0;0,1;1,0", "plain decimal"),
        ("NaN,0;0,1;1,0", "plain decimal"),
        ("Infinity,0;0,1;1,0", "plain decimal"),
        ("1000,0;0,1;1,0", "plain decimal"),
        ("٣,0;0,1;1,0", "plain decimal"),  # a non-ASCII digit
        ("90.000001,0;0,1;1,0", r"latitude must be in \[-90, 90\]"),
        ("0,180.000001;0,1;1,0", r"longitude must be in \[-180, 180\]"),
        ("-91,0;0,1;1,0", "latitude"),
        ("0,0;0,2.000001;1,0", "at most 2°"),
        ("0,0;2.000001,0;1,1", "at most 2°"),
        ("0," * 601, "at most 1200 characters"),
    ],
)
def test_rejected_with_the_rule_named(text: str, rule: str) -> None:
    with pytest.raises(BoundaryError, match=rule):
        parse_boundary(text)


def test_the_longest_boundary_fits_the_length_cap() -> None:
    corner = "-89.123456,-179.123456"
    corners = [corner.replace("456", f"{n:03d}") for n in range(49)]
    text = ";".join([*corners, corner])
    assert len(text) <= 1200
    assert len(parse_boundary(text).corners) == 50


# --------------------------------------------------------------------------- #
# Ray casting.
# --------------------------------------------------------------------------- #


def _inside(boundary: Boundary, lat: str, lon: str) -> bool:
    return boundary.contains(D(lat), D(lon))


def test_a_rectangle_is_half_open_like_a_grid_cell() -> None:
    square = parse_boundary(SQUARE)
    # South and west edges in, north and east out, corners included.
    assert _inside(square, "30.25", "-97.75")
    assert _inside(square, "30.25", "-97.72")
    assert _inside(square, "30.27", "-97.75")
    assert _inside(square, "30.299999", "-97.700001")
    assert not _inside(square, "30.30", "-97.72")
    assert not _inside(square, "30.27", "-97.70")
    assert not _inside(square, "30.30", "-97.70")
    assert not _inside(square, "30.249999", "-97.72")
    assert not _inside(square, "30.27", "-97.750001")
    # The same in either orientation and from any starting corner.
    reverse = Boundary(tuple(reversed(square.corners)))
    rotated = Boundary(square.corners[2:] + square.corners[:2])
    for point in [("30.25", "-97.75"), ("30.30", "-97.72"), ("30.27", "-97.70")]:
        assert _inside(reverse, *point) == _inside(rotated, *point) == _inside(square, *point)


@pytest.mark.parametrize(
    "point",
    [
        (D("30.25"), D("-97.75")),
        (D("30.299999"), D("-97.700001")),
        (D("30.267153"), D("-97.743057")),
        (D("30.30"), D("-97.70")),
        (D("30.30"), D("-97.75")),
        (D("30.25"), D("-97.70")),
        (D("30.249999"), D("-97.750001")),
    ],
)
def test_a_cell_drawn_as_a_rectangle_holds_exactly_its_points(point: tuple[D, D]) -> None:
    step = GRID_STEPS["latlon_grid_0p05"]
    square = parse_boundary(SQUARE)
    assert square.contains(*point) == (grid_cell(*point, step)[0] == "30.25,-97.75")


def test_a_triangle_uses_exact_arithmetic() -> None:
    # The west edge runs from (0, 0) to (1.5, 0.5): longitude = latitude / 3 on
    # it, which no finite decimal states exactly at latitude 0.5.
    triangle = parse_boundary("0,0;1.5,0.5;0,0.5")
    assert _inside(triangle, "0.5", "0.166667")  # just east of the edge
    assert not _inside(triangle, "0.5", "0.166666")  # just west of it
    # A point exactly on a west edge is inside, as on a rectangle's west edge.
    assert _inside(triangle, "0.75", "0.25")
    assert not _inside(triangle, "0.75", "0.249999")


def test_even_odd_on_a_self_crossing_boundary() -> None:
    # A pentagram drawn in one stroke: the points are wrapped once, the centre twice.
    pentagram = parse_boundary("1,0.5;0.2,0.8;0.7,0.1;0.7,0.9;0.2,0.2")
    assert _inside(pentagram, "0.85", "0.5")  # a tip: once
    assert not _inside(pentagram, "0.5", "0.5")  # the centre: twice
    assert not _inside(pentagram, "0.1", "0.5")  # outside
    bowtie = parse_boundary("0,0;1,1;0,1;1,0")
    assert _inside(bowtie, "0.5", "0.2")
    assert _inside(bowtie, "0.5", "0.8")
    assert not _inside(bowtie, "0.2", "0.5")


def test_a_zero_area_boundary_holds_nothing() -> None:
    line = parse_boundary("0,0;1,1;0.5,0.5")
    point = parse_boundary("2,2;2,2;2,2;2,2.000001")  # the closing repeat is not last
    for lat, lon in [("0", "0"), ("0.5", "0.5"), ("0.5", "0.4"), ("2", "2"), ("1", "1")]:
        assert not _inside(line, lat, lon)
        assert not _inside(point, lat, lon)
