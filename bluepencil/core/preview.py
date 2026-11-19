# SPDX-FileCopyrightText: 2026 Prakhar Katiyar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""What a file to combine holds, and a small picture of its first page.

The Combine list shows these before anything is combined, and points out the
files that cannot be: locked, damaged, or neither a PDF nor a picture. Files
are read here the same way combining reads them (pages.insert_files), so the
list and the result agree. Runs in the engine process.
"""

from pathlib import Path

import pymupdf

from .document import OpenError, open_document
from .pages import NOT_READABLE_AS_PDF, UNSUPPORTED_FILE, PageError, image_turn

#: Kinds of file.
PDF = "pdf"
PICTURE = "picture"


def inspect(path: str, password: str | None = None, size: int = 96) -> tuple[dict, bytes]:
    """Describe `path`, with its first page drawn at most `size` pixels wide
    and high, as RGB.

    Raises OpenError or PageError for a file that combining would refuse.
    """
    try:
        document = open_document(path, password)
    except OpenError as error:
        if error.code not in NOT_READABLE_AS_PDF:
            raise  # missing, unreadable, or locked
        return _picture(path, size, error)
    try:
        page = document[0]
        scale = size / max(page.rect.width, page.rect.height, 1)
        pixmap = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False)
        return {"kind": PDF, "pages": document.page_count, **_describe(pixmap)}, pixmap.samples
    finally:
        document.close()


def _picture(path: str, size: int, not_pdf: OpenError) -> tuple[dict, bytes]:
    try:
        picture = pymupdf.Pixmap(path)  # as pages.insert_image reads it
    except (RuntimeError, ValueError, pymupdf.mupdf.FzErrorBase) as error:
        raise PageError(UNSUPPORTED_FILE, f"{Path(path).name}: {not_pdf.code}") from error
    scale = min(1.0, size / max(picture.width, picture.height, 1))
    width, height = max(1, round(picture.width * scale)), max(1, round(picture.height * scale))
    small = pymupdf.Pixmap(picture, width, height, None)
    turn = image_turn(path)
    if turn or small.alpha or small.colorspace is None or small.colorspace.n != 3:
        # Upright, on a white page, as it will look once combined.
        if turn in (90, 270):
            width, height = height, width
        sheet = pymupdf.open()
        try:
            page = sheet.new_page(width=width, height=height)
            page.insert_image(page.rect, pixmap=small, rotate=turn)
            small = page.get_pixmap(alpha=False)
        finally:
            sheet.close()
    return {"kind": PICTURE, "pages": 1, **_describe(small)}, small.samples


def _describe(pixmap: pymupdf.Pixmap) -> dict:
    return {"width": pixmap.width, "height": pixmap.height, "stride": pixmap.stride}
