# SPDX-FileCopyrightText: 2026 Prakhar Katiyar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Undo, redo, saving and carrying on after a crash (plan, D4 and D5)."""

import os
import stat
from pathlib import Path

import pymupdf
import pytest

from bluepencil.core import pages, session
from bluepencil.core.pages import PageError
from bluepencil.core.session import SaveError, Session

from .test_pages import labels


def fingerprint(document: pymupdf.Document) -> list[tuple]:
    """Everything an edit can change about the pages."""
    return [
        (labels(document)[i], document[i].rotation, round(document[i].rect.width), round(document[i].rect.height))
        for i in range(document.page_count)
    ]


@pytest.fixture
def opened(make_pdf):
    current = Session(str(make_pdf(pages=5)))
    yield current
    current.close()


@pytest.fixture
def picture(tmp_path):
    pixmap = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 200, 100), False)
    pixmap.clear_with(120)
    path = tmp_path / "picture.png"
    pixmap.save(str(path))
    return str(path)


EDITS = {
    "rotate": lambda document, _paths: pages.rotate(document, [1, 3], 90),
    "delete": lambda document, _paths: pages.delete(document, [0, 4]),
    "duplicate": lambda document, _paths: pages.duplicate(document, [2]),
    "move": lambda document, _paths: pages.move(document, [4], 0),
    "insert-blank": lambda document, _paths: pages.insert_blank(document, 2),
    "insert-pdf": lambda document, paths: pages.insert_pdf(document, paths["pdf"], 1),
    "insert-image": lambda document, paths: pages.insert_image(document, paths["picture"], 5),
}


@pytest.mark.parametrize("name", EDITS)
def test_undo_and_redo_return_to_identical_documents(opened, make_pdf, picture, name):
    paths = {"pdf": str(make_pdf("other.pdf", pages=2)), "picture": picture}
    before = fingerprint(opened.document)
    opened.edit(lambda document: EDITS[name](document, paths))
    after = fingerprint(opened.document)
    assert after != before
    opened.undo()
    assert fingerprint(opened.document) == before
    opened.redo()
    assert fingerprint(opened.document) == after


def test_modified_follows_what_is_on_disk(opened):
    assert not opened.modified and not opened.can_undo
    opened.edit(lambda document: pages.rotate(document, [0], 90))
    assert opened.modified and opened.can_undo and not opened.can_redo
    opened.undo()
    assert not opened.modified and opened.can_redo
    opened.redo()
    assert opened.modified
    opened.save()
    assert not opened.modified
    opened.undo()
    assert opened.modified


def test_a_new_edit_after_undo_drops_the_steps_that_were_undone(opened):
    opened.edit(lambda document: pages.rotate(document, [0], 90))
    rotated = fingerprint(opened.document)
    opened.edit(lambda document: pages.delete(document, [1]))
    opened.undo()
    opened.edit(lambda document: pages.duplicate(document, [4]))
    assert not opened.can_redo
    opened.undo()
    assert fingerprint(opened.document) == rotated


def test_a_failed_edit_changes_nothing(opened):
    before = fingerprint(opened.document)
    with pytest.raises(PageError):
        opened.edit(lambda document: pages.delete(document, range(5)))
    assert fingerprint(opened.document) == before
    assert not opened.can_undo and not opened.modified


def test_only_so_many_steps_are_kept(opened, monkeypatch):
    monkeypatch.setattr(session, "MAX_STEPS", 3)
    monkeypatch.setattr(session, "MIN_STEPS", 1)
    for _step in range(6):
        opened.edit(lambda document: pages.rotate(document, [0], 90))
    undone = 0
    while opened.can_undo:
        opened.undo()
        undone += 1
    assert undone == 3
    assert len(opened.snapshots) == 4
    assert opened.modified  # the file on disk is no longer in the history


def test_snapshots_are_private_and_deleted_on_close(make_pdf, tmp_path):
    current = Session(str(make_pdf()))
    current.edit(lambda document: pages.rotate(document, [0], 90))
    folder = current.folder
    assert folder is not None and folder.parent == tmp_path / "cache" / "bluepencil" / "snapshots"
    assert stat.S_IMODE(folder.stat().st_mode) == 0o700
    assert len(list(folder.iterdir())) == 2
    current.close()
    assert not folder.exists()


# Saving


def test_save_writes_the_edits_and_keeps_the_file_mode(opened):
    path = Path(opened.path)
    path.chmod(0o640)
    opened.edit(lambda document: pages.delete(document, [1]))
    opened.save()
    assert labels(pymupdf.open(path)) == ["Page 1", "Page 3", "Page 4", "Page 5"]
    assert stat.S_IMODE(path.stat().st_mode) == 0o640
    assert not list(path.parent.glob("*.part"))


