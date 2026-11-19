# SPDX-FileCopyrightText: 2026 Prakhar Katiyar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Checking files before they are combined, and their small first-page pictures."""

import pymupdf
import pytest

from bluepencil.core import preview
from bluepencil.core.document import OpenError
from bluepencil.core.pages import PageError


def check_image(info: dict, pixels: bytes) -> None:
    assert info["stride"] == info["width"] * 3
    assert len(pixels) == info["stride"] * info["height"]


def test_a_pdf_gives_its_page_count_and_its_first_page(make_pdf):
    info, pixels = preview.inspect(str(make_pdf(pages=3, size=(595, 842))), size=96)
    assert (info["kind"], info["pages"]) == (preview.PDF, 3)
    assert info["height"] == 96 and info["width"] == round(96 * 595 / 842)
    check_image(info, pixels)
    assert set(pixels) != {255}  # the page's frame and text, not just white


def test_a_landscape_page_fits_the_same_square(make_pdf):
    info, _pixels = preview.inspect(str(make_pdf(pages=1, size=(842, 595))), size=96)
    assert info["width"] == 96 and info["height"] < 96


def test_a_picture_is_one_page_and_transparency_shows_as_white(tmp_path):
    path = tmp_path / "logo.png"
    clear = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 400, 200), True)
    clear.clear_with(0)
    clear.set_alpha(bytes(400 * 200))  # every pixel transparent
    clear.save(str(path))
    info, pixels = preview.inspect(str(path), size=96)
    assert (info["kind"], info["pages"]) == (preview.PICTURE, 1)
    assert (info["width"], info["height"]) == (96, 48)
    check_image(info, pixels)
    assert set(pixels) == {255}


def test_a_small_picture_is_not_enlarged(tmp_path):
    path = tmp_path / "icon.png"
    small = pymupdf.Pixmap(pymupdf.csGRAY, pymupdf.IRect(0, 0, 40, 30), False)
    small.clear_with(90)
    small.save(str(path))
    info, pixels = preview.inspect(str(path), size=96)
    assert (info["width"], info["height"]) == (40, 30)
    check_image(info, pixels)  # grey turned into RGB


def test_a_locked_pdf_needs_its_password(make_pdf):
    locked = str(make_pdf("locked.pdf", pages=2, password="secret"))
    for password, code in ((None, "needs-password"), ("guess", "wrong-password")):
        with pytest.raises(OpenError) as error:
            preview.inspect(locked, password)
        assert error.value.code == code
    info, _pixels = preview.inspect(locked, "secret")
    assert info["pages"] == 2


@pytest.mark.parametrize("content", [b"hello", b"garbage " * 200])
def test_files_that_are_neither_pdfs_nor_pictures_are_refused(tmp_path, content):
    path = tmp_path / "notes.txt"
    path.write_bytes(content)
    with pytest.raises(PageError) as error:
        preview.inspect(str(path))
    assert error.value.code == "unsupported-file"


def test_a_missing_file_is_reported(tmp_path):
    with pytest.raises(OpenError) as error:
        preview.inspect(str(tmp_path / "gone.pdf"))
    assert error.value.code == "not-found"
