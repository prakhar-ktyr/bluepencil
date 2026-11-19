# SPDX-FileCopyrightText: 2026 Prakhar Katiyar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Changing pages, undo and redo, saving, and closing with unsaved changes."""

import os
import signal

import gi
import pymupdf

gi.require_version("Gio", "2.0")
from gi.repository import Gio  # noqa: E402

from .helpers import loaded  # noqa: E402


def settled(window) -> bool:
    """nothing on its way to the engine, and the current page drawn"""
    view = window.view
    return not window._busy and view is not None and view.pages[view.current_page].texture is not None


def unsaved(window) -> bool:
    """the change to arrive"""
    return settled(window) and bool(window._state.get("modified"))


def saved(window) -> bool:
    """the file to be saved"""
    return settled(window) and not window._state.get("modified")


def rotate(window) -> None:
    window.activate_action("win.rotate-right", None)


def first_page_size(window) -> tuple[float, float]:
    page = window.view.pages[0]
    return page.width_pt, page.height_pt


def test_a_change_marks_the_file_unsaved_and_undo_and_redo_work(run_app, make_pdf):
    def check_rotated(window) -> None:
        assert first_page_size(window) == (842, 595)
        assert window._title.get_subtitle() == "• sample.pdf"
        # Fitted to the width of the page that is now landscape.
        assert window._zoom_button.get_label() == f"{round(window.view.zoom * 100)}%"
        assert window._actions["undo"].get_enabled()
        assert window._actions["save"].get_enabled()
        assert not window._actions["redo"].get_enabled()
        window.activate_action("win.undo", None)

    def check_undone(window) -> None:
        assert first_page_size(window) == (595, 842)
        assert window._title.get_subtitle() == "sample.pdf"
        assert window._actions["redo"].get_enabled()
        assert not window._actions["save"].get_enabled()
        window.activate_action("win.redo", None)

    def check_redone(window) -> None:
        assert first_page_size(window) == (842, 595)

    run_app(
        (loaded, rotate),
        (unsaved, check_rotated),
        (saved, check_undone),
        (unsaved, check_redone),
        argv=[make_pdf()],
    )


def test_a_replaced_view_no_longer_sets_the_zoom_or_the_page_number(run_app, make_pdf):
    # Each change brings a new view. The old one can still finish work it had
    # queued, such as fitting its pages to a new size, and say so.
    views = []

    def rotate_keeping_the_view(window) -> None:
        views.append(window.view)
        rotate(window)

    def check(window) -> None:
        old = views[0]
        assert window.view is not old
        old.set_zoom(3.0)
        old.emit("current-page-changed", 2)
        assert window._zoom_button.get_label() == f"{round(window.view.zoom * 100)}%"
        assert window._page_entry.get_text() == "1"

    run_app((loaded, rotate_keeping_the_view), (unsaved, check), argv=[make_pdf()])


def test_save_writes_the_change_to_the_file(run_app, make_pdf):
    path = make_pdf()

    def check(window) -> None:
        assert window._title.get_subtitle() == "sample.pdf"
        assert pymupdf.open(path)[0].rotation == 90

    run_app(
        (loaded, rotate),
        (unsaved, lambda window: window.activate_action("win.save", None)),
        (saved, check),
        argv=[path],
    )


def test_deleting_the_only_page_is_refused(run_app, make_pdf):
    def check(window) -> None:
        assert window.view.page_count == 1
        assert not window._state.get("modified")

    run_app(
        (loaded, lambda window: window.activate_action("win.delete-page", None)),
        (settled, check),
        argv=[make_pdf(pages=1)],
    )


def dialog_shown(window) -> bool:
    """the "Save Changes?" question"""
    dialog = window.get_visible_dialog()
    return dialog is not None and dialog.get_heading() == "Save Changes?"


def test_closing_with_unsaved_changes_asks_and_discard_keeps_the_file(run_app, make_pdf):
    path = make_pdf()

    def answer(window) -> None:
        assert window.get_visible()  # still open, waiting for the answer
        window.get_visible_dialog().emit("response", "discard")

    run_app((loaded, rotate), (unsaved, lambda window: window.close()), (dialog_shown, answer), argv=[path])
    assert pymupdf.open(path)[0].rotation == 0


def test_closing_and_choosing_save_saves_first(run_app, make_pdf):
    path = make_pdf()
    run_app(
        (loaded, rotate),
        (unsaved, lambda window: window.close()),
        (dialog_shown, lambda window: window.get_visible_dialog().emit("response", "save")),
        argv=[path],
    )
    assert pymupdf.open(path)[0].rotation == 90


def test_quit_asks_about_unsaved_changes_too(run_app, make_pdf):
    run_app(
        (loaded, rotate),
        (unsaved, lambda window: window.get_application().activate_action("quit", None)),
        (dialog_shown, lambda window: window.get_visible_dialog().emit("response", "discard")),
        argv=[make_pdf()],
    )


def test_changes_and_their_history_survive_an_engine_crash(run_app, make_pdf):
    def crash(window) -> None:
        os.kill(window._engine.pid, signal.SIGKILL)

    def restarted(window) -> bool:
        """the engine to start again"""
        return len(window._restarts) == 1 and window._engine.running and not window._busy

    def still_rotated_then_undo(window) -> None:
        assert first_page_size(window) == (842, 595)
        assert window._state.get("modified")
        window.activate_action("win.undo", None)

    def check(window) -> None:
        assert first_page_size(window) == (595, 842)

    run_app(
        (loaded, rotate),
        (unsaved, crash),
        (restarted, still_rotated_then_undo),
        (saved, check),
        argv=[make_pdf()],
    )


def test_save_as_carries_on_in_the_new_file(run_app, make_pdf, tmp_path):
    original = make_pdf()
    target = tmp_path / "copy"

    def save_as(window) -> None:
        window.save_as(Gio.File.new_for_path(str(target)))

    def moved(window) -> bool:
        """the copy to be saved"""
        return saved(window) and window.current_file.get_path() == f"{target}.pdf"

    def check(window) -> None:
        assert window._title.get_subtitle() == "copy.pdf"
        assert window.get_application().history.recent()[0].path == f"{target}.pdf"
        assert pymupdf.open(f"{target}.pdf")[0].rotation == 90
        assert pymupdf.open(original)[0].rotation == 0

    run_app((loaded, rotate), (unsaved, save_as), (moved, check), argv=[original])
