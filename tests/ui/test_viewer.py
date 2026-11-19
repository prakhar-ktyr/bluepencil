# SPDX-FileCopyrightText: 2026 Prakhar Katiyar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The page viewer, driven the way a user would drive it."""

import math
import os
import signal

import gi

gi.require_version("Gio", "2.0")
from gi.repository import Gio  # noqa: E402

from bluepencil.ui.document_view import MARGIN, _same_scale  # noqa: E402

from .helpers import drawn_top, loaded  # noqa: E402


def fills_the_width(window) -> bool:
    """the page to be laid out as wide as the visible area"""
    if not loaded(window):
        return False
    view = window.view
    visible_width = view._scroller.get_hadjustment().get_page_size()
    return abs(view.pages[0].get_width() - (visible_width - 2 * MARGIN)) <= 2


def test_pages_fit_the_window_width_at_first(run_app, make_pdf):
    def check(window) -> None:
        view = window.view
        assert view.fit_mode == "width"
        assert view.zoom > 1.1  # the default window is wider than a page at 100 %
        assert window._zoom_button.get_label() == f"{round(view.zoom * 100)}%"

    run_app((fills_the_width, check), argv=[make_pdf()])


def test_fit_page_after_a_jump_keeps_that_page_on_screen(run_app, make_pdf):
    def jump(window) -> None:
        window._page_entry.set_text("237")
        window._page_entry.emit("activate")

    def arrived(window) -> bool:
        """page 237 to be drawn"""
        return window.view.pages[236].texture is not None

    def fit_page(window) -> None:
        window.activate_action("win.zoom-fit-page", None)

    def settled(window) -> bool:
        """page 237 to be fitted to the visible area, drawn sharply, near the top"""
        view = window.view
        page = view.pages[236]
        return (
            view.fit_mode == "page"
            # Fitted to the visible area as it is now, and laid out at that
            # zoom: the view refits just after each change of the visible
            # area, and GTK lays the pages out again on the next frame.
            and math.isclose(view.zoom, view._fit_zoom("page"), rel_tol=1e-4)  # as set_zoom judges it
            and page.get_height() == page.pixel_size()[1]
            and _same_scale(page.texture_scale, view._target_scale(page))  # no redraw is coming
            and 0 <= drawn_top(view, 236) < 3 * MARGIN
        )

    def check(window) -> None:
        view = window.view
        page = view.pages[236]
        visible_height = view._scroller.get_vadjustment().get_page_size()
        assert page.get_height() <= visible_height - 2 * MARGIN + 1
        assert window._page_entry.get_text() == "237"

    run_app((loaded, jump), (arrived, fit_page), (settled, check), argv=[make_pdf(pages=300)])


def test_opens_a_pdf_and_renders_only_pages_near_the_screen(run_app, make_pdf):
    def check(window) -> None:
        view = window.view
        assert view.page_count == 40
        assert window._title.get_subtitle() == "sample.pdf"
        assert window._page_total.get_label() == "of 40"
        assert window._page_entry.get_text() == "1"
        touched = [page.index for page in view.pages if page.texture is not None or page.requested_scale]
        assert max(touched) < 8, f"pages far below the screen were rendered: {touched}"

    run_app((loaded, check), argv=[make_pdf(pages=40)])


def test_zoom_in_enlarges_the_pages_and_renders_them_sharper(run_app, make_pdf):
    before: dict[str, float] = {}

    def zoom_in(window) -> None:
        page = window.view.pages[0]
        before.update(width=page.get_width(), scale=page.texture_scale)
        window.activate_action("win.zoom-in", None)

    def sharper(window) -> bool:
        """page 1 to be drawn larger and re-rendered"""
        page = window.view.pages[0]
        return page.get_width() > before["width"] * 1.15 and page.texture_scale > before["scale"] * 1.15

    def check(window) -> None:
        assert window.view.fit_mode is None
        assert window._zoom_button.get_label() == f"{round(window.view.zoom * 100)}%"

    run_app((loaded, zoom_in), (sharper, check), argv=[make_pdf()])