def test_save_keeps_the_password(make_pdf):
    current = Session(str(make_pdf("locked.pdf", password="secret")), "secret")
    current.edit(lambda document: pages.rotate(document, [0], 90))
    current.save()
    saved = pymupdf.open(current.path)
    assert saved.needs_pass
    assert saved.authenticate("secret")
    assert saved[0].rotation == 90
    current.close()


def test_save_as_writes_elsewhere_and_carries_on_there(opened, tmp_path):
    original = opened.path
    copy = str(tmp_path / "copy.pdf")
    opened.edit(lambda document: pages.rotate(document, [0], 180))
    opened.save(copy)
    assert opened.path == copy and not opened.modified
    assert pymupdf.open(copy)[0].rotation == 180
    assert pymupdf.open(original)[0].rotation == 0


def test_save_through_a_link_updates_the_real_file(make_pdf, tmp_path):
    real = make_pdf("real.pdf")
    link = tmp_path / "link.pdf"
    link.symlink_to(real)
    current = Session(str(link))
    current.edit(lambda document: pages.rotate(document, [0], 90))
    current.save()
    assert link.is_symlink()
    assert pymupdf.open(real)[0].rotation == 90
    current.close()


@pytest.mark.skipif(os.geteuid() == 0, reason="permissions do not apply to root")
def test_a_failed_save_leaves_the_original_as_it_was(make_pdf, tmp_path):
    folder = tmp_path / "locked-folder"
    folder.mkdir()
    path = make_pdf("in-folder.pdf")
    moved = folder / "in-folder.pdf"
    path.rename(moved)
    original = moved.read_bytes()
    current = Session(str(moved))
    current.edit(lambda document: pages.rotate(document, [0], 90))
    folder.chmod(0o500)
    try:
        with pytest.raises(SaveError) as error:
            current.save()
        assert error.value.code == session.NO_PERMISSION
        assert moved.read_bytes() == original
        assert sorted(p.name for p in folder.iterdir()) == ["in-folder.pdf"]
        assert current.modified
    finally:
        folder.chmod(0o700)
        current.close()


# After a crash


def test_a_new_engine_carries_on_with_the_edits_and_their_history(opened):
    opened.edit(lambda document: pages.rotate(document, [0], 90))
    opened.edit(lambda document: pages.delete(document, [1]))
    opened.edit(lambda document: pages.duplicate(document, [0]))
    opened.undo()
    state = opened.state()
    expected = fingerprint(opened.document)
    # The old engine is gone without closing anything; its snapshots remain.
    history = state["history"]
    resumed = Session.resume(opened.path, None, **{key: history[key] for key in history})
    assert fingerprint(resumed.document) == expected
    assert resumed.can_undo and resumed.can_redo and resumed.modified
    resumed.undo()
    assert fingerprint(resumed.document)[0][1] == 90  # rotated, page 2 not yet deleted
    assert len(resumed.document) == 5


def test_without_its_snapshots_a_new_engine_starts_from_the_file(opened, tmp_path):
    opened.edit(lambda document: pages.rotate(document, [0], 90))
    history = opened.state()["history"]
    for name in history["files"]:
        Path(name).unlink()
    resumed = Session.resume(opened.path, None, **history)
    assert fingerprint(resumed.document)[0][1] == 0
    assert not resumed.can_undo and not resumed.modified


# Combining files into a new document


def test_combine_makes_an_unsaved_document_from_several_files(make_pdf, picture, tmp_path):
    first, second = make_pdf("first.pdf", pages=2), make_pdf("second.pdf", pages=1)
    target = str(tmp_path / "Combined.pdf")
    combined = Session.combine([str(first), picture, str(second)], target)
    assert labels(combined.document) == ["Page 1", "Page 2", "blank", "Page 1"]
    assert combined.untitled and combined.modified and not combined.can_undo
    assert not Path(target).exists()

    combined.edit(lambda document: pages.delete(document, [2]))
    combined.undo()
    assert not combined.can_undo  # the combined document is where undo stops

    combined.save(target)
    assert not combined.untitled and not combined.modified
    assert labels(pymupdf.open(target)) == ["Page 1", "Page 2", "blank", "Page 1"]
    combined.close()


def test_combine_refuses_files_it_cannot_use(tmp_path):
    (tmp_path / "notes.txt").write_text("hello")
    with pytest.raises(PageError):
        Session.combine([str(tmp_path / "notes.txt")], str(tmp_path / "Combined.pdf"))


def test_a_combined_document_survives_an_engine_crash(make_pdf, tmp_path):
    combined = Session.combine([str(make_pdf(pages=3))], str(tmp_path / "Combined.pdf"))
    history = combined.state()["history"]
    resumed = Session.resume(combined.path, None, **history)
    assert resumed.untitled and resumed.modified
    assert resumed.document.page_count == 3
