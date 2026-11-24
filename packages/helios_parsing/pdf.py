"""PDF menus as HTML: the ``pdf-v2`` reader (ADR-0029 D3).

A PDF with a text layer is read page by page with ``pypdf``'s plain extraction (plain keeps a
multi-column menu's reading order; layout mode sets the columns side by side on one line), except
a page plain mode breaks into one word per line, which is read in layout mode. Each
non-empty line becomes one ``<p>`` of a minimal HTML document, pages separated by ``<hr>``, so
the existing segmenter (``segment-v2``) reads it and everything after it is unchanged: the page
check, the bundle (``body`` = the PDF bytes, ``rendered_dom`` = this document), chunking,
extraction, the validator, [5b]-[5d] and Gold.

``PDF_READER_VERSION`` names this output: a change to the document ``read_pdf`` returns for the
same bytes needs a new version. A file ``pypdf`` can't open, or an encrypted one, is
``pdf_unreadable``; a short text layer is accepted when a page has letters and a marked price. Other
short documents are ``pdf_no_text``. Only the first :data:`MAX_PAGES` pages are read;
the fetch's body cap (3 MB) bounds the input.
"""

from __future__ import annotations

import html
import logging
import re
from dataclasses import dataclass
from io import BytesIO
from typing import Literal

from pypdf import PageObject, PdfReader

PDF_READER_VERSION = "pdf-v2"
_MARKED_PRICE = re.compile(r"\$\s*\d")
MAX_PAGES = 40
MIN_TEXT_CHARS = 200
# A page whose plain text is mostly one word per line (a file that places every word on its own)
# is read in layout mode instead: at least this many non-empty lines, this share single words.
FRAGMENTED_MIN_LINES = 30
FRAGMENTED_SHARE = 0.8

PdfFailure = Literal["pdf_unreadable", "pdf_no_text"]


@dataclass(frozen=True, slots=True)
class PdfDocument:
    """A PDF's text as the HTML document the segmenter reads."""

    html: str
    pages: int  # pages read (at most MAX_PAGES)
    chars: int  # characters of text on them, whitespace excluded


def is_pdf(content_type: str, body: bytes | None) -> bool:
    """A PDF response: an ``application/pdf`` type, or ``%PDF-`` magic under any type."""
    return "pdf" in content_type.lower() or (body or b"").startswith(b"%PDF-")


def pdf_html(pages: list[list[str]]) -> str:
    """The document for ``pages`` (each a list of text lines): one ``<p>`` per non-empty line,
    whitespace collapsed, ``<hr>`` between pages."""
    parts = []
    for number, lines in enumerate(pages):
        if number:
            parts.append("<hr>")
        parts.extend(
            f"<p>{html.escape(text, quote=False)}</p>"
            for line in lines
            if (text := " ".join(line.split()))
        )
    return "<!doctype html><html><body>" + "".join(parts) + "</body></html>"


def _fragmented(lines: list[str]) -> bool:
    """Plain text that is mostly one word per line (:data:`FRAGMENTED_SHARE`)."""
    words = [len(line.split()) for line in lines if line.strip()]
    return len(words) >= FRAGMENTED_MIN_LINES and sum(
        n == 1 for n in words
    ) >= FRAGMENTED_SHARE * len(words)


def _page_lines(page: PageObject) -> list[str]:
    lines = (page.extract_text(extraction_mode="plain") or "").splitlines()
    if _fragmented(lines):
        lines = (page.extract_text(extraction_mode="layout") or "").splitlines()
    return lines


def read_pdf(body: bytes) -> PdfDocument | PdfFailure:
    """``body``'s text layer as a :class:`PdfDocument`, or why it can't be read."""
    # pypdf logs recoverable oddities (font encodings, broken xref tables) as warnings; the
    # outcome is what counts here
    logging.getLogger("pypdf").setLevel(logging.ERROR)
    try:
        reader = PdfReader(BytesIO(body))
        if reader.is_encrypted:
            return "pdf_unreadable"
        pages = [_page_lines(page) for page in reader.pages[:MAX_PAGES]]
    except Exception:  # noqa: BLE001 - a malformed file raises anything; it is unreadable
        return "pdf_unreadable"
    chars = sum(len("".join(line.split())) for lines in pages for line in lines)
    if chars < MIN_TEXT_CHARS and not any(
        any(_MARKED_PRICE.search(line) for line in lines)
        and any(any(c.isalpha() for c in line) for line in lines)
        for lines in pages
    ):
        return "pdf_no_text"
    return PdfDocument(html=pdf_html(pages), pages=len(pages), chars=chars)
