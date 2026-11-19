# SPDX-FileCopyrightText: 2026 Prakhar Katiyar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Offering back the changes a crash left unsaved."""

from pathlib import Path

import pymupdf

from ..crash import crash_after_rotating


def recovery_offered(window) -> bool:
    """the offer to recover"""
    dialog = window.get_visible_dialog()
    return dialog is not None and dialog.get_heading() == "Recover Unsaved Changes?"


def test_the_changes_a_crash_left_come_back_unsaved(run_app, make_pdf):
    path = make_pdf()
    crash_after_rotating(path)

    def recover(window) -> None:
        dialog = window.get_visible_dialog()
        assert "sample.pdf" in dialog.get_body()
        dialog.emit("response", "recover")

    def recovered(window) -> bool:
        """the recovered document"""
        view = window.view
        return view is not None and view.pages[0].texture is not None and not window._busy

    def check(window) -> None:
        page = window.view.pages[0]
        assert (page.width_pt, page.height_pt) == (842, 595)
        assert window._title.get_subtitle() == "• sample.pdf"
        assert window._actions["undo"].get_enabled()
        assert pymupdf.open(path)[0].rotation == 0  # the file waits for Save

    run_app((recovery_offered, recover), (recovered, check))


def test_discard_deletes_what_the_crash_left(run_app, make_pdf):
    history = crash_after_rotating(make_pdf())

    def discard(window) -> None:
        window.get_visible_dialog().emit("response", "discard")

    def check(window) -> None:
        assert not Path(history["folder"]).exists()
        assert window.current_file is None

    run_app((recovery_offered, discard), (lambda window: True, check))


def rotate(window) -> None:
    window.activate_action("win.rotate-right", None)


def rotated(window) -> bool:
    """the change"""
    return bool(window._state.get("modified")) and not window._busy


def no_offer(window) -> None:
    assert window.get_visible_dialog() is None


def test_changes_discarded_on_closing_are_not_offered(run_app, make_pdf):
    run_app(
        (lambda window: window.view is not None, rotate),
        (rotated, lambda window: window.close()),
        (lambda window: window.get_visible_dialog() is not None,
         lambda window: window.get_visible_dialog().emit("response", "discard")),
        argv=[make_pdf()],
    )
    run_app((lambda window: True, no_offer))


def test_changes_left_when_the_app_is_stopped_without_asking_are_offered(run_app, make_pdf):
    # The test harness stops the app directly, as a log-out might.
    run_app((lambda window: window.view is not None, rotate), (rotated, lambda window: None), argv=[make_pdf()])
    run_app((recovery_offered, lambda window: None))
