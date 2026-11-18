# SPDX-FileCopyrightText: 2026 Prakhar Katiyar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Sample files for the benchmarks, made once and kept in build/bench/.

It runs as a separate process, so that the PDF library never loads into the
process whose interface is being measured.
"""

import random
import sys
from pathlib import Path

import pymupdf

TEXT_PAGES = 500
SCAN_PAGES = 30
#: Each scanned page is a photo at this resolution, like a scanner makes.
SCAN_DPI = 300

_TEXT = (
    "the tenant agrees to pay rent on the first day of each month and to keep the premises in good "
    "repair while the landlord remains responsible for the structure heating water and electrical "
    "installations as described in the schedule attached to this agreement"
)
_WORDS = _TEXT.split()


def _paragraphs(seed: int, count: int = 9) -> str:
    """Ordinary-looking body text that differs from page to page."""
    words = len(_WORDS)
    paragraphs = []
    for paragraph in range(count):
        start = (seed * 7 + paragraph * 13) % words
        length = 55 + (seed + paragraph) % 30
        text = " ".join(_WORDS[(start + i) % words] for i in range(length))
        paragraphs.append(text.capitalize() + ".")
    return "\n\n".join(paragraphs)


def _text_page(document: pymupdf.Document, number: int, paper: pymupdf.Pixmap | None = None) -> None:
    page = document.new_page(width=595, height=842)  # A4
    if paper is not None:
        tile = 128
        for x in range(0, 595, tile):
            for y in range(0, 842, tile):
                page.insert_image(pymupdf.Rect(x, y, x + tile, y + tile), pixmap=paper)
    page.insert_text((72, 60), f"Section {number // 10 + 1}", fontsize=16, fontname="hebo")
    page.insert_textbox(pymupdf.Rect(72, 80, 523, 780), _paragraphs(number), fontsize=11, fontname="helv")
    page.insert_text((290, 815), str(number + 1), fontsize=9, fontname="helv")


def text_document(path: Path) -> None:
    document = pymupdf.open()
    for number in range(TEXT_PAGES):
        _text_page(document, number)
    document.save(path, garbage=3, deflate=True)
    document.close()


def scanned_document(path: Path) -> None:
    """Pages that are only pictures: a greyscale photo of a text page each.

    The paper has grain, as in a real scan, so that the photos are as large
    and as slow to decode as real ones.
    """
    noise = random.Random(1).randbytes(512 * 512)
    paper = pymupdf.Pixmap(pymupdf.csGRAY, 512, 512, bytes(215 + value % 41 for value in noise), False)
    source = pymupdf.open()
    document = pymupdf.open()
    for number in range(SCAN_PAGES):
        _text_page(source, number, paper)
        photo = source[number].get_pixmap(dpi=SCAN_DPI, colorspace=pymupdf.csGRAY)
        page = document.new_page(width=595, height=842)
        page.insert_image(page.rect, stream=photo.tobytes("jpeg", jpg_quality=80))
    document.save(path, garbage=3, deflate=True)
    document.close()
    source.close()


def main() -> None:
    folder = Path(sys.argv[1])
    folder.mkdir(parents=True, exist_ok=True)
    for name, make in (("text-500.pdf", text_document), ("scan-300dpi.pdf", scanned_document)):
        path = folder / name
        if not path.exists():
            print(f"Making {path.name}…", flush=True)
            temporary = path.with_suffix(".tmp")
            make(temporary)
            temporary.replace(path)


if __name__ == "__main__":
    main()
