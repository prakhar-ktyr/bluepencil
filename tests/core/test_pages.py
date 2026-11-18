# SPDX-FileCopyrightText: 2026 Prakhar Katiyar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Page operations, called directly on documents."""

import pymupdf
import pytest

from bluepencil.core import pages
from bluepencil.core.document import OpenError, open_document
from bluepencil.core.pages import PageError


def labels(document: pymupdf.Document) -> list[str]:
    """What each page says, which tells pages apart: "Page 3" and so on."""
    return [document[i].get_text().strip().split("\n")[0] or "blank" for i in range(document.page_count)]


def numbered(count: int) -> list[str]:
    return [f"Page {n}" for n in range(1, count + 1)]


@pytest.fixture
def document(make_pdf):
    """A five-page document; pages say "Page 1" to "Page 5"."""
    opened = open_document(str(make_pdf(pages=5)))
    yield opened
    opened.close()


def with_bookmarks_and_link(document: pymupdf.Document) -> None:
    """Bookmarks to pages 1 and 3, and a link on page 1 to page 3."""
    document.set_toc([[1, "Start", 1], [1, "Middle", 3]])
    document[0].insert_link({"kind": pymupdf.LINK_GOTO, "from": pymupdf.Rect(72, 300, 200, 320), "page": 2})


def link_targets(page: pymupdf.Page) -> list[int]:
    return [link["page"] for link in page.get_links()]


# Rotate


def test_rotate_turns_only_the_chosen_pages(document):
    assert pages.rotate(document, [0, 2], 90) == [0, 2]
    assert [document[i].rotation for i in range(5)] == [90, 0, 90, 0, 0]
    pages.rotate(document, [2], 270)
    assert document[2].rotation == 0


def test_rotate_accepts_only_quarter_turns(document):
    with pytest.raises(PageError) as error:
        pages.rotate(document, [0], 45)
    assert error.value.code == pages.BAD_ANGLE


def test_pages_that_do_not_exist_are_refused(document):
    for wrong in ([5], [-1], []):
        with pytest.raises(PageError) as error:
            pages.rotate(document, wrong, 90)
        assert error.value.code == pages.BAD_PAGES


# Delete


def test_delete_removes_pages_and_selects_the_next_one(document):
    assert pages.delete(document, [2, 1]) == [1]
    assert labels(document) == ["Page 1", "Page 4", "Page 5"]


def test_deleting_the_last_page_selects_the_new_last_page(document):
    assert pages.delete(document, [4]) == [3]


def test_a_document_keeps_at_least_one_page(document):
    with pytest.raises(PageError) as error:
        pages.delete(document, range(5))
    assert error.value.code == pages.NO_PAGES_LEFT
    assert document.page_count == 5


def test_links_to_deleted_pages_go_and_others_follow(document):
    with_bookmarks_and_link(document)
    pages.delete(document, [1])  # "Page 2": the linked page moves up
    assert link_targets(document[0]) == [1]
    assert document.get_toc() == [[1, "Start", 1], [1, "Middle", 2]]
    pages.delete(document, [1])  # the linked page itself
    assert link_targets(document[0]) == []


# Duplicate


def test_duplicate_puts_each_copy_after_its_page(document):
    assert pages.duplicate(document, [0, 4]) == [1, 6]
    assert labels(document) == ["Page 1", "Page 1", "Page 2", "Page 3", "Page 4", "Page 5", "Page 5"]


def test_a_copy_is_independent_of_its_original(document):
    pages.duplicate(document, [0])
    pages.rotate(document, [1], 90)
    assert (document[0].rotation, document[1].rotation) == (0, 90)


# Move


@pytest.mark.parametrize(
    ("chosen", "to", "order", "selected"),
    [
        ([3], 0, [4, 1, 2, 3, 5], [0]),
        ([0], 5, [2, 3, 4, 5, 1], [4]),
        ([0, 1], 4, [3, 4, 1, 2, 5], [2, 3]),
        ([1, 3], 3, [1, 3, 2, 4, 5], [2, 3]),
        ([4, 0], 2, [2, 1, 5, 3, 4], [1, 2]),
        ([2], 2, [1, 2, 3, 4, 5], [2]),
    ],
)
def test_move_keeps_the_moved_pages_in_order(document, chosen, to, order, selected):
    assert pages.move(document, chosen, to) == selected
    assert labels(document) == [f"Page {n}" for n in order]


def test_bookmarks_and_links_follow_moved_pages(document):
    with_bookmarks_and_link(document)
    pages.move(document, [2], 0)  # "Page 3" to the front
    assert labels(document)[:3] == ["Page 3", "Page 1", "Page 2"]
    assert document.get_toc() == [[1, "Start", 2], [1, "Middle", 1]]
    assert link_targets(document[1]) == [0]


# Insert


def test_insert_blank_page_takes_the_size_of_the_page_before(make_pdf):
    document = open_document(str(make_pdf(pages=2, sizes=[(300, 400), (500, 600)])))
    assert pages.insert_blank(document, 1) == [1]
    assert labels(document) == ["Page 1", "blank", "Page 2"]
    assert (document[1].rect.width, document[1].rect.height) == (300, 400)
    assert pages.insert_blank(document, 3) == [3]
    assert document.page_count == 4


