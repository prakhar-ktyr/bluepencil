# SPDX-FileCopyrightText: 2026 Prakhar Katiyar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Opening and rendering, called directly: no engine process, no GTK."""

import os

import pymupdf
import pytest

from bluepencil.core.document import OpenError, describe, open_document
from bluepencil.core.engine import Engine
from bluepencil.core.limits import MAX_PAGE_PIXELS
from bluepencil.core.render import render_page


def test_open_reports_every_page_size(make_pdf):
    path = make_pdf(pages=3, sizes=[(595, 842), (842, 595), (300, 400)])
    info = describe(open_document(str(path)))
    assert info["page_count"] == 3
    assert info["pages"] == [[595, 842], [842, 595], [300, 400]]
    assert info["repaired"] is False


def test_rotated_page_reports_its_size_as_shown(make_pdf, tmp_path):
    document = pymupdf.open(make_pdf(pages=1))
    document[0].set_rotation(90)
    rotated = tmp_path / "rotated.pdf"
    document.save(rotated)
    assert describe(open_document(str(rotated)))["pages"] == [[842, 595]]


@pytest.mark.parametrize(("password", "code"), [(None, "needs-password"), ("wrong", "wrong-password")])
def test_protected_file_needs_its_password(make_pdf, password, code):
    path = make_pdf(password="secret")
    with pytest.raises(OpenError) as caught:
        open_document(str(path), password)
    assert caught.value.code == code


def test_right_password_opens_the_file(make_pdf):
    assert open_document(str(make_pdf(password="secret")), "secret").page_count == 3


def test_missing_file(tmp_path):
    with pytest.raises(OpenError) as caught:
        open_document(str(tmp_path / "nowhere.pdf"))
    assert caught.value.code == "not-found"


@pytest.mark.skipif(os.geteuid() == 0, reason="root can read any file")
def test_unreadable_file(make_pdf):
    path = make_pdf()
    path.chmod(0)
    with pytest.raises(OpenError) as caught:
        open_document(str(path))
    assert caught.value.code == "no-permission"


def _png() -> bytes:
    return pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 20, 20), False).tobytes("png")


@pytest.mark.parametrize(
    "content",
    [b"", b"%PDF-1.7\n", b"not a pdf at all " * 100, _png()],
    ids=["empty", "header-only", "text", "png-image"],
)
def test_damaged_or_foreign_file_is_refused(tmp_path, content):
    path = tmp_path / "broken.pdf"
    path.write_bytes(content)
    with pytest.raises(OpenError) as caught:
        open_document(str(path))
    assert caught.value.code in ("damaged", "no-pages", "not-pdf")


def test_image_named_like_a_pdf_is_refused_as_not_a_pdf(tmp_path):
    path = tmp_path / "photo.pdf"
    path.write_bytes(_png())
    with pytest.raises(OpenError) as caught:
        open_document(str(path))
    assert caught.value.code == "not-pdf"


def test_render_size_follows_the_scale(make_pdf):
    document = open_document(str(make_pdf(pages=1)))
    info, pixels = render_page(document, 0, 2.0)
    assert (info["width"], info["height"]) == (1190, 1684)
    assert info["stride"] == info["width"] * 3
    assert len(pixels) == info["stride"] * info["height"]


def test_render_draws_the_page(make_pdf):
    document = open_document(str(make_pdf(pages=1)))
    _info, pixels = render_page(document, 0, 1.0)
    assert max(pixels) == 255  # white paper
    assert min(pixels) < 100  # dark ink


def test_render_part_of_a_page(make_pdf):
    document = open_document(str(make_pdf(pages=1)))
    info, _pixels = render_page(document, 0, 2.0, clip=[0, 0, 100, 50])
    assert (info["width"], info["height"]) == (200, 100)


def test_huge_zoom_is_limited(make_pdf):
    document = open_document(str(make_pdf(pages=1)))
    info, _pixels = render_page(document, 0, 50.0)
    assert info["width"] * info["height"] <= MAX_PAGE_PIXELS * 1.01
    assert info["scale"] < 50.0


def test_render_of_a_missing_page_is_an_error(make_pdf):
    document = open_document(str(make_pdf(pages=2)))
    with pytest.raises(IndexError):
        render_page(document, 2, 1.0)


def test_engine_answers_mistakes_with_errors(make_pdf):
    engine = Engine()
    assert engine.handle({"op": "render", "page": 0, "scale": 1})[0] == {"ok": False, "error": "no-document"}
    reply, _ = engine.handle({"op": "open", "path": str(make_pdf())})
    assert reply["ok"] and reply["page_count"] == 3
    assert engine.handle({"op": "teleport"})[0]["error"] == "unknown-request"
