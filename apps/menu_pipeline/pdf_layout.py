"""Inspect a confirmed menu page offline. Return text lines and word boxes in page order."""

from __future__ import annotations

import argparse
import csv
import io
import json
import re
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any


def _output(args: list[str]) -> str:
    return subprocess.run(args, capture_output=True, check=True, text=True, timeout=90).stdout  # noqa: S603 - fixed executable and argument list


def _priced_rows(lines: list[list[dict[str, Any]]]) -> list[dict[str, Any]]:
    """Join horizontally separated cells only on aligned, non-overlapping text rows."""
    words = sorted((w for line in lines for w in line), key=lambda w: sum(w["box"][1::2]))
    bands: list[list[dict[str, Any]]] = []
    for word in words:
        _, top, _, bottom = word["box"]
        if bands:
            _, y0, _, y1 = bands[-1][0]["box"]
            if min(bottom, y1) - max(top, y0) >= 0.65 * max(bottom - top, y1 - y0):
                bands[-1].append(word)
                continue
        bands.append([word])
    rows = []
    headers: list[dict[str, Any]] = []
    for band in bands:
        cells = sorted(band, key=lambda w: w["box"][0])
        sizes = [w for w in cells if str(w["text"]).lower() in {"small", "medium", "large"}]
        if len(sizes) >= 2 and len(sizes) == len(cells):
            headers = sizes
            continue
        prices = [w for w in cells if re.fullmatch(r"\$\d+(?:\.\d{2})?", str(w["text"]))]
        if not prices:
            headers = []
            continue
        names = cells[: -len(prices)]
        if (
            not names
            or cells[-len(prices) :] != prices
            or not any(c.isalpha() for w in names for c in str(w["text"]))
        ):
            continue
        if len(prices) > 1 and (
            len(prices) != len(headers)
            or any(
                min(p["box"][2], h["box"][2]) <= max(p["box"][0], h["box"][0])
                for p, h in zip(prices, headers, strict=True)
            )
        ):
            continue
        rows.append(
            {
                "name_words": names,
                "prices": [
                    {"word": price, "variant": headers[i] if len(prices) > 1 else None}
                    for i, price in enumerate(prices)
                ],
            }
        )
    return rows


def page_lines(source: Path, page: int, *, ocr: bool = False) -> dict[str, Any]:
    if page < 1:
        raise ValueError("page must be positive")
    path = str(source.resolve(strict=True))
    lines: list[list[dict[str, Any]]] = []
    if ocr:
        with tempfile.TemporaryDirectory() as folder:
            image = Path(folder) / "page"
            if source.suffix.lower() == ".pdf":
                _output(
                    [
                        "pdftoppm",
                        "-png",
                        "-scale-to",
                        "2400",
                        "-singlefile",
                        "-f",
                        str(page),
                        "-l",
                        str(page),
                        path,
                        str(image),
                    ]
                )
                path = str(image.with_suffix(".png"))
            elif page != 1:
                raise ValueError("an image has one page")
            tsv = _output(["tesseract", path, "stdout", "tsv"])
        groups: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
        for row in csv.DictReader(io.StringIO(tsv), delimiter="\t", quoting=csv.QUOTE_NONE):
            if row["level"] == "5" and row["text"].strip():
                x, y, w, h = (int(row[k]) for k in ("left", "top", "width", "height"))
                groups.setdefault((row["block_num"], row["par_num"], row["line_num"]), []).append(
                    {"text": row["text"], "box": [x, y, x + w, y + h]}
                )
        lines.extend(groups.values())
    else:
        xml = _output(["pdftotext", "-bbox-layout", "-f", str(page), "-l", str(page), path, "-"])
        root = ET.fromstring(xml)  # noqa: S314 - XML serialized by local pdftotext
        for line in root.findall(".//{*}line"):
            lines.append(
                [
                    {
                        "text": word.text,
                        "box": [float(word.attrib[k]) for k in ("xMin", "yMin", "xMax", "yMax")],
                    }
                    for word in line.findall("{*}word")
                ]
            )
    return {
        "page": page,
        "units": "pixels" if ocr else "points",
        "lines": lines,
        "priced_rows": _priced_rows(lines),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file", type=Path)
    parser.add_argument("--page", type=int, default=1)
    parser.add_argument("--ocr", action="store_true")
    args = parser.parse_args()
    print(json.dumps(page_lines(args.file, args.page, ocr=args.ocr), ensure_ascii=False))


if __name__ == "__main__":
    main()
