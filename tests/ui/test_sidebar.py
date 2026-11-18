# SPDX-FileCopyrightText: 2026 Prakhar Katiyar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The thumbnail sidebar."""

import os
import signal

from .helpers import loaded
from .test_viewer import fills_the_width


def thumbnails_shown(window) -> bool:
    """the sidebar to show the first thumbnail"""
    return window._split.get_show_sidebar() and window.sidebar.items[0].props.texture is not None


def show_sidebar(window) -> None:
    window.activate_action("win.toggle-sidebar", None)


def touched(sidebar) -> list[int]:
    """Pages whose thumbnail was rendered or asked for."""
    rendered = [item.index for item in sidebar.items if item.props.texture is not None]
    return sorted(set(rendered) | sidebar._requested)


def test_thumbnails_cost_nothing_until_the_sidebar_opens(run_app, make_pdf):
    def check(window) -> None:
        assert not window._split.get_show_sidebar()
        assert window.sidebar is None  # not even built

    run_app((loaded, check), argv=[make_pdf(pages=50)])


def test_f9_shows_thumbnails_for_the_rows_in_view_only(run_app, make_pdf):
    def check(window) -> None:
        assert window._actions["toggle-sidebar"].get_state().get_boolean()
        pages = touched(window.sidebar)
        assert max(pages) < 60, f"thumbnails far down the list were rendered: {pages}"

    run_app((loaded, show_sidebar), (thumbnails_shown, check), argv=[make_pdf(pages=300)])


def test_choosing_a_thumbnail_shows_that_page(run_app, make_pdf):
    def choose(window) -> None:
        window.sidebar._selection.set_selected(24)  # what a click does

    def arrived(window) -> bool:
        """page 25 to be current and drawn"""
        return window.view.current_page == 24 and window.view.pages[24].texture is not None

    def check(window) -> None:
        assert window._page_entry.get_text() == "25"

    run_app((loaded, show_sidebar), (thumbnails_shown, choose), (arrived, check), argv=[make_pdf(pages=60)])


def test_selection_follows_the_page_being_read(run_app, make_pdf):
    def jump(window) -> None:
        window._page_entry.set_text("40")
        window._page_entry.emit("activate")

    def followed(window) -> bool:
        """the sidebar to select page 40 and draw its thumbnail"""
        return window.sidebar.selected == 39 and window.sidebar.items[39].props.texture is not None

    def check(window) -> None:
        assert window.view.current_page == 39

    run_app((loaded, show_sidebar), (thumbnails_shown, jump), (followed, check), argv=[make_pdf(pages=60)])


def test_pages_refit_when_the_sidebar_opens(run_app, make_pdf):
    before = {}

    def show(window) -> None:
        before["width"] = window.view.pages[0].get_width()
        show_sidebar(window)

    def refitted(window) -> bool:
        """the page to be refitted to the narrower area beside the sidebar"""
        return window.view.pages[0].get_width() < before["width"] - 100 and fills_the_width(window)

    def check(window) -> None:
        assert window.view.fit_mode == "width"

    run_app((fills_the_width, show), (refitted, check), argv=[make_pdf()])


def test_thumbnails_come_back_after_an_engine_crash(run_app, make_pdf):
    crashed = {}

    def crash(window) -> None:
        crashed["pid"] = window._engine.pid
        for item in window.sidebar.items:
            item.props.texture = None
        os.kill(crashed["pid"], signal.SIGKILL)

    def recovered(window) -> bool:
        """a new engine to redraw the first thumbnail"""
        new_engine = window._engine.pid not in (None, crashed["pid"])
        return new_engine and window.sidebar.items[0].props.texture is not None

    run_app(
        (loaded, show_sidebar),
        (thumbnails_shown, crash),
        (recovered, lambda _window: None),
        argv=[make_pdf()],
    )