def test_page_box_jumps_to_a_page(run_app, make_pdf):
    def jump(window) -> None:
        window._page_entry.set_text("25")
        window._page_entry.emit("activate")

    def arrived(window) -> bool:
        """page 25 to be current and drawn"""
        return window.view.current_page == 24 and window.view.pages[24].texture is not None

    def check(window) -> None:
        assert window._page_entry.get_text() == "25"
        assert window.view.pages[0].texture is not None or window.view.pages[0].requested_scale == 0

    run_app((loaded, jump), (arrived, check), argv=[make_pdf(pages=40)])


def test_last_page_stays_current_after_jumping_to_it(run_app, make_pdf):
    def jump(window) -> None:
        window._page_entry.set_text("40")
        window._page_entry.emit("activate")

    def arrived(window) -> bool:
        """the last page to be drawn"""
        return window.view.pages[39].texture is not None

    def check(window) -> None:
        assert window.view.current_page == 39
        assert window._page_entry.get_text() == "40"

    run_app((loaded, jump), (arrived, check), argv=[make_pdf(pages=40)])


def test_damaged_file_says_why_it_cannot_open(run_app, tmp_path):
    path = tmp_path / "broken.pdf"
    path.write_bytes(b"garbage " * 200)

    def shown(window) -> bool:
        """the error page"""
        return window._status.get_title() == "Can’t Open “broken.pdf”"

    def check(window) -> None:
        assert "damaged" in window._status.get_description()
        assert window.view is None and window.current_file is None
        assert window.is_empty

    run_app((shown, check), argv=[path])


def test_protected_file_opens_after_the_right_password(run_app, make_pdf):
    def asked(window) -> bool:
        """the password dialog"""
        return window.get_visible_dialog() is not None

    def asked_again(window) -> bool:
        """the password dialog, saying the password was wrong"""
        dialog = window.get_visible_dialog()
        return dialog is not None and "not correct" in dialog.get_body()

    def answer(password):
        def type_and_confirm(window) -> None:
            dialog = window.get_visible_dialog()
            dialog.get_extra_child().set_text(password)
            dialog.emit("response", "open")
            dialog.force_close()

        return type_and_confirm

    def check(window) -> None:
        assert window.view.page_count == 3

    run_app(
        (asked, answer("guess")),
        (asked_again, answer("secret")),
        (loaded, check),
        argv=[make_pdf(password="secret")],
    )


def test_file_opened_during_a_password_prompt_gets_its_own_window(run_app, make_pdf):
    def asked(window) -> bool:
        """the password dialog"""
        return window.get_visible_dialog() is not None

    def open_another(window) -> None:
        window.get_application().open_file(Gio.File.new_for_path(str(make_pdf("other.pdf"))), window)

    def both(window) -> bool:
        """the other file to open in a second window"""
        windows = window.get_application().get_windows()
        return len(windows) == 2 and any(w.view is not None for w in windows)

    def check(window) -> None:
        first, second = window.get_application().get_windows()[::-1]
        assert first.get_visible_dialog() is not None and first.view is None
        assert second._title.get_subtitle() == "other.pdf"

    run_app((asked, open_another), (both, check), argv=[make_pdf(password="secret")])


def test_engine_crash_is_recovered(run_app, make_pdf):
    crashed = {}

    def crash(window) -> None:
        crashed["pid"] = window._engine.pid
        for page in window.view.pages:
            page.drop_texture()
        os.kill(crashed["pid"], signal.SIGKILL)

    def recovered(window) -> bool:
        """a new engine to draw page 1 again"""
        return window._engine.pid not in (None, crashed["pid"]) and window.view.pages[0].texture is not None

    def check(window) -> None:
        assert window.current_file is not None

    run_app((loaded, crash), (recovered, check), argv=[make_pdf()])


def test_two_files_open_in_two_windows(run_app, make_pdf):
    def both(window) -> bool:
        """both files to open"""
        windows = window.get_application().get_windows()
        return len(windows) == 2 and all(w.view is not None for w in windows)

    def check(window) -> None:
        names = sorted(w._title.get_subtitle() for w in window.get_application().get_windows())
        assert names == ["a.pdf", "b.pdf"]

    run_app((both, check), argv=[make_pdf("a.pdf"), make_pdf("b.pdf")])
