# SPDX-FileCopyrightText: 2026 Prakhar Katiyar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Page operations: rotate, delete, duplicate, move, insert, extract, split.

Each operation changes the open document in place and returns the pages to
select afterwards, counted from 0, so the interface can show the result.
Bookmarks and links keep pointing at the same pages when pages move; links to
deleted pages are removed.
"""

from collections.abc import Sequence
from pathlib import Path

import pymupdf

from .document import KEEP_ENCRYPTION, OpenError, open_document

#: Largest page made from an image, in points: A4, either way round. Bigger
#: images, such as phone photos, are scaled down to fit.
_IMAGE_PAGE_LIMIT = (595.0, 842.0)


class PageError(Exception):
    """An operation that cannot be done, with a code the interface explains."""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code


#: Codes for PageError.
NO_PAGES_LEFT = "no-pages-left"
BAD_PAGES = "bad-pages"
BAD_ANGLE = "bad-angle"
NOT_AN_IMAGE = "not-an-image"
UNSUPPORTED_FILE = "unsupported-file"


def _checked(document: pymupdf.Document, pages: Sequence[int]) -> list[int]:
    """The pages, sorted and without repeats, after checking they exist."""
    unique = sorted(set(pages))
    if not unique or unique[0] < 0 or unique[-1] >= document.page_count:
        raise PageError(BAD_PAGES, f"{list(pages)} in a document of {document.page_count} pages")
    return unique


def rotate(document: pymupdf.Document, pages: Sequence[int], degrees: int) -> list[int]:
    """Turn pages clockwise by a multiple of 90 degrees."""
    if degrees % 90:
        raise PageError(BAD_ANGLE, str(degrees))
    chosen = _checked(document, pages)
    for index in chosen:
        page = document[index]
        page.set_rotation((page.rotation + degrees) % 360)
    return chosen


def delete(document: pymupdf.Document, pages: Sequence[int]) -> list[int]:
    """Delete pages; the page after the last deleted one is selected."""
    chosen = _checked(document, pages)
    if len(chosen) == document.page_count:
        raise PageError(NO_PAGES_LEFT)
    document.delete_pages(chosen)
    after = chosen[-1] - len(chosen) + 1
    return [min(after, document.page_count - 1)]


def duplicate(document: pymupdf.Document, pages: Sequence[int]) -> list[int]:
    """Put a copy of each page right after it; the copies are selected."""
    chosen = _checked(document, pages)
    # From the end, so that earlier copies do not shift later pages.
    for index in reversed(chosen):
        document.fullcopy_page(index, index + 1 if index + 1 < document.page_count else -1)
    return [index + offset + 1 for offset, index in enumerate(chosen)]


def move(document: pymupdf.Document, pages: Sequence[int], to: int) -> list[int]:
    """Move pages, keeping their order, to just before page `to`.

    `to` counts in the order before the move; the page count puts them last.
    """
    chosen = _checked(document, pages)
    count = document.page_count
    if not 0 <= to <= count:
        raise PageError(BAD_PAGES, f"cannot move to {to}")
    moving = set(chosen)
    before = [index for index in range(to) if index not in moving]
    after = [index for index in range(to, count) if index not in moving]
    order = before + chosen + after
    if order != list(range(count)):
        document.select(order)
    return list(range(len(before), len(before) + len(chosen)))


def insert_blank(document: pymupdf.Document, at: int, size: tuple[float, float] | None = None) -> list[int]:
    """Insert an empty page before page `at`, the size of its neighbour by default."""
    at = _insertion_point(document, at)
    if size is None:
        neighbour = document[max(at - 1, 0)].rect
        size = (neighbour.width, neighbour.height)
    document.new_page(pno=at if at < document.page_count else -1, width=size[0], height=size[1])
    return [at]


def insert_pdf(document: pymupdf.Document, path: str, at: int, password: str | None = None) -> list[int]:
    """Insert every page of another PDF before page `at`, with its bookmarks."""
    at = _insertion_point(document, at)
    source = open_document(path, password)
    try:
        count = source.page_count
        bookmarks = source.get_toc(simple=False)
        document.insert_pdf(source, start_at=at if at < document.page_count else -1)
    finally:
        source.close()
    if bookmarks:
        _merge_bookmarks(document, bookmarks, at)
    return list(range(at, at + count))


def insert_image(document: pymupdf.Document, path: str, at: int) -> list[int]:
    """Insert a picture (JPEG, PNG, TIFF and others) as a page of its own."""
    at = _insertion_point(document, at)
    try:
        picture = pymupdf.Pixmap(path)
    except (RuntimeError, ValueError, pymupdf.mupdf.FzErrorBase) as error:
        raise PageError(NOT_AN_IMAGE, str(error)) from error
    except FileNotFoundError as error:
        raise OpenError("not-found", path) from error
    # Its own size at its own resolution, scaled down to fit an A4 page.
    resolution = picture.xres or 96, picture.yres or 96
    width, height = picture.width * 72 / resolution[0], picture.height * 72 / resolution[1]
    limit = _IMAGE_PAGE_LIMIT if height >= width else _IMAGE_PAGE_LIMIT[::-1]
    scale = min(1.0, limit[0] / width, limit[1] / height)
    page = document.new_page(
        pno=at if at < document.page_count else -1, width=width * scale, height=height * scale
    )
    # From the file itself, so a JPEG is stored as it is, without recompressing.
    page.insert_image(page.rect, filename=path)
    return [at]


def insert_files(document: pymupdf.Document, paths: Sequence[str], at: int) -> list[int]:
    """Insert PDFs and pictures, in this order, before page `at`."""
    position = _insertion_point(document, at)
    inserted: list[int] = []
    for path in paths:
        try:
            added = insert_pdf(document, path, position)
        except OpenError as error:
            if error.code not in ("not-pdf", "damaged"):
                raise
            try:
                added = insert_image(document, path, position)
            except PageError:
                raise PageError(UNSUPPORTED_FILE, Path(path).name) from error
        inserted.extend(added)
        position += len(added)
    return inserted


def subset(document: pymupdf.Document, pages: Sequence[int], password: str | None = None) -> pymupdf.Document:
    """A new document with just these pages, in this order, keeping bookmarks
    and links among them, and any password. The caller closes it."""
    chosen = list(pages)
    _checked(document, chosen)
    copy = pymupdf.open("pdf", document.tobytes(garbage=0, encryption=KEEP_ENCRYPTION))
    if copy.needs_pass and not copy.authenticate(password or ""):
        copy.close()
        raise OpenError("needs-password")
    copy.select(chosen)
    return copy


def extract(document: pymupdf.Document, pages: Sequence[int], path: str, password: str | None = None) -> None:
    """Write these pages to a new PDF at `path`."""
    copy = subset(document, pages, password)
    try:
        # Unused objects, such as the other pages, are left out of the file.
        copy.save(path, garbage=3, deflate=True, encryption=KEEP_ENCRYPTION)
    finally:
        copy.close()


def split(
    document: pymupdf.Document,
    groups: Sequence[Sequence[int]],
    folder: str,
    stem: str,
    password: str | None = None,
) -> list[str]:
    """Write each group of pages to its own PDF in `folder`; return the paths.

    Files are named "<stem>, part 1.pdf" and so on; existing files are never
    replaced.
    """
    written = []
    for number, group in enumerate(groups, start=1):
        path = _free_name(Path(folder), f"{stem}, part {number}")
        extract(document, group, str(path), password)
        written.append(str(path))
    return written


def _insertion_point(document: pymupdf.Document, at: int) -> int:
    if not 0 <= at <= document.page_count:
        raise PageError(BAD_PAGES, f"cannot insert at {at}")
    return at


def _merge_bookmarks(document: pymupdf.Document, inserted: list, at: int) -> None:
    """Add the bookmarks of pages inserted at `at` among the document's own,
    where those pages now are."""
    shifted = []
    for level, title, page, *rest in inserted:
        entry = [level, title, page + at if page > 0 else page]
        if rest and isinstance(rest[0], dict):
            target = {key: value for key, value in rest[0].items() if key != "xref"}
            if target.get("kind") == pymupdf.LINK_NAMED and page > 0:
                # Names belong to the other file: point at the page itself.
                target["kind"] = pymupdf.LINK_GOTO
                target.pop("name", None)
                target.pop("nameddest", None)
            entry.append(target)
        shifted.append(entry)
    own = document.get_toc(simple=False)
    # Before the first top-level bookmark that points past the inserted pages.
    position = next(
        (i for i, (level, _title, page, *_rest) in enumerate(own) if level == 1 and page > at),
        len(own),
    )
    document.set_toc(own[:position] + shifted + own[position:])


def _free_name(folder: Path, name: str) -> Path:
    path = folder / f"{name}.pdf"
    number = 2
    while path.exists():
        path = folder / f"{name} ({number}).pdf"
        number += 1
    return path
