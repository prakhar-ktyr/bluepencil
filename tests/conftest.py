# SPDX-FileCopyrightText: 2026 Prakhar Katiyar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Fixtures for every test. PDFs are generated, so no sample files are needed."""

import pymupdf
import pytest


@pytest.fixture
def make_pdf(tmp_path):
    """Return a function that writes a small PDF and returns its path."""

    def make(name="sample.pdf", pages=3, size=(595, 842), sizes=None, password=None):
        document = pymupdf.open()
        for index in range(pages):
            width, height = sizes[index] if sizes else size
            page = document.new_page(width=width, height=height)
            page.draw_rect(pymupdf.Rect(36, 36, width - 36, height - 36), color=(0.2, 0.3, 0.8), width=2)
            page.insert_text((72, 110), f"Page {index + 1}", fontsize=36)
        path = tmp_path / name
        options = {}
        if password is not None:
            options = {
                "encryption": pymupdf.mupdf.PDF_ENCRYPT_AES_256,
                "user_pw": password,
                "owner_pw": password + "-owner",
            }
        document.save(path, **options)
        document.close()
        return path

    return make
