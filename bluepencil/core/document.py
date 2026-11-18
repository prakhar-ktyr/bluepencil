# SPDX-FileCopyrightText: 2026 Prakhar Katiyar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Opening a PDF and describing its pages. Runs in the engine process."""

import os
from pathlib import Path

import pymupdf

# Why a file could not be opened. The interface turns these into messages.
NOT_FOUND = "not-found"
NO_PERMISSION = "no-permission"
DAMAGED = "damaged"
NOT_PDF = "not-pdf"
NEEDS_PASSWORD = "needs-password"
WRONG_PASSWORD = "wrong-password"
NO_PAGES = "no-pages"


class OpenError(Exception):
    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail


def open_document(path: str, password: str | None = None) -> pymupdf.Document:
    """Open `path` as a PDF, unlocking it with `password` if it has one."""
    if not Path(path).exists():
        raise OpenError(NOT_FOUND, path)
    if not os.access(path, os.R_OK):
        raise OpenError(NO_PERMISSION, path)
    try:
        document = pymupdf.open(path, filetype="pdf")
    except (RuntimeError, ValueError, OSError) as error:
        raise OpenError(DAMAGED, str(error)) from error
    # The library also reads images, e-books and other formats, and goes by
    # the content whatever the requested type: Bluepencil is a PDF app.
    if not document.is_pdf:
        document.close()
        raise OpenError(NOT_PDF)
    if document.needs_pass:
        if password is None:
            document.close()
            raise OpenError(NEEDS_PASSWORD)
        if not document.authenticate(password):
            document.close()
            raise OpenError(WRONG_PASSWORD)
    if document.page_count == 0:
        document.close()
        raise OpenError(NO_PAGES)
    return document


def describe(document: pymupdf.Document) -> dict:
    """What the interface needs to lay the document out."""
    return {
        "page_count": document.page_count,
        # Sizes in points, as shown on screen: rotation and cropping applied.
        "pages": [[page.rect.width, page.rect.height] for page in document.pages()],
        "repaired": bool(document.is_repaired),
        "title": (document.metadata or {}).get("title") or "",
    }
