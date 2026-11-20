# SPDX-FileCopyrightText: 2026 Prakhar Katiyar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The Compress dialog."""

import gi
import pymupdf

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk  # noqa: E402

from bluepencil.core.places import jobs_root  # noqa: E402

from .helpers import loaded  # noqa: E402


def open_dialog(window) -> None:
    window.activate_action("win.compress", None)


def dialog_open(window) -> bool:
    """the Compress dialog"""
    return window.compress_dialog is not None and window.get_visible_dialog() is window.compress_dialog


def compress_with(preset: str):
    def action(window) -> None:
        window.compress_dialog.choices[preset].set_active(True)
        window.compress_dialog.start()

    return action


def done(window) -> bool:
    """the result"""
    return window.compress_dialog.stage.get_visible_child_name() == "done"


def leftovers() -> list[str]:
    folder = jobs_root()
    return sorted(path.name for path in folder.iterdir()) if folder.exists() else []


def test_compress_shows_the_real_result_and_saves_a_smaller_copy(run_app, photos, tmp_path):
    before = photos.stat().st_size
    target = tmp_path / "small"

    def save(window) -> None:
        dialog = window.compress_dialog
        assert dialog.save_button.get_visible()
        assert dialog.result_label.get_label().endswith("% smaller")
        window.save_compressed_copy(dialog, str(target))

    def saved(window) -> bool:
        """the smaller copy"""
        return (tmp_path / "small.pdf").exists() and window.get_visible_dialog() is None

    def check(window) -> None:
        assert (tmp_path / "small.pdf").stat().st_size < before / 4
        assert photos.stat().st_size == before  # the original is untouched
        assert not window._state.get("modified")
        assert leftovers() == []

    run_app(
        (loaded, open_dialog),
        (dialog_open, compress_with("email")),
        (done, save),
        (saved, check),
        argv=[photos],
    )


def test_the_compress_button_is_as_tall_as_other_buttons(run_app, photos):
    # The stages of the dialog share the height of the tallest one, and the
    # button stretched to fill it.
    def laid_out(window) -> bool:
        """the dialog to be laid out"""
        return dialog_open(window) and window.compress_dialog.compress_button.get_height() > 0

    def check(window) -> None:
        button = window.compress_dialog.compress_button
        _minimum, natural, _baseline, _natural_baseline = button.measure(
            Gtk.Orientation.VERTICAL, button.get_width()
        )
        _found, bounds = button.compute_bounds(button)  # with its padding, as measured
        assert bounds.get_height() == natural

    run_app((loaded, open_dialog), (laid_out, check), argv=[photos])


def test_when_nothing_can_be_saved_it_says_so(run_app, photos):
    def check(window) -> None:
        dialog = window.compress_dialog
        assert not dialog.save_button.get_visible()
        assert dialog.result_label.get_label() == "This setting cannot make the file smaller. Nothing was changed."
        assert leftovers() == []

    run_app((loaded, open_dialog), (dialog_open, compress_with("lossless")), (done, check), argv=[photos])


def test_cancel_and_close_leave_nothing_behind(run_app, photos):
    def start_then_cancel(window) -> None:
        compress_with("email")(window)
        window.compress_dialog.cancel()

    def check_cancelled(window) -> None:
        dialog = window.compress_dialog
        assert dialog.stage.get_visible_child_name() == "choose"
        assert [name for name in leftovers() if not name.startswith(".")] == []
        compress_with("balanced")(window)

    def close(window) -> None:
        assert leftovers()  # the result waits to be saved
        window.compress_dialog.close()

    def check_closed(window) -> None:
        assert leftovers() == []

    run_app(
        (loaded, open_dialog),
        (dialog_open, start_then_cancel),
        (lambda window: True, check_cancelled),
        (done, close),
        (lambda window: window.get_visible_dialog() is None, check_closed),
        argv=[photos],
    )


def test_unsaved_changes_are_part_of_the_copy(run_app, photos, tmp_path):
    def rotate(window) -> None:
        window.activate_action("win.rotate-right", None)

    def rotated(window) -> bool:
        """the change"""
        return bool(window._state.get("modified")) and not window._busy

    def save(window) -> None:
        window.save_compressed_copy(window.compress_dialog, str(tmp_path / "small.pdf"))

    def check(window) -> None:
        assert pymupdf.open(tmp_path / "small.pdf")[0].rotation == 90
        assert pymupdf.open(photos)[0].rotation == 0

    run_app(
        (loaded, rotate),
        (rotated, open_dialog),
        (dialog_open, compress_with("email")),
        (done, save),
        (lambda window: (tmp_path / "small.pdf").exists(), check),
        argv=[photos],
    )
