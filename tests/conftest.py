# SPDX-FileCopyrightText: 2026 Prakhar Katiyar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Fixtures for every test. PDFs are generated, so no sample files are needed."""

import os

import pymupdf
import pytest

# Desktop settings start from their defaults in tests, whatever the
# developer's own desktop is set to. GLib reads this once, at first use.
os.environ["GSETTINGS_BACKEND"] = "memory"


@pytest.fixture(autouse=True)
def private_state(tmp_path, monkeypatch):
    """Keep the app's state and cache, such as recent files and snapshots,
    inside each test's folder."""
    state = tmp_path / "state"
    monkeypatch.setenv("XDG_STATE_HOME", str(state))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    return state


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
