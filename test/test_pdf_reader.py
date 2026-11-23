"""PDF menus (ADR-0029): the ``pdf-v1`` reader, the D5 table-row rule, and discovery's PDF branch.

PDFs are built here (:func:`pdf_bytes`, ASCII-only, Helvetica text); HTTP is a mock transport.
"""

from __future__ import annotations

from datetime import UTC, datetime
from io import BytesIO
from typing import TYPE_CHECKING

from pypdf import PdfReader, PdfWriter

from apps.discovery.web_client import (
    CaptureFailure,
    MenuPdfLinked,
    MenuUrlDiscovery,
    is_pdf_link,
)
from packages.helios_parsing.pdf import (
    MAX_PAGES,
    PDF_READER_VERSION,
    PdfDocument,
    _fragmented,
    is_pdf,
    pdf_html,
    read_pdf,
)
from packages.helios_parsing.prices import bare_page, price_tokens, table_rows
from packages.helios_parsing.segment import Block, segment
from test.test_web_client import _fetcher

if TYPE_CHECKING:
    from pathlib import Path

MENU_LINES = [
    "DINNER MENU",
    "Starters",
    "Queso Flameado 12",
    "Elote 7",
    "Mains",
    "Carne Asada Plate $24",
    "Enchiladas Verdes $18.50",
    "Desserts",
    "Tres Leches Cake 9",
    "Churros with chocolate 8",
    "Margarita (house) 11",
    "Pollo en Mole Poblano with rice and beans $21",
    "Chile Relleno stuffed with Oaxaca cheese $17",
    "Fish Tacos Ensenada style, cabbage, crema $16",
]


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def pdf_bytes(pages: list[list[str]]) -> bytes:
    """A minimal, valid, ASCII-only PDF: one Helvetica text line per string, a page per list."""
    count = len(pages)
    font = 3 + 2 * count
    objects = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids ["
        + " ".join(f"{3 + 2 * i} 0 R" for i in range(count))
        + f"] /Count {count} >>",
    ]
    for i, lines in enumerate(pages):
        stream = "BT /F1 11 Tf 14 TL 72 760 Td " + " ".join(
            f"({_escape(line)}) Tj T*" for line in lines
        )
        stream += " ET"
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents {4 + 2 * i} 0 R "
            f"/Resources << /Font << /F1 {font} 0 R >> >> >>"
        )
        objects.append(f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream")
    objects.append("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    out = "%PDF-1.4\n"
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n{body}\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n"
    out += "".join(f"{offset:010d} 00000 n \n" for offset in offsets)
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n"
    return out.encode("ascii")


class _WordVerifier:
    """A page is a menu when its HTML says ``MENU`` (the classifier is tested elsewhere)."""

    name = "word-v1"

    def is_menu(self, html: str, url: str, *, trust_path: bool) -> bool:
        del url, trust_path
        return "MENU" in html


def _blocks(*texts: str) -> list[Block]:
    return segment("".join(f"<p>{t}</p>" for t in texts))


# -- the reader ----------------------------------------------------------------------------


def test_read_pdf_turns_each_line_into_a_paragraph_and_pages_into_rules() -> None:
    document = read_pdf(pdf_bytes([MENU_LINES[:6], MENU_LINES[6:]]))
    assert isinstance(document, PdfDocument)
    assert document.pages == 2
    blocks = segment(document.html)
    assert [b.text for b in blocks] == MENU_LINES
    assert document.html.count("<hr>") == 1
    assert PDF_READER_VERSION == "pdf-v1"


def test_read_pdf_refusals() -> None:
    assert read_pdf(b"not a pdf at all") == "pdf_unreadable"
    assert read_pdf(b"%PDF-1.7") == "pdf_unreadable"
    assert read_pdf(pdf_bytes([["Menu", "Tacos 3"]])) == "pdf_no_text"  # an image-only menu
    writer = PdfWriter(clone_from=PdfReader(BytesIO(pdf_bytes([MENU_LINES]))))
    writer.encrypt("secret", algorithm="RC4-128")
    encrypted = BytesIO()
    writer.write(encrypted)
    assert read_pdf(encrypted.getvalue()) == "pdf_unreadable"


def test_read_pdf_reads_at_most_max_pages() -> None:
    document = read_pdf(pdf_bytes([[f"Page {n} dish with a long name {n}"] * 3 for n in range(45)]))
    assert isinstance(document, PdfDocument)
    assert document.pages == MAX_PAGES
    assert "Page 39 " in document.html and "Page 40 " not in document.html


def test_a_page_broken_into_one_word_per_line_is_fragmented() -> None:
    words = [
        "CAP",
        "CITY",
        "COMEDY",
        "CLUB",
        "FOOD",
        "MENU",
        "APPETIZERS",
        "&",
        "BASKETS",
        "CHIPS",
        "&",
        "SALSA",
        "A",
        "mild",
        "salsa",
    ]
    broken = [line for word in words * 3 for line in (word, " ")]
    assert _fragmented(broken)  # read in layout mode instead
    assert not _fragmented(broken[:20])  # too short to judge
    assert not _fragmented(MENU_LINES * 3)


def test_pdf_html_escapes_and_collapses_whitespace() -> None:
    assert pdf_html([["  Fish  &  Chips <b> 12 ", "", "   "]]) == (
        "<!doctype html><html><body><p>Fish &amp; Chips &lt;b&gt; 12</p></body></html>"
    )


def test_is_pdf_and_pdf_links() -> None:
    assert is_pdf("application/pdf", b"")
    assert is_pdf("application/octet-stream", b"%PDF-1.4 ...")
    assert not is_pdf("text/html", b"<html>")
    assert is_pdf_link("https://k.com/s/Menu.PDF?v=2")
    assert not is_pdf_link("https://k.com/menu")


# -- D5: a numeric table's row printed as one block (validator-v13) -----------------------------


def test_v13_a_number_row_block_gives_no_bare_reading() -> None:
    blocks = _blocks(
        "Chicken Alfredo",
        "1570 870 97 56 2 300 2400 103 6 7 79",
        "Lasagna Classico",
        "240 230 26 4.5 0 15 740 2 0 less than 1 g 1",
        "Breadstick 140",
        "1 2 3 4 5 6 7 8 9 10 11 12",
    )
    assert table_rows(blocks) == frozenset({1, 3, 5})
    tokens = price_tokens(blocks)
    assert [len(row) for row in tokens] == [0, 0, 0, 0, 1, 0]
    assert tokens[4][0].amount == 140


def test_v13_keeps_money_and_priced_lines_with_a_few_counts() -> None:
    blocks = _blocks(
        "12.50 13.50 14.50 15.50 16.50 17.50",  # a row of decimal prices: money still reads
        "Party Pack 12 tacos 2 queso 1 rice 1 beans 1 salsa 45",  # numbers under two thirds
        "Wings 6 10 20",  # under six numbers
    )
    assert table_rows(blocks) == frozenset({0})  # a row, but its money is kept
    tokens = price_tokens(blocks)
    assert [str(t.amount) for t in tokens[0]] == [
        "12.50",
        "13.50",
        "14.50",
        "15.50",
        "16.50",
        "17.50",
    ]
    assert [(str(t.amount), t.kind) for t in tokens[1]] == [("45", "bare")]
    assert [(str(t.amount), t.kind) for t in tokens[2]] == [("20", "bare")]


def test_v13_number_rows_do_not_vote_in_bare_page() -> None:
    rows = ["Dish A", "Dish B", "Dish C", "Dish D"]
    blocks = _blocks("Burger $12", *(f"{r}</p><p>{n}10 20 30 40 50 60" for n, r in enumerate(rows)))
    assert table_rows(blocks)
    assert not bare_page(blocks)


# -- discovery reads a linked menu PDF (ADR-0029 D2) ----------------------------------------


def test_discovery_takes_a_linked_menu_pdf_through_a_cdn_redirect(tmp_path: Path) -> None:
    pdf = pdf_bytes([MENU_LINES]).decode("ascii")
    routes = {
        "https://k.com/": (200, '<a href="/s/Dinner-Menu.pdf">Dinner menu</a>', "text/html"),
        "https://k.com/s/Dinner-Menu.pdf": (302, "https://cdn.example/files/dinner.pdf", ""),
        "https://cdn.example/files/dinner.pdf": (200, pdf, "application/pdf"),
    }
    with _fetcher(tmp_path, routes, page_check=_WordVerifier()) as fetcher:
        found = fetcher.discover_menu_attempt("https://k.com/")
    assert isinstance(found, tuple)
    (menu,) = found
    assert isinstance(menu, MenuUrlDiscovery)
    assert (menu.menu_url, menu.signal, menu.found_via) == (
        "https://k.com/s/Dinner-Menu.pdf",
        "pdf",
        "https://k.com/",
    )
    assert menu.page_html is not None and "<p>Carne Asada Plate $24</p>" in menu.page_html


def test_a_pdf_link_with_spaces_is_percent_encoded(tmp_path: Path) -> None:
    pdf = pdf_bytes([MENU_LINES]).decode("ascii")
    routes = {
        "https://k.com/": (200, '<a href="/menu nutritional info.pdf">Menu</a>', "text/html"),
        "https://k.com/menu%20nutritional%20info.pdf": (200, pdf, "application/pdf"),
    }
    with _fetcher(tmp_path, routes, page_check=_WordVerifier()) as fetcher:
        found = fetcher.discover_menu_attempt("https://k.com/")
    assert isinstance(found, tuple)
    (menu,) = found
    assert isinstance(menu, MenuUrlDiscovery)
    assert menu.menu_url == "https://k.com/menu%20nutritional%20info.pdf"


def test_a_pdf_link_obeys_the_cdn_hosts_robots(tmp_path: Path) -> None:
    pdf = pdf_bytes([MENU_LINES]).decode("ascii")
    routes = {
        "https://k.com/": (200, '<a href="/s/menu.pdf">Menu</a>', "text/html"),
        "https://k.com/s/menu.pdf": (302, "https://cdn.example/files/menu.pdf", ""),
        "https://cdn.example/robots.txt": (200, "User-agent: *\nDisallow: /files/", "text/plain"),
        "https://cdn.example/files/menu.pdf": (200, pdf, "application/pdf"),
    }
    with _fetcher(tmp_path, routes, page_check=_WordVerifier()) as fetcher:
        found = fetcher.discover_menu_attempt("https://k.com/")
    assert found == (MenuPdfLinked("https://k.com/s/menu.pdf"),)  # unfetched: menu_pdf_only


def test_an_html_link_still_refuses_a_cross_host_redirect(tmp_path: Path) -> None:
    routes = {"https://k.com/menu": (302, "https://other.example/menu", "")}
    with _fetcher(tmp_path, routes, page_check=_WordVerifier()) as fetcher:
        refused = fetcher.fetch_page("https://k.com/menu")
    assert isinstance(refused, CaptureFailure)
    assert refused.reason_code == "redirect_refused"


def test_a_pdf_link_that_leaves_its_site_must_end_in_a_pdf(tmp_path: Path) -> None:
    routes = {
        "https://k.com/s/menu.pdf": (302, "https://other.example/menu", ""),
        "https://other.example/menu": (200, "<h1>MENU</h1><p>Tacos $3</p>", "text/html"),
    }
    with _fetcher(tmp_path, routes, page_check=_WordVerifier()) as fetcher:
        refused = fetcher.fetch_page("https://k.com/s/menu.pdf")
    assert isinstance(refused, CaptureFailure)
    assert refused.reason_code == "redirect_refused"


def test_discovery_reports_why_a_linked_pdf_was_not_read(tmp_path: Path) -> None:
    routes = {
        "https://k.com/": (200, '<a href="/menu.pdf">Menu</a>', "text/html"),
        "https://k.com/menu.pdf": (200, "<html>moved</html>", "text/html"),
        "https://j.com/": (200, '<a href="/menu.pdf">Menu</a>', "text/html"),
        "https://j.com/menu.pdf": (200, pdf_bytes([["MENU"]]).decode("ascii"), "application/pdf"),
        "https://n.com/": (200, '<a href="/files/menu.pdf">Menu</a>', "text/html"),
        "https://n.com/files/menu.pdf": (
            200,
            pdf_bytes([["Nutrition facts", "Serving size and calories for every item"] * 9]).decode(
                "ascii"
            ),
            "application/pdf",
        ),
    }
    with _fetcher(tmp_path, routes, page_check=_WordVerifier()) as fetcher:
        assert fetcher.discover_menu_attempt("https://k.com/") == (
            MenuPdfLinked("https://k.com/menu.pdf", "not_pdf"),
        )
        assert fetcher.discover_menu_attempt("https://j.com/") == (
            MenuPdfLinked("https://j.com/menu.pdf", "pdf_no_text"),
        )
        # read, but the page check finds no menu in it
        assert fetcher.discover_menu_attempt("https://n.com/") == (
            MenuPdfLinked("https://n.com/files/menu.pdf"),
        )


def test_reverification_reads_a_saved_pdf_menu_afresh(tmp_path: Path) -> None:
    pdf = pdf_bytes([MENU_LINES]).decode("ascii")
    routes = {
        "https://k.com/": (200, "<p>Home</p>", "text/html"),
        "https://cdn.example/menu.pdf": (200, pdf, "application/pdf"),
    }
    with _fetcher(tmp_path, routes, page_check=_WordVerifier()) as fetcher:
        checked = fetcher.verify_menu_attempt(
            "https://k.com/",
            "https://cdn.example/menu.pdf",
            not_before=datetime(2000, 1, 1, tzinfo=UTC),
        )
    assert isinstance(checked, MenuUrlDiscovery)
    assert (checked.menu_url, checked.signal) == ("https://cdn.example/menu.pdf", "pdf")