def test_insert_pdf_brings_its_pages_and_bookmarks(document, tmp_path):
    with_bookmarks_and_link(document)
    other = pymupdf.open()
    for number in (1, 2):
        other.new_page().insert_text((72, 110), f"Other {number}", fontsize=36)
    other.set_toc([[1, "Other start", 1], [2, "Other detail", 2]])
    other.save(tmp_path / "other.pdf")

    assert pages.insert_pdf(document, str(tmp_path / "other.pdf"), 1) == [1, 2]
    assert labels(document) == ["Page 1", "Other 1", "Other 2", "Page 2", "Page 3", "Page 4", "Page 5"]
    assert document.get_toc() == [
        [1, "Start", 1],
        [1, "Other start", 2],
        [2, "Other detail", 3],
        [1, "Middle", 5],
    ]
    assert link_targets(document[0]) == [4]


def test_insert_pdf_with_a_password(document, make_pdf):
    locked = make_pdf("locked.pdf", pages=1, password="secret")
    with pytest.raises(OpenError) as error:
        pages.insert_pdf(document, str(locked), 0)
    assert error.value.code == "needs-password"
    assert pages.insert_pdf(document, str(locked), 0, password="secret") == [0]
    assert document.page_count == 6


def test_insert_image_keeps_its_size_at_its_resolution(document, tmp_path):
    picture = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 400, 300), False)
    picture.clear_with(180)
    picture.set_dpi(96, 96)
    path = tmp_path / "small.png"
    picture.save(str(path))
    assert pages.insert_image(document, str(path), 5) == [5]
    page = document[5]
    assert (round(page.rect.width), round(page.rect.height)) == (300, 225)
    assert page.get_images()


def test_insert_image_shrinks_large_photos_to_a4(document, tmp_path):
    photo = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 4000, 3000), False)
    photo.clear_with(90)
    photo.set_dpi(72, 72)
    path = tmp_path / "photo.jpg"
    photo.save(str(path))
    pages.insert_image(document, str(path), 0)
    page = document[0]
    # Within landscape A4 (842 by 595 points), the same shape as the photo.
    assert round(page.rect.height) == 595
    assert round(page.rect.width) == round(595 * 4000 / 3000)


def test_insert_image_refuses_other_files(document, tmp_path):
    path = tmp_path / "notes.txt"
    path.write_text("not a picture")
    with pytest.raises(PageError) as error:
        pages.insert_image(document, str(path), 0)
    assert error.value.code == pages.NOT_AN_IMAGE


# Extract and split


def test_extract_writes_just_those_pages_in_that_order(document, tmp_path):
    with_bookmarks_and_link(document)
    path = tmp_path / "extract.pdf"
    pages.extract(document, [2, 0], str(path))
    result = pymupdf.open(path)
    assert labels(result) == ["Page 3", "Page 1"]
    assert link_targets(result[1]) == [0]
    assert document.page_count == 5  # the open document is unchanged


def test_extract_keeps_the_password(make_pdf, tmp_path):
    locked = open_document(str(make_pdf("locked.pdf", pages=3, password="secret")), "secret")
    path = tmp_path / "part.pdf"
    pages.extract(locked, [1], str(path), password="secret")
    result = pymupdf.open(path)
    assert result.needs_pass
    assert result.authenticate("secret")
    assert labels(result) == ["Page 2"]


def test_split_writes_numbered_files_without_replacing_any(document, tmp_path):
    (tmp_path / "report, part 1.pdf").write_bytes(b"someone else's file")
    written = pages.split(document, pages.every(2, 5), str(tmp_path), "report")
    assert [p.rsplit("/", 1)[1] for p in written] == [
        "report, part 1 (2).pdf",
        "report, part 2.pdf",
        "report, part 3.pdf",
    ]
    assert [labels(pymupdf.open(p)) for p in written] == [["Page 1", "Page 2"], ["Page 3", "Page 4"], ["Page 5"]]
    assert (tmp_path / "report, part 1.pdf").read_bytes() == b"someone else's file"


@pytest.mark.parametrize(
    ("text", "groups"),
    [
        ("1-3, 5, 8-", [[0, 1, 2], [4], [7, 8, 9]]),
        ("2", [[1]]),
        ("-2; 9–10", [[0, 1], [8, 9]]),
        (" 1 - 10 ", [list(range(10))]),
    ],
)
def test_page_ranges_as_people_type_them(text, groups):
    assert pages.parse_ranges(text, 10) == groups


@pytest.mark.parametrize("text", ["", "0", "3-2", "11", "1-11", "a", "1,,x"])
def test_wrong_page_ranges_are_refused(text):
    with pytest.raises(ValueError):
        pages.parse_ranges(text, 10)


def test_every_n_pages():
    assert pages.every(4, 10) == [[0, 1, 2, 3], [4, 5, 6, 7], [8, 9]]
    with pytest.raises(ValueError):
        pages.every(0, 10)


def test_insert_files_takes_pdfs_and_pictures_in_order(document, make_pdf, tmp_path):
    picture = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 200, 100), False)
    picture.clear_with(200)
    picture.save(str(tmp_path / "picture.png"))
    other = make_pdf("other.pdf", pages=2)
    selected = pages.insert_files(document, [str(tmp_path / "picture.png"), str(other)], 1)
    assert selected == [1, 2, 3]
    assert labels(document) == ["Page 1", "blank", "Page 1", "Page 2", "Page 2", "Page 3", "Page 4", "Page 5"]
    assert document[1].get_images()


def test_insert_files_refuses_files_that_are_neither(document, tmp_path):
    (tmp_path / "notes.txt").write_text("hello")
    with pytest.raises(PageError) as error:
        pages.insert_files(document, [str(tmp_path / "notes.txt")], 0)
    assert error.value.code == pages.UNSUPPORTED_FILE
