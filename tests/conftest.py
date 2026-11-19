# SPDX-FileCopyrightText: 2026 Prakhar Katiyar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Fixtures for every test. PDFs are generated, so no sample files are needed."""

import os
import random
import sys
import traceback

import pymupdf
import pytest

# Desktop settings start from their defaults in tests, whatever the
# developer's own desktop is set to. GLib reads this once, at first use.
os.environ["GSETTINGS_BACKEND"] = "memory"
# GTK's accessibility backend for when there is no accessibility bus, as in
# CI: the same in every run, whatever the developer's desktop provides.
os.environ["GTK_A11Y"] = "test"


@pytest.fixture(autouse=True)
def no_errors_in_handlers(monkeypatch):
    """Fail the test if a signal handler or a callback raised. PyGObject only
    prints those errors, through sys.excepthook, and carries on, so a test
    would pass unless it checks exactly what broke."""
    raised: list[str] = []
    monkeypatch.setattr(sys, "excepthook", lambda *error: raised.append("".join(traceback.format_exception(*error))))
    yield
    assert not raised, "an error was raised in a handler:\n" + "\n".join(raised)


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


@pytest.fixture
def photos(tmp_path):
    """Two small pages, each a 300-dpi photo stored without loss, plus a line
    of text: a file that compression should shrink a lot."""
    noise = random.Random(7)
    document = pymupdf.open()
    for number in (1, 2):
        page = document.new_page(width=216, height=288)  # 3 by 4 inches
        picture = pymupdf.Pixmap(pymupdf.csRGB, 900, 1200, noise.randbytes(900 * 1200 * 3), False)
        page.insert_image(page.rect, pixmap=picture)
        page.insert_text((20, 40), f"Page {number}", fontsize=18)
    path = tmp_path / "photos.pdf"
    document.save(path, deflate=True)
    return path


@pytest.fixture
def phone_photo(tmp_path):
    """A JPEG stored 400 wide and 300 high, with a blue band down its left
    edge, tagged to be turned 90 degrees clockwise for viewing, as phones
    store portrait photos. Upright it is 300 wide and 400 high, the band on
    top."""
    picture = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 400, 300), False)
    picture.clear_with(200)
    picture.set_rect(pymupdf.IRect(0, 0, 100, 300), (40, 40, 200))
    path = tmp_path / "phone.jpg"
    picture.save(str(path))
    # An Exif block with just the orientation (tag 0x0112) set to 6.
    tiff = (
        b"MM\x00\x2a" + (8).to_bytes(4, "big") + (1).to_bytes(2, "big")
        + (0x0112).to_bytes(2, "big") + (3).to_bytes(2, "big") + (1).to_bytes(4, "big")
        + (6).to_bytes(2, "big") + b"\x00\x00" + (0).to_bytes(4, "big")
    )
    exif = b"Exif\x00\x00" + tiff
    jpeg = path.read_bytes()
    path.write_bytes(jpeg[:2] + b"\xff\xe1" + (len(exif) + 2).to_bytes(2, "big") + exif + jpeg[2:])
    return str(path)
